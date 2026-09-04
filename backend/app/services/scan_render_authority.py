from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    RenderedArtifact,
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
)
from app.schemas.scans import ScanRead, ScanRenderSummary

LEGACY_OUTCOME_FIELDS = (
    "rendered_attempted_count",
    "rendered_completed_count",
    "rendered_failed_count",
    "rendered_skipped_count",
    "rendered_blocked_request_count",
    "rendered_artifact_count",
)


def resolve_scan_render_authority(db: Session, scan: Scan) -> ScanRenderSummary:
    return resolve_scan_render_authorities(db, [scan])[scan.id]


def scan_render_observation_ownership(scan_id: int) -> ColumnElement[bool]:
    run_id = (
        select(RenderRun.id)
        .where(RenderRun.source_scan_id == scan_id, RenderRun.trigger == "scan")
        .order_by(RenderRun.created_at, RenderRun.id)
        .limit(1)
        .scalar_subquery()
    )
    return or_(
        and_(run_id.is_not(None), RenderedObservation.render_run_id == run_id),
        and_(
            run_id.is_(None),
            ResourceSnapshot.scan_id == scan_id,
            RenderedObservation.render_run_id.is_(None),
        ),
    )


def resolve_scan_render_authorities(
    db: Session, scans: Iterable[Scan]
) -> dict[int, ScanRenderSummary]:
    scan_list = list(scans)
    if not scan_list:
        return {}
    scan_ids = [scan.id for scan in scan_list]
    runs = list(
        db.scalars(
            select(RenderRun)
            .where(
                RenderRun.source_scan_id.in_(scan_ids),
                RenderRun.trigger == "scan",
            )
            .order_by(RenderRun.source_scan_id, RenderRun.created_at, RenderRun.id)
        )
    )
    authoritative_runs: dict[int, RenderRun] = {}
    for run in runs:
        if run.source_scan_id is not None:
            authoritative_runs.setdefault(run.source_scan_id, run)

    run_ids = [run.id for run in authoritative_runs.values()]
    retained_by_run = {
        int(key): int(value)
        for key, value in db.execute(
            select(RenderedObservation.render_run_id, func.count(RenderedObservation.id))
            .where(RenderedObservation.render_run_id.in_(run_ids))
            .group_by(RenderedObservation.render_run_id)
        )
        if key is not None
    }
    deleted_by_run = {
        int(key): int(value)
        for key, value in db.execute(
            select(RenderRunTarget.render_run_id, func.count(RenderRunTarget.id))
            .where(
                RenderRunTarget.render_run_id.in_(run_ids),
                RenderRunTarget.evidence_deleted_at.is_not(None),
            )
            .group_by(RenderRunTarget.render_run_id)
        )
    }
    artifacts_by_run = {
        int(key): int(value)
        for key, value in db.execute(
            select(RenderedObservation.render_run_id, func.count(RenderedArtifact.id))
            .select_from(RenderedArtifact)
            .join(
                RenderedObservation,
                RenderedObservation.id == RenderedArtifact.rendered_observation_id,
            )
            .where(RenderedObservation.render_run_id.in_(run_ids))
            .group_by(RenderedObservation.render_run_id)
        )
        if key is not None
    }
    legacy_observations = {
        int(key): int(value)
        for key, value in db.execute(
            select(ResourceSnapshot.scan_id, func.count(RenderedObservation.id))
            .select_from(RenderedObservation)
            .join(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
            .where(
                ResourceSnapshot.scan_id.in_(scan_ids),
                RenderedObservation.render_run_id.is_(None),
            )
            .group_by(ResourceSnapshot.scan_id)
        )
    }
    legacy_artifacts = {
        int(key): int(value)
        for key, value in db.execute(
            select(ResourceSnapshot.scan_id, func.count(RenderedArtifact.id))
            .select_from(RenderedArtifact)
            .join(
                RenderedObservation,
                RenderedObservation.id == RenderedArtifact.rendered_observation_id,
            )
            .join(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
            .where(
                ResourceSnapshot.scan_id.in_(scan_ids),
                RenderedObservation.render_run_id.is_(None),
            )
            .group_by(ResourceSnapshot.scan_id)
        )
    }

    return {
        scan.id: _summary_for_scan(
            scan,
            authoritative_runs.get(scan.id),
            retained_by_run,
            deleted_by_run,
            artifacts_by_run,
            legacy_observations.get(scan.id, 0),
            legacy_artifacts.get(scan.id, 0),
        )
        for scan in scan_list
    }


def scan_read(db: Session, scan: Scan, *, note_count: int = 0) -> ScanRead:
    summary = resolve_scan_render_authority(db, scan)
    return _scan_read(scan, summary, note_count=note_count)


def scan_reads(db: Session, scans: Iterable[Scan]) -> list[ScanRead]:
    scan_list = list(scans)
    summaries = resolve_scan_render_authorities(db, scan_list)
    return [_scan_read(scan, summaries[scan.id]) for scan in scan_list]


def _scan_read(scan: Scan, summary: ScanRenderSummary, *, note_count: int = 0) -> ScanRead:
    values = {name: getattr(scan, name) for name in ScanRead.model_fields if hasattr(scan, name)}
    values.update(
        render=summary,
        render_run_id=summary.render_run_id,
        render_run_status=summary.status,
        note_count=note_count,
    )
    return ScanRead.model_validate(values)


def _summary_for_scan(
    scan: Scan,
    run: RenderRun | None,
    retained_by_run: dict[int, int],
    deleted_by_run: dict[int, int],
    artifacts_by_run: dict[int, int],
    legacy_observation_count: int,
    legacy_artifact_count: int,
) -> ScanRenderSummary:
    if run is not None:
        retained = retained_by_run.get(run.id, 0)
        deleted = deleted_by_run.get(run.id, 0)
        return ScanRenderSummary(
            authority="render_run",
            selected_count=scan.rendered_selected_count,
            render_run_id=run.id,
            status=run.status,
            target_count=run.target_count,
            attempted_count=run.attempted_count,
            completed_count=run.completed_count,
            failed_count=run.failed_count,
            skipped_count=run.skipped_count,
            blocked_request_count=run.blocked_request_count,
            artifact_count=run.artifact_count,
            retained_observation_count=retained,
            deleted_observation_count=deleted,
            unattempted_target_count=max(run.target_count - retained - deleted, 0),
            retained_artifact_count=artifacts_by_run.get(run.id, 0),
            started_at=run.started_at,
            finished_at=run.finished_at,
            legacy=False,
        )
    has_legacy_outcomes = any(getattr(scan, field) for field in LEGACY_OUTCOME_FIELDS)
    if legacy_observation_count or (
        has_legacy_outcomes and scan.stop_reason != "starting_page_not_render_eligible"
    ):
        target_count = max(scan.rendered_selected_count, scan.rendered_attempted_count)
        return ScanRenderSummary(
            authority="legacy_scan",
            selected_count=scan.rendered_selected_count,
            status=None,
            target_count=target_count,
            attempted_count=scan.rendered_attempted_count,
            completed_count=scan.rendered_completed_count,
            failed_count=scan.rendered_failed_count,
            skipped_count=scan.rendered_skipped_count,
            blocked_request_count=scan.rendered_blocked_request_count,
            artifact_count=scan.rendered_artifact_count,
            retained_observation_count=legacy_observation_count,
            deleted_observation_count=0,
            unattempted_target_count=max(target_count - legacy_observation_count, 0),
            retained_artifact_count=legacy_artifact_count,
            legacy=True,
        )
    return ScanRenderSummary(
        authority="none",
        selected_count=scan.rendered_selected_count,
        target_count=0,
        attempted_count=0,
        completed_count=0,
        failed_count=0,
        skipped_count=0,
        blocked_request_count=0,
        artifact_count=0,
        retained_observation_count=0,
        deleted_observation_count=0,
        unattempted_target_count=0,
        retained_artifact_count=0,
        legacy=False,
    )
