from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.browser.config import BROWSER_POLICY_VERSION, CAPTURE_SCHEMA_VERSION, RENDERER_VERSION
from app.browser.outcomes import classify_main_navigation
from app.browser.privacy import redact_text, redact_url, sanitize_headers
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.security import validate_public_destination
from app.crawler.url_normalizer import URL_NORMALIZATION_V1_VERSION

ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class CapturedArtifact:
    artifact_type: str
    content: bytes
    media_type: str
    width: int | None = None
    height: int | None = None
    gzip_content: bool = False


@dataclass
class CaptureResult:
    state: str = "completed"
    final_url: str | None = None
    status: int | None = None
    title: str | None = None
    readiness_state: str = "domcontentloaded"
    load_event_reached: bool = False
    fonts_ready_reached: bool = False
    user_agent: str | None = None
    duration_ms: int = 0
    error_type: str | None = None
    error_message: str | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)
    network: list[dict[str, Any]] = field(default_factory=list)
    console: list[dict[str, Any]] = field(default_factory=list)
    page_errors: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[CapturedArtifact] = field(default_factory=list)
    blocked_requests: int = 0
    network_truncated: bool = False
    console_truncated: bool = False
    page_errors_truncated: bool = False
    total_network_bytes: int = 0
    callback_result: Any = None


class BrowserUnavailableError(RuntimeError):
    pass


class ObservedByteBudget:
    def __init__(self, resource_limit: int, total_limit: int):
        self.resource_limit = resource_limit
        self.total_limit = total_limit
        self.resources: dict[str, int] = {}
        self.total = 0

    def observe(self, request_id: str, encoded_bytes: int) -> set[str]:
        if encoded_bytes <= 0:
            return set()
        self.resources[request_id] = self.resources.get(request_id, 0) + encoded_bytes
        self.total += encoded_bytes
        return self._violations(request_id)

    def finish(self, request_id: str, encoded_bytes: int) -> set[str]:
        previous = self.resources.get(request_id, 0)
        if encoded_bytes <= 0:
            return self._violations(request_id)
        if encoded_bytes != previous:
            self.total += encoded_bytes - previous
            self.resources[request_id] = encoded_bytes
        return self._violations(request_id)

    def _violations(self, request_id: str) -> set[str]:
        violations = set()
        if self.resources.get(request_id, 0) > self.resource_limit:
            violations.add("resource_byte_budget_exceeded")
        if self.total > self.total_limit:
            violations.add("total_network_budget_exceeded")
        return violations


class BrowserRenderer:
    def __init__(
        self,
        config: ScopeConfig,
        starting_url: str,
        normalization_version: str = URL_NORMALIZATION_V1_VERSION,
    ):
        self.config = config
        self.scope = ScopeEngine(config, starting_url, normalization_version)
        self._playwright: Any = None
        self.browser: Any = None
        self.browser_version: str | None = None
        self.playwright_version = importlib.metadata.version("playwright")

    async def __aenter__(self) -> BrowserRenderer:
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=True, args=["--no-proxy-server"]
            )
            self.browser_version = self.browser.version
        except Exception as exc:
            if self._playwright:
                await self._playwright.stop()
            raise BrowserUnavailableError(
                "Chromium could not launch. Run: python -m playwright install chromium"
            ) from exc
        try:
            probe = await self.browser.new_context(
                locale=self.config.render_locale,
                timezone_id=self.config.render_timezone,
                color_scheme=self.config.render_color_scheme,
                reduced_motion=self.config.render_reduced_motion,
            )
            await probe.close()
        except Exception as exc:
            await self.browser.close()
            await self._playwright.stop()
            self.browser = None
            self._playwright = None
            raise ValueError(
                "Browser locale, timezone, color scheme, or motion configuration is unsupported."
            ) from exc
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def capture(
        self,
        url: str,
        *,
        after_ready: Callable[[Any], Awaitable[Any]] | None = None,
        capture_artifacts: bool = True,
    ) -> CaptureResult:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        started = time.monotonic()
        result = CaptureResult()
        context = await self.browser.new_context(
            viewport={
                "width": self.config.render_viewport_width,
                "height": self.config.render_viewport_height,
            },
            device_scale_factor=self.config.render_device_scale_factor,
            locale=self.config.render_locale,
            timezone_id=self.config.render_timezone,
            color_scheme=self.config.render_color_scheme,
            reduced_motion=self.config.render_reduced_motion,
            service_workers="block",
            accept_downloads=False,
        )
        page: Any = None
        request_rows: dict[int, dict[str, Any]] = {}
        main_navigation_count = 0
        main_navigation_status: int | None = None
        network_sequence = 0
        byte_budget = ObservedByteBudget(
            self.config.render_max_resource_bytes,
            self.config.render_max_total_network_bytes,
        )
        byte_budget_exhausted = False
        byte_budget_stop_reason: str | None = None
        budget_warning_types: set[str] = set()
        cdp_request_urls: dict[str, str] = {}
        rows_by_url: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        event_tasks: set[asyncio.Task[Any]] = set()
        cdp: Any = None

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        def warning(kind: str, message: str) -> None:
            if len(result.warnings) < 50:
                result.warnings.append({"type": kind, "message": redact_text(message, 1000)})

        async def route_request(route: Any, request: Any) -> None:
            nonlocal main_navigation_count, network_sequence
            network_sequence += 1
            sequence = network_sequence
            reason: str | None = None
            method = request.method.upper()
            scheme = request.url.split(":", 1)[0].lower()
            is_main_navigation = bool(
                page and request.is_navigation_request() and request.frame == page.main_frame
            )
            if method not in ALLOWED_METHODS:
                reason = "unsafe_method"
            elif request.resource_type == "media":
                reason = "unbounded_media"
            elif scheme in {"about", "data", "blob"} and not is_main_navigation:
                pass
            elif scheme not in {"http", "https"}:
                reason = "unsupported_scheme"
            elif byte_budget_exhausted:
                reason = byte_budget_stop_reason or "network_byte_budget_exceeded"
            else:
                try:
                    await validate_public_destination(
                        request.url, self.config.allow_private_networks
                    )
                    if is_main_navigation:
                        main_navigation_count += 1
                        if main_navigation_count > self.config.max_redirects + 1:
                            reason = "redirect_limit_exceeded"
                        decision = self.scope.evaluate(request.url)
                        if not decision.in_scope:
                            reason = f"navigation_{decision.decision}"
                except Exception:
                    reason = "unsafe_destination"
            redacted, digest = redact_url(request.url)
            row = {
                "sequence": sequence,
                "request_key": hashlib.sha256(f"{id(request)}:{request.url}".encode()).hexdigest(),
                "redacted_url": redacted,
                "url_sha256": digest,
                "method": method,
                "resource_type": request.resource_type,
                "is_navigation_request": request.is_navigation_request(),
                "is_main_navigation": is_main_navigation,
                "request_started_offset_ms": elapsed(),
                "request_headers_json": sanitize_headers(await request.all_headers()),
                "response_headers_json": {},
                "blocked_by_policy": bool(reason),
                "policy_reason": reason,
            }
            if len(result.network) < self.config.render_max_network_entries:
                result.network.append(row)
                request_rows[id(request)] = row
                rows_by_url[request.url].append(row)
            else:
                result.network_truncated = True
            if reason:
                result.blocked_requests += 1
                await route.abort("blockedbyclient")
            else:
                await route.continue_()

        async def response_seen(response: Any) -> None:
            nonlocal main_navigation_status
            row = request_rows.get(id(response.request))
            if not row:
                return
            if row["is_main_navigation"]:
                main_navigation_status = response.status
            headers = await response.all_headers()
            row.update(
                response_status=response.status,
                response_status_text=response.status_text[:128],
                response_headers_json=sanitize_headers(headers, response=True),
                response_mime_type=headers.get("content-type", "")[:255],
            )

        async def apply_byte_observation(
            request_id: str, encoded_bytes: int, *, finished: bool = False
        ) -> None:
            nonlocal byte_budget_exhausted, byte_budget_stop_reason
            violations = (
                byte_budget.finish(request_id, encoded_bytes)
                if finished
                else byte_budget.observe(request_id, encoded_bytes)
            )
            result.total_network_bytes = byte_budget.total
            url = cdp_request_urls.get(request_id)
            if url and rows_by_url[url]:
                row = rows_by_url[url][0]
                row["encoded_data_length"] = byte_budget.resources.get(request_id, 0)
                if finished:
                    rows_by_url[url].popleft()
            for kind in sorted(violations):
                if kind not in budget_warning_types:
                    budget_warning_types.add(kind)
                    warning(
                        kind,
                        "Observed encoded network bytes exceeded the configured "
                        + ("resource limit." if kind.startswith("resource") else "total limit."),
                    )
            if not violations or byte_budget_exhausted:
                return
            byte_budget_exhausted = True
            byte_budget_stop_reason = (
                "total_network_budget_exceeded"
                if "total_network_budget_exceeded" in violations
                else "resource_byte_budget_exceeded"
            )
            if cdp is not None:
                stop_failures = 0
                for command, params in (
                    ("Network.setBlockedURLs", {"urls": ["*"]}),
                    ("Page.stopLoading", {}),
                ):
                    try:
                        await cdp.send(command, params)
                    except Exception as exc:
                        stop_failures += 1
                        warning("network_budget_stop_failed", str(exc))
                if stop_failures == 2 and page and not page.is_closed():
                    await page.close()

        def schedule(coro: Any) -> None:
            task = asyncio.create_task(coro)
            event_tasks.add(task)

            def event_done(completed: asyncio.Task[Any]) -> None:
                event_tasks.discard(completed)
                if completed.cancelled():
                    return
                error = completed.exception()
                if error is not None:
                    warning("network_accounting_failed", str(error))

            task.add_done_callback(event_done)

        def request_finished(request: Any) -> None:
            row = request_rows.get(id(request))
            if row:
                row["duration_ms"] = elapsed() - row["request_started_offset_ms"]

        def request_failed(request: Any) -> None:
            row = request_rows.get(id(request))
            if row:
                row["failure_reason"] = redact_text(request.failure or "request_failed", 1000)
                request_finished(request)

        try:
            await context.route("**/*", route_request)
            await context.add_init_script("""
                Object.defineProperty(window, 'open', {value: () => null});
                class BlockedWebSocket {
                    constructor() { throw new Error('WebSocket blocked by capture policy'); }
                }
                class BlockedEventSource {
                    constructor() { throw new Error('EventSource blocked by capture policy'); }
                }
                Object.defineProperty(window, 'WebSocket', {value: BlockedWebSocket});
                Object.defineProperty(window, 'EventSource', {value: BlockedEventSource});
            """)
            page = await context.new_page()
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.enable")
            cdp.on(
                "Network.requestWillBeSent",
                lambda event: cdp_request_urls.__setitem__(
                    event["requestId"], event["request"]["url"]
                ),
            )
            cdp.on(
                "Network.dataReceived",
                lambda event: schedule(
                    apply_byte_observation(
                        event["requestId"],
                        int(event.get("encodedDataLength") or event.get("dataLength", 0)),
                    )
                ),
            )
            cdp.on(
                "Network.loadingFinished",
                lambda event: schedule(
                    apply_byte_observation(
                        event["requestId"],
                        int(event.get("encodedDataLength", 0)),
                        finished=True,
                    )
                ),
            )
            page.on("response", response_seen)
            page.on("requestfinished", request_finished)
            page.on("requestfailed", request_failed)
            page.on(
                "dialog", lambda dialog: asyncio.create_task(self._dismiss_dialog(dialog, warning))
            )
            page.on(
                "download",
                lambda download: asyncio.create_task(self._cancel_download(download, warning)),
            )
            page.on("popup", lambda popup: asyncio.create_task(self._close_popup(popup, warning)))

            def console_seen(message: Any) -> None:
                if len(result.console) >= self.config.render_max_console_entries:
                    result.console_truncated = True
                    return
                location = message.location or {}
                source = redact_url(location.get("url", ""))[0] if location.get("url") else None
                result.console.append(
                    {
                        "sequence": len(result.console) + 1,
                        "message_type": message.type[:32],
                        "text": redact_text(message.text, 8000),
                        "source_url": source,
                        "line_number": location.get("lineNumber"),
                        "column_number": location.get("columnNumber"),
                        "timestamp_offset_ms": elapsed(),
                    }
                )

            def error_seen(error: Any) -> None:
                if len(result.page_errors) >= self.config.render_max_page_errors:
                    result.page_errors_truncated = True
                    return
                result.page_errors.append(
                    {
                        "sequence": len(result.page_errors) + 1,
                        "error_name": getattr(error, "name", type(error).__name__)[:128],
                        "message": redact_text(str(error), 8000),
                        "stack": redact_text(getattr(error, "stack", None) or "", 16000),
                        "source_url": None,
                        "timestamp_offset_ms": elapsed(),
                    }
                )

            page.on("console", console_seen)
            page.on("pageerror", error_seen)
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.config.render_navigation_timeout_seconds * 1000,
            )
            result.status = response.status if response else None
            result.readiness_state = "domcontentloaded"
            result.final_url = page.url
            outcome = classify_main_navigation(result.status)
            result.state = outcome.capture_state
            result.error_type = outcome.error_type
            result.error_message = outcome.error_message
            if outcome.artifacts_eligible:
                result.title = (await page.title())[:2000]
                result.user_agent = (await page.evaluate("navigator.userAgent"))[:2000]
                try:
                    await page.wait_for_load_state(
                        "load", timeout=self.config.render_load_timeout_seconds * 1000
                    )
                    result.load_event_reached = True
                    result.readiness_state = "load"
                except PlaywrightTimeoutError:
                    warning(
                        "load_event_timeout",
                        "The load event did not arrive within the configured timeout.",
                    )
                try:
                    await page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
                    result.fonts_ready_reached = True
                except Exception:
                    warning("fonts_readiness_failed", "Font readiness could not be confirmed.")
                await page.wait_for_timeout(250)
                if after_ready is not None:
                    result.callback_result = await after_ready(page)
                if capture_artifacts:
                    await self._capture_artifacts(page, result, warning)
                if result.warnings or result.page_errors:
                    result.state = "completed_with_warnings"
        except asyncio.CancelledError:
            result.state = "cancelled"
            raise
        except Exception as exc:
            if byte_budget_exhausted:
                result.state = "completed_with_warnings"
                result.error_type = "network_byte_budget_exceeded"
                result.error_message = "Browser loading stopped after an observed byte limit."
                if page and not page.is_closed():
                    result.final_url = page.url
            elif main_navigation_status in {204, 205}:
                result.status = main_navigation_status
                result.final_url = page.url if page and not page.is_closed() else url
                outcome = classify_main_navigation(main_navigation_status)
                result.state = outcome.capture_state
                result.error_type = outcome.error_type
                result.error_message = outcome.error_message
            else:
                result.state = "failed"
                result.error_type = type(exc).__name__[:64]
                result.error_message = redact_text(str(exc), 8000)
        finally:
            try:
                await context.unroute_all(behavior="ignoreErrors")
            except Exception as exc:
                warning("route_teardown_failed", str(exc))
                if result.state == "completed":
                    result.state = "completed_with_warnings"
            if event_tasks:
                await asyncio.gather(*event_tasks, return_exceptions=True)
            result.total_network_bytes = byte_budget.total
            result.duration_ms = elapsed()
            try:
                await context.close()
            except Exception as exc:
                warning("context_close_failed", str(exc))
                if result.state == "completed":
                    result.state = "completed_with_warnings"
        return result

    async def _capture_artifacts(self, page: Any, result: CaptureResult, warning: Any) -> None:
        try:
            dom = (await page.content()).encode("utf-8")
            if len(dom) <= self.config.render_max_dom_bytes:
                result.artifacts.append(
                    CapturedArtifact(
                        "rendered_dom", dom, "text/plain; charset=utf-8", gzip_content=True
                    )
                )
            else:
                warning(
                    "artifact_too_large", "Rendered DOM exceeded its byte limit and was omitted."
                )
        except Exception as exc:
            warning("dom_capture_failed", str(exc))
        try:
            png = await page.screenshot(type="png", animations="disabled", caret="hide")
            if len(png) <= self.config.render_max_screenshot_bytes:
                result.artifacts.append(
                    CapturedArtifact(
                        "viewport_screenshot",
                        png,
                        "image/png",
                        self.config.render_viewport_width,
                        self.config.render_viewport_height,
                    )
                )
            else:
                warning("artifact_too_large", "Viewport screenshot exceeded its byte limit.")
        except Exception as exc:
            warning("screenshot_failed", str(exc))
        if not self.config.render_capture_full_page:
            return
        try:
            height = int(
                await page.evaluate(
                    "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                )
            )
            if height > self.config.render_max_full_page_height:
                warning(
                    "full_page_height_exceeded",
                    "Full-page screenshot was omitted because the page was too tall.",
                )
                return
            png = await page.screenshot(
                type="png", full_page=True, animations="disabled", caret="hide"
            )
            if len(png) <= self.config.render_max_screenshot_bytes:
                result.artifacts.append(
                    CapturedArtifact(
                        "full_page_screenshot",
                        png,
                        "image/png",
                        self.config.render_viewport_width,
                        height,
                    )
                )
            else:
                warning("artifact_too_large", "Full-page screenshot exceeded its byte limit.")
        except Exception as exc:
            warning("full_page_screenshot_failed", str(exc))

    async def _dismiss_dialog(self, dialog: Any, warning: Any) -> None:
        warning("dialog_dismissed", f"Dismissed {dialog.type} dialog: {dialog.message[:500]}")
        await dialog.dismiss()

    async def _cancel_download(self, download: Any, warning: Any) -> None:
        warning("download_blocked", "A browser download was cancelled.")
        await download.cancel()

    async def _close_popup(self, popup: Any, warning: Any) -> None:
        warning("popup_blocked", "A popup was closed by capture policy.")
        await popup.close()


def configuration_fingerprint(config: ScopeConfig) -> str:
    values = {key: value for key, value in config.to_dict().items() if key.startswith("render_")}
    values.update(
        renderer=RENDERER_VERSION, policy=BROWSER_POLICY_VERSION, schema=CAPTURE_SCHEMA_VERSION
    )
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
