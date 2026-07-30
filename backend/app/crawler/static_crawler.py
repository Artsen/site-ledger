import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from app.crawler.html_parser import parse_html
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.security import UnsafeDestinationError, validate_public_destination
from app.crawler.url_normalizer import NormalizedUrl
from app.models import ResourceOccurrence, ResourceSnapshot, Scan
from app.services.repositories import get_or_create_resource
from app.storage.content_store import LocalContentStore


@dataclass(frozen=True)
class CrawlItem:
    normalized: NormalizedUrl
    requested_url: str
    depth: int


REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class StaticPageCrawler:
    def __init__(
        self,
        db: Session,
        store: LocalContentStore,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.db = db
        self.store = store
        self.transport = transport

    async def run(self, scan: Scan) -> None:
        config = ScopeConfig.from_dict(scan.scope_config)
        scope = ScopeEngine(config, scan.starting_url)
        initial = scope.evaluate(scan.starting_url)
        if initial.normalized is None or not initial.in_scope:
            scan.status = "failed"
            scan.fatal_error_message = initial.exclusion_reason or "Starting URL is out of scope"
            scan.finished_at = datetime.now(UTC)
            self.db.commit()
            return

        scan.status = "running"
        scan.started_at = datetime.now(UTC)
        queue: deque[CrawlItem] = deque(
            [CrawlItem(initial.normalized, initial.normalized.normalized_url, 0)]
        )
        seen = {initial.normalized.normalized_url}
        fetched: set[str] = set()
        had_errors = False
        self._update_counts(scan, len(seen), len(fetched), len(queue))
        self.db.commit()

        async with httpx.AsyncClient(
            follow_redirects=False,
            max_redirects=config.max_redirects,
            timeout=config.request_timeout_seconds,
            headers={"User-Agent": config.user_agent},
            transport=self.transport,
        ) as client:
            while queue and scan.status != "cancelled" and len(fetched) < config.max_pages:
                item = queue.popleft()
                scan.queued_count = len(queue)
                self.db.commit()
                if item.depth > config.max_depth:
                    scan.skipped_count += 1
                    continue
                try:
                    snapshot, anchors = await self._fetch_one(scan, item, client, config, scope)
                    fetched.add(item.normalized.normalized_url)
                    if snapshot.error_type:
                        had_errors = True
                    for anchor in anchors:
                        result = scope.evaluate(
                            anchor.raw_href or "", snapshot.final_url or item.requested_url, seen
                        )
                        target = (
                            get_or_create_resource(self.db, result.normalized)
                            if result.normalized
                            else None
                        )
                        occurrence = ResourceOccurrence(
                            source_snapshot_id=snapshot.id,
                            raw_href=anchor.raw_href,
                            resolved_url=anchor.resolved_url,
                            normalized_target_url=result.normalized.normalized_url
                            if result.normalized
                            else None,
                            target_resource_id=target.id if target else None,
                            anchor_text=anchor.anchor_text,
                            title=anchor.title,
                            aria_label=anchor.aria_label,
                            rel=anchor.rel,
                            target=anchor.target,
                            dom_path=anchor.dom_path,
                            in_scope=result.in_scope,
                            scope_decision=result.decision,
                            exclusion_reason=result.exclusion_reason,
                        )
                        self.db.add(occurrence)
                        if (
                            result.in_scope
                            and result.normalized is not None
                            and result.normalized.normalized_url not in seen
                            and item.depth + 1 <= config.max_depth
                            and len(seen) < config.max_pages
                        ):
                            seen.add(result.normalized.normalized_url)
                            queue.append(
                                CrawlItem(
                                    result.normalized,
                                    result.normalized.normalized_url,
                                    item.depth + 1,
                                )
                            )
                    self._update_counts(scan, len(seen), len(fetched), len(queue))
                    self.db.commit()
                except (
                    Exception
                ) as exc:  # page-level failures are persisted, not fatal scan failures
                    had_errors = True
                    self._record_failure(scan, item, "connection_error", str(exc))
                    fetched.add(item.normalized.normalized_url)
                    self._update_counts(scan, len(seen), len(fetched), len(queue))
                    self.db.commit()
                if config.delay_between_requests_ms:
                    await asyncio.sleep(config.delay_between_requests_ms / 1000)

        if scan.status == "cancelled":
            scan.stop_reason = "cancelled_by_user"
        else:
            scan.status = "completed_with_errors" if had_errors else "completed"
            scan.stop_reason = "page_limit_reached" if queue else "queue_exhausted"
        scan.finished_at = datetime.now(UTC)
        scan.queued_count = len(queue)
        self.db.commit()

    async def _fetch_one(
        self,
        scan: Scan,
        item: CrawlItem,
        client: httpx.AsyncClient,
        config: ScopeConfig,
        scope: ScopeEngine,
    ) -> tuple[ResourceSnapshot, list[Any]]:
        resource = get_or_create_resource(self.db, item.normalized)
        started = monotonic()
        try:
            await validate_public_destination(item.requested_url, config.allow_private_networks)
            response, content, redirect_chain = await self._get_with_validated_redirects(
                client, item.requested_url, config, scope
            )
            response_time_ms = int((monotonic() - started) * 1000)
            content_type = response.headers.get("content-type")
            is_html = "text/html" in (content_type or "").lower() or not content_type
            parsed = parse_html(content, str(response.url)) if is_html else None
            blob = (
                self.store.put_html(self.db, content, content_type, response.encoding)
                if is_html
                else None
            )
            snapshot = ResourceSnapshot(
                scan_id=scan.id,
                resource_id=resource.id,
                requested_url=item.requested_url,
                final_url=str(response.url),
                http_status=response.status_code,
                content_type=content_type,
                encoding=response.encoding,
                crawl_depth=item.depth,
                fetched_at=datetime.now(UTC),
                response_time_ms=response_time_ms,
                response_headers=dict(response.headers),
                redirect_chain=redirect_chain,
                html_blob_id=blob.id if blob else None,
                raw_html_sha256=blob.sha256 if blob else None,
                head_sha256=parsed.head_sha256 if parsed else None,
                page_title=parsed.title if parsed else None,
                html_language=parsed.html_language if parsed else None,
                meta_description=parsed.meta_description if parsed else None,
                meta_robots=parsed.meta_robots if parsed else None,
                canonical_url=parsed.canonical_url if parsed else None,
                parsed_head_json=parsed.head_json if parsed else None,
                fetch_state="fetched" if is_html else "skipped",
                error_type=None if is_html else "unsupported_content_type",
                error_message=None if is_html else "Response was not HTML",
            )
            self.db.add(snapshot)
            self.db.flush()
            if not is_html:
                scan.skipped_count += 1
            return snapshot, parsed.anchors if parsed else []
        except httpx.TooManyRedirects as exc:
            return self._record_failure(scan, item, "too_many_redirects", str(exc)), []
        except ResponseTooLargeError as exc:
            return self._record_failure(
                scan, item, "response_too_large", str(exc), redirect_chain=exc.redirect_chain
            ), []
        except RedirectFailureError as exc:
            return self._record_failure(
                scan,
                item,
                exc.error_type,
                str(exc),
                final_url=exc.final_url,
                http_status=exc.http_status,
                response_headers=exc.response_headers,
                redirect_chain=exc.redirect_chain,
            ), []
        except httpx.ConnectTimeout as exc:
            return self._record_failure(scan, item, "connection_timeout", str(exc)), []
        except httpx.ReadTimeout as exc:
            return self._record_failure(scan, item, "read_timeout", str(exc)), []
        except httpx.ConnectError as exc:
            return self._record_failure(scan, item, _connect_error_type(exc), str(exc)), []
        except UnsafeDestinationError as exc:
            return self._record_failure(scan, item, "unsafe_destination", str(exc)), []
        except httpx.InvalidURL as exc:
            return self._record_failure(scan, item, "invalid_url", str(exc)), []
        except ValueError as exc:
            return self._record_failure(scan, item, "invalid_url", str(exc)), []

    async def _get_with_validated_redirects(
        self,
        client: httpx.AsyncClient,
        start_url: str,
        config: ScopeConfig,
        scope: ScopeEngine,
    ) -> tuple[httpx.Response, bytes, list[dict[str, Any]]]:
        current_url = start_url
        initial = scope.evaluate(start_url)
        seen_redirects: set[str] = (
            {initial.normalized.normalized_url} if initial.normalized else set()
        )
        redirect_chain: list[dict[str, Any]] = []

        for _hop in range(config.max_redirects + 1):
            await validate_public_destination(current_url, config.allow_private_networks)
            async with client.stream("GET", current_url) as response:
                if response.status_code not in REDIRECT_STATUSES:
                    content = await self._read_limited_response(response, config, redirect_chain)
                    return response, content, redirect_chain

                location = response.headers.get("location")
                try:
                    resolved_url = urljoin(str(response.url), location) if location else None
                except ValueError as exc:
                    redirect_chain.append(
                        {
                            "requested_url": current_url,
                            "status_code": response.status_code,
                            "location": location,
                            "resolved_url": None,
                        }
                    )
                    raise RedirectFailureError(
                        "invalid_url",
                        str(exc),
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    ) from exc
                redirect_chain.append(
                    {
                        "requested_url": current_url,
                        "status_code": response.status_code,
                        "location": location,
                        "resolved_url": resolved_url,
                    }
                )
                if not location or not resolved_url:
                    raise RedirectFailureError(
                        "invalid_url",
                        "Redirect response did not include a valid Location header",
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    )
                try:
                    httpx.URL(resolved_url)
                except httpx.InvalidURL as exc:
                    raise RedirectFailureError(
                        "invalid_url",
                        str(exc),
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    ) from exc
                destination = scope.evaluate(resolved_url)
                if destination.normalized is None:
                    raise RedirectFailureError(
                        destination.decision,
                        destination.exclusion_reason or "Redirect location is invalid",
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    )
                if destination.decision != "crawlable":
                    raise RedirectFailureError(
                        "scope_excluded",
                        destination.exclusion_reason or "Redirect left configured scope",
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    )
                if destination.normalized.normalized_url in seen_redirects:
                    raise RedirectFailureError(
                        "redirect_loop",
                        "Redirect loop detected",
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    )
                await validate_public_destination(
                    destination.normalized.normalized_url, config.allow_private_networks
                )
                seen_redirects.add(destination.normalized.normalized_url)
                current_url = destination.normalized.normalized_url

        raise RedirectFailureError(
            "too_many_redirects",
            "Redirect limit exceeded",
            current_url,
            None,
            None,
            redirect_chain,
        )

    @staticmethod
    async def _read_limited_response(
        response: httpx.Response,
        config: ScopeConfig,
        redirect_chain: list[dict[str, Any]],
    ) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > config.max_html_response_bytes:
                    raise ResponseTooLargeError(
                        "Content-Length exceeded configured response limit", redirect_chain
                    )
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > config.max_html_response_bytes:
                raise ResponseTooLargeError(
                    "Streamed response exceeded configured response limit", redirect_chain
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _record_failure(
        self,
        scan: Scan,
        item: CrawlItem,
        error_type: str,
        message: str,
        final_url: str | None = None,
        http_status: int | None = None,
        response_headers: dict[str, Any] | None = None,
        redirect_chain: list[dict[str, Any]] | None = None,
    ) -> ResourceSnapshot:
        resource = get_or_create_resource(self.db, item.normalized)
        snapshot = ResourceSnapshot(
            scan_id=scan.id,
            resource_id=resource.id,
            requested_url=item.requested_url,
            final_url=final_url,
            http_status=http_status,
            content_type=None,
            encoding=None,
            crawl_depth=item.depth,
            fetched_at=datetime.now(UTC),
            response_time_ms=None,
            response_headers=response_headers,
            redirect_chain=redirect_chain or [],
            html_blob_id=None,
            raw_html_sha256=None,
            head_sha256=None,
            page_title=None,
            html_language=None,
            meta_description=None,
            meta_robots=None,
            canonical_url=None,
            parsed_head_json=None,
            fetch_state="failed",
            error_type=error_type,
            error_message=message,
        )
        scan.failed_count += 1
        self.db.add(snapshot)
        self.db.flush()
        return snapshot

    @staticmethod
    def _update_counts(scan: Scan, discovered: int, fetched: int, queued: int) -> None:
        scan.discovered_count = discovered
        scan.fetched_count = fetched
        scan.queued_count = queued


def _connect_error_type(exc: httpx.ConnectError) -> str:
    text = str(exc).lower()
    if "name" in text or "dns" in text:
        return "dns_error"
    if "ssl" in text or "tls" in text:
        return "tls_error"
    return "connection_error"


class RedirectFailureError(Exception):
    def __init__(
        self,
        error_type: str,
        message: str,
        final_url: str | None,
        http_status: int | None,
        response_headers: dict[str, Any] | None,
        redirect_chain: list[dict[str, Any]],
    ):
        super().__init__(message)
        self.error_type = error_type
        self.final_url = final_url
        self.http_status = http_status
        self.response_headers = response_headers
        self.redirect_chain = redirect_chain


class ResponseTooLargeError(Exception):
    def __init__(self, message: str, redirect_chain: list[dict[str, Any]]):
        super().__init__(message)
        self.redirect_chain = redirect_chain
