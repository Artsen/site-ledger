from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, TypeVar

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ResourceSnapshot,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanComparisonLinkResult,
    ScanComparisonPageResult,
    ScanComparisonResourceResult,
    ScanComparisonSummary,
    ScanLinkProjection,
    ScanPageProjection,
    ScanProjectionBuild,
    ScanResourceProjection,
    ScanSeed,
    ScanSeedOrigin,
    ScanSummaryProjection,
    WebResource,
)
from app.services.scan_projections import (
    TERMINAL_SCAN_STATUSES,
    current_projection_build,
)

SCAN_COMPARISON_VERSION = "scan-comparison-v1"
SCAN_COMPARISON_ALGORITHM = "scan-comparison-v1|page-v1|resource-v1|link-v1|scan-projection-v1"
ACTIVE_COMPARISON_BUILD_STATUSES = {"queued", "waiting_for_projections", "building"}
COMPARISON_BATCH_SIZE = 400
T = TypeVar("T")


class ComparisonBuildCancelled(RuntimeError):
    pass


class ComparisonEligibilityError(ValueError):
    pass


class ComparisonProjectionUnavailable(RuntimeError):
    pass


def _chunks(items: list[T], size: int = COMPARISON_BATCH_SIZE) -> Iterable[list[T]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def current_comparison_build(db: Session, comparison_id: int) -> ScanComparisonBuild | None:
    comparison = db.get(ScanComparison, comparison_id)
    if comparison is None or comparison.current_build_id is None:
        return None
    build = db.get(ScanComparisonBuild, comparison.current_build_id)
    if (
        build is None
        or build.status != "ready"
        or build.comparison_version != SCAN_COMPARISON_VERSION
        or build.algorithm_identity != SCAN_COMPARISON_ALGORITHM
    ):
        return None
    return build


def create_comparison(
    db: Session, site_id: int, baseline_scan_id: int, target_scan_id: int
) -> ScanComparison:
    baseline, target = _validate_eligibility(db, site_id, baseline_scan_id, target_scan_id)
    existing = db.scalar(
        select(ScanComparison).where(
            ScanComparison.website_property_id == site_id,
            ScanComparison.baseline_scan_id == baseline.id,
            ScanComparison.target_scan_id == target.id,
        )
    )
    if existing is not None:
        return existing
    comparison = ScanComparison(
        website_property_id=site_id,
        baseline_scan_id=baseline.id,
        target_scan_id=target.id,
    )
    db.add(comparison)
    db.flush()
    return comparison


def create_comparison_build(
    db: Session, comparison_id: int, *, force: bool = False
) -> ScanComparisonBuild:
    comparison = db.get(ScanComparison, comparison_id)
    if comparison is None:
        raise ValueError("Comparison not found.")
    _validate_eligibility(
        db,
        comparison.website_property_id,
        comparison.baseline_scan_id,
        comparison.target_scan_id,
    )
    active = db.scalar(
        select(ScanComparisonBuild).where(
            ScanComparisonBuild.scan_comparison_id == comparison.id,
            ScanComparisonBuild.active_key.is_not(None),
        )
    )
    if active is not None:
        return active
    current = current_comparison_build(db, comparison.id)
    if current is not None and not force:
        return current
    baseline_projection = current_projection_build(db, comparison.baseline_scan_id)
    target_projection = current_projection_build(db, comparison.target_scan_id)
    status = (
        "queued"
        if baseline_projection is not None and target_projection is not None
        else "waiting_for_projections"
    )
    build = ScanComparisonBuild(
        scan_comparison_id=comparison.id,
        comparison_version=SCAN_COMPARISON_VERSION,
        algorithm_identity=SCAN_COMPARISON_ALGORITHM,
        status=status,
        active_key=f"{comparison.id}:{SCAN_COMPARISON_VERSION}",
        warnings_json=[],
        validation_json={},
    )
    try:
        with db.begin_nested():
            db.add(build)
            db.flush()
    except IntegrityError:
        concurrent = db.scalar(
            select(ScanComparisonBuild).where(
                ScanComparisonBuild.scan_comparison_id == comparison.id,
                ScanComparisonBuild.active_key.is_not(None),
            )
        )
        if concurrent is not None:
            return concurrent
        raise
    return build


def execute_comparison_build(
    db: Session,
    build_id: int,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> ScanComparisonBuild:
    build = db.get(ScanComparisonBuild, build_id)
    if build is None:
        raise ValueError("Comparison build not found.")
    comparison = db.get(ScanComparison, build.scan_comparison_id)
    if comparison is None:
        raise ValueError("Comparison not found.")
    baseline, target = _validate_eligibility(
        db,
        comparison.website_property_id,
        comparison.baseline_scan_id,
        comparison.target_scan_id,
    )
    baseline_projection = current_projection_build(db, baseline.id)
    target_projection = current_projection_build(db, target.id)
    if baseline_projection is None or target_projection is None:
        build.status = "waiting_for_projections"
        db.commit()
        raise ComparisonProjectionUnavailable(
            "Compatible prepared results are required for both Scans."
        )
    started = perf_counter()
    build.status = "building"
    build.started_at = datetime.now(UTC)
    build.error_type = build.error_message = None
    _pin_projection_provenance(build, baseline_projection, target_projection)
    db.commit()
    try:
        _clear_staged_rows(db, build.id)
        _check_cancelled(should_cancel)
        coverage = _coverage(db, baseline, target)
        build.baseline_scope_fingerprint = coverage["baseline_scope_fingerprint"]
        build.target_scope_fingerprint = coverage["target_scope_fingerprint"]
        build.baseline_seed_fingerprint = coverage["baseline_seed_fingerprint"]
        build.target_seed_fingerprint = coverage["target_seed_fingerprint"]
        build.coverage_state = coverage["coverage_state"]
        build.warnings_json = coverage["warnings"]
        db.commit()
        _report(progress, "analyzing_coverage", 1, 1)

        page_rows = _page_rows(db, baseline, target, baseline_projection, target_projection)
        _insert_batches(
            db,
            ScanComparisonPageResult,
            page_rows,
            build.id,
            "comparing_pages",
            progress,
            should_cancel,
        )
        resource_rows = _resource_rows(db, baseline_projection, target_projection)
        _insert_batches(
            db,
            ScanComparisonResourceResult,
            resource_rows,
            build.id,
            "comparing_resources",
            progress,
            should_cancel,
        )
        link_rows = _link_rows(db, baseline_projection, target_projection)
        _insert_batches(
            db,
            ScanComparisonLinkResult,
            link_rows,
            build.id,
            "comparing_links",
            progress,
            should_cancel,
        )
        _populate_page_topology(page_rows, link_rows)
        _replace_page_rows(db, build.id, page_rows)
        _report(progress, "calculating_page_topology", len(page_rows), len(page_rows))
        summary = _summary_row(
            db,
            build.id,
            baseline_projection,
            target_projection,
            page_rows,
            resource_rows,
            link_rows,
        )
        db.execute(insert(ScanComparisonSummary), [summary])
        db.commit()
        _report(progress, "calculating_summary", 1, 1)
        validation = _validate_build(db, build.id, page_rows, resource_rows, link_rows)
        checksum = _comparison_checksum(coverage, page_rows, resource_rows, link_rows, summary)
        _report(progress, "validating", 1, 1)

        prior_id = comparison.current_build_id
        now = datetime.now(UTC)
        build.status = "ready"
        build.active_key = None
        build.finished_at = now
        build.failed_at = None
        build.build_duration_ms = int((perf_counter() - started) * 1000)
        build.page_result_count = len(page_rows)
        build.resource_result_count = len(resource_rows)
        build.link_result_count = len(link_rows)
        build.comparison_checksum_sha256 = checksum
        build.validation_json = validation
        comparison.current_build_id = build.id
        if prior_id and prior_id != build.id:
            prior = db.get(ScanComparisonBuild, prior_id)
            if prior is not None:
                prior.status = "superseded"
        db.commit()
        _report(progress, "activating", 1, 1)
        db.refresh(build)
        return build
    except ComparisonBuildCancelled:
        _finish_failed_build(db, build, "cancelled", "cancelled", "Build cancelled by user.")
        raise
    except ComparisonProjectionUnavailable:
        raise
    except Exception as exc:
        _finish_failed_build(db, build, "failed", type(exc).__name__, str(exc))
        raise


def verify_comparison_build(db: Session, comparison_id: int) -> dict[str, Any]:
    build = current_comparison_build(db, comparison_id)
    if build is None:
        raise ValueError("No current compatible comparison exists.")
    page_rows = [
        _model_dict(row)
        for row in db.scalars(
            select(ScanComparisonPageResult).where(
                ScanComparisonPageResult.comparison_build_id == build.id
            )
        )
    ]
    resource_rows = [
        _model_dict(row)
        for row in db.scalars(
            select(ScanComparisonResourceResult).where(
                ScanComparisonResourceResult.comparison_build_id == build.id
            )
        )
    ]
    link_rows = [
        _model_dict(row)
        for row in db.scalars(
            select(ScanComparisonLinkResult).where(
                ScanComparisonLinkResult.comparison_build_id == build.id
            )
        )
    ]
    summary_model = db.scalar(
        select(ScanComparisonSummary).where(ScanComparisonSummary.comparison_build_id == build.id)
    )
    assert summary_model is not None
    validation = _validate_build(db, build.id, page_rows, resource_rows, link_rows)
    return {**validation, "checksum_sha256": build.comparison_checksum_sha256}


def mark_comparison_build_terminal(
    db: Session, build_id: int, status: str, error_type: str, error_message: str
) -> None:
    build = db.get(ScanComparisonBuild, build_id)
    if build is not None and build.status in ACTIVE_COMPARISON_BUILD_STATUSES:
        _finish_failed_build(db, build, status, error_type, error_message)


def delete_comparison(db: Session, comparison_id: int) -> bool:
    comparison = db.get(ScanComparison, comparison_id)
    if comparison is None:
        return False
    active = db.scalar(
        select(func.count())
        .select_from(ScanComparisonBuild)
        .where(
            ScanComparisonBuild.scan_comparison_id == comparison_id,
            ScanComparisonBuild.active_key.is_not(None),
        )
    )
    if active:
        raise ValueError("Cancel active comparison work before deleting this comparison.")
    comparison.current_build_id = None
    db.flush()
    db.delete(comparison)
    db.commit()
    return True


def queue_waiting_comparisons_for_scan(db: Session, scan_id: int) -> list[int]:
    from app.services.background_jobs import enqueue_scan_comparison_job

    builds = list(
        db.scalars(
            select(ScanComparisonBuild)
            .join(
                ScanComparison,
                ScanComparison.id == ScanComparisonBuild.scan_comparison_id,
            )
            .where(
                ScanComparisonBuild.status == "waiting_for_projections",
                ScanComparisonBuild.active_key.is_not(None),
                (ScanComparison.baseline_scan_id == scan_id)
                | (ScanComparison.target_scan_id == scan_id),
            )
        )
    )
    queued: list[int] = []
    for build in builds:
        comparison = db.get(ScanComparison, build.scan_comparison_id)
        assert comparison is not None
        if current_projection_build(db, comparison.baseline_scan_id) and current_projection_build(
            db, comparison.target_scan_id
        ):
            build.status = "queued"
            enqueue_scan_comparison_job(db, build.id, comparison.id, comparison.website_property_id)
            queued.append(build.id)
    return queued


def queue_adjacent_comparison_for_scan(db: Session, scan_id: int) -> ScanComparison | None:
    target = db.get(Scan, scan_id)
    if (
        target is None
        or target.website_property_id is None
        or target.status not in {"completed", "completed_with_errors"}
        or current_projection_build(db, target.id) is None
    ):
        return None
    baseline = db.scalar(
        select(Scan)
        .where(
            Scan.website_property_id == target.website_property_id,
            Scan.id != target.id,
            Scan.status.in_({"completed", "completed_with_errors"}),
            (Scan.created_at < target.created_at)
            | ((Scan.created_at == target.created_at) & (Scan.id < target.id)),
        )
        .order_by(Scan.created_at.desc(), Scan.id.desc())
    )
    if baseline is None:
        return None
    comparison = create_comparison(db, target.website_property_id, baseline.id, target.id)
    build = create_comparison_build(db, comparison.id)
    if current_projection_build(db, baseline.id) is None:
        from app.services.background_jobs import enqueue_scan_projection_job
        from app.services.scan_projections import create_projection_build

        projection = create_projection_build(db, baseline.id)
        if projection.status == "queued":
            enqueue_scan_projection_job(db, projection.id, baseline)
    if build.status == "queued":
        from app.services.background_jobs import enqueue_scan_comparison_job

        enqueue_scan_comparison_job(db, build.id, comparison.id, comparison.website_property_id)
    return comparison


def _validate_eligibility(
    db: Session, site_id: int, baseline_scan_id: int, target_scan_id: int
) -> tuple[Scan, Scan]:
    if baseline_scan_id == target_scan_id:
        raise ComparisonEligibilityError("Baseline and Target Scans must be different.")
    baseline = db.get(Scan, baseline_scan_id)
    target = db.get(Scan, target_scan_id)
    if baseline is None or target is None:
        raise ComparisonEligibilityError("Baseline or Target Scan was not found.")
    if baseline.website_property_id is None or target.website_property_id is None:
        raise ComparisonEligibilityError("Ad-hoc Scan comparison is not supported.")
    if baseline.website_property_id != site_id or target.website_property_id != site_id:
        raise ComparisonEligibilityError("Both Scans must belong to this Site.")
    if baseline.status not in TERMINAL_SCAN_STATUSES or target.status not in TERMINAL_SCAN_STATUSES:
        raise ComparisonEligibilityError("Both Scans must be terminal.")
    return baseline, target


def _pin_projection_provenance(
    build: ScanComparisonBuild,
    baseline: ScanProjectionBuild,
    target: ScanProjectionBuild,
) -> None:
    build.baseline_projection_build_id = baseline.id
    build.target_projection_build_id = target.id
    build.baseline_projection_version = baseline.projection_version
    build.target_projection_version = target.projection_version
    build.baseline_projection_algorithm_identity = baseline.algorithm_identity
    build.target_projection_algorithm_identity = target.algorithm_identity
    build.baseline_projection_checksum = baseline.checksum_sha256
    build.target_projection_checksum = target.checksum_sha256
    build.baseline_projection_created_at = baseline.created_at
    build.target_projection_created_at = target.created_at


def _coverage(db: Session, baseline: Scan, target: Scan) -> dict[str, Any]:
    baseline_scope = _hash_json(baseline.scope_config)
    target_scope = _hash_json(target.scope_config)
    baseline_seed = _seed_fingerprint(db, baseline.id)
    target_seed = _seed_fingerprint(db, target.id)
    warnings: set[str] = set()
    if baseline_scope != target_scope:
        warnings.add("scope_changed")
    if baseline.starting_url != target.starting_url:
        warnings.add("starting_url_changed")
    if baseline_seed != target_seed:
        warnings.add("seed_inputs_changed")
    for side, scan in (("baseline", baseline), ("target", target)):
        if scan.status != "completed":
            warnings.add(f"{side}_{scan.status}")
        if scan.stop_reason and scan.stop_reason not in {"completed", "queue_empty"}:
            warnings.add(f"{side}_stop_reason:{scan.stop_reason}")
            if "limit" in scan.stop_reason or scan.stop_reason.startswith("max_"):
                warnings.add(f"{side}_stopped_by_limit")
        if scan.failed_count:
            warnings.add(f"{side}_fetch_failures")
    limited_statuses = {"failed", "cancelled", "interrupted"}
    limited = baseline.status in limited_statuses or target.status in limited_statuses
    return {
        "baseline_scope_fingerprint": baseline_scope,
        "target_scope_fingerprint": target_scope,
        "baseline_seed_fingerprint": baseline_seed,
        "target_seed_fingerprint": target_seed,
        "coverage_state": "limited"
        if limited
        else "comparable_with_warnings"
        if warnings
        else "comparable",
        "warnings": sorted(warnings),
    }


def _seed_fingerprint(db: Session, scan_id: int) -> str:
    rows = db.execute(
        select(ScanSeed, ScanSeedOrigin)
        .outerjoin(ScanSeedOrigin, ScanSeedOrigin.scan_seed_id == ScanSeed.id)
        .where(ScanSeed.scan_id == scan_id)
        .order_by(ScanSeed.normalized_url, ScanSeed.id, ScanSeedOrigin.id)
    ).all()
    values = [
        {
            "url": seed.normalized_url or seed.requested_url,
            "depth": seed.depth,
            "scope": seed.scope_decision,
            "origin": origin.origin_type if origin else None,
            "source": origin.url_source_id if origin else None,
            "raw_url": origin.raw_url if origin else None,
            "metadata": origin.metadata_json if origin else None,
        }
        for seed, origin in rows
    ]
    return _hash_json(values)


def _page_rows(
    db: Session,
    baseline_scan: Scan,
    target_scan: Scan,
    baseline_build: ScanProjectionBuild,
    target_build: ScanProjectionBuild,
) -> list[dict[str, Any]]:
    baseline = {
        row.resource_id: row
        for row in db.scalars(
            select(ScanPageProjection).where(
                ScanPageProjection.projection_build_id == baseline_build.id
            )
        )
    }
    target = {
        row.resource_id: row
        for row in db.scalars(
            select(ScanPageProjection).where(
                ScanPageProjection.projection_build_id == target_build.id
            )
        )
    }
    resource_ids = sorted(set(baseline) | set(target))
    missing_baseline = set(resource_ids) - set(baseline)
    missing_target = set(resource_ids) - set(target)
    opposite_baseline = _opposite_snapshots(db, baseline_scan.id, missing_baseline)
    opposite_target = _opposite_snapshots(db, target_scan.id, missing_target)
    rows: list[dict[str, Any]] = []
    for resource_id in resource_ids:
        before = baseline.get(resource_id)
        after = target.get(resource_id)
        identity = before or after
        assert identity is not None
        presence = (
            "observed_in_both"
            if before and after
            else "newly_observed"
            if after
            else "not_observed_in_target"
        )
        before_json = _page_projection_json(before) if before else None
        after_json = _page_projection_json(after) if after else None
        flags = _page_flags(before_json, after_json)
        content_state = _equality_state(before, after, "content_hash")
        head_state = _equality_state(before, after, "head_hash")
        meaningful = sum(flags.values())
        if presence != "observed_in_both":
            change_state = "not_applicable"
        elif meaningful:
            change_state = "changed"
        elif content_state == "unavailable" or head_state == "unavailable":
            change_state = "indeterminate"
        else:
            change_state = "no_tracked_change"
        rows.append(
            {
                "resource_id": resource_id,
                "normalized_url": identity.normalized_url,
                "host": identity.host,
                "path": identity.path,
                "baseline_page_projection_id": before.id if before else None,
                "target_page_projection_id": after.id if after else None,
                "baseline_snapshot_id": before.snapshot_id
                if before
                else _snapshot_id(opposite_baseline.get(resource_id)),
                "target_snapshot_id": after.snapshot_id
                if after
                else _snapshot_id(opposite_target.get(resource_id)),
                "presence_state": presence,
                "baseline_presence_detail": "page_observed"
                if before
                else _presence_detail(opposite_baseline.get(resource_id)),
                "target_presence_detail": "page_observed"
                if after
                else _presence_detail(opposite_target.get(resource_id)),
                "change_state": change_state,
                "content_state": content_state,
                "head_state": head_state,
                "changed_field_count": meaningful,
                **flags,
                "baseline_http_status": before.http_status if before else None,
                "target_http_status": after.http_status if after else None,
                "baseline_content_hash": before.content_hash if before else None,
                "target_content_hash": after.content_hash if after else None,
                "baseline_head_hash": before.head_hash if before else None,
                "target_head_hash": after.head_hash if after else None,
                "response_time_ms_delta": _delta(before, after, "response_time_ms"),
                "network_bytes_delta": _delta(before, after, "network_bytes_transferred"),
                "raw_html_size_delta": _delta(before, after, "raw_html_size"),
                "stored_html_size_delta": _delta(before, after, "stored_html_size"),
                "outgoing_edges_newly_observed": 0,
                "outgoing_edges_not_observed": 0,
                "outgoing_edges_changed": 0,
                "incoming_edges_newly_observed": 0,
                "incoming_edges_not_observed": 0,
                "incoming_edges_changed": 0,
                "baseline_json": before_json,
                "target_json": after_json,
            }
        )
    return rows


def _resource_rows(
    db: Session, baseline_build: ScanProjectionBuild, target_build: ScanProjectionBuild
) -> list[dict[str, Any]]:
    baseline = {
        row.resource_id: row
        for row in db.scalars(
            select(ScanResourceProjection).where(
                ScanResourceProjection.projection_build_id == baseline_build.id
            )
        )
    }
    target = {
        row.resource_id: row
        for row in db.scalars(
            select(ScanResourceProjection).where(
                ScanResourceProjection.projection_build_id == target_build.id
            )
        )
    }
    rows: list[dict[str, Any]] = []
    fields = (
        "effective_kind",
        "classification_source",
        "observed",
        "discovered_only",
        "final_url",
        "http_status",
        "normalized_mime_type",
        "content_disposition_filename",
        "declared_content_length",
        "occurrence_count",
        "source_page_count",
        "anchor_occurrence_count",
        "embedded_occurrence_count",
        "in_scope_occurrence_count",
        "out_of_scope_occurrence_count",
        "observation_count",
    )
    for resource_id in sorted(set(baseline) | set(target)):
        before = baseline.get(resource_id)
        after = target.get(resource_id)
        identity = before or after
        assert identity is not None
        presence = (
            "observed_in_both"
            if before and after
            else "newly_observed"
            if after
            else "not_observed_in_target"
        )
        changed = [
            field
            for field in fields
            if before and after and getattr(before, field) != getattr(after, field)
        ]
        rows.append(
            {
                "resource_id": resource_id,
                "normalized_url": identity.normalized_url,
                "host": identity.host,
                "path": identity.path,
                "baseline_resource_projection_id": before.id if before else None,
                "target_resource_projection_id": after.id if after else None,
                "baseline_snapshot_id": before.latest_snapshot_id if before else None,
                "target_snapshot_id": after.latest_snapshot_id if after else None,
                "presence_state": presence,
                "change_state": "changed"
                if changed
                else "no_tracked_change"
                if before and after
                else "not_applicable",
                "changed_field_count": len(changed),
                "baseline_kind": before.effective_kind if before else None,
                "target_kind": after.effective_kind if after else None,
                "baseline_mime_type": before.normalized_mime_type if before else None,
                "target_mime_type": after.normalized_mime_type if after else None,
                "baseline_http_status": before.http_status if before else None,
                "target_http_status": after.http_status if after else None,
                "status_changed": bool(
                    before and after and before.http_status != after.http_status
                ),
                "observed_state_changed": bool(
                    before and after and before.observed != after.observed
                ),
                "occurrence_delta": _delta(before, after, "occurrence_count"),
                "source_page_delta": _delta(before, after, "source_page_count"),
                "declared_size_delta": _delta(before, after, "declared_content_length"),
                "baseline_json": _resource_projection_json(before) if before else None,
                "target_json": _resource_projection_json(after) if after else None,
            }
        )
    return rows


def _link_rows(
    db: Session, baseline_build: ScanProjectionBuild, target_build: ScanProjectionBuild
) -> list[dict[str, Any]]:
    baseline = _link_map(db, baseline_build.id)
    target = _link_map(db, target_build.id)
    resource_ids = {item for key in set(baseline) | set(target) for item in key}
    urls: dict[int, str] = (
        {
            resource_id: normalized_url
            for resource_id, normalized_url in db.execute(
                select(WebResource.id, WebResource.normalized_url).where(
                    WebResource.id.in_(resource_ids)
                )
            )
        }
        if resource_ids
        else {}
    )
    fields = (
        "occurrence_count",
        "unique_anchor_count",
        "empty_anchor_count",
        "follow_count",
        "nofollow_count",
        "self_link",
        "in_scope_count",
        "out_of_scope_count",
        "role_counts_json",
        "scope_counts_json",
        "dom_regions_json",
    )
    rows: list[dict[str, Any]] = []
    for source_id, target_id in sorted(set(baseline) | set(target)):
        before = baseline.get((source_id, target_id))
        after = target.get((source_id, target_id))
        presence = (
            "observed_in_both"
            if before and after
            else "newly_observed"
            if after
            else "not_observed_in_target"
        )
        changed = [
            field
            for field in fields
            if before and after and getattr(before, field) != getattr(after, field)
        ]
        rows.append(
            {
                "source_resource_id": source_id,
                "target_resource_id": target_id,
                "source_url": urls.get(source_id, ""),
                "target_url": urls.get(target_id, ""),
                "baseline_link_projection_id": before.id if before else None,
                "target_link_projection_id": after.id if after else None,
                "baseline_source_snapshot_id": before.source_snapshot_id if before else None,
                "target_source_snapshot_id": after.source_snapshot_id if after else None,
                "presence_state": presence,
                "change_state": "changed"
                if changed
                else "no_tracked_change"
                if before and after
                else "not_applicable",
                "changed_field_count": len(changed),
                "baseline_occurrence_count": before.occurrence_count if before else 0,
                "target_occurrence_count": after.occurrence_count if after else 0,
                "occurrence_delta": (after.occurrence_count if after else 0)
                - (before.occurrence_count if before else 0),
                "baseline_json": _link_projection_json(before) if before else None,
                "target_json": _link_projection_json(after) if after else None,
            }
        )
    return rows


def _link_map(db: Session, build_id: int) -> dict[tuple[int, int], ScanLinkProjection]:
    return {
        (row.source_resource_id, row.target_resource_id): row
        for row in db.scalars(
            select(ScanLinkProjection).where(ScanLinkProjection.projection_build_id == build_id)
        )
    }


def _populate_page_topology(
    page_rows: list[dict[str, Any]], link_rows: list[dict[str, Any]]
) -> None:
    pages = {row["resource_id"]: row for row in page_rows}
    labels = {
        "newly_observed": "newly_observed",
        "not_observed_in_target": "not_observed",
        "changed": "changed",
    }
    for link in link_rows:
        label = labels.get(link["presence_state"]) or labels.get(link["change_state"])
        if label is None:
            continue
        source = pages.get(link["source_resource_id"])
        target = pages.get(link["target_resource_id"])
        if source:
            source[f"outgoing_edges_{label}"] += 1
        if target:
            target[f"incoming_edges_{label}"] += 1


def _summary_row(
    db: Session,
    build_id: int,
    baseline_build: ScanProjectionBuild,
    target_build: ScanProjectionBuild,
    pages: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_summary = db.scalar(
        select(ScanSummaryProjection).where(
            ScanSummaryProjection.projection_build_id == baseline_build.id
        )
    )
    target_summary = db.scalar(
        select(ScanSummaryProjection).where(
            ScanSummaryProjection.projection_build_id == target_build.id
        )
    )
    return {
        "comparison_build_id": build_id,
        "page_counts_json": _result_counts(pages),
        "resource_counts_json": _result_counts(resources),
        "link_counts_json": {
            **_result_counts(links),
            "occurrence_delta": sum(row["occurrence_delta"] for row in links),
        },
        "scan_summary_delta_json": _summary_delta(baseline_summary, target_summary),
    }


def _result_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    presence = Counter(row["presence_state"] for row in rows)
    changes = Counter(row["change_state"] for row in rows)
    return {
        "total": len(rows),
        **{key: presence[key] for key in sorted(presence)},
        **{key: changes[key] for key in sorted(changes)},
    }


def _summary_delta(
    before: ScanSummaryProjection | None, after: ScanSummaryProjection | None
) -> dict[str, Any]:
    if before is None or after is None:
        return {}
    fields = (
        "page_total",
        "successful_page_total",
        "failed_page_total",
        "resource_total",
        "observed_resource_total",
        "discovered_only_resource_total",
        "resource_occurrence_total",
        "link_occurrence_total",
        "link_edge_total",
        "rendered_page_total",
        "rendered_artifact_total",
        "retry_total",
        "recovered_page_total",
    )
    result: dict[str, Any] = {
        field: {
            "baseline": getattr(before, field),
            "target": getattr(after, field),
            "delta": getattr(after, field) - getattr(before, field),
        }
        for field in fields
    }
    for field in (
        "error_counts_json",
        "status_counts_json",
        "resource_kind_counts_json",
        "http_status_counts_json",
        "depth_counts_json",
    ):
        keys = sorted(set(getattr(before, field)) | set(getattr(after, field)))
        result[field] = {
            key: {
                "baseline": getattr(before, field).get(key, 0),
                "target": getattr(after, field).get(key, 0),
                "delta": getattr(after, field).get(key, 0) - getattr(before, field).get(key, 0),
            }
            for key in keys
        }
    return result


def _page_flags(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, bool]:
    mapping = {
        "content_changed": ("content_hash",),
        "head_changed": ("head_hash",),
        "http_status_changed": ("http_status",),
        "fetch_state_changed": ("fetch_state",),
        "final_url_changed": ("final_url",),
        "redirect_state_changed": ("redirects",),
        "content_type_changed": ("content_type",),
        "title_changed": ("page_title",),
        "canonical_changed": ("canonical_url",),
        "robots_changed": ("robots_directives",),
        "language_changed": ("language",),
        "depth_changed": ("crawl_depth",),
        "inbound_links_changed": ("inbound_source_page_count", "inbound_occurrence_count"),
        "outbound_links_changed": ("outbound_target_count", "outbound_occurrence_count"),
        "embedded_resources_changed": ("embedded_resource_count",),
        "rendered_state_changed": ("rendered_capture_state",),
        "rendered_counts_changed": (
            "rendered_network_count",
            "rendered_console_count",
            "rendered_page_error_count",
            "rendered_artifact_count",
        ),
    }
    return {
        name: bool(before and after and any(before[field] != after[field] for field in fields))
        for name, fields in mapping.items()
    }


def _page_projection_json(row: ScanPageProjection | None) -> dict[str, Any] | None:
    if row is None:
        return None
    fields = (
        "requested_url",
        "final_url",
        "page_title",
        "crawl_depth",
        "fetch_state",
        "http_status",
        "error_type",
        "content_type",
        "content_hash",
        "head_hash",
        "canonical_url",
        "robots_directives",
        "language",
        "redirects",
        "response_time_ms",
        "network_bytes_transferred",
        "raw_html_size",
        "stored_html_size",
        "inbound_source_page_count",
        "inbound_occurrence_count",
        "outbound_target_count",
        "outbound_occurrence_count",
        "embedded_resource_count",
        "rendered_capture_state",
        "rendered_network_count",
        "rendered_console_count",
        "rendered_page_error_count",
        "rendered_artifact_count",
        "fetched_at",
    )
    return {field: _json_value(getattr(row, field)) for field in fields}


def _resource_projection_json(row: ScanResourceProjection | None) -> dict[str, Any] | None:
    if row is None:
        return None
    fields = (
        "effective_kind",
        "classification_source",
        "observed",
        "discovered_only",
        "final_url",
        "http_status",
        "normalized_mime_type",
        "content_disposition_filename",
        "declared_content_length",
        "network_bytes_transferred",
        "fetched_at",
        "response_time_ms",
        "occurrence_count",
        "source_page_count",
        "anchor_occurrence_count",
        "embedded_occurrence_count",
        "in_scope_occurrence_count",
        "out_of_scope_occurrence_count",
        "observation_count",
    )
    return {field: _json_value(getattr(row, field)) for field in fields}


def _link_projection_json(row: ScanLinkProjection | None) -> dict[str, Any] | None:
    if row is None:
        return None
    fields = (
        "occurrence_count",
        "unique_anchor_count",
        "empty_anchor_count",
        "follow_count",
        "nofollow_count",
        "self_link",
        "in_scope_count",
        "out_of_scope_count",
        "role_counts_json",
        "scope_counts_json",
        "dom_regions_json",
        "first_discovered_at",
        "latest_discovered_at",
    )
    return {field: _json_value(getattr(row, field)) for field in fields}


def _opposite_snapshots(
    db: Session, scan_id: int, resource_ids: set[int]
) -> dict[int, ResourceSnapshot]:
    if not resource_ids:
        return {}
    result: dict[int, ResourceSnapshot] = {}
    for chunk in _chunks(sorted(resource_ids)):
        rows = db.scalars(
            select(ResourceSnapshot)
            .where(ResourceSnapshot.scan_id == scan_id, ResourceSnapshot.resource_id.in_(chunk))
            .order_by(ResourceSnapshot.resource_id, ResourceSnapshot.id.desc())
        )
        for row in rows:
            result.setdefault(row.resource_id, row)
    return result


def _presence_detail(snapshot: ResourceSnapshot | None) -> str:
    if snapshot is None:
        return "not_observed"
    if snapshot.fetch_state == "failed" or snapshot.error_type:
        return "fetch_failed"
    return "observed_as_non_html"


def _snapshot_id(snapshot: ResourceSnapshot | None) -> int | None:
    return snapshot.id if snapshot else None


def _equality_state(before: Any, after: Any, field: str) -> str:
    if before is None or after is None:
        return "not_applicable"
    before_value = getattr(before, field)
    after_value = getattr(after, field)
    if before_value is None or after_value is None:
        return "unavailable"
    return "same" if before_value == after_value else "changed"


def _delta(before: Any, after: Any, field: str) -> int | None:
    if before is None or after is None:
        return None
    left = getattr(before, field)
    right = getattr(after, field)
    return right - left if left is not None and right is not None else None


def _replace_page_rows(db: Session, build_id: int, rows: list[dict[str, Any]]) -> None:
    db.execute(
        delete(ScanComparisonPageResult).where(
            ScanComparisonPageResult.comparison_build_id == build_id
        )
    )
    for chunk in _chunks(rows):
        db.execute(
            insert(ScanComparisonPageResult),
            [{"comparison_build_id": build_id, **row} for row in chunk],
        )
    db.commit()


def _insert_batches(
    db: Session,
    model: type[Any],
    rows: list[dict[str, Any]],
    build_id: int,
    phase: str,
    progress: Callable[[str, int, int], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> None:
    total = len(rows)
    for number, chunk in enumerate(_chunks(rows), start=1):
        _check_cancelled(should_cancel)
        db.execute(insert(model), [{"comparison_build_id": build_id, **row} for row in chunk])
        db.commit()
        _report(progress, phase, min(number * COMPARISON_BATCH_SIZE, total), total)


def _clear_staged_rows(db: Session, build_id: int) -> None:
    for model in (
        ScanComparisonSummary,
        ScanComparisonLinkResult,
        ScanComparisonResourceResult,
        ScanComparisonPageResult,
    ):
        db.execute(delete(model).where(model.comparison_build_id == build_id))
    db.flush()


def _validate_build(
    db: Session,
    build_id: int,
    pages: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = {
        "page_result_count": db.scalar(
            select(func.count())
            .select_from(ScanComparisonPageResult)
            .where(ScanComparisonPageResult.comparison_build_id == build_id)
        )
        or 0,
        "resource_result_count": db.scalar(
            select(func.count())
            .select_from(ScanComparisonResourceResult)
            .where(ScanComparisonResourceResult.comparison_build_id == build_id)
        )
        or 0,
        "link_result_count": db.scalar(
            select(func.count())
            .select_from(ScanComparisonLinkResult)
            .where(ScanComparisonLinkResult.comparison_build_id == build_id)
        )
        or 0,
    }
    expected = {
        "page_result_count": len(pages),
        "resource_result_count": len(resources),
        "link_result_count": len(links),
    }
    if counts != expected:
        raise ValueError(f"Comparison validation count mismatch: {counts} != {expected}")
    if any(row["presence_state"] == "removed" for row in [*pages, *resources, *links]):
        raise ValueError("Comparison result used prohibited removal terminology.")
    return {**counts, "validated": True}


def _comparison_checksum(
    coverage: dict[str, Any],
    pages: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    links: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    payload = {
        "version": SCAN_COMPARISON_VERSION,
        "algorithm": SCAN_COMPARISON_ALGORITHM,
        "coverage": coverage,
        "pages": [
            _checksum_row(
                row,
                {
                    "baseline_page_projection_id",
                    "target_page_projection_id",
                    "baseline_snapshot_id",
                    "target_snapshot_id",
                },
            )
            for row in pages
        ],
        "resources": [
            _checksum_row(
                row,
                {
                    "baseline_resource_projection_id",
                    "target_resource_projection_id",
                    "baseline_snapshot_id",
                    "target_snapshot_id",
                },
            )
            for row in resources
        ],
        "links": [
            _checksum_row(
                row,
                {
                    "baseline_link_projection_id",
                    "target_link_projection_id",
                    "baseline_source_snapshot_id",
                    "target_source_snapshot_id",
                },
            )
            for row in links
        ],
        "summary": {key: value for key, value in summary.items() if key != "comparison_build_id"},
    }
    return _hash_json(payload)


def _checksum_row(row: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in sorted(row.items()) if key not in excluded}


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_value).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def _check_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel and should_cancel():
        raise ComparisonBuildCancelled


def _report(
    progress: Callable[[str, int, int], None] | None, phase: str, current: int, total: int
) -> None:
    if progress:
        progress(phase, current, total)


def _finish_failed_build(
    db: Session, build: ScanComparisonBuild, status: str, error_type: str, error_message: str
) -> None:
    build.status = status
    build.active_key = None
    build.failed_at = datetime.now(UTC)
    build.error_type = error_type
    build.error_message = error_message
    db.commit()


def _model_dict(model: Any) -> dict[str, Any]:
    return {
        column.name: getattr(model, column.name)
        for column in model.__table__.columns
        if column.name not in {"id", "comparison_build_id"}
    }
