from __future__ import annotations

import difflib
import hashlib
import json
from collections import Counter
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    ContentBlob,
    RenderedObservation,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanComparisonLinkResult,
    ScanComparisonPageResult,
    ScanComparisonResourceResult,
    ScanComparisonSummary,
    SitePage,
)
from app.schemas.comparisons import (
    ComparisonLinkList,
    ComparisonLinkRead,
    ComparisonPageList,
    ComparisonPageRead,
    ComparisonResourceList,
    ComparisonResourceRead,
    ComparisonScanRead,
    OccurrenceDiffList,
    OccurrenceDiffRead,
    PageChangeHistoryItem,
    PageChangeHistoryList,
    ScanComparisonBuildRead,
    ScanComparisonList,
    ScanComparisonOverview,
    ScanComparisonRead,
    SourceDiffRead,
)
from app.services.scan_comparisons import current_comparison_build
from app.services.source_comparison import SourceAnalysis, analyze_source, normalize_volatile_source
from app.storage.content_store import BlobNotFoundError, LocalContentStore

SOURCE_DIFF_MAX_INPUT_BYTES = 1024 * 1024
SOURCE_DIFF_MAX_LINES = 5000
SOURCE_DIFF_MAX_OUTPUT_BYTES = 1024 * 1024
OCCURRENCE_DIFF_MAX_COMPARE = 20_000


def list_comparisons(
    db: Session, site_id: int, *, limit: int = 50, offset: int = 0
) -> ScanComparisonList:
    query = select(ScanComparison).where(ScanComparison.website_property_id == site_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(ScanComparison.created_at.desc(), ScanComparison.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return ScanComparisonList(
        items=[_comparison_read(db, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_comparison_overview(
    db: Session, site_id: int, comparison_id: int
) -> ScanComparisonOverview | None:
    comparison = _site_comparison(db, site_id, comparison_id)
    if comparison is None:
        return None
    summary: dict[str, Any] | None = None
    build = current_comparison_build(db, comparison.id)
    if build:
        row = db.scalar(
            select(ScanComparisonSummary).where(
                ScanComparisonSummary.comparison_build_id == build.id
            )
        )
        if row:
            summary = {
                "pages": row.page_counts_json,
                "resources": row.resource_counts_json,
                "links": row.link_counts_json,
                "scan": row.scan_summary_delta_json,
            }
    return ScanComparisonOverview(comparison=_comparison_read(db, comparison), summary=summary)


def list_comparison_pages(
    db: Session,
    site_id: int,
    comparison_id: int,
    *,
    search: str | None = None,
    presence: str | None = None,
    change: str | None = None,
    content: str | None = None,
    head: str | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    changed_only: bool = True,
    http_changed: bool | None = None,
    baseline_status: int | None = None,
    target_status: int | None = None,
    redirect_changed: bool | None = None,
    links_changed: bool | None = None,
    rendered_changed: bool | None = None,
    sort: str = "url",
    direction: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> ComparisonPageList | None:
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    query: Select[Any] = select(ScanComparisonPageResult).where(
        ScanComparisonPageResult.comparison_build_id == build.id
    )
    if search:
        query = query.where(ScanComparisonPageResult.normalized_url.ilike(f"%{search}%"))
    if presence:
        query = query.where(ScanComparisonPageResult.presence_state == presence)
    if change:
        query = query.where(ScanComparisonPageResult.change_state == change)
    elif changed_only:
        query = query.where(
            or_(
                ScanComparisonPageResult.primary_change_class.in_(
                    ("substantive_change", "metadata_change", "technical_change")
                ),
                ScanComparisonPageResult.presence_state != "observed_in_both",
            )
        )
    if content:
        query = query.where(ScanComparisonPageResult.content_state == content)
    if head:
        query = query.where(ScanComparisonPageResult.head_state == head)
    if host:
        query = query.where(ScanComparisonPageResult.host == host.lower())
    if path_prefix:
        query = query.where(ScanComparisonPageResult.path.startswith(path_prefix))
    filters = {
        ScanComparisonPageResult.http_status_changed: http_changed,
        ScanComparisonPageResult.redirect_state_changed: redirect_changed,
        ScanComparisonPageResult.rendered_state_changed: rendered_changed,
    }
    for column, value in filters.items():
        if value is not None:
            query = query.where(column == value)
    if links_changed is not None:
        query = query.where(
            or_(
                ScanComparisonPageResult.inbound_links_changed == links_changed,
                ScanComparisonPageResult.outbound_links_changed == links_changed,
            )
        )
    if baseline_status is not None:
        query = query.where(ScanComparisonPageResult.baseline_http_status == baseline_status)
    if target_status is not None:
        query = query.where(ScanComparisonPageResult.target_http_status == target_status)
    sort_map = {
        "url": ScanComparisonPageResult.normalized_url,
        "presence": ScanComparisonPageResult.presence_state,
        "change": ScanComparisonPageResult.change_state,
        "content": ScanComparisonPageResult.document_content_state,
        "metadata": ScanComparisonPageResult.metadata_state,
        "technical": ScanComparisonPageResult.technical_state,
        "raw_source": ScanComparisonPageResult.exact_source_state,
        "baseline_status": ScanComparisonPageResult.baseline_http_status,
        "target_status": ScanComparisonPageResult.target_http_status,
        "changed_field_count": ScanComparisonPageResult.changed_field_count,
        "response_time_delta": ScanComparisonPageResult.response_time_ms_delta,
        "byte_delta": ScanComparisonPageResult.network_bytes_delta,
        "link_change_count": (
            ScanComparisonPageResult.outgoing_edges_newly_observed
            + ScanComparisonPageResult.outgoing_edges_not_observed
            + ScanComparisonPageResult.outgoing_edges_changed
            + ScanComparisonPageResult.incoming_edges_newly_observed
            + ScanComparisonPageResult.incoming_edges_not_observed
            + ScanComparisonPageResult.incoming_edges_changed
        ),
    }
    return _page_list(
        db, build, query, sort_map.get(sort, sort_map["url"]), direction, limit, offset
    )


def get_comparison_page(
    db: Session, site_id: int, comparison_id: int, resource_id: int
) -> ComparisonPageRead | None:
    from app.services.url_identity import resolve_resource_id

    resource_id = resolve_resource_id(db, resource_id) or resource_id
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    row = db.scalar(
        select(ScanComparisonPageResult).where(
            ScanComparisonPageResult.comparison_build_id == build.id,
            ScanComparisonPageResult.resource_id == resource_id,
        )
    )
    if row is None:
        return None
    result = ComparisonPageRead.model_validate(row)
    for side, snapshot_id in (
        ("baseline_json", result.baseline_snapshot_id),
        ("target_json", result.target_snapshot_id),
    ):
        snapshot = db.get(ResourceSnapshot, snapshot_id) if snapshot_id else None
        if snapshot:
            values = dict(getattr(result, side) or {})
            values.update(
                {
                    "meta_description": snapshot.meta_description,
                    "redirect_chain": snapshot.redirect_chain,
                    "retrieval_method": snapshot.retrieval_method,
                    "parse_method": snapshot.parse_method,
                    "retrieval_http_status": snapshot.retrieval_http_status,
                    "reused_from_snapshot_id": snapshot.reused_from_snapshot_id,
                }
            )
            setattr(result, side, values)
    return result


def list_comparison_resources(
    db: Session,
    site_id: int,
    comparison_id: int,
    *,
    search: str | None = None,
    presence: str | None = None,
    change: str | None = None,
    kind: str | None = None,
    mime: str | None = None,
    host: str | None = None,
    status_changed: bool | None = None,
    observed_state_changed: bool | None = None,
    sort: str = "url",
    direction: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> ComparisonResourceList | None:
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    query: Select[Any] = select(ScanComparisonResourceResult).where(
        ScanComparisonResourceResult.comparison_build_id == build.id
    )
    if search:
        query = query.where(ScanComparisonResourceResult.normalized_url.ilike(f"%{search}%"))
    for column, value in (
        (ScanComparisonResourceResult.presence_state, presence),
        (ScanComparisonResourceResult.change_state, change),
        (ScanComparisonResourceResult.target_kind, kind),
        (ScanComparisonResourceResult.target_mime_type, mime),
        (ScanComparisonResourceResult.host, host.lower() if host else None),
        (ScanComparisonResourceResult.status_changed, status_changed),
        (ScanComparisonResourceResult.observed_state_changed, observed_state_changed),
    ):
        if value is not None:
            query = query.where(column == value)
    sort_map = {
        "url": ScanComparisonResourceResult.normalized_url,
        "presence": ScanComparisonResourceResult.presence_state,
        "change": ScanComparisonResourceResult.change_state,
        "kind": ScanComparisonResourceResult.target_kind,
        "mime": ScanComparisonResourceResult.target_mime_type,
        "status": ScanComparisonResourceResult.target_http_status,
        "size_delta": ScanComparisonResourceResult.declared_size_delta,
        "occurrence_delta": ScanComparisonResourceResult.occurrence_delta,
        "source_page_delta": ScanComparisonResourceResult.source_page_delta,
    }
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order: Any = sort_map.get(sort, sort_map["url"])
    order = order.desc() if direction == "desc" else order.asc()
    rows = db.scalars(
        query.order_by(order, ScanComparisonResourceResult.id).limit(limit).offset(offset)
    )
    return ComparisonResourceList(
        items=[ComparisonResourceRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        comparison_build_id=build.id,
        comparison_version=build.comparison_version,
    )


def get_comparison_resource(
    db: Session, site_id: int, comparison_id: int, resource_id: int
) -> ComparisonResourceRead | None:
    from app.services.url_identity import resolve_resource_id

    resource_id = resolve_resource_id(db, resource_id) or resource_id
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    row = db.scalar(
        select(ScanComparisonResourceResult).where(
            ScanComparisonResourceResult.comparison_build_id == build.id,
            ScanComparisonResourceResult.resource_id == resource_id,
        )
    )
    return ComparisonResourceRead.model_validate(row) if row else None


def list_comparison_links(
    db: Session,
    site_id: int,
    comparison_id: int,
    *,
    search: str | None = None,
    presence: str | None = None,
    change: str | None = None,
    role: str | None = None,
    scope: str | None = None,
    min_occurrence_delta: int | None = None,
    sort: str = "source",
    direction: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> ComparisonLinkList | None:
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    query: Select[Any] = select(ScanComparisonLinkResult).where(
        ScanComparisonLinkResult.comparison_build_id == build.id
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ScanComparisonLinkResult.source_url.ilike(pattern),
                ScanComparisonLinkResult.target_url.ilike(pattern),
            )
        )
    if presence:
        query = query.where(ScanComparisonLinkResult.presence_state == presence)
    if change:
        query = query.where(ScanComparisonLinkResult.change_state == change)
    if role:
        query = query.where(
            or_(
                ScanComparisonLinkResult.baseline_json["role_counts_json"][role].as_integer() > 0,
                ScanComparisonLinkResult.target_json["role_counts_json"][role].as_integer() > 0,
            )
        )
    if scope:
        query = query.where(
            or_(
                ScanComparisonLinkResult.baseline_json["scope_counts_json"][scope].as_integer() > 0,
                ScanComparisonLinkResult.target_json["scope_counts_json"][scope].as_integer() > 0,
            )
        )
    if min_occurrence_delta is not None:
        query = query.where(
            func.abs(ScanComparisonLinkResult.occurrence_delta) >= min_occurrence_delta
        )
    sort_map = {
        "source": ScanComparisonLinkResult.source_url,
        "target": ScanComparisonLinkResult.target_url,
        "presence": ScanComparisonLinkResult.presence_state,
        "change": ScanComparisonLinkResult.change_state,
        "baseline_occurrences": ScanComparisonLinkResult.baseline_occurrence_count,
        "target_occurrences": ScanComparisonLinkResult.target_occurrence_count,
        "occurrence_delta": ScanComparisonLinkResult.occurrence_delta,
    }
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order: Any = sort_map.get(sort, sort_map["source"])
    order = order.desc() if direction == "desc" else order.asc()
    rows = db.scalars(
        query.order_by(order, ScanComparisonLinkResult.id).limit(limit).offset(offset)
    )
    return ComparisonLinkList(
        items=[ComparisonLinkRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        comparison_build_id=build.id,
        comparison_version=build.comparison_version,
    )


def get_comparison_link(
    db: Session,
    site_id: int,
    comparison_id: int,
    source_resource_id: int,
    target_resource_id: int,
) -> ComparisonLinkRead | None:
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    row = db.scalar(
        select(ScanComparisonLinkResult).where(
            ScanComparisonLinkResult.comparison_build_id == build.id,
            ScanComparisonLinkResult.source_resource_id == source_resource_id,
            ScanComparisonLinkResult.target_resource_id == target_resource_id,
        )
    )
    return ComparisonLinkRead.model_validate(row) if row else None


def link_occurrence_diff(
    db: Session,
    site_id: int,
    comparison_id: int,
    source_resource_id: int,
    target_resource_id: int,
    *,
    limit: int,
    offset: int,
) -> OccurrenceDiffList | None:
    build = _ready_build(db, site_id, comparison_id)
    if build is None:
        return None
    result = db.scalar(
        select(ScanComparisonLinkResult).where(
            ScanComparisonLinkResult.comparison_build_id == build.id,
            ScanComparisonLinkResult.source_resource_id == source_resource_id,
            ScanComparisonLinkResult.target_resource_id == target_resource_id,
        )
    )
    if result is None:
        return None
    before = _edge_occurrences(db, result.baseline_source_snapshot_id, target_resource_id)
    after = _edge_occurrences(db, result.target_source_snapshot_id, target_resource_id)
    truncated = (
        len(before) > OCCURRENCE_DIFF_MAX_COMPARE or len(after) > OCCURRENCE_DIFF_MAX_COMPARE
    )
    before = before[:OCCURRENCE_DIFF_MAX_COMPARE]
    after = after[:OCCURRENCE_DIFF_MAX_COMPARE]
    before_counts = Counter(item[0] for item in before)
    after_counts = Counter(item[0] for item in after)
    samples = {fingerprint: payload for fingerprint, payload in [*before, *after]}
    items: list[OccurrenceDiffRead] = []
    for fingerprint in sorted(set(before_counts) | set(after_counts)):
        common = min(before_counts[fingerprint], after_counts[fingerprint])
        if common:
            items.append(
                OccurrenceDiffRead(
                    state="present_in_both",
                    fingerprint=fingerprint,
                    occurrence=samples[fingerprint],
                    count=common,
                )
            )
        if after_counts[fingerprint] > common:
            items.append(
                OccurrenceDiffRead(
                    state="newly_observed",
                    fingerprint=fingerprint,
                    occurrence=samples[fingerprint],
                    count=after_counts[fingerprint] - common,
                )
            )
        if before_counts[fingerprint] > common:
            items.append(
                OccurrenceDiffRead(
                    state="not_observed_in_target",
                    fingerprint=fingerprint,
                    occurrence=samples[fingerprint],
                    count=before_counts[fingerprint] - common,
                )
            )
    return OccurrenceDiffList(
        items=items[offset : offset + limit],
        total=len(items),
        limit=limit,
        offset=offset,
        compared_baseline_count=len(before),
        compared_target_count=len(after),
        truncated=truncated,
    )


def page_source_diff(
    db: Session,
    store: LocalContentStore,
    site_id: int,
    comparison_id: int,
    resource_id: int,
    *,
    mode: str = "exact",
) -> SourceDiffRead | None:
    result = get_comparison_page(db, site_id, comparison_id, resource_id)
    if result is None:
        return None
    before = (
        db.get(ResourceSnapshot, result.baseline_snapshot_id)
        if result.baseline_snapshot_id
        else None
    )
    after = (
        db.get(ResourceSnapshot, result.target_snapshot_id) if result.target_snapshot_id else None
    )
    if before is None or before.html_blob_id is None:
        return SourceDiffRead(state="baseline_missing", diff_text="", mode=mode)
    if after is None or after.html_blob_id is None:
        return SourceDiffRead(state="target_missing", diff_text="", mode=mode)
    before_blob = db.get(ContentBlob, before.html_blob_id)
    after_blob = db.get(ContentBlob, after.html_blob_id)
    if before_blob is None:
        return SourceDiffRead(state="baseline_missing", diff_text="", mode=mode)
    if after_blob is None:
        return SourceDiffRead(state="target_missing", diff_text="", mode=mode)
    if (
        before_blob.raw_byte_size > SOURCE_DIFF_MAX_INPUT_BYTES
        or after_blob.raw_byte_size > SOURCE_DIFF_MAX_INPUT_BYTES
    ):
        return SourceDiffRead(state="too_large", diff_text="", mode=mode)
    try:
        before_bytes, after_bytes = store.get(before_blob), store.get(after_blob)
        before_text = before_bytes.decode(before_blob.encoding or "utf-8", errors="strict")
        after_text = after_bytes.decode(after_blob.encoding or "utf-8", errors="strict")
    except (BlobNotFoundError, LookupError, UnicodeDecodeError):
        return SourceDiffRead(state="decoding_failed", diff_text="", mode=mode)
    if mode == "meaningful":
        before_text = normalize_volatile_source(before_text)[0]
        after_text = normalize_volatile_source(after_text)[0]
    if before_text == after_text:
        return SourceDiffRead(state="identical", diff_text="", mode=mode)
    lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile="Baseline",
            tofile="Target",
            lineterm="",
        )
    )
    output_truncated = len(lines) > SOURCE_DIFF_MAX_LINES
    text = "\n".join(lines[:SOURCE_DIFF_MAX_LINES])
    encoded = text.encode("utf-8")
    if len(encoded) > SOURCE_DIFF_MAX_OUTPUT_BYTES:
        text = encoded[:SOURCE_DIFF_MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        output_truncated = True
    return SourceDiffRead(
        state="truncated" if output_truncated else "available",
        diff_text=text,
        mode=mode,
        output_truncated=output_truncated,
    )


def page_change_history(
    db: Session,
    site_id: int,
    resource_id: int,
    *,
    store: LocalContentStore | None = None,
    limit: int,
    offset: int,
) -> PageChangeHistoryList | None:
    from app.services.url_identity import resolve_resource_id

    resource_id = resolve_resource_id(db, resource_id) or resource_id
    if not db.scalar(
        select(SitePage.id).where(
            SitePage.website_property_id == site_id, SitePage.resource_id == resource_id
        )
    ):
        return None
    scans = list(
        db.scalars(
            select(Scan)
            .where(Scan.website_property_id == site_id)
            .order_by(Scan.created_at, Scan.id)
        )
    )
    scan_positions = {scan.id: position for position, scan in enumerate(scans)}
    rows = db.execute(
        select(ResourceSnapshot, Scan, RenderedObservation.capture_state)
        .options(joinedload(ResourceSnapshot.blob))
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .outerjoin(RenderedObservation, RenderedObservation.snapshot_id == ResourceSnapshot.id)
        .where(
            Scan.website_property_id == site_id,
            ResourceSnapshot.resource_id == resource_id,
            or_(
                ResourceSnapshot.representation_kind == "html_page",
                ResourceSnapshot.html_blob_id.is_not(None),
                ResourceSnapshot.content_type.ilike("text/html%"),
                ResourceSnapshot.content_type.ilike("application/xhtml+xml%"),
            ),
        )
        .order_by(Scan.created_at, Scan.id, ResourceSnapshot.id)
    ).all()
    items: list[PageChangeHistoryItem] = []
    previous: tuple[ResourceSnapshot, Scan, str | None] | None = None
    source_cache: dict[int, SourceAnalysis | None] = {}
    for snapshot, scan, rendered_state in rows:
        flags = _history_flags(
            previous[0] if previous else None,
            snapshot,
            previous[2] if previous else None,
            rendered_state,
            store,
            source_cache,
        )
        intervening = 0
        if previous:
            intervening = max(scan_positions[scan.id] - scan_positions[previous[1].id] - 1, 0)
        items.append(
            PageChangeHistoryItem(
                scan_id=scan.id,
                snapshot_id=snapshot.id,
                scan_created_at=scan.created_at,
                scan_status=scan.status,
                observed_at=snapshot.fetched_at,
                http_status=snapshot.http_status,
                fetch_state=snapshot.fetch_state,
                content_hash=snapshot.raw_html_sha256,
                head_hash=snapshot.head_sha256,
                title=snapshot.page_title,
                canonical_url=snapshot.canonical_url,
                robots_directives=snapshot.meta_robots,
                rendered_state=rendered_state,
                change_label=_history_label(flags, previous is None),
                changed_flags=flags,
                previous_snapshot_id=previous[0].id if previous else None,
                previous_scan_id=previous[1].id if previous else None,
                intervening_scan_count=intervening,
                intervening_unsuccessful_observation_count=intervening,
            )
        )
        previous = (snapshot, scan, rendered_state)
    return PageChangeHistoryList(
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


def _page_list(
    db: Session,
    build: ScanComparisonBuild,
    query: Select[Any],
    order: Any,
    direction: str,
    limit: int,
    offset: int,
) -> ComparisonPageList:
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = order.desc() if direction == "desc" else order.asc()
    rows = db.scalars(
        query.order_by(order, ScanComparisonPageResult.id).limit(limit).offset(offset)
    )
    return ComparisonPageList(
        items=[ComparisonPageRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        comparison_build_id=build.id,
        comparison_version=build.comparison_version,
    )


def _comparison_read(db: Session, comparison: ScanComparison) -> ScanComparisonRead:
    baseline = db.get(Scan, comparison.baseline_scan_id)
    target = db.get(Scan, comparison.target_scan_id)
    assert baseline is not None and target is not None
    active = db.scalar(
        select(ScanComparisonBuild)
        .where(
            ScanComparisonBuild.scan_comparison_id == comparison.id,
            ScanComparisonBuild.active_key.is_not(None),
        )
        .order_by(ScanComparisonBuild.id.desc())
    )
    current = (
        db.get(ScanComparisonBuild, comparison.current_build_id)
        if comparison.current_build_id
        else None
    )
    return ScanComparisonRead(
        id=comparison.id,
        website_property_id=comparison.website_property_id,
        baseline_scan_id=comparison.baseline_scan_id,
        target_scan_id=comparison.target_scan_id,
        current_build_id=comparison.current_build_id,
        created_at=comparison.created_at,
        updated_at=comparison.updated_at,
        baseline_scan=_scan_read(baseline),
        target_scan=_scan_read(target),
        current_build=ScanComparisonBuildRead.model_validate(current) if current else None,
        active_build=ScanComparisonBuildRead.model_validate(active) if active else None,
    )


def _scan_read(scan: Scan) -> ComparisonScanRead:
    return ComparisonScanRead(
        id=scan.id,
        status=scan.status,
        starting_url=scan.starting_url,
        created_at=scan.created_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        stop_reason=scan.stop_reason,
        failed_count=scan.failed_count,
    )


def _site_comparison(db: Session, site_id: int, comparison_id: int) -> ScanComparison | None:
    return db.scalar(
        select(ScanComparison).where(
            ScanComparison.id == comparison_id, ScanComparison.website_property_id == site_id
        )
    )


def _ready_build(db: Session, site_id: int, comparison_id: int) -> ScanComparisonBuild | None:
    comparison = _site_comparison(db, site_id, comparison_id)
    return current_comparison_build(db, comparison.id) if comparison else None


def _edge_occurrences(
    db: Session, source_snapshot_id: int | None, target_resource_id: int
) -> list[tuple[str, dict[str, Any]]]:
    if source_snapshot_id is None:
        return []
    rows = db.scalars(
        select(ResourceOccurrence)
        .where(
            ResourceOccurrence.source_snapshot_id == source_snapshot_id,
            ResourceOccurrence.target_resource_id == target_resource_id,
        )
        .order_by(ResourceOccurrence.id)
    )
    result = []
    for row in rows:
        payload = {
            "raw_href": row.raw_href,
            "resolved_url": row.resolved_url,
            "anchor_text": row.anchor_text,
            "title": row.title,
            "aria_label": row.aria_label,
            "rel": row.rel,
            "target": row.target,
            "dom_path": row.dom_path,
            "scope_decision": row.scope_decision,
            "link_role": row.link_role,
            "link_role_rule": row.link_role_rule,
            "link_context": row.link_context_json,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result.append((fingerprint, payload))
    return result


def _history_flags(
    before: ResourceSnapshot | None,
    after: ResourceSnapshot,
    before_rendered: str | None,
    after_rendered: str | None,
    store: LocalContentStore | None,
    source_cache: dict[int, SourceAnalysis | None],
) -> list[str]:
    if before is None:
        return []
    fields = {
        "head_metadata": (before.head_sha256, after.head_sha256),
        "http_status": (before.http_status, after.http_status),
        "redirect": (before.final_url, after.final_url),
        "rendered_summary": (before_rendered, after_rendered),
    }
    flags = [name for name, values in fields.items() if values[0] != values[1]]
    if before.raw_html_sha256 != after.raw_html_sha256:
        before_source = _history_source_analysis(before, store, source_cache)
        after_source = _history_source_analysis(after, store, source_cache)
        if (
            before_source is not None
            and after_source is not None
            and before_source.document_content_hash == after_source.document_content_hash
        ):
            flags.insert(0, "source")
        else:
            flags.insert(0, "content")
    return flags


def _history_source_analysis(
    snapshot: ResourceSnapshot,
    store: LocalContentStore | None,
    cache: dict[int, SourceAnalysis | None],
) -> SourceAnalysis | None:
    if snapshot.blob is None or store is None:
        return None
    if snapshot.blob.id not in cache:
        try:
            content = store.get(snapshot.blob)
        except BlobNotFoundError:
            cache[snapshot.blob.id] = None
        else:
            cache[snapshot.blob.id] = analyze_source(
                content, snapshot.blob.encoding or snapshot.encoding
            )
    return cache[snapshot.blob.id]


def _history_label(flags: list[str], first: bool) -> str:
    if first:
        return "First observation"
    if not flags:
        return "No tracked change"
    if len(flags) > 1:
        return "Multiple tracked changes"
    labels = {
        "content": "Content changed",
        "source": "Technical/source change",
        "head_metadata": "Head metadata changed",
        "http_status": "HTTP status changed",
        "redirect": "Redirect changed",
        "rendered_summary": "Rendered summary changed",
    }
    return labels[flags[0]]
