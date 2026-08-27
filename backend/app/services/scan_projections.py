from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, TypeVar

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import (
    ContentBlob,
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    ScanLinkProjection,
    ScanPageProjection,
    ScanProjectionBuild,
    ScanProjectionState,
    ScanResourceProjection,
    ScanSeed,
    ScanSeedOrigin,
    ScanSummaryProjection,
)
from app.schemas.projections import ProjectionMetadata, ScanProjectionStatusRead
from app.services.job_types import ExecutionOwnershipLost

SCAN_PROJECTION_VERSION = "scan-projection-v2"
CURRENT_SCAN_PROJECTION_ALGORITHM = "scan-projection-v2:resource-classifier-v1:link-role-v1"
LEGACY_COMPATIBLE_SCAN_PROJECTION_ALGORITHMS: frozenset[str] = frozenset()
# Retain the original exported name for callers while new code uses the explicit current identity.
SCAN_PROJECTION_ALGORITHM = CURRENT_SCAN_PROJECTION_ALGORITHM
TERMINAL_SCAN_STATUSES = {
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
    "interrupted",
}
ACTIVE_BUILD_STATUSES = {"queued", "building"}
PROJECTION_BATCH_SIZE = 400
T = TypeVar("T")


class ProjectionBuildCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectionContext:
    scan: Scan | None
    build: ScanProjectionBuild | None


def is_compatible_projection_algorithm(value: str) -> bool:
    return (
        value == CURRENT_SCAN_PROJECTION_ALGORITHM
        or value in LEGACY_COMPATIBLE_SCAN_PROJECTION_ALGORITHMS
    )


def _chunks(items: list[T], size: int = PROJECTION_BATCH_SIZE) -> Iterable[list[T]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def current_projection_build(db: Session, scan_id: int) -> ScanProjectionBuild | None:
    state = db.get(ScanProjectionState, scan_id)
    if state is None or state.current_build_id is None:
        return None
    build = db.get(ScanProjectionBuild, state.current_build_id)
    if (
        build is None
        or build.status != "ready"
        or build.projection_version != SCAN_PROJECTION_VERSION
        or not is_compatible_projection_algorithm(build.algorithm_identity)
    ):
        return None
    return build


def resolve_projection_context(db: Session, scan_id: int) -> ProjectionContext:
    row = db.execute(
        select(Scan, ScanProjectionBuild)
        .options(joinedload(Scan.website_property))
        .outerjoin(ScanProjectionState, ScanProjectionState.scan_id == Scan.id)
        .outerjoin(
            ScanProjectionBuild,
            ScanProjectionBuild.id == ScanProjectionState.current_build_id,
        )
        .where(Scan.id == scan_id)
    ).one_or_none()
    if row is None:
        return ProjectionContext(None, None)
    scan, build = row
    compatible = (
        build
        if build is not None
        and build.status == "ready"
        and build.projection_version == SCAN_PROJECTION_VERSION
        and is_compatible_projection_algorithm(build.algorithm_identity)
        else None
    )
    return ProjectionContext(scan, compatible)


def materialized_metadata(build: ScanProjectionBuild) -> ProjectionMetadata:
    return ProjectionMetadata(
        projection_source="materialized",
        projection_version=build.projection_version,
        projection_build_id=build.id,
        projection_status="ready",
    )


def dynamic_metadata(scan: Scan | None) -> ProjectionMetadata:
    return ProjectionMetadata(
        projection_source="dynamic",
        projection_version=SCAN_PROJECTION_VERSION,
        projection_status=(
            "missing" if scan and scan.status in TERMINAL_SCAN_STATUSES else "not_terminal"
        ),
    )


def projection_metadata(db: Session, scan_id: int) -> ProjectionMetadata:
    scan = db.get(Scan, scan_id)
    build = current_projection_build(db, scan_id)
    if build is not None:
        return ProjectionMetadata(
            projection_source="materialized",
            projection_version=build.projection_version,
            projection_build_id=build.id,
            projection_status="ready",
        )
    active = db.scalar(
        select(ScanProjectionBuild)
        .where(
            ScanProjectionBuild.scan_id == scan_id,
            ScanProjectionBuild.active_key.is_not(None),
        )
        .order_by(ScanProjectionBuild.id.desc())
    )
    status = active.status if active else "missing"
    if scan is not None and scan.status not in TERMINAL_SCAN_STATUSES:
        status = "not_terminal"
    return ProjectionMetadata(
        projection_source="dynamic",
        projection_version=SCAN_PROJECTION_VERSION,
        projection_status=status,
    )


def projection_status(db: Session, scan_id: int) -> ScanProjectionStatusRead | None:
    scan = db.get(Scan, scan_id)
    if scan is None:
        return None
    state = db.get(ScanProjectionState, scan_id)
    current = (
        db.get(ScanProjectionBuild, state.current_build_id)
        if state and state.current_build_id
        else None
    )
    active = db.scalar(
        select(ScanProjectionBuild)
        .where(
            ScanProjectionBuild.scan_id == scan_id,
            ScanProjectionBuild.active_key.is_not(None),
        )
        .order_by(ScanProjectionBuild.id.desc())
    )
    latest = db.scalar(
        select(ScanProjectionBuild)
        .where(ScanProjectionBuild.scan_id == scan_id)
        .order_by(ScanProjectionBuild.id.desc())
    )
    compatible = current_projection_build(db, scan_id)
    return ScanProjectionStatusRead(
        scan_id=scan.id,
        scan_status=scan.status,
        expected_version=SCAN_PROJECTION_VERSION,
        projection_source="materialized" if compatible else "dynamic",
        projection_status=(
            active.status
            if active
            else latest.status
            if compatible
            and latest
            and latest.id != compatible.id
            and latest.status in {"failed", "cancelled"}
            else "ready"
            if compatible
            else "version_mismatch"
            if current and current.projection_version != SCAN_PROJECTION_VERSION
            else latest.status
            if latest and latest.status in {"failed", "cancelled"}
            else "version_mismatch"
            if current
            else "missing"
            if scan.status in TERMINAL_SCAN_STATUSES
            else "not_terminal"
        ),
        current_build=current,
        active_build=active,
        latest_build=latest,
        can_build=scan.status in TERMINAL_SCAN_STATUSES and active is None,
        can_rebuild=compatible is not None and active is None,
    )


def create_projection_build(
    db: Session, scan_id: int, *, force: bool = False
) -> ScanProjectionBuild:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise ValueError("Scan not found.")
    if scan.status not in TERMINAL_SCAN_STATUSES:
        raise ValueError("Only terminal Scans can build optimized results.")
    active = db.scalar(
        select(ScanProjectionBuild).where(
            ScanProjectionBuild.scan_id == scan_id,
            ScanProjectionBuild.active_key.is_not(None),
        )
    )
    if active is not None:
        return active
    current = current_projection_build(db, scan_id)
    if current is not None and not force:
        return current
    build = ScanProjectionBuild(
        scan_id=scan_id,
        projection_version=SCAN_PROJECTION_VERSION,
        algorithm_identity=CURRENT_SCAN_PROJECTION_ALGORITHM,
        status="queued",
        active_key=f"{scan_id}:{SCAN_PROJECTION_VERSION}",
        validation_json={},
    )
    try:
        with db.begin_nested():
            db.add(build)
            db.flush()
    except IntegrityError:
        concurrent = db.scalar(
            select(ScanProjectionBuild).where(
                ScanProjectionBuild.scan_id == scan_id,
                ScanProjectionBuild.active_key.is_not(None),
            )
        )
        if concurrent is not None:
            return concurrent
        raise
    if db.get(ScanProjectionState, scan_id) is None:
        db.add(ScanProjectionState(scan_id=scan_id))
        db.flush()
    return build


def execute_projection_build(
    db: Session,
    build_id: int,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> ScanProjectionBuild:
    build = db.get(ScanProjectionBuild, build_id)
    if build is None:
        raise ValueError("Projection build not found.")
    scan = db.get(Scan, build.scan_id)
    if scan is None or scan.status not in TERMINAL_SCAN_STATUSES:
        raise ValueError("Projection source Scan is not terminal.")
    started = perf_counter()
    build.status = "building"
    build.started_at = datetime.now(UTC)
    build.error_type = build.error_message = None
    db.commit()
    try:
        _clear_staged_rows(db, build.id)
        pages = _page_rows(db, scan)
        _check_cancelled(should_cancel)
        _insert_batches(db, ScanPageProjection, pages, build.id, progress, "pages", should_cancel)
        resources, resource_summary = _resource_rows(db, scan.id)
        _check_cancelled(should_cancel)
        _insert_batches(
            db,
            ScanResourceProjection,
            resources,
            build.id,
            progress,
            "resources",
            should_cancel,
        )
        links = _link_rows(db, scan.id, pages)
        _check_cancelled(should_cancel)
        _insert_batches(db, ScanLinkProjection, links, build.id, progress, "links", should_cancel)
        summary = _summary_row(db, scan, build.id, pages, resources, links, resource_summary)
        db.execute(insert(ScanSummaryProjection), [summary])
        db.flush()
        validation = _validate_build(db, scan, build.id, pages, resources, links)
        checksum = _projection_checksum(pages, resources, links, summary)
        state = db.get(ScanProjectionState, scan.id)
        assert state is not None
        _check_cancelled(should_cancel)
        prior_id = state.current_build_id
        now = datetime.now(UTC)
        build.status = "ready"
        build.active_key = None
        build.finished_at = now
        build.page_count = len(pages)
        build.resource_count = len(resources)
        build.link_edge_count = len(links)
        build.graph_node_count = len(pages)
        build.graph_edge_count = len(links)
        build.rendered_page_count = 0
        build.source_snapshot_count = validation["source_snapshot_count"]
        build.source_link_occurrence_count = validation["source_link_occurrence_count"]
        build.source_resource_reference_count = validation["source_resource_reference_count"]
        build.build_duration_ms = int((perf_counter() - started) * 1000)
        build.checksum_sha256 = checksum
        build.validation_json = validation
        state.current_build_id = build.id
        if prior_id and prior_id != build.id:
            prior = db.get(ScanProjectionBuild, prior_id)
            if prior is not None:
                prior.status = "superseded"
        db.commit()
        db.refresh(build)
        return build
    except ProjectionBuildCancelled:
        _finish_failed_build(db, build, "cancelled", "cancelled", "Build cancelled by user.")
        raise
    except ExecutionOwnershipLost:
        db.rollback()
        raise
    except Exception as exc:
        _finish_failed_build(db, build, "failed", type(exc).__name__, str(exc))
        raise


def verify_projection_build(db: Session, scan_id: int) -> dict[str, Any]:
    build = current_projection_build(db, scan_id)
    if build is None:
        raise ValueError("No current compatible projection exists.")
    scan = db.get(Scan, scan_id)
    assert scan is not None
    pages = list(
        db.execute(
            select(ScanPageProjection).where(ScanPageProjection.projection_build_id == build.id)
        ).scalars()
    )
    resources = list(
        db.execute(
            select(ScanResourceProjection).where(
                ScanResourceProjection.projection_build_id == build.id
            )
        ).scalars()
    )
    links = list(
        db.execute(
            select(ScanLinkProjection).where(ScanLinkProjection.projection_build_id == build.id)
        ).scalars()
    )
    validation = _validate_build(db, scan, build.id, pages, resources, links)
    return {
        **validation,
        "checksum_sha256": build.checksum_sha256,
        "projection_version": build.projection_version,
    }


def mark_projection_build_terminal(
    db: Session,
    build_id: int,
    status: str,
    error_type: str,
    error_message: str,
    *,
    commit: bool = True,
) -> None:
    build = db.get(ScanProjectionBuild, build_id)
    if build is not None and build.status in ACTIVE_BUILD_STATUSES:
        _finish_failed_build(db, build, status, error_type, error_message, commit=commit)


def delete_scan_projection_data(db: Session, scan_id: int) -> None:
    build_ids = select(ScanProjectionBuild.id).where(ScanProjectionBuild.scan_id == scan_id)
    for model in (
        ScanSummaryProjection,
        ScanLinkProjection,
        ScanResourceProjection,
        ScanPageProjection,
    ):
        db.execute(delete(model).where(model.projection_build_id.in_(build_ids)))
    db.execute(delete(ScanProjectionState).where(ScanProjectionState.scan_id == scan_id))
    db.execute(delete(ScanProjectionBuild).where(ScanProjectionBuild.scan_id == scan_id))


def _page_rows(db: Session, scan: Scan) -> list[dict[str, Any]]:
    snapshots = list(
        db.scalars(
            select(ResourceSnapshot)
            .options(joinedload(ResourceSnapshot.resource), joinedload(ResourceSnapshot.blob))
            .where(
                ResourceSnapshot.scan_id == scan.id,
                or_(
                    ResourceSnapshot.representation_kind == "html_page",
                    ResourceSnapshot.html_blob_id.is_not(None),
                    ResourceSnapshot.content_type.ilike("text/html%"),
                    ResourceSnapshot.content_type.ilike("application/xhtml+xml%"),
                ),
            )
            .order_by(ResourceSnapshot.requested_url, ResourceSnapshot.id)
        )
    )
    snapshot_ids = [item.id for item in snapshots]
    inbound: dict[int, tuple[int, int, str | None]] = {
        resource_id: (occurrence_count, source_count, discovery_source)
        for resource_id, occurrence_count, source_count, discovery_source in db.execute(
            select(
                ResourceOccurrence.target_resource_id,
                func.count(ResourceOccurrence.id),
                func.count(func.distinct(ResourceOccurrence.source_snapshot_id)),
                func.min(func.coalesce(ResourceSnapshot.final_url, ResourceSnapshot.requested_url)),
            )
            .join(
                ResourceSnapshot,
                ResourceSnapshot.id == ResourceOccurrence.source_snapshot_id,
            )
            .where(ResourceSnapshot.scan_id == scan.id)
            .group_by(ResourceOccurrence.target_resource_id)
        )
        if resource_id is not None
    }
    outbound = {
        snapshot_id: (occurrence_count, target_count)
        for snapshot_id, occurrence_count, target_count in db.execute(
            select(
                ResourceOccurrence.source_snapshot_id,
                func.count(ResourceOccurrence.id),
                func.count(func.distinct(ResourceOccurrence.target_resource_id)),
            )
            .where(
                ResourceOccurrence.source_snapshot_id.in_(snapshot_ids),
                ResourceOccurrence.relation_type == "page_link",
            )
            .group_by(ResourceOccurrence.source_snapshot_id)
        )
    }
    embedded: dict[int, int] = {
        snapshot_id: count
        for snapshot_id, count in db.execute(
            select(
                ResourceReferenceOccurrence.source_snapshot_id,
                func.count(ResourceReferenceOccurrence.id),
            )
            .where(ResourceReferenceOccurrence.source_snapshot_id.in_(snapshot_ids))
            .group_by(ResourceReferenceOccurrence.source_snapshot_id)
        )
    }
    seed_counts: dict[int, int] = {
        resource_id: count
        for resource_id, count in db.execute(
            select(ScanSeed.resource_id, func.count(ScanSeedOrigin.id))
            .outerjoin(ScanSeedOrigin, ScanSeedOrigin.scan_seed_id == ScanSeed.id)
            .where(ScanSeed.scan_id == scan.id)
            .group_by(ScanSeed.resource_id)
        )
        if resource_id is not None
    }
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        resource = snapshot.resource
        outbound_values = outbound.get(snapshot.id, (0, 0))
        inbound_values = inbound.get(resource.id, (0, 0, None))
        blob: ContentBlob | None = snapshot.blob
        rows.append(
            {
                "projection_build_id": 0,
                "scan_id": scan.id,
                "snapshot_id": snapshot.id,
                "resource_id": resource.id,
                "requested_url": snapshot.requested_url,
                "final_url": snapshot.final_url,
                "normalized_url": resource.normalized_url,
                "host": resource.host,
                "path": resource.path,
                "page_title": snapshot.page_title,
                "crawl_depth": snapshot.crawl_depth,
                "fetch_state": snapshot.fetch_state,
                "http_status": snapshot.http_status,
                "error_type": snapshot.error_type,
                "error_message": snapshot.error_message,
                "content_type": snapshot.content_type,
                "content_hash": snapshot.raw_html_sha256,
                "head_hash": snapshot.head_sha256,
                "canonical_url": snapshot.canonical_url,
                "robots_directives": snapshot.meta_robots,
                "language": snapshot.html_language,
                "redirects": bool(snapshot.redirect_chain),
                "response_time_ms": snapshot.response_time_ms,
                "network_bytes_transferred": snapshot.network_bytes_transferred,
                "raw_html_size": blob.raw_byte_size if blob else None,
                "stored_html_size": blob.stored_byte_size if blob else None,
                "inbound_source_page_count": inbound_values[1],
                "inbound_occurrence_count": inbound_values[0],
                "outbound_target_count": outbound_values[1],
                "outbound_occurrence_count": outbound_values[0],
                "embedded_resource_count": embedded.get(snapshot.id, 0),
                "discovery_source": inbound_values[2],
                "is_seed": resource.id in seed_counts,
                "seed_origin_count": seed_counts.get(resource.id, 0),
                "is_starting_page": scan.starting_url
                in {snapshot.requested_url, snapshot.final_url},
                "rendered_capture_state": None,
                "rendered_network_count": 0,
                "rendered_console_count": 0,
                "rendered_page_error_count": 0,
                "rendered_artifact_count": 0,
                "rendered_captured_at": None,
                "fetched_at": snapshot.fetched_at,
            }
        )
    return rows


def _resource_rows(db: Session, scan_id: int) -> tuple[list[dict[str, Any]], Any]:
    from app.services.resource_queries import (
        list_scan_resources_dynamic,
        scan_resource_summary_dynamic,
    )

    first = list_scan_resources_dynamic(db, scan_id, limit=1)
    assert first is not None
    listed = list_scan_resources_dynamic(db, scan_id, limit=max(first.total, 1))
    assert listed is not None
    rows = [
        {
            "projection_build_id": 0,
            "scan_id": scan_id,
            "resource_id": item.resource_id,
            "normalized_url": item.normalized_url,
            "host": item.host,
            "path": item.path,
            "file_extension": item.file_extension,
            "effective_kind": item.effective_kind,
            "classification_source": item.classification_source,
            "observed": item.observed,
            "discovered_only": item.discovered_only,
            "latest_snapshot_id": item.snapshot_id,
            "final_url": item.final_url,
            "http_status": item.http_status,
            "normalized_mime_type": item.normalized_mime_type,
            "content_disposition_filename": item.content_disposition_filename,
            "declared_content_length": item.declared_content_length,
            "network_bytes_transferred": item.network_bytes_transferred,
            "fetched_at": item.fetched_at,
            "response_time_ms": item.response_time_ms,
            "occurrence_count": item.occurrence_count,
            "source_page_count": item.source_page_count,
            "anchor_occurrence_count": item.anchor_occurrence_count,
            "embedded_occurrence_count": item.embedded_occurrence_count,
            "in_scope_occurrence_count": item.in_scope_occurrence_count,
            "out_of_scope_occurrence_count": item.out_of_scope_occurrence_count,
            "first_discovered_at": item.first_discovered_at,
            "latest_discovered_at": item.latest_discovered_at,
            "observation_count": item.observation_count,
        }
        for item in listed.items
    ]
    return rows, scan_resource_summary_dynamic(db, scan_id)


def _link_rows(db: Session, scan_id: int, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    page_by_snapshot = {row["snapshot_id"]: row for row in pages}
    snapshot_by_resource = {row["resource_id"]: row["snapshot_id"] for row in pages}
    occurrences = db.scalars(
        select(ResourceOccurrence)
        .join(ResourceSnapshot, ResourceSnapshot.id == ResourceOccurrence.source_snapshot_id)
        .where(
            ResourceSnapshot.scan_id == scan_id,
            ResourceOccurrence.relation_type == "page_link",
            ResourceOccurrence.target_resource_id.is_not(None),
        )
        .order_by(ResourceOccurrence.id)
    )
    aggregates: dict[tuple[int, int], dict[str, Any]] = {}
    anchors: defaultdict[tuple[int, int], set[str]] = defaultdict(set)
    for occurrence in occurrences:
        if (
            occurrence.source_snapshot_id not in page_by_snapshot
            or occurrence.target_resource_id is None
        ):
            continue
        key = (occurrence.source_snapshot_id, occurrence.target_resource_id)
        source = page_by_snapshot[occurrence.source_snapshot_id]
        row = aggregates.setdefault(
            key,
            {
                "projection_build_id": 0,
                "scan_id": scan_id,
                "source_snapshot_id": occurrence.source_snapshot_id,
                "source_resource_id": source["resource_id"],
                "target_resource_id": occurrence.target_resource_id,
                "target_snapshot_id": snapshot_by_resource.get(occurrence.target_resource_id),
                "occurrence_count": 0,
                "unique_anchor_count": 0,
                "empty_anchor_count": 0,
                "follow_count": 0,
                "nofollow_count": 0,
                "self_link": source["resource_id"] == occurrence.target_resource_id,
                "in_scope_count": 0,
                "out_of_scope_count": 0,
                "role_counts_json": {},
                "scope_counts_json": {},
                "dom_regions_json": {
                    "header": 0,
                    "footer": 0,
                    "nav": 0,
                    "aside": 0,
                    "main": 0,
                    "body": 0,
                },
                "sample_anchors_json": [],
                "first_discovered_at": occurrence.discovered_at,
                "latest_discovered_at": occurrence.discovered_at,
            },
        )
        row["occurrence_count"] += 1
        nofollow = bool(occurrence.rel and "nofollow" in occurrence.rel.casefold())
        row["nofollow_count" if nofollow else "follow_count"] += 1
        anchor = (occurrence.anchor_text or "").strip()
        if anchor:
            anchors[key].add(anchor)
        else:
            row["empty_anchor_count"] += 1
        row["in_scope_count" if occurrence.in_scope else "out_of_scope_count"] += 1
        _increment(row["role_counts_json"], occurrence.link_role or "legacy_unclassified")
        _increment(row["scope_counts_json"], occurrence.scope_decision)
        _increment(row["dom_regions_json"], _dom_region(occurrence.dom_path))
        row["first_discovered_at"] = min(row["first_discovered_at"], occurrence.discovered_at)
        row["latest_discovered_at"] = max(row["latest_discovered_at"], occurrence.discovered_at)
    for key, row in aggregates.items():
        sorted_anchors = sorted(anchors[key])
        row["unique_anchor_count"] = len(sorted_anchors)
        row["sample_anchors_json"] = sorted_anchors[:5]
    return [aggregates[key] for key in sorted(aggregates)]


def _summary_row(
    db: Session,
    scan: Scan,
    build_id: int,
    pages: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    links: list[dict[str, Any]],
    resource_summary: Any,
) -> dict[str, Any]:
    return {
        "projection_build_id": build_id,
        "scan_id": scan.id,
        "page_total": len(pages),
        "successful_page_total": sum(
            bool(row["http_status"] and 200 <= row["http_status"] < 400 and not row["error_type"])
            for row in pages
        ),
        "failed_page_total": sum(
            bool(row["error_type"] or (row["http_status"] and row["http_status"] >= 400))
            for row in pages
        ),
        "resource_total": len(resources),
        "observed_resource_total": resource_summary.observed_resources if resource_summary else 0,
        "discovered_only_resource_total": resource_summary.discovered_only_resources
        if resource_summary
        else 0,
        "resource_occurrence_total": resource_summary.total_occurrences if resource_summary else 0,
        "link_occurrence_total": sum(row["occurrence_count"] for row in links),
        "link_edge_total": len(links),
        "rendered_page_total": 0,
        "rendered_artifact_total": 0,
        "retry_total": scan.static_retry_request_count,
        "recovered_page_total": scan.static_recovered_after_retry_count,
        "error_counts_json": dict(Counter(row["error_type"] for row in pages if row["error_type"])),
        "status_counts_json": dict(
            Counter(str(row["http_status"]) for row in pages if row["http_status"] is not None)
        ),
        "resource_kind_counts_json": dict(Counter(row["effective_kind"] for row in resources)),
        "http_status_counts_json": dict(
            Counter(str(row["http_status"]) for row in pages if row["http_status"] is not None)
        ),
        "depth_counts_json": dict(Counter(str(row["crawl_depth"]) for row in pages)),
    }


def _validate_build(
    db: Session, scan: Scan, build_id: int, pages: list[Any], resources: list[Any], links: list[Any]
) -> dict[str, Any]:
    snapshot_count = (
        db.scalar(
            select(func.count(ResourceSnapshot.id)).where(ResourceSnapshot.scan_id == scan.id)
        )
        or 0
    )
    link_count = (
        db.scalar(
            select(func.count(ResourceOccurrence.id))
            .join(ResourceSnapshot, ResourceSnapshot.id == ResourceOccurrence.source_snapshot_id)
            .where(
                ResourceSnapshot.scan_id == scan.id, ResourceOccurrence.relation_type == "page_link"
            )
        )
        or 0
    )
    reference_count = (
        db.scalar(
            select(func.count(ResourceReferenceOccurrence.id))
            .join(
                ResourceSnapshot,
                ResourceSnapshot.id == ResourceReferenceOccurrence.source_snapshot_id,
            )
            .where(ResourceSnapshot.scan_id == scan.id)
        )
        or 0
    )
    stored = {
        "pages": db.scalar(
            select(func.count(ScanPageProjection.id)).where(
                ScanPageProjection.projection_build_id == build_id
            )
        )
        or 0,
        "resources": db.scalar(
            select(func.count(ScanResourceProjection.id)).where(
                ScanResourceProjection.projection_build_id == build_id
            )
        )
        or 0,
        "links": db.scalar(
            select(func.count(ScanLinkProjection.id)).where(
                ScanLinkProjection.projection_build_id == build_id
            )
        )
        or 0,
    }
    expected = {"pages": len(pages), "resources": len(resources), "links": len(links)}
    if stored != expected:
        raise RuntimeError(
            f"Projection row validation failed: expected {expected}, stored {stored}"
        )
    return {
        "status": "passed",
        "projection_version": SCAN_PROJECTION_VERSION,
        "source_snapshot_count": snapshot_count,
        "source_link_occurrence_count": link_count,
        "source_resource_reference_count": reference_count,
        "projected_page_count": stored["pages"],
        "projected_resource_count": stored["resources"],
        "projected_link_edge_count": stored["links"],
        "raw_evidence_mutated": False,
    }


def _projection_checksum(
    pages: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    links: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    identity = {
        "version": SCAN_PROJECTION_VERSION,
        "pages": [(row["snapshot_id"], row["content_hash"], row["head_hash"]) for row in pages],
        "resources": [
            (row["resource_id"], row["effective_kind"], row["occurrence_count"])
            for row in resources
        ],
        "links": [
            (row["source_snapshot_id"], row["target_resource_id"], row["occurrence_count"])
            for row in links
        ],
        "summary": {
            key: value for key, value in summary.items() if key not in {"projection_build_id"}
        },
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _insert_batches(
    db: Session,
    model: Any,
    rows: list[dict[str, Any]],
    build_id: int,
    progress: Callable[[str, int, int], None] | None,
    phase: str,
    should_cancel: Callable[[], bool] | None,
) -> None:
    total = len(rows)
    for batch_number, batch in enumerate(_chunks(rows), 1):
        _check_cancelled(should_cancel)
        for row in batch:
            row["projection_build_id"] = build_id
        db.execute(insert(model), batch)
        db.commit()
        if progress:
            progress(phase, min(batch_number * PROJECTION_BATCH_SIZE, total), total)


def _clear_staged_rows(db: Session, build_id: int, *, commit: bool = True) -> None:
    for model in (
        ScanSummaryProjection,
        ScanLinkProjection,
        ScanResourceProjection,
        ScanPageProjection,
    ):
        db.execute(delete(model).where(model.projection_build_id == build_id))
    if commit:
        db.commit()


def _finish_failed_build(
    db: Session,
    build: ScanProjectionBuild,
    status: str,
    error_type: str,
    error_message: str,
    *,
    commit: bool = True,
) -> None:
    if commit:
        db.rollback()
    build = db.get(ScanProjectionBuild, build.id) or build
    _clear_staged_rows(db, build.id, commit=commit)
    build.status = status
    build.active_key = None
    build.failed_at = datetime.now(UTC)
    build.finished_at = build.failed_at
    build.error_type = error_type
    build.error_message = error_message[:2000]
    if commit:
        db.commit()


def _check_cancelled(callback: Callable[[], bool] | None) -> None:
    if callback and callback():
        raise ProjectionBuildCancelled("Projection build cancelled.")


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def _dom_region(path: str | None) -> str:
    value = (path or "").casefold()
    for region in ("header", "footer", "nav", "aside", "main"):
        if region in value:
            return region
    return "body"
