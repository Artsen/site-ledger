import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.safe_fetch import (
    FetchLimits,
    RedirectFailureError,
    ResponseTooLargeError,
    SafeHttpFetcher,
    connect_error_type,
)
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.security import UnsafeDestinationError, validate_public_destination
from app.crawler.url_normalizer import NormalizedUrl
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, ScanSeed, WebResource
from app.services.cache_policy import (
    find_revalidation_candidate,
    representation_headers,
    request_variant_fingerprint,
    response_header_value,
)
from app.services.parse_artifacts import get_or_create_artifact
from app.services.repositories import get_or_create_resource
from app.services.site_pages import ensure_site_page
from app.storage.content_store import LocalContentStore

TRANSIENT_FETCH_ERRORS = {
    "connection_timeout",
    "read_timeout",
    "connection_error",
    "dns_error",
    "tls_error",
}


@dataclass(frozen=True)
class CrawlItem:
    normalized: NormalizedUrl
    requested_url: str
    depth: int


@dataclass(frozen=True)
class StaticCrawlResult:
    had_errors: bool
    cancelled: bool
    stop_reason: str
    fatal_error: str | None = None


class StaticPageCrawler:
    def __init__(
        self,
        db: Session,
        store: LocalContentStore,
        transport: httpx.AsyncBaseTransport | None = None,
        should_cancel: Callable[[], bool] | None = None,
        progress_callback: Callable[[Scan], None] | None = None,
        retry_progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.db = db
        self.store = store
        self.transport = transport
        self.should_cancel = should_cancel
        self.progress_callback = progress_callback
        self.retry_progress_callback = retry_progress_callback
        self._resource_cache: dict[str, WebResource] = {}

    async def run(self, scan: Scan) -> None:
        await self._execute(scan, finalize=True)

    async def collect(self, scan: Scan) -> StaticCrawlResult:
        return await self._execute(scan, finalize=False)

    async def _execute(self, scan: Scan, *, finalize: bool) -> StaticCrawlResult:
        self._resource_cache.clear()
        config = ScopeConfig.from_dict(scan.scope_config)
        scope = ScopeEngine(config, scan.starting_url)
        initial = scope.evaluate(scan.starting_url)
        if initial.normalized is None or not initial.in_scope:
            message = initial.exclusion_reason or "Starting URL is out of scope"
            if finalize:
                scan.status = "failed"
                scan.fatal_error_message = message
                scan.finished_at = datetime.now(UTC)
            self.db.commit()
            return StaticCrawlResult(False, False, "invalid_starting_url", message)

        if finalize:
            scan.status = "running"
            scan.started_at = datetime.now(UTC)
        queue = self._initial_queue(scan, initial.normalized)
        seen = {item.normalized.normalized_url for item in queue}
        fetched: set[str] = set()
        transient_failures: list[tuple[CrawlItem, ResourceSnapshot]] = []
        had_errors = False
        self._update_counts(scan, len(seen), len(fetched), len(queue))
        self.db.commit()

        client = httpx.AsyncClient(
            follow_redirects=False,
            max_redirects=config.max_redirects,
            timeout=config.request_timeout_seconds,
            transport=self.transport,
            limits=httpx.Limits(
                max_connections=max(2, config.concurrent_requests_per_host),
                max_keepalive_connections=max(2, config.concurrent_requests_per_host),
            ),
        )

        try:
            while queue and scan.status != "cancelled" and len(fetched) < config.max_pages:
                if self._cancel_requested():
                    scan.status = "cancelled"
                    break
                item = queue.popleft()
                scan.queued_count = len(queue)
                self.db.commit()
                if item.depth > config.max_depth:
                    scan.skipped_count += 1
                    continue
                try:
                    snapshot, anchors = await self._fetch_one(scan, item, config, scope, client)
                    fetched.add(item.normalized.normalized_url)
                    self._mark_seed(scan.id, item.normalized.normalized_url, "fetched")
                    if snapshot.error_type in TRANSIENT_FETCH_ERRORS:
                        transient_failures.append((item, snapshot))
                    elif snapshot.error_type:
                        had_errors = True
                    self._persist_anchors(
                        scan, snapshot, item, anchors, config, scope, seen, queue, discover=True
                    )
                    self._update_counts(scan, len(seen), len(fetched), len(queue))
                    self.db.commit()
                    self._progress(scan)
                # Page-level failures are persisted instead of failing the whole scan.
                except Exception as exc:
                    had_errors = True
                    self._record_failure(scan, item, "connection_error", str(exc))
                    fetched.add(item.normalized.normalized_url)
                    self._mark_seed(scan.id, item.normalized.normalized_url, "failed")
                    self._update_counts(scan, len(seen), len(fetched), len(queue))
                    self.db.commit()
                    self._progress(scan)
                if config.delay_between_requests_ms:
                    await self._sleep_with_cancellation(
                        config.delay_between_requests_ms / 1000, scan
                    )

            if scan.status != "cancelled":
                for retry_index, (item, failed_snapshot) in enumerate(transient_failures, 1):
                    if self._cancel_requested():
                        scan.status = "cancelled"
                        break
                    retry_snapshot, anchors = await self._fetch_one(
                        scan, item, config, scope, client
                    )
                    self.db.delete(failed_snapshot)
                    scan.failed_count = max(0, scan.failed_count - 1)
                    if retry_snapshot.error_type:
                        had_errors = True
                        self._mark_seed(scan.id, item.normalized.normalized_url, "failed")
                    else:
                        self._mark_seed(scan.id, item.normalized.normalized_url, "fetched")
                        self._persist_anchors(
                            scan,
                            retry_snapshot,
                            item,
                            anchors,
                            config,
                            scope,
                            seen,
                            queue,
                            discover=False,
                        )
                    self.db.commit()
                    if self.retry_progress_callback:
                        self.retry_progress_callback(retry_index, len(transient_failures))
        finally:
            await client.aclose()

        cancelled = scan.status == "cancelled"
        stop_reason = (
            "cancelled_by_user"
            if cancelled
            else ("page_limit_reached" if queue else "queue_exhausted")
        )
        if finalize:
            scan.stop_reason = stop_reason
            if not cancelled:
                scan.status = "completed_with_errors" if had_errors else "completed"
            scan.finished_at = datetime.now(UTC)
        scan.queued_count = len(queue)
        self.db.commit()
        self._progress(scan)
        return StaticCrawlResult(had_errors, cancelled, stop_reason)

    async def _fetch_one(
        self,
        scan: Scan,
        item: CrawlItem,
        config: ScopeConfig,
        scope: ScopeEngine,
        client: httpx.AsyncClient,
    ) -> tuple[ResourceSnapshot, list[Any]]:
        resource = self._resource(item.normalized)
        try:
            await validate_public_destination(item.requested_url, config.allow_private_networks)
            request_headers = representation_headers(config.user_agent)
            fingerprint = request_variant_fingerprint(request_headers)
            candidate = (
                find_revalidation_candidate(
                    self.db,
                    scan=scan,
                    resource_id=resource.id,
                    request_headers=request_headers,
                    store=self.store,
                )
                if config.enable_http_revalidation
                else None
            )
            fetch_headers = {"Accept": request_headers["accept"]}
            if candidate is not None:
                fetch_headers.update(candidate.request_headers)
            fetcher = SafeHttpFetcher(
                FetchLimits(
                    timeout_seconds=config.request_timeout_seconds,
                    max_response_bytes=config.max_html_response_bytes,
                    max_redirects=config.max_redirects,
                    user_agent=config.user_agent,
                    allow_private_networks=config.allow_private_networks,
                ),
                transport=self.transport,
                redirect_validator=lambda url: _validate_redirect(scope, url),
                destination_validator=validate_public_destination,
                client=client,
            )
            result = await fetcher.get(item.requested_url, headers=fetch_headers)
            if candidate is not None:
                scan.conditional_request_count += 1
            if candidate is not None and result.http_status == 304:
                if result.final_url == candidate.snapshot.final_url and candidate.snapshot.blob:
                    revalidation_artifact_result = get_or_create_artifact(
                        self.db,
                        blob=candidate.snapshot.blob,
                        content=self.store.get(candidate.snapshot.blob),
                        resolution_base_url=candidate.snapshot.final_url
                        or candidate.snapshot.requested_url,
                    )
                    revalidation_artifact = revalidation_artifact_result.artifact
                    anchors = revalidation_artifact_result.anchors
                    snapshot = ResourceSnapshot(
                        scan_id=scan.id,
                        resource_id=resource.id,
                        requested_url=item.requested_url,
                        final_url=candidate.snapshot.final_url,
                        http_status=candidate.snapshot.http_status,
                        content_type=candidate.snapshot.content_type,
                        encoding=candidate.snapshot.encoding,
                        crawl_depth=item.depth,
                        fetched_at=datetime.now(UTC),
                        response_time_ms=result.response_time_ms,
                        response_headers=candidate.snapshot.response_headers,
                        redirect_chain=result.redirect_chain,
                        html_blob_id=candidate.snapshot.html_blob_id,
                        parse_artifact_id=revalidation_artifact.id,
                        reused_from_snapshot_id=candidate.snapshot.id,
                        raw_html_sha256=candidate.snapshot.raw_html_sha256,
                        head_sha256=revalidation_artifact.head_sha256,
                        page_title=revalidation_artifact.page_title,
                        html_language=revalidation_artifact.html_language,
                        meta_description=revalidation_artifact.meta_description,
                        meta_robots=revalidation_artifact.meta_robots,
                        canonical_url=revalidation_artifact.canonical_url,
                        parsed_head_json=revalidation_artifact.parsed_head_json,
                        fetch_state="fetched",
                        error_type=None,
                        error_message=None,
                        retrieval_method="conditional_not_modified",
                        parse_method="reused_not_modified",
                        retrieval_http_status=304,
                        retrieval_response_headers=result.headers,
                        network_bytes_transferred=0,
                        request_variant_fingerprint=candidate.fingerprint,
                        etag=candidate.snapshot.etag,
                        last_modified=candidate.snapshot.last_modified,
                        cache_control=candidate.snapshot.cache_control,
                        vary_header=candidate.snapshot.vary_header,
                    )
                    self.db.add(snapshot)
                    self.db.flush()
                    ensure_site_page(
                        self.db,
                        scan=scan,
                        resource=resource,
                        associated_at=snapshot.fetched_at,
                    )
                    scan.not_modified_count += 1
                    scan.parse_reuse_count += 1
                    scan.reused_content_bytes += candidate.snapshot.blob.raw_byte_size
                    return snapshot, anchors
                result = await fetcher.get(
                    item.requested_url,
                    headers={"Accept": request_headers["accept"]},
                )
            content_type = result.content_type
            is_html = "text/html" in (content_type or "").lower() or not content_type
            blob = (
                self.store.put_html(self.db, result.content, content_type, result.encoding)
                if is_html
                else None
            )
            artifact_result = (
                get_or_create_artifact(
                    self.db,
                    blob=blob,
                    content=result.content,
                    resolution_base_url=result.final_url,
                    force_parse=not config.enable_parse_reuse,
                )
                if blob
                else None
            )
            artifact = artifact_result.artifact if artifact_result else None
            anchors = artifact_result.anchors if artifact_result else []
            if artifact_result:
                if artifact_result.parsed:
                    scan.full_parse_count += 1
                else:
                    scan.parse_reuse_count += 1
            scan.network_bytes_transferred += len(result.content)
            snapshot = ResourceSnapshot(
                scan_id=scan.id,
                resource_id=resource.id,
                requested_url=item.requested_url,
                final_url=result.final_url,
                http_status=result.http_status,
                content_type=content_type,
                encoding=result.encoding,
                crawl_depth=item.depth,
                fetched_at=datetime.now(UTC),
                response_time_ms=result.response_time_ms,
                response_headers=result.headers,
                redirect_chain=result.redirect_chain,
                html_blob_id=blob.id if blob else None,
                parse_artifact_id=artifact.id if artifact else None,
                raw_html_sha256=blob.sha256 if blob else None,
                head_sha256=artifact.head_sha256 if artifact else None,
                page_title=artifact.page_title if artifact else None,
                html_language=artifact.html_language if artifact else None,
                meta_description=artifact.meta_description if artifact else None,
                meta_robots=artifact.meta_robots if artifact else None,
                canonical_url=artifact.canonical_url if artifact else None,
                parsed_head_json=artifact.parsed_head_json if artifact else None,
                fetch_state="fetched" if is_html else "skipped",
                error_type=None if is_html else "unsupported_content_type",
                error_message=None if is_html else "Response was not HTML",
                retrieval_method="full_fetch_after_revalidation_fallback"
                if candidate is not None
                else "full_fetch"
                if is_html
                else "non_html",
                parse_method=artifact_result.parse_method if artifact_result else "not_applicable",
                retrieval_http_status=result.http_status,
                retrieval_response_headers=result.headers,
                network_bytes_transferred=len(result.content),
                request_variant_fingerprint=fingerprint,
                etag=response_header_value(result.headers, "etag"),
                last_modified=response_header_value(result.headers, "last-modified"),
                cache_control=response_header_value(result.headers, "cache-control"),
                vary_header=response_header_value(result.headers, "vary"),
            )
            self.db.add(snapshot)
            self.db.flush()
            ensure_site_page(
                self.db,
                scan=scan,
                resource=resource,
                associated_at=snapshot.fetched_at,
            )
            if not is_html:
                scan.skipped_count += 1
            return snapshot, anchors
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
            return self._record_failure(scan, item, connect_error_type(exc), str(exc)), []
        except UnsafeDestinationError as exc:
            return self._record_failure(scan, item, "unsafe_destination", str(exc)), []
        except httpx.InvalidURL as exc:
            return self._record_failure(scan, item, "invalid_url", str(exc)), []
        except ValueError as exc:
            return self._record_failure(scan, item, "invalid_url", str(exc)), []

    def _persist_anchors(
        self,
        scan: Scan,
        snapshot: ResourceSnapshot,
        item: CrawlItem,
        anchors: list[Any],
        config: ScopeConfig,
        scope: ScopeEngine,
        seen: set[str],
        queue: deque[CrawlItem],
        *,
        discover: bool,
    ) -> None:
        for anchor in anchors:
            result = scope.evaluate(
                anchor.raw_href or "", snapshot.final_url or item.requested_url, seen
            )
            target = self._resource(result.normalized) if result.normalized else None
            self.db.add(
                ResourceOccurrence(
                    source_snapshot_id=snapshot.id,
                    raw_href=anchor.raw_href,
                    resolved_url=anchor.resolved_url,
                    normalized_target_url=(
                        result.normalized.normalized_url if result.normalized else None
                    ),
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
                    link_role=anchor.link_role,
                    link_role_rule=anchor.link_role_rule,
                    link_context_json=anchor.link_context_json,
                )
            )
            if (
                discover
                and result.in_scope
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
        resource = self._resource(item.normalized)
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
        ensure_site_page(
            self.db,
            scan=scan,
            resource=resource,
            associated_at=snapshot.fetched_at,
        )
        return snapshot

    def _resource(self, normalized: NormalizedUrl) -> WebResource:
        cached = self._resource_cache.get(normalized.normalized_url)
        if cached is not None:
            return cached
        resource = get_or_create_resource(self.db, normalized)
        self._resource_cache[normalized.normalized_url] = resource
        return resource

    @staticmethod
    def _update_counts(scan: Scan, discovered: int, fetched: int, queued: int) -> None:
        scan.discovered_count = discovered
        scan.fetched_count = fetched
        scan.queued_count = queued

    def _initial_queue(self, scan: Scan, initial: NormalizedUrl) -> deque[CrawlItem]:
        seeds = list(
            self.db.scalars(
                select(ScanSeed)
                .where(ScanSeed.scan_id == scan.id, ScanSeed.queue_state == "queued")
                .order_by(ScanSeed.created_at, ScanSeed.id)
            )
        )
        if not seeds:
            return deque([CrawlItem(initial, initial.normalized_url, 0)])
        queue: deque[CrawlItem] = deque()
        for seed in seeds:
            if not seed.normalized_url:
                continue
            try:
                normalized = NormalizedUrl(
                    raw_url=seed.requested_url,
                    resolved_url=seed.requested_url,
                    normalized_url=seed.normalized_url,
                    scheme=seed.normalized_url.split(":", 1)[0],
                    host=seed.resource.host if seed.resource else "",
                    port=seed.resource.port if seed.resource else None,
                    path=seed.resource.path if seed.resource else "/",
                    query=seed.resource.query if seed.resource else "",
                )
            except ValueError:
                continue
            queue.append(CrawlItem(normalized, seed.requested_url, seed.depth))
        return queue or deque([CrawlItem(initial, initial.normalized_url, 0)])

    def _mark_seed(self, scan_id: int, normalized_url: str, state: str) -> None:
        seed = self.db.scalar(
            select(ScanSeed).where(
                ScanSeed.scan_id == scan_id,
                ScanSeed.normalized_url == normalized_url,
            )
        )
        if seed:
            seed.queue_state = state

    def _cancel_requested(self) -> bool:
        return bool(self.should_cancel and self.should_cancel())

    def _progress(self, scan: Scan) -> None:
        if self.progress_callback:
            self.progress_callback(scan)

    async def _sleep_with_cancellation(self, seconds: float, scan: Scan) -> None:
        remaining = seconds
        while remaining > 0:
            if self._cancel_requested():
                scan.status = "cancelled"
                return
            interval = min(0.25, remaining)
            await asyncio.sleep(interval)
            remaining -= interval


async def _validate_redirect(
    scope: ScopeEngine, url: str
) -> tuple[bool, str | None, str | None, str | None]:
    destination = scope.evaluate(url)
    if destination.normalized is None:
        return (
            False,
            destination.decision,
            destination.exclusion_reason or "Redirect location is invalid",
            None,
        )
    if destination.decision != "crawlable":
        return (
            False,
            "scope_excluded",
            destination.exclusion_reason or "Redirect left configured scope",
            destination.normalized.normalized_url,
        )
    return True, None, None, destination.normalized.normalized_url
