from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.crawler.safe_fetch import FetchLimits, SafeFetchResult, SafeHttpFetcher
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.url_normalizer import UrlNormalizationError, normalize_url_for_version
from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    AiDocumentValidation,
    SourceRefresh,
    UrlSource,
    UrlSourceEntry,
    WebsiteProperty,
)
from app.parsers.ai_documents import (
    PARSER_VERSION,
    ParsedAiReference,
    classify_ai_document,
    parse_ai_index,
)
from app.schemas.ai_documents import (
    AiDocumentDiscoveryCandidate,
    AiDocumentDiscoveryResult,
    AiDocumentSettings,
    AiDocumentSourceCreate,
    AiDocumentSourceRead,
    AiSourceDeletePreview,
)
from app.services.ai_document_persistence import (
    AiDocumentBlobResolver,
    AiDocumentInventoryAccumulator,
    AiDocumentInventoryOrigin,
    AiDocumentPreviousSnapshotResolver,
    AiDocumentResourceResolver,
    link_refresh_children,
)
from app.services.source_management import (
    DuplicateSourceError,
    _delete_unreferenced_source_resources,
)
from app.services.url_identity import active_url_normalization_version
from app.storage.ai_document_store import LocalAiDocumentStore


@dataclass(frozen=True)
class _QueuedDocument:
    url: str
    depth: int
    role: str
    explicit_relation: str | None
    ancestors: frozenset[str]


@dataclass
class _RefreshStats:
    document_discovered_count: int = 0
    document_fetched_count: int = 0
    document_saved_count: int = 0
    document_unchanged_count: int = 0
    document_changed_count: int = 0
    document_failed_count: int = 0
    document_skipped_count: int = 0
    reference_count: int = 0
    cycle_count: int = 0
    total_network_bytes: int = 0
    total_retained_bytes: int = 0

    def apply(self, evidence: AiDocumentRefresh) -> None:
        evidence.document_discovered_count = self.document_discovered_count
        evidence.document_fetched_count = self.document_fetched_count
        evidence.document_saved_count = self.document_saved_count
        evidence.document_unchanged_count = self.document_unchanged_count
        evidence.document_changed_count = self.document_changed_count
        evidence.document_failed_count = self.document_failed_count
        evidence.document_skipped_count = self.document_skipped_count
        evidence.reference_count = self.reference_count
        evidence.cycle_count = self.cycle_count
        evidence.total_network_bytes = self.total_network_bytes
        evidence.total_retained_bytes = self.total_retained_bytes


class AiDocumentCancellationRequested(RuntimeError):
    pass


async def discover_ai_document_sources(
    db: Session,
    site_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AiDocumentDiscoveryResult | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    base = _origin(site.base_url)
    normalization_version = active_url_normalization_version(db)
    candidates: list[tuple[str, str, str | None]] = [
        (urljoin(base, "/llms.txt"), "conventional_root", "llms-txt"),
        (urljoin(base, "/.well-known/llms.txt"), "well_known", "llms-txt"),
    ]
    root_result: SafeFetchResult | None = None
    try:
        root_result = await _fetch(
            site, base, 256_000, transport, normalization_version=normalization_version
        )
        candidates.extend(_header_candidates(root_result))
    except Exception:
        pass
    unique: dict[str, tuple[str, str | None]] = {}
    for raw_url, method, relation in candidates:
        try:
            normalized = normalize_url_for_version(
                raw_url,
                normalization_version=normalization_version,
                base_url=site.base_url,
            ).normalized_url
        except (UrlNormalizationError, ValueError):
            continue
        unique.setdefault(normalized, (method, relation))
    existing = set(
        db.scalars(
            select(UrlSource.normalized_source_url).where(
                UrlSource.website_property_id == site.id,
                UrlSource.source_type == "ai_document",
            )
        )
    )
    results: list[AiDocumentDiscoveryCandidate] = []
    for url, (method, relation) in unique.items():
        try:
            fetched = await _fetch(
                site,
                url,
                5_000_000,
                transport,
                normalization_version=normalization_version,
            )
            status = (
                "found"
                if 200 <= fetched.http_status < 300
                else "not_found"
                if fetched.http_status == 404
                else "error"
            )
            results.append(
                AiDocumentDiscoveryCandidate(
                    url=fetched.final_url,
                    discovery_method=method,
                    relation=relation,
                    status=status,
                    http_status=fetched.http_status,
                    already_configured=url in existing,
                )
            )
        except Exception as exc:
            results.append(
                AiDocumentDiscoveryCandidate(
                    url=url,
                    discovery_method=method,
                    relation=relation,
                    status="blocked" if "unsafe" in type(exc).__name__.lower() else "error",
                    message=str(exc)[:1000],
                    already_configured=url in existing,
                )
            )
    return AiDocumentDiscoveryResult(candidates=results)


def create_ai_document_source(
    db: Session, site_id: int, payload: AiDocumentSourceCreate
) -> UrlSource | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    normalized = _in_scope_url(site, payload.entry_url, active_url_normalization_version(db))
    if db.scalar(
        select(UrlSource.id).where(
            UrlSource.website_property_id == site.id,
            UrlSource.source_type == "ai_document",
            UrlSource.normalized_source_url == normalized,
        )
    ):
        raise DuplicateSourceError("An AI Document Source with this entry URL already exists.")
    source = UrlSource(
        website_property_id=site.id,
        source_type="ai_document",
        name=payload.name.strip(),
        source_url=normalized,
        normalized_source_url=normalized,
        is_active=payload.is_active,
        discovery_mode=payload.discovery_mode,
        settings_json=payload.settings.model_dump(),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def get_ai_source(db: Session, source_id: int) -> AiDocumentSourceRead | None:
    source = db.scalar(
        select(UrlSource)
        .options(joinedload(UrlSource.website_property))
        .where(UrlSource.id == source_id, UrlSource.source_type == "ai_document")
    )
    if source is None or source.normalized_source_url is None:
        return None
    return _serialize_ai_source(db, source)


def update_ai_source(
    db: Session,
    source_id: int,
    *,
    entry_url: str | None = None,
    is_active: bool | None = None,
    settings: AiDocumentSettings | None = None,
) -> AiDocumentSourceRead | None:
    source = db.scalar(
        select(UrlSource).where(UrlSource.id == source_id, UrlSource.source_type == "ai_document")
    )
    if source is None:
        return None
    if entry_url is not None:
        normalized = _in_scope_url(
            source.website_property,
            entry_url,
            active_url_normalization_version(db),
        )
        duplicate = db.scalar(
            select(UrlSource.id).where(
                UrlSource.website_property_id == source.website_property_id,
                UrlSource.source_type == "ai_document",
                UrlSource.normalized_source_url == normalized,
                UrlSource.id != source.id,
            )
        )
        if duplicate:
            raise DuplicateSourceError("An AI Document Source with this entry URL already exists.")
        source.source_url = normalized
        source.normalized_source_url = normalized
    if is_active is not None:
        source.is_active = is_active
    if settings is not None:
        source.settings_json = settings.model_dump()
    db.commit()
    return get_ai_source(db, source.id)


def _serialize_ai_source(db: Session, source: UrlSource) -> AiDocumentSourceRead:
    assert source.normalized_source_url is not None
    latest_source_refresh = db.scalar(
        select(SourceRefresh)
        .where(SourceRefresh.url_source_id == source.id)
        .order_by(SourceRefresh.id.desc())
        .limit(1)
    )
    latest = db.scalar(
        select(AiDocumentRefresh)
        .join(SourceRefresh)
        .where(SourceRefresh.url_source_id == source.id)
        .order_by(AiDocumentRefresh.id.desc())
        .limit(1)
    )
    current = (
        db.scalar(
            select(func.count(UrlSourceEntry.id)).where(
                UrlSourceEntry.url_source_id == source.id, UrlSourceEntry.is_current.is_(True)
            )
        )
        or 0
    )
    warnings = 0
    if latest:
        warnings = (
            db.scalar(
                select(func.count(AiDocumentValidation.id)).where(
                    AiDocumentValidation.refresh_id == latest.id,
                    AiDocumentValidation.severity.in_({"warning", "error"}),
                )
            )
            or 0
        )
    return AiDocumentSourceRead(
        id=source.id,
        website_property_id=source.website_property_id,
        site_name=source.website_property.name,
        name=source.name,
        entry_url=source.normalized_source_url,
        discovery_mode=source.discovery_mode,
        is_active=source.is_active,
        settings=AiDocumentSettings.model_validate(source.settings_json or {}),
        last_refresh_status=source.last_refresh_status,
        last_successful_refresh_at=source.last_successful_refresh_at,
        current_entry_count=current,
        latest_refresh_id=latest.id if latest else None,
        latest_source_refresh_id=latest_source_refresh.id if latest_source_refresh else None,
        document_count=latest.document_saved_count if latest else 0,
        reference_count=latest.reference_count if latest else 0,
        warning_count=warnings,
        retained_bytes=latest.total_retained_bytes if latest else 0,
    )


async def execute_ai_document_refresh(
    db: Session,
    source_refresh: SourceRefresh,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[SourceRefresh], None] | None = None,
    store: LocalAiDocumentStore | None = None,
    performance_metrics: dict[str, float | int] | None = None,
) -> AiDocumentRefresh:
    refresh_started = perf_counter()
    source = source_refresh.url_source
    if source.source_type != "ai_document" or not source.normalized_source_url:
        raise ValueError("AI Document Source entry URL is missing.")
    settings = AiDocumentSettings.model_validate(source.settings_json or {})
    store = store or LocalAiDocumentStore(get_settings().ai_document_storage_root)
    normalization_version = active_url_normalization_version(db)
    scope_engine = ScopeEngine(
        ScopeConfig.from_dict(source.website_property.scope_config),
        source.website_property.base_url,
        normalization_version,
    )
    resource_resolver = AiDocumentResourceResolver(db, normalization_version)
    previous_resolver = AiDocumentPreviousSnapshotResolver(db, source.id)
    blob_resolver = AiDocumentBlobResolver(store)
    inventory = AiDocumentInventoryAccumulator()
    stats = _RefreshStats()
    evidence = AiDocumentRefresh(
        source_refresh_id=source_refresh.id,
        status="running",
        configuration_json=settings.model_dump(),
        root_candidate_count=1,
    )
    db.add(evidence)
    db.flush()
    queue = deque(
        [_QueuedDocument(source.normalized_source_url, 0, "root_index", "llms-txt", frozenset())]
    )
    fetched: dict[str, AiDocumentSnapshot] = {}
    index_count = 0
    while queue and len(fetched) < settings.max_total_documents:
        if should_cancel and should_cancel():
            evidence.status = source_refresh.status = "cancelled"
            evidence.stop_reason = "cancelled_by_user"
            break
        item = queue.popleft()
        normalized_value = normalize_url_for_version(
            item.url,
            normalization_version=normalization_version,
            base_url=source.website_property.base_url,
        )
        normalized = normalized_value.normalized_url
        if normalized in fetched:
            continue
        resource = resource_resolver.resolve(normalized_value)
        previous = previous_resolver.get(resource)
        headers = _conditional_headers(previous)
        try:
            result = await _fetch_document(
                source.website_property,
                normalized,
                settings,
                transport=transport,
                headers=headers,
                allow_external=settings.follow_external_documents,
                should_cancel=should_cancel,
                normalization_version=normalization_version,
            )
            stats.total_network_bytes += result.network_bytes_transferred
            if stats.total_network_bytes > settings.max_total_network_bytes:
                evidence.stop_reason = "max_total_network_bytes"
                _validation(
                    db, evidence, "warning", "budget_exhaustion", "Network byte budget was reached."
                )
                break
            content, reused_blob, change_state = _effective_content(result, previous, store)
            kind, rule = classify_ai_document(
                result.final_url,
                result.content_type,
                content,
                explicit_relation=item.explicit_relation,
            )
            response_mime = _mime(result.content_type)
            if response_mime in {"text/html", "application/xhtml+xml"}:
                kind, rule = "html_page_reference", "mime_html_response_mismatch"
                _validation(
                    db,
                    evidence,
                    "warning",
                    "document_representation_mismatch",
                    "The advertised AI document returned HTML; its body was not retained.",
                )
            elif response_mime and not (
                response_mime.startswith("text/")
                or "json" in response_mime
                or "yaml" in response_mime
            ):
                kind, rule = "unsupported_binary", "mime_unsupported_binary"
            successful_response = 200 <= result.http_status < 300 or result.http_status == 304
            accepted = successful_response and kind in {
                "llms_index",
                "llms_full",
                "markdown_document",
                "text_document",
                "openapi_specification",
                "asyncapi_specification",
                "json_document",
                "yaml_document",
            }
            blob = None
            if (
                accepted
                and content is not None
                and stats.total_retained_bytes + len(content) <= settings.max_total_retained_bytes
            ):
                blob = reused_blob or blob_resolver.put(
                    db, content, _mime(result.content_type), result.encoding or "utf-8"
                )
                stats.total_retained_bytes += len(content)
            elif accepted and content is not None:
                _validation(
                    db,
                    evidence,
                    "warning",
                    "budget_exhaustion",
                    "Retained byte budget was reached.",
                )
            snapshot = AiDocumentSnapshot(
                refresh_id=evidence.id,
                resource_id=resource.id,
                requested_url=normalized,
                final_url=result.final_url,
                parent_depth_min=item.depth,
                document_role=item.role,
                document_kind=kind,
                classification_rule=rule,
                fetch_state=(
                    "saved"
                    if blob
                    else "not_found"
                    if result.http_status == 404
                    else "http_error"
                    if not successful_response
                    else "metadata_only"
                ),
                http_status=result.http_status,
                normalized_mime_type=_mime(result.content_type),
                encoding=result.encoding or "utf-8",
                response_headers=result.headers,
                redirect_chain=result.redirect_chain,
                fetched_at=datetime.now(UTC),
                response_time_ms=result.response_time_ms,
                declared_content_length=_int_header(result.headers, "content-length"),
                network_bytes_transferred=result.network_bytes_transferred,
                retained_blob_id=blob.id if blob else None,
                raw_sha256=blob.sha256 if blob else None,
                parse_state="not_applicable",
                warning_count=0,
                change_state=change_state,
            )
            db.add(snapshot)
            db.flush()
            fetched[normalized] = snapshot
            stats.document_discovered_count += 1
            stats.document_fetched_count += 1
            stats.document_saved_count += int(blob is not None)
            stats.document_unchanged_count += int(change_state == "unchanged")
            stats.document_changed_count += int(change_state in {"new", "changed"})
            if not successful_response:
                stats.document_skipped_count += 1
                if result.http_status == 404 and item.depth == 0:
                    _validation(
                        db,
                        evidence,
                        "info",
                        "root_candidate_not_found",
                        "The configured AI document entry point was not found.",
                        snapshot=snapshot,
                    )
                else:
                    stats.document_failed_count += 1
                    _validation(
                        db,
                        evidence,
                        "warning",
                        "document_http_error",
                        f"Document retrieval returned HTTP {result.http_status}.",
                        snapshot=snapshot,
                    )
            elif kind == "llms_index" and content is not None:
                index_count += 1
                parsed = parse_ai_index(content, result.final_url, snapshot.encoding or "utf-8")
                snapshot.parsed_title, snapshot.parsed_summary, snapshot.parsed_intro = (
                    parsed.title,
                    parsed.summary,
                    parsed.introduction,
                )
                snapshot.parse_state, snapshot.parse_version = "parsed", PARSER_VERSION
                snapshot.parse_warnings_json, snapshot.warning_count = (
                    parsed.warnings,
                    len(parsed.warnings),
                )
                for warning in parsed.warnings:
                    _validation(
                        db,
                        evidence,
                        "warning",
                        warning["code"],
                        warning["message"],
                        snapshot=snapshot,
                    )
                parsed_references = parsed.references[: settings.max_references_per_document]
                normalized_references = []
                for parsed_ref in parsed_references:
                    try:
                        normalized_references.append(
                            normalize_url_for_version(
                                parsed_ref.resolved_url,
                                normalization_version=normalization_version,
                                base_url=snapshot.final_url or snapshot.requested_url,
                            )
                        )
                    except (UrlNormalizationError, ValueError):
                        continue
                resource_resolver.resolve_many(normalized_references)
                previous_resolver.prime(
                    resource_resolver.cache[item.normalized_url] for item in normalized_references
                )
                for parsed_ref in parsed_references:
                    reference, should_fetch = _reference(
                        db,
                        snapshot,
                        parsed_ref,
                        item,
                        settings,
                        scope_engine,
                        resource_resolver,
                        inventory,
                    )
                    stats.reference_count += 1
                    stats.cycle_count += int(reference.forms_cycle)
                    if (
                        should_fetch
                        and item.depth < settings.max_nesting_depth
                        and index_count < settings.max_index_documents
                    ):
                        queue.append(
                            _QueuedDocument(
                                reference.normalized_target_url or reference.resolved_url or "",
                                item.depth + 1,
                                "nested_index"
                                if reference.inferred_kind == "llms_index"
                                else "declared_document",
                                None,
                                item.ancestors | {normalized},
                            )
                        )
            elif kind in {"html_page_reference", "unsupported_binary", "unknown"}:
                stats.document_skipped_count += 1
            if progress_callback and stats.document_discovered_count % 50 == 0:
                stats.apply(evidence)
                source_refresh.discovered_entry_count = stats.document_discovered_count
                source_refresh.accepted_entry_count = stats.document_saved_count
                source_refresh.rejected_entry_count = stats.document_failed_count
                progress_callback(source_refresh)
        except AiDocumentCancellationRequested:
            evidence.status = source_refresh.status = "cancelled"
            evidence.stop_reason = "cancelled_by_user"
            break
        except Exception as exc:
            snapshot = AiDocumentSnapshot(
                refresh_id=evidence.id,
                resource_id=resource.id,
                requested_url=normalized,
                parent_depth_min=item.depth,
                document_role=item.role,
                document_kind="unknown",
                classification_rule="fetch_failure",
                fetch_state="failed",
                response_headers={},
                redirect_chain=[],
                network_bytes_transferred=0,
                parse_state="failed",
                warning_count=1,
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],
                change_state="unknown",
            )
            db.add(snapshot)
            db.flush()
            fetched[normalized] = snapshot
            stats.document_discovered_count += 1
            stats.document_failed_count += 1
            _validation(
                db,
                evidence,
                "warning",
                "document_fetch_failed",
                f"Document fetch failed: {str(exc)[:1000]}",
                snapshot=snapshot,
            )
    if queue and not evidence.stop_reason:
        evidence.stop_reason = "max_total_documents"
        _validation(
            db, evidence, "warning", "budget_exhaustion", "Document count limit was reached."
        )
    db.flush()
    link_refresh_children(db, evidence.id)
    inventory_started = perf_counter()
    inventory.persist(db, source, evidence)
    inventory_seconds = perf_counter() - inventory_started
    resource_resolver.touch_resolved()
    stats.apply(evidence)
    warning_count = (
        db.scalar(
            select(func.count(AiDocumentValidation.id)).where(
                AiDocumentValidation.refresh_id == evidence.id,
                AiDocumentValidation.severity.in_({"warning", "error"}),
            )
        )
        or 0
    )
    if evidence.status == "running":
        evidence.status = "completed_with_errors" if warning_count else "completed"
    source_refresh.status = evidence.status
    source_refresh.finished_at = datetime.now(UTC)
    source_refresh.discovered_entry_count = evidence.document_discovered_count
    source_refresh.accepted_entry_count = evidence.document_saved_count
    source_refresh.rejected_entry_count = evidence.document_failed_count
    source_refresh.warnings_json = [{"warning_count": warning_count}]
    if progress_callback:
        progress_callback(source_refresh)
    db.flush()
    if performance_metrics is not None:
        performance_metrics.update(
            {
                "inventory_seconds": inventory_seconds,
                "total_seconds": perf_counter() - refresh_started,
                "peak_batch_size": max(
                    resource_resolver.peak_batch_size,
                    previous_resolver.peak_batch_size,
                    inventory.peak_batch_size,
                ),
            }
        )
    return evidence


def preview_ai_source_deletion(db: Session, source_id: int) -> AiSourceDeletePreview | None:
    source = db.scalar(
        select(UrlSource).where(UrlSource.id == source_id, UrlSource.source_type == "ai_document")
    )
    if source is None:
        return None
    refresh_ids = (
        select(AiDocumentRefresh.id)
        .join(SourceRefresh)
        .where(SourceRefresh.url_source_id == source.id)
    )
    blob_ids = (
        select(AiDocumentSnapshot.retained_blob_id)
        .where(
            AiDocumentSnapshot.refresh_id.in_(refresh_ids),
            AiDocumentSnapshot.retained_blob_id.is_not(None),
        )
        .distinct()
    )
    unique_blobs = list(db.scalars(blob_ids))
    shared = 0
    reclaimable = 0
    for blob_id in unique_blobs:
        outside_count = (
            db.scalar(
                select(func.count(AiDocumentSnapshot.id)).where(
                    AiDocumentSnapshot.retained_blob_id == blob_id,
                    AiDocumentSnapshot.refresh_id.not_in(refresh_ids),
                )
            )
            or 0
        )
        if outside_count:
            shared += 1
        else:
            reclaimable += (
                db.scalar(
                    select(AiDocumentBlob.stored_byte_size).where(AiDocumentBlob.id == blob_id)
                )
                or 0
            )
    return AiSourceDeletePreview(
        refresh_count=db.scalar(
            select(func.count(SourceRefresh.id)).where(SourceRefresh.url_source_id == source.id)
        )
        or 0,
        snapshot_count=db.scalar(
            select(func.count(AiDocumentSnapshot.id)).where(
                AiDocumentSnapshot.refresh_id.in_(refresh_ids)
            )
        )
        or 0,
        reference_count=db.scalar(
            select(func.count(AiDocumentReference.id))
            .join(
                AiDocumentSnapshot, AiDocumentSnapshot.id == AiDocumentReference.parent_snapshot_id
            )
            .where(AiDocumentSnapshot.refresh_id.in_(refresh_ids))
        )
        or 0,
        current_inventory_origin_count=db.scalar(
            select(func.count(UrlSourceEntry.id)).where(
                UrlSourceEntry.url_source_id == source.id, UrlSourceEntry.is_current.is_(True)
            )
        )
        or 0,
        unique_blob_count=len(unique_blobs),
        shared_blob_count=shared,
        exclusive_blob_count=len(unique_blobs) - shared,
        reclaimable_storage_bytes=reclaimable,
    )


def delete_ai_source(db: Session, source_id: int, store: LocalAiDocumentStore) -> int | None:
    preview = preview_ai_source_deletion(db, source_id)
    if preview is None:
        return None
    source = db.get(UrlSource, source_id)
    assert source is not None
    refresh_ids = (
        select(AiDocumentRefresh.id)
        .join(SourceRefresh)
        .where(SourceRefresh.url_source_id == source.id)
    )
    candidate_blob_ids = list(
        db.scalars(
            select(AiDocumentSnapshot.retained_blob_id)
            .where(
                AiDocumentSnapshot.refresh_id.in_(refresh_ids),
                AiDocumentSnapshot.retained_blob_id.is_not(None),
            )
            .distinct()
        )
    )
    orphan_blobs = list(
        db.scalars(
            select(AiDocumentBlob).where(
                AiDocumentBlob.id.in_(candidate_blob_ids),
                ~select(AiDocumentSnapshot.id)
                .where(
                    AiDocumentSnapshot.retained_blob_id == AiDocumentBlob.id,
                    AiDocumentSnapshot.refresh_id.not_in(refresh_ids),
                )
                .exists(),
            )
        )
    )
    resource_ids = list(
        db.scalars(
            select(AiDocumentSnapshot.resource_id).where(
                AiDocumentSnapshot.refresh_id.in_(refresh_ids)
            )
        )
    ) + list(
        db.scalars(
            select(AiDocumentReference.target_resource_id)
            .join(
                AiDocumentSnapshot,
                AiDocumentSnapshot.id == AiDocumentReference.parent_snapshot_id,
            )
            .where(
                AiDocumentSnapshot.refresh_id.in_(refresh_ids),
                AiDocumentReference.target_resource_id.is_not(None),
            )
        )
    )
    for evidence in db.scalars(
        select(AiDocumentRefresh).where(AiDocumentRefresh.id.in_(refresh_ids))
    ):
        db.delete(evidence)
    db.flush()
    db.delete(source)
    db.flush()
    _delete_unreferenced_source_resources(
        db, [resource_id for resource_id in resource_ids if resource_id is not None]
    )
    for blob in orphan_blobs:
        db.delete(blob)
    db.commit()
    for blob in orphan_blobs:
        store.delete(blob)
    return source_id


def _reference(
    db: Session,
    snapshot: AiDocumentSnapshot,
    parsed_ref: ParsedAiReference,
    item: _QueuedDocument,
    settings: AiDocumentSettings,
    scope_engine: ScopeEngine,
    resource_resolver: AiDocumentResourceResolver,
    inventory: AiDocumentInventoryAccumulator,
) -> tuple[AiDocumentReference, bool]:
    raw_url = parsed_ref.raw_url
    resolved = parsed_ref.resolved_url
    try:
        scope = scope_engine.evaluate(resolved, snapshot.final_url or snapshot.requested_url)
        if scope.normalized is None:
            raise UrlNormalizationError(scope.exclusion_reason or "URL is invalid")
        normalized_value = scope.normalized
        normalized = normalized_value.normalized_url
        resource = resource_resolver.resolve(normalized_value)
        kind, rule = classify_ai_document(normalized, None, parent_kind="llms_index")
        forms_cycle = normalized in item.ancestors or normalized == snapshot.requested_url
        role = (
            "nested_index"
            if kind == "llms_index"
            else "corpus"
            if kind == "llms_full"
            else "declared_document"
        )
        reference = AiDocumentReference(
            parent_snapshot_id=snapshot.id,
            target_resource_id=resource.id,
            position=parsed_ref.position,
            section_title=parsed_ref.section_title,
            label=parsed_ref.label,
            description=parsed_ref.description,
            raw_url=raw_url,
            resolved_url=resolved,
            normalized_target_url=normalized,
            optional=parsed_ref.optional,
            inferred_role=role,
            inferred_kind=kind,
            classification_rule=rule,
            in_scope=scope.in_scope,
            scope_decision=scope.decision,
            exclusion_reason=scope.exclusion_reason,
            discovery_depth=item.depth + 1,
            forms_cycle=forms_cycle,
        )
        db.add(reference)
        eligible_inventory = scope.in_scope and kind not in {
            "llms_index",
            "llms_full",
            "unsupported_binary",
            "external_reference",
        }
        if eligible_inventory:
            inventory.add(
                normalized,
                AiDocumentInventoryOrigin(
                    resource_id=resource.id,
                    raw_url=raw_url,
                    scope_decision=scope.decision,
                    values={
                        "parent_snapshot_id": snapshot.id,
                        "parent_url": snapshot.final_url or snapshot.requested_url,
                        "section": reference.section_title,
                        "label": reference.label,
                        "description": reference.description,
                        "position": reference.position,
                        "optional": reference.optional,
                        "discovery_depth": reference.discovery_depth,
                        "raw_url": raw_url,
                        "resolved_url": resolved,
                    },
                ),
            )
        should_fetch = (
            (scope.in_scope or settings.follow_external_documents)
            and not forms_cycle
            and (
                kind == "llms_index"
                or (
                    settings.save_declared_documents
                    and kind
                    in {
                        "llms_full",
                        "markdown_document",
                        "text_document",
                        "openapi_specification",
                        "asyncapi_specification",
                        "json_document",
                        "yaml_document",
                    }
                )
            )
        )
        return reference, should_fetch
    except (UrlNormalizationError, ValueError) as exc:
        reference = AiDocumentReference(
            parent_snapshot_id=snapshot.id,
            position=parsed_ref.position,
            section_title=parsed_ref.section_title,
            label=parsed_ref.label,
            description=parsed_ref.description,
            raw_url=raw_url,
            resolved_url=resolved,
            optional=parsed_ref.optional,
            inferred_role="reference",
            inferred_kind="external_reference",
            classification_rule="invalid_or_unsupported_url",
            in_scope=False,
            scope_decision="invalid_url",
            exclusion_reason=str(exc)[:1000],
            discovery_depth=item.depth + 1,
        )
        db.add(reference)
        return reference, False


def _validation(
    db: Session,
    refresh: AiDocumentRefresh,
    severity: str,
    code: str,
    message: str,
    *,
    snapshot: AiDocumentSnapshot | None = None,
) -> None:
    db.add(
        AiDocumentValidation(
            refresh_id=refresh.id,
            snapshot_id=snapshot.id if snapshot else None,
            severity=severity,
            code=code,
            message=message[:2000],
            data_json={},
        )
    )


async def _fetch(
    site: WebsiteProperty,
    url: str,
    max_bytes: int,
    transport: httpx.AsyncBaseTransport | None,
    normalization_version: str,
    headers: dict[str, str] | None = None,
    allow_external: bool = False,
    timeout_seconds: float | None = None,
) -> SafeFetchResult:
    config = ScopeConfig.from_dict(site.scope_config)
    fetcher = SafeHttpFetcher(
        FetchLimits(
            timeout_seconds=timeout_seconds or config.request_timeout_seconds,
            max_response_bytes=max_bytes,
            max_redirects=config.max_redirects,
            user_agent=config.user_agent,
            allow_private_networks=config.allow_private_networks,
        ),
        transport=transport,
        redirect_validator=lambda redirect_url: _redirect(
            site, redirect_url, normalization_version, allow_external
        ),
    )
    return await fetcher.get(url, headers=headers)


async def _fetch_document(
    site: WebsiteProperty,
    url: str,
    settings: AiDocumentSettings,
    *,
    transport: httpx.AsyncBaseTransport | None,
    headers: dict[str, str],
    allow_external: bool,
    should_cancel: Callable[[], bool] | None,
    normalization_version: str,
) -> SafeFetchResult:
    for attempt in range(settings.max_attempts):
        if should_cancel and should_cancel():
            raise AiDocumentCancellationRequested("Cancellation requested during document retry.")
        try:
            result = await _fetch(
                site,
                url,
                settings.max_individual_document_bytes,
                transport,
                headers=headers,
                allow_external=allow_external,
                timeout_seconds=settings.request_timeout_seconds,
                normalization_version=normalization_version,
            )
            if result.http_status not in {408, 425, 429, 500, 502, 503, 504}:
                return result
            if attempt == settings.max_attempts - 1:
                return result
        except (httpx.TransportError, OSError):
            if attempt == settings.max_attempts - 1:
                raise
        await asyncio.sleep(min(1.0, 0.1 * (2**attempt)))
    raise RuntimeError("AI document retry loop ended unexpectedly.")


async def _redirect(
    site: WebsiteProperty,
    url: str,
    normalization_version: str,
    allow_external: bool = False,
) -> tuple[bool, str | None, str | None, str | None]:
    result = ScopeEngine(
        ScopeConfig.from_dict(site.scope_config), site.base_url, normalization_version
    ).evaluate(url)
    if allow_external and result.normalized is not None:
        return True, None, None, result.normalized.normalized_url
    if result.normalized is None or not result.in_scope:
        return (
            False,
            "scope_excluded",
            result.exclusion_reason,
            result.normalized.normalized_url if result.normalized else None,
        )
    return True, None, None, result.normalized.normalized_url


def _header_candidates(result: SafeFetchResult) -> list[tuple[str, str, str | None]]:
    found: list[tuple[str, str, str | None]] = []
    link = result.headers.get("link", "")
    for part in link.split(","):
        if "<" not in part or ">" not in part:
            continue
        target = part.split("<", 1)[1].split(">", 1)[0]
        lower = part.casefold()
        relation = (
            "llms-full-txt"
            if "llms-full-txt" in lower
            else "llms-txt"
            if "llms-txt" in lower
            else None
        )
        if relation:
            found.append((urljoin(result.final_url, target), "http_link_header", relation))
    if hint := result.headers.get("x-llms-txt"):
        found.append((urljoin(result.final_url, hint), "x_llms_txt_header", "llms-txt"))
    return found


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _in_scope_url(site: WebsiteProperty, url: str, normalization_version: str) -> str:
    result = ScopeEngine(
        ScopeConfig.from_dict(site.scope_config), site.base_url, normalization_version
    ).evaluate(url, site.base_url)
    if result.normalized is None:
        raise ValueError(result.exclusion_reason or "Entry URL is invalid.")
    if not result.in_scope:
        raise ValueError(result.exclusion_reason or "Entry URL is outside Site scope.")
    return result.normalized.normalized_url


def _mime(value: str | None) -> str | None:
    return value.split(";", 1)[0].strip().casefold() if value else None


def _int_header(headers: dict[str, str], name: str) -> int | None:
    try:
        return int(headers[name]) if name in headers else None
    except ValueError:
        return None


def _conditional_headers(previous: AiDocumentSnapshot | None) -> dict[str, str]:
    if previous is None:
        return {}
    headers: dict[str, str] = {}
    if etag := previous.response_headers.get("etag"):
        headers["If-None-Match"] = etag
    if modified := previous.response_headers.get("last-modified"):
        headers["If-Modified-Since"] = modified
    return headers


def _effective_content(
    result: SafeFetchResult, previous: AiDocumentSnapshot | None, store: LocalAiDocumentStore
) -> tuple[bytes | None, AiDocumentBlob | None, str]:
    if result.http_status == 304 and previous and previous.blob:
        return store.get(previous.blob), previous.blob, "unchanged"
    if not (200 <= result.http_status < 300):
        return None, None, "unknown"
    if previous and previous.raw_sha256:
        import hashlib

        state = (
            "unchanged"
            if hashlib.sha256(result.content).hexdigest() == previous.raw_sha256
            else "changed"
        )
        return result.content, None, state
    return result.content, None, "new"
