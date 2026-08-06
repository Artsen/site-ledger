from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.crawler.safe_fetch import FetchLimits, SafeFetchResult, SafeHttpFetcher
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.url_normalizer import UrlNormalizationError, normalize_url
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
from app.services.repositories import get_or_create_resource
from app.services.source_management import DuplicateSourceError, upsert_source_entry
from app.storage.ai_document_store import LocalAiDocumentStore


@dataclass(frozen=True)
class _QueuedDocument:
    url: str
    depth: int
    role: str
    explicit_relation: str | None
    ancestors: frozenset[str]


async def discover_ai_document_sources(
    db: Session,
    site_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AiDocumentDiscoveryResult | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    base = _origin(site.base_url)
    candidates: list[tuple[str, str, str | None]] = [
        (urljoin(base, "/llms.txt"), "conventional_root", "llms-txt"),
        (urljoin(base, "/.well-known/llms.txt"), "well_known", "llms-txt"),
    ]
    root_result: SafeFetchResult | None = None
    try:
        root_result = await _fetch(site, base, 256_000, transport)
        candidates.extend(_header_candidates(root_result))
    except Exception:
        pass
    unique: dict[str, tuple[str, str | None]] = {}
    for raw_url, method, relation in candidates:
        try:
            normalized = normalize_url(raw_url, site.base_url).normalized_url
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
            fetched = await _fetch(site, url, 5_000_000, transport)
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
    normalized = _in_scope_url(site, payload.entry_url)
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
                    AiDocumentValidation.refresh_id == latest.id
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
) -> AiDocumentRefresh:
    source = source_refresh.url_source
    if source.source_type != "ai_document" or not source.normalized_source_url:
        raise ValueError("AI Document Source entry URL is missing.")
    settings = AiDocumentSettings.model_validate(source.settings_json or {})
    store = store or LocalAiDocumentStore(get_settings().ai_document_storage_root)
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
    pending_references: list[AiDocumentReference] = []
    index_count = 0
    seen_inventory: set[str] = set()
    while queue and len(fetched) < settings.max_total_documents:
        if should_cancel and should_cancel():
            evidence.status = source_refresh.status = "cancelled"
            evidence.stop_reason = "cancelled_by_user"
            break
        item = queue.popleft()
        normalized = normalize_url(item.url, source.website_property.base_url).normalized_url
        if normalized in fetched:
            continue
        resource = get_or_create_resource(db, normalize_url(normalized))
        previous = _previous_snapshot(db, source.id, resource.id)
        headers = _conditional_headers(previous)
        try:
            result = await _fetch(
                source.website_property,
                normalized,
                settings.max_individual_document_bytes,
                transport,
                headers=headers,
            )
            evidence.total_network_bytes += result.network_bytes_transferred
            if evidence.total_network_bytes > settings.max_total_network_bytes:
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
            accepted = kind in {
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
                and evidence.total_retained_bytes + len(content)
                <= settings.max_total_retained_bytes
            ):
                blob = reused_blob or store.put(
                    db, content, _mime(result.content_type), result.encoding or "utf-8"
                )
                evidence.total_retained_bytes += len(content)
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
                fetch_state="saved" if blob else "metadata_only",
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
            evidence.document_discovered_count += 1
            evidence.document_fetched_count += 1
            evidence.document_saved_count += int(blob is not None)
            evidence.document_unchanged_count += int(change_state == "unchanged")
            evidence.document_changed_count += int(change_state in {"new", "changed"})
            if kind == "llms_index" and content is not None:
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
                for parsed_ref in parsed.references[: settings.max_references_per_document]:
                    reference, should_fetch = _reference(
                        db, source, evidence, snapshot, parsed_ref, item, fetched, seen_inventory
                    )
                    pending_references.append(reference)
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
                evidence.document_skipped_count += 1
            if progress_callback:
                source_refresh.discovered_entry_count = evidence.document_discovered_count
                source_refresh.accepted_entry_count = evidence.document_saved_count
                source_refresh.rejected_entry_count = evidence.document_failed_count
                progress_callback(source_refresh)
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
            evidence.document_discovered_count += 1
            evidence.document_failed_count += 1
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
    for reference in pending_references:
        child = fetched.get(reference.normalized_target_url or "")
        if child:
            reference.child_snapshot_id = child.id
    _mark_inventory_current(db, source.id, seen_inventory)
    evidence.reference_count = len(pending_references)
    evidence.cycle_count = sum(int(reference.forms_cycle) for reference in pending_references)
    warning_count = (
        db.scalar(
            select(func.count(AiDocumentValidation.id)).where(
                AiDocumentValidation.refresh_id == evidence.id
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
    db.flush()
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
    db.delete(source)
    db.flush()
    orphan_blobs = list(
        db.scalars(
            select(AiDocumentBlob).where(
                AiDocumentBlob.id.in_(candidate_blob_ids),
                ~select(AiDocumentSnapshot.id)
                .where(AiDocumentSnapshot.retained_blob_id == AiDocumentBlob.id)
                .exists(),
            )
        )
    )
    for blob in orphan_blobs:
        db.delete(blob)
    db.commit()
    for blob in orphan_blobs:
        store.delete(blob)
    return source_id


def _reference(
    db: Session,
    source: UrlSource,
    evidence: AiDocumentRefresh,
    snapshot: AiDocumentSnapshot,
    parsed_ref: ParsedAiReference,
    item: _QueuedDocument,
    fetched: dict[str, AiDocumentSnapshot],
    seen_inventory: set[str],
) -> tuple[AiDocumentReference, bool]:
    raw_url = parsed_ref.raw_url
    resolved = parsed_ref.resolved_url
    try:
        normalized = normalize_url(
            resolved, snapshot.final_url or snapshot.requested_url
        ).normalized_url
        scope = ScopeEngine(
            ScopeConfig.from_dict(source.website_property.scope_config),
            source.website_property.base_url,
        ).evaluate(normalized)
        resource = get_or_create_resource(db, normalize_url(normalized))
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
        db.flush()
        eligible_inventory = scope.in_scope and kind not in {
            "llms_index",
            "llms_full",
            "unsupported_binary",
            "external_reference",
        }
        if eligible_inventory:
            entry, _ = upsert_source_entry(
                db,
                source,
                normalized,
                site=source.website_property,
                source_type="ai_document",
                refresh_id=evidence.source_refresh_id,
                metadata={
                    "ai_refresh_id": evidence.id,
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
            )
            reference.inventory_entry_id = entry.id
            if entry.normalized_url:
                seen_inventory.add(entry.normalized_url)
        should_fetch = (
            scope.in_scope
            and not forms_cycle
            and (
                kind == "llms_index"
                or (
                    AiDocumentSettings.model_validate(
                        source.settings_json or {}
                    ).save_declared_documents
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
        db.flush()
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
    headers: dict[str, str] | None = None,
) -> SafeFetchResult:
    config = ScopeConfig.from_dict(site.scope_config)
    fetcher = SafeHttpFetcher(
        FetchLimits(
            timeout_seconds=config.request_timeout_seconds,
            max_response_bytes=max_bytes,
            max_redirects=config.max_redirects,
            user_agent=config.user_agent,
            allow_private_networks=config.allow_private_networks,
        ),
        transport=transport,
        redirect_validator=lambda redirect_url: _redirect(site, redirect_url),
    )
    return await fetcher.get(url, headers=headers)


async def _redirect(
    site: WebsiteProperty, url: str
) -> tuple[bool, str | None, str | None, str | None]:
    result = ScopeEngine(ScopeConfig.from_dict(site.scope_config), site.base_url).evaluate(url)
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


def _in_scope_url(site: WebsiteProperty, url: str) -> str:
    normalized = normalize_url(url, site.base_url).normalized_url
    result = ScopeEngine(ScopeConfig.from_dict(site.scope_config), site.base_url).evaluate(
        normalized
    )
    if not result.in_scope:
        raise ValueError(result.exclusion_reason or "Entry URL is outside Site scope.")
    return normalized


def _mime(value: str | None) -> str | None:
    return value.split(";", 1)[0].strip().casefold() if value else None


def _int_header(headers: dict[str, str], name: str) -> int | None:
    try:
        return int(headers[name]) if name in headers else None
    except ValueError:
        return None


def _previous_snapshot(db: Session, source_id: int, resource_id: int) -> AiDocumentSnapshot | None:
    return db.scalar(
        select(AiDocumentSnapshot)
        .join(AiDocumentRefresh)
        .join(SourceRefresh)
        .options(joinedload(AiDocumentSnapshot.blob))
        .where(
            SourceRefresh.url_source_id == source_id,
            AiDocumentSnapshot.resource_id == resource_id,
            AiDocumentSnapshot.retained_blob_id.is_not(None),
        )
        .order_by(AiDocumentSnapshot.id.desc())
        .limit(1)
    )


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


def _mark_inventory_current(db: Session, source_id: int, seen: set[str]) -> None:
    query = update(UrlSourceEntry).where(
        UrlSourceEntry.url_source_id == source_id, UrlSourceEntry.is_current.is_(True)
    )
    if seen:
        query = query.where(
            or_(UrlSourceEntry.normalized_url.is_(None), UrlSourceEntry.normalized_url.not_in(seen))
        )
    db.execute(query.values(is_current=False))
