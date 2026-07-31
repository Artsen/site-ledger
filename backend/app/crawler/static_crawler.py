import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.html_parser import parse_html
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
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, ScanSeed
from app.services.repositories import get_or_create_resource
from app.storage.content_store import LocalContentStore


@dataclass(frozen=True)
class CrawlItem:
    normalized: NormalizedUrl
    requested_url: str
    depth: int


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
        queue = self._initial_queue(scan, initial.normalized)
        seen = {item.normalized.normalized_url for item in queue}
        fetched: set[str] = set()
        had_errors = False
        self._update_counts(scan, len(seen), len(fetched), len(queue))
        self.db.commit()

        while queue and scan.status != "cancelled" and len(fetched) < config.max_pages:
            item = queue.popleft()
            scan.queued_count = len(queue)
            self.db.commit()
            if item.depth > config.max_depth:
                scan.skipped_count += 1
                continue
            try:
                snapshot, anchors = await self._fetch_one(scan, item, config, scope)
                fetched.add(item.normalized.normalized_url)
                self._mark_seed(scan.id, item.normalized.normalized_url, "fetched")
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
            except Exception as exc:  # page-level failures are persisted, not fatal scan failures
                had_errors = True
                self._record_failure(scan, item, "connection_error", str(exc))
                fetched.add(item.normalized.normalized_url)
                self._mark_seed(scan.id, item.normalized.normalized_url, "failed")
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
        config: ScopeConfig,
        scope: ScopeEngine,
    ) -> tuple[ResourceSnapshot, list[Any]]:
        resource = get_or_create_resource(self.db, item.normalized)
        try:
            await validate_public_destination(item.requested_url, config.allow_private_networks)
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
            )
            result = await fetcher.get(item.requested_url)
            content_type = result.content_type
            is_html = "text/html" in (content_type or "").lower() or not content_type
            parsed = parse_html(result.content, result.final_url) if is_html else None
            blob = (
                self.store.put_html(self.db, result.content, content_type, result.encoding)
                if is_html
                else None
            )
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
            return self._record_failure(scan, item, connect_error_type(exc), str(exc)), []
        except UnsafeDestinationError as exc:
            return self._record_failure(scan, item, "unsafe_destination", str(exc)), []
        except httpx.InvalidURL as exc:
            return self._record_failure(scan, item, "invalid_url", str(exc)), []
        except ValueError as exc:
            return self._record_failure(scan, item, "invalid_url", str(exc)), []

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
