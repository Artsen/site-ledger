from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.safe_fetch import (
    FetchLimits,
    RedirectFailureError,
    ResponseTooLargeError,
    SafeFetchResult,
    SafeHttpFetcher,
    connect_error_type,
)
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.security import UnsafeDestinationError
from app.crawler.url_normalizer import normalize_url
from app.models import SourceRefresh, UrlSource, UrlSourceEntry, WebsiteProperty
from app.parsers.compression import (
    DecompressedResponseTooLargeError,
    InvalidGzipError,
    maybe_decompress_gzip,
)
from app.parsers.robots import parse_sitemap_directives
from app.parsers.sitemap import SitemapParseError, parse_sitemap_xml
from app.services.source_management import upsert_source_entry


@dataclass(frozen=True)
class RefreshLimits:
    max_response_bytes: int = 2_000_000
    max_decompressed_bytes: int = 10_000_000
    max_redirects: int = 10
    timeout_seconds: float = 10
    max_index_depth: int = 3
    max_child_sources: int = 100


async def refresh_source(
    db: Session,
    site_id: int,
    source_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SourceRefresh | None:
    refresh = create_source_refresh(db, site_id, source_id)
    if refresh is None:
        return None
    return await execute_source_refresh(db, refresh.id, transport=transport)


def create_source_refresh(
    db: Session, site_id: int, source_id: int, *, commit: bool = True
) -> SourceRefresh | None:
    source = db.scalar(
        select(UrlSource).where(
            UrlSource.id == source_id,
            UrlSource.website_property_id == site_id,
        )
    )
    if source is None:
        return None
    refresh = _start_refresh(db, source, status="queued")
    if commit:
        db.commit()
        db.refresh(refresh)
    return refresh


async def execute_source_refresh(
    db: Session,
    refresh_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[SourceRefresh], None] | None = None,
) -> SourceRefresh | None:
    refresh = db.get(SourceRefresh, refresh_id)
    if refresh is None:
        return None
    source = refresh.url_source
    limits = _limits_from_site(source.website_property)
    _start_existing_refresh(source, refresh)
    db.commit()
    try:
        _raise_if_cancelled(should_cancel)
        if source.source_type == "robots":
            await _refresh_robots(
                db,
                source,
                refresh,
                limits,
                transport,
                should_cancel,
                progress_callback,
            )
        elif source.source_type == "sitemap":
            await _refresh_sitemap(
                db,
                source,
                refresh,
                limits,
                transport,
                set(),
                0,
                should_cancel,
                progress_callback,
            )
        elif source.source_type == "manual":
            refresh.status = "completed"
            refresh.finished_at = datetime.now(UTC)
        else:
            raise ValueError(f"Unsupported source type: {source.source_type}")
    except SourceRefreshCancelled:
        refresh.status = "cancelled"
        refresh.error_type = "cancelled"
        refresh.error_message = "Refresh cancelled by user."
        refresh.finished_at = datetime.now(UTC)
    except Exception as exc:
        refresh.status = "failed"
        refresh.error_type = _error_type(exc)
        refresh.error_message = str(exc)
        refresh.finished_at = datetime.now(UTC)
    _finish_source(source, refresh)
    db.commit()
    db.refresh(refresh)
    return refresh


def create_robots_source(db: Session, site_id: int) -> UrlSource | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    robots_url = _robots_url(site.base_url)
    normalized = normalize_url(robots_url).normalized_url
    existing = db.scalar(
        select(UrlSource).where(
            UrlSource.website_property_id == site.id,
            UrlSource.source_type == "robots",
            UrlSource.normalized_source_url == normalized,
        )
    )
    if existing:
        return existing
    source = UrlSource(
        website_property_id=site.id,
        source_type="robots",
        name="robots.txt",
        source_url=normalized,
        normalized_source_url=normalized,
        is_active=True,
        discovery_mode="configured",
        settings_json={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


async def discover_from_robots(
    db: Session,
    site_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SourceRefresh | None:
    source = create_robots_source(db, site_id)
    if source is None:
        return None
    refresh = create_source_refresh(db, site_id, source.id)
    if refresh is None:
        return None
    return await execute_source_refresh(db, refresh.id, transport)


def create_robots_discovery_refresh(
    db: Session, site_id: int, *, commit: bool = True
) -> SourceRefresh | None:
    source = create_robots_source(db, site_id)
    if source is None:
        return None
    return create_source_refresh(db, site_id, source.id, commit=commit)


async def _refresh_robots(
    db: Session,
    source: UrlSource,
    refresh: SourceRefresh,
    limits: RefreshLimits,
    transport: httpx.AsyncBaseTransport | None,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[SourceRefresh], None] | None = None,
) -> None:
    if not source.normalized_source_url:
        raise ValueError("Robots source URL is missing.")
    result = await _fetch(source.website_property, source.normalized_source_url, limits, transport)
    _raise_if_cancelled(should_cancel)
    refresh.http_status = result.http_status
    refresh.fetched_url = result.requested_url
    refresh.final_url = result.final_url
    refresh.response_bytes = len(result.content)
    refresh.content_type = result.content_type
    directives = parse_sitemap_directives(result.content, result.final_url)
    refresh.discovered_entry_count = len(directives)
    child_count = 0
    for directive in directives[: limits.max_child_sources]:
        _raise_if_cancelled(should_cancel)
        normalized = normalize_url(directive.resolved_url).normalized_url
        existing = db.scalar(
            select(UrlSource).where(
                UrlSource.website_property_id == source.website_property_id,
                UrlSource.source_type == "sitemap",
                UrlSource.normalized_source_url == normalized,
            )
        )
        if existing:
            continue
        child = UrlSource(
            website_property_id=source.website_property_id,
            parent_source_id=source.id,
            root_source_id=source.id,
            source_type="sitemap",
            name=f"Sitemap from robots {child_count + 1}",
            source_url=normalized,
            normalized_source_url=normalized,
            is_active=True,
            discovery_mode="robots_discovered",
            settings_json={"raw_directive": directive.raw_value, "robots_url": source.source_url},
        )
        db.add(child)
        child_count += 1
    refresh.child_source_count = child_count
    refresh.accepted_entry_count = child_count
    refresh.rejected_entry_count = max(0, len(directives) - limits.max_child_sources)
    refresh.status = "completed" if refresh.rejected_entry_count == 0 else "completed_with_errors"
    refresh.finished_at = datetime.now(UTC)
    _progress(progress_callback, refresh)


async def _refresh_sitemap(
    db: Session,
    source: UrlSource,
    refresh: SourceRefresh,
    limits: RefreshLimits,
    transport: httpx.AsyncBaseTransport | None,
    seen_sources: set[str],
    depth: int,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[SourceRefresh], None] | None = None,
) -> None:
    _raise_if_cancelled(should_cancel)
    if not source.normalized_source_url:
        raise ValueError("Sitemap source URL is missing.")
    if source.normalized_source_url in seen_sources:
        raise ValueError("Sitemap cycle detected.")
    if depth > limits.max_index_depth:
        raise ValueError("Sitemap index recursion limit exceeded.")
    seen_sources.add(source.normalized_source_url)
    result = await _fetch(source.website_property, source.normalized_source_url, limits, transport)
    _raise_if_cancelled(should_cancel)
    refresh.http_status = result.http_status
    refresh.fetched_url = result.requested_url
    refresh.final_url = result.final_url
    refresh.response_bytes = len(result.content)
    refresh.content_type = result.content_type
    content, _decompressed = maybe_decompress_gzip(
        result.content,
        url=result.final_url,
        content_type=result.content_type,
        max_decompressed_bytes=limits.max_decompressed_bytes,
    )
    parsed = parse_sitemap_xml(content)
    if parsed.document_type == "urlset":
        seen_entries: set[str] = set()
        added = updated = accepted = rejected = 0
        for sitemap_url in parsed.urls:
            _raise_if_cancelled(should_cancel)
            entry, state = upsert_source_entry(
                db,
                source,
                sitemap_url.loc,
                site=source.website_property,
                source_type="sitemap",
                refresh_id=refresh.id,
                metadata={"document_type": "urlset"},
                sitemap_lastmod=sitemap_url.lastmod,
                sitemap_changefreq=sitemap_url.changefreq,
                sitemap_priority=sitemap_url.priority,
            )
            if entry.normalized_url:
                seen_entries.add(entry.normalized_url)
            if state == "added":
                added += 1
            else:
                updated += 1
            if entry.validation_state == "valid":
                accepted += 1
            else:
                rejected += 1
        no_longer = _mark_missing_not_current(db, source.id, seen_entries)
        refresh.discovered_entry_count = len(parsed.urls)
        refresh.accepted_entry_count = accepted
        refresh.rejected_entry_count = rejected
        refresh.entries_added = added
        refresh.entries_updated = updated
        refresh.entries_no_longer_current = no_longer
        refresh.status = "completed" if rejected == 0 else "completed_with_errors"
        refresh.finished_at = datetime.now(UTC)
        _progress(progress_callback, refresh)
        return
    child_count = 0
    warnings: list[dict[str, Any]] = []
    for child in parsed.children[: limits.max_child_sources]:
        _raise_if_cancelled(should_cancel)
        normalized = normalize_url(child.loc).normalized_url
        child_source = db.scalar(
            select(UrlSource).where(
                UrlSource.website_property_id == source.website_property_id,
                UrlSource.source_type == "sitemap",
                UrlSource.normalized_source_url == normalized,
            )
        )
        if child_source is None:
            child_source = UrlSource(
                website_property_id=source.website_property_id,
                parent_source_id=source.id,
                root_source_id=source.root_source_id or source.id,
                source_type="sitemap",
                name=f"Child sitemap {child_count + 1}",
                source_url=normalized,
                normalized_source_url=normalized,
                is_active=True,
                discovery_mode="sitemap_index_discovered",
                settings_json={"parent_lastmod": child.lastmod},
            )
            db.add(child_source)
            db.flush()
        child_count += 1
        child_refresh = _start_refresh(db, child_source)
        try:
            await _refresh_sitemap(
                db,
                child_source,
                child_refresh,
                limits,
                transport,
                seen_sources,
                depth + 1,
                should_cancel,
                progress_callback,
            )
        except Exception as exc:
            child_refresh.status = "failed"
            child_refresh.error_type = _error_type(exc)
            child_refresh.error_message = str(exc)
            child_refresh.finished_at = datetime.now(UTC)
            warnings.append({"source_url": normalized, "error_type": child_refresh.error_type})
        _finish_source(child_source, child_refresh)
    refresh.child_source_count = child_count
    refresh.discovered_entry_count = len(parsed.children)
    refresh.accepted_entry_count = child_count
    refresh.rejected_entry_count = max(0, len(parsed.children) - limits.max_child_sources)
    refresh.warnings_json = warnings
    refresh.status = (
        "completed"
        if not warnings and refresh.rejected_entry_count == 0
        else "completed_with_errors"
    )
    refresh.finished_at = datetime.now(UTC)
    _progress(progress_callback, refresh)


async def _fetch(
    site: WebsiteProperty,
    url: str,
    limits: RefreshLimits,
    transport: httpx.AsyncBaseTransport | None,
) -> SafeFetchResult:
    config = ScopeConfig.from_dict(site.scope_config)
    fetcher = SafeHttpFetcher(
        FetchLimits(
            timeout_seconds=limits.timeout_seconds,
            max_response_bytes=limits.max_response_bytes,
            max_redirects=limits.max_redirects,
            user_agent=config.user_agent,
            allow_private_networks=config.allow_private_networks,
        ),
        transport=transport,
        redirect_validator=lambda redirect_url: _validate_redirect(site, redirect_url),
    )
    return await fetcher.get(url)


async def _validate_redirect(
    site: WebsiteProperty, url: str
) -> tuple[bool, str | None, str | None, str | None]:
    config = ScopeConfig.from_dict(site.scope_config)
    result = ScopeEngine(config, site.base_url).evaluate(url)
    if result.normalized is None:
        return False, result.decision, result.exclusion_reason, None
    if result.decision != "crawlable":
        return False, "scope_excluded", result.exclusion_reason, result.normalized.normalized_url
    return True, None, None, result.normalized.normalized_url


class SourceRefreshCancelled(RuntimeError):
    pass


def _raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel and should_cancel():
        raise SourceRefreshCancelled("Cancellation requested.")


def _progress(
    progress_callback: Callable[[SourceRefresh], None] | None, refresh: SourceRefresh
) -> None:
    if progress_callback:
        progress_callback(refresh)


def _start_refresh(db: Session, source: UrlSource, status: str = "running") -> SourceRefresh:
    now = datetime.now(UTC)
    refresh = SourceRefresh(
        url_source_id=source.id,
        status=status,
        started_at=now,
        response_bytes=0,
        discovered_entry_count=0,
        accepted_entry_count=0,
        rejected_entry_count=0,
        child_source_count=0,
        entries_added=0,
        entries_updated=0,
        entries_no_longer_current=0,
        warnings_json=[],
    )
    source.last_refresh_status = status
    source.last_refresh_started_at = now if status == "running" else None
    db.add(refresh)
    db.flush()
    return refresh


def _start_existing_refresh(source: UrlSource, refresh: SourceRefresh) -> None:
    now = datetime.now(UTC)
    refresh.status = "running"
    refresh.started_at = now
    refresh.finished_at = None
    refresh.error_type = None
    refresh.error_message = None
    source.last_refresh_status = "running"
    source.last_refresh_started_at = now


def _finish_source(source: UrlSource, refresh: SourceRefresh) -> None:
    source.last_refresh_status = refresh.status
    source.last_refresh_started_at = refresh.started_at
    source.last_refresh_finished_at = refresh.finished_at
    source.last_http_status = refresh.http_status
    source.last_error_type = refresh.error_type
    source.last_error_message = refresh.error_message
    if refresh.status in {"completed", "completed_with_errors"}:
        source.last_successful_refresh_at = refresh.finished_at


def _mark_missing_not_current(db: Session, source_id: int, seen_entries: set[str]) -> int:
    query = select(UrlSourceEntry).where(
        UrlSourceEntry.url_source_id == source_id,
        UrlSourceEntry.is_current.is_(True),
    )
    if seen_entries:
        query = query.where(UrlSourceEntry.normalized_url.not_in(seen_entries))
    stale = list(db.scalars(query))
    for entry in stale:
        entry.is_current = False
    return len(stale)


def _limits_from_site(site: WebsiteProperty) -> RefreshLimits:
    config = ScopeConfig.from_dict(site.scope_config)
    return RefreshLimits(
        max_response_bytes=config.max_html_response_bytes,
        max_decompressed_bytes=max(
            config.max_html_response_bytes * 5, config.max_html_response_bytes
        ),
        max_redirects=config.max_redirects,
        timeout_seconds=config.request_timeout_seconds,
    )


def _robots_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, "/robots.txt", "", ""))


def _error_type(exc: Exception) -> str:
    if isinstance(exc, ResponseTooLargeError):
        return "response_too_large"
    if isinstance(exc, DecompressedResponseTooLargeError):
        return "decompressed_response_too_large"
    if isinstance(exc, InvalidGzipError):
        return "invalid_gzip"
    if isinstance(exc, SitemapParseError):
        return "sitemap_parse_error"
    if isinstance(exc, RedirectFailureError):
        return exc.error_type
    if isinstance(exc, httpx.ConnectTimeout):
        return "connection_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.ConnectError):
        return connect_error_type(exc)
    if isinstance(exc, UnsafeDestinationError):
        return "unsafe_destination"
    return "connection_error"
