from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    ArtifactBlob,
    BackgroundJob,
    JobEvent,
    RenderedArtifact,
    RenderedConsoleMessage,
    RenderedNetworkEntry,
    RenderedObservation,
    RenderedPageError,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    WebsiteProperty,
)
from app.schemas.rendered import RenderDeleteImpact, RenderDeleteResult
from app.services.job_types import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES
from app.storage.artifact_store import LocalArtifactStore

MAX_RENDER_DELETE_SELECTION = 500
ACTIVE_RENDER_DELETE_REASON = "Finish or cancel this Render Run before deleting evidence."


@dataclass(frozen=True)
class _ArtifactImpact:
    blobs: list[ArtifactBlob]
    exclusive: list[ArtifactBlob]


def preview_rendered_observations(
    db: Session,
    observation_ids: list[int],
    *,
    targets_requested: int | None = None,
) -> RenderDeleteImpact:
    ids = _bounded_ids(observation_ids, "observation_ids") if observation_ids else []
    if not ids and targets_requested is None:
        raise ValueError("observation_ids must contain at least one ID.")
    observations = list(
        db.scalars(select(RenderedObservation).where(RenderedObservation.id.in_(ids)))
    )
    reason = _active_run_reason(
        db, {item.render_run_id for item in observations if item.render_run_id}
    )
    impact = _observation_impact(db, [item.id for item in observations])
    requested = targets_requested if targets_requested is not None else len(ids)
    return RenderDeleteImpact(
        can_delete=reason is None,
        reason=reason,
        targets_requested=requested,
        observations=len(observations),
        targets_already_without_evidence=max(requested - len(observations), 0),
        **impact,
    )


def delete_rendered_observations(
    db: Session,
    observation_ids: list[int],
    *,
    artifact_store: LocalArtifactStore,
    targets_requested: int | None = None,
) -> RenderDeleteResult:
    preview = preview_rendered_observations(
        db, observation_ids, targets_requested=targets_requested
    )
    _require_deletable(preview)
    ids = (
        list(
            db.scalars(
                select(RenderedObservation.id).where(RenderedObservation.id.in_(observation_ids))
            )
        )
        if observation_ids
        else []
    )
    target_ids = list(
        db.scalars(
            select(RenderedObservation.render_run_target_id).where(
                RenderedObservation.id.in_(ids),
                RenderedObservation.render_run_target_id.is_not(None),
            )
        )
    )
    blobs = _artifact_impact(db, ids).blobs
    _delete_observation_rows(db, ids)
    if target_ids:
        db.execute(
            update(RenderRunTarget)
            .where(RenderRunTarget.id.in_(target_ids))
            .values(evidence_deleted_at=datetime.now(UTC))
        )
    db.flush()
    deleted_blobs = _delete_unreferenced_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = cleanup_render_artifact_files(artifact_store, deleted_blobs)
    return _result_from_preview(
        preview,
        deleted_blobs,
        files_deleted,
        warnings,
        deleted_observation_id=ids[0] if len(ids) == 1 else None,
    )


def preview_run_target_deletion(
    db: Session, site_id: int, run_id: int, target_ids: list[int]
) -> RenderDeleteImpact | None:
    ids = _bounded_ids(target_ids, "target_ids")
    run = _owned_run(db, site_id, run_id)
    if run is None:
        return None
    owned = list(
        db.scalars(
            select(RenderRunTarget.id).where(
                RenderRunTarget.render_run_id == run.id,
                RenderRunTarget.id.in_(ids),
            )
        )
    )
    if len(owned) != len(ids):
        raise ValueError("One or more selected targets do not belong to this Render Run.")
    observation_ids = list(
        db.scalars(
            select(RenderedObservation.id).where(
                RenderedObservation.render_run_target_id.in_(owned)
            )
        )
    )
    preview = preview_rendered_observations(db, observation_ids, targets_requested=len(owned))
    reason = _active_run_reason(db, {run.id})
    if reason is None:
        return preview
    return preview.model_copy(update={"can_delete": False, "reason": reason})


def delete_run_target_evidence(
    db: Session,
    site_id: int,
    run_id: int,
    target_ids: list[int],
    artifact_store: LocalArtifactStore,
) -> RenderDeleteResult | None:
    preview = preview_run_target_deletion(db, site_id, run_id, target_ids)
    if preview is None:
        return None
    _require_deletable(preview)
    observation_ids = list(
        db.scalars(
            select(RenderedObservation.id).where(
                RenderedObservation.render_run_target_id.in_(target_ids)
            )
        )
    )
    return delete_rendered_observations(
        db,
        observation_ids,
        artifact_store=artifact_store,
        targets_requested=len(target_ids),
    )


def preview_render_run_deletion(
    db: Session, site_id: int, run_id: int
) -> RenderDeleteImpact | None:
    run = _owned_run(db, site_id, run_id)
    if run is None:
        return None
    observation_ids = list(
        db.scalars(
            select(RenderedObservation.id).where(RenderedObservation.render_run_id == run.id)
        )
    )
    base = preview_rendered_observations(db, observation_ids, targets_requested=0)
    target_counts = db.execute(
        select(
            func.count(RenderRunTarget.id),
            func.sum(func.coalesce(RenderRunTarget.evidence_deleted_at.is_not(None), False)),
        ).where(RenderRunTarget.render_run_id == run.id)
    ).one()
    jobs = select(BackgroundJob.id).where(BackgroundJob.render_run_id == run.id)
    target_count = target_counts[0] or 0
    deleted_target_count = target_counts[1] or 0
    unattempted_target_count = max(target_count - len(observation_ids) - deleted_target_count, 0)
    return base.model_copy(
        update={
            "can_delete": base.reason is None and run.status in TERMINAL_JOB_STATUSES,
            "reason": base.reason
            or (None if run.status in TERMINAL_JOB_STATUSES else ACTIVE_RENDER_DELETE_REASON),
            "runs": 1,
            "targets_requested": target_count,
            "targets_already_without_evidence": deleted_target_count + unattempted_target_count,
            "run_targets": target_count,
            "deleted_targets": deleted_target_count,
            "unattempted_targets": unattempted_target_count,
            "background_jobs": db.scalar(select(func.count()).select_from(jobs.subquery())) or 0,
            "job_events": db.scalar(
                select(func.count(JobEvent.id)).where(JobEvent.job_id.in_(jobs))
            )
            or 0,
            "child_rerender_links_detached": db.scalar(
                select(func.count(RenderRun.id)).where(RenderRun.source_render_run_id == run.id)
            )
            or 0,
        }
    )


def delete_render_run(
    db: Session,
    site_id: int,
    run_id: int,
    confirmation: str,
    artifact_store: LocalArtifactStore,
) -> RenderDeleteResult | None:
    preview = preview_render_run_deletion(db, site_id, run_id)
    if preview is None:
        return None
    if confirmation != f"DELETE RENDER RUN {run_id}":
        raise ValueError(f"Type DELETE RENDER RUN {run_id} to confirm.")
    _require_deletable(preview)
    observation_ids = list(
        db.scalars(
            select(RenderedObservation.id).where(RenderedObservation.render_run_id == run_id)
        )
    )
    blobs = _artifact_impact(db, observation_ids).blobs
    _delete_observation_rows(db, observation_ids)
    job_ids = select(BackgroundJob.id).where(BackgroundJob.render_run_id == run_id)
    db.execute(delete(JobEvent).where(JobEvent.job_id.in_(job_ids)))
    db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids)))
    db.execute(
        update(RenderRun)
        .where(RenderRun.source_render_run_id == run_id)
        .values(source_render_run_id=None)
    )
    db.execute(delete(RenderRunTarget).where(RenderRunTarget.render_run_id == run_id))
    db.execute(delete(RenderRun).where(RenderRun.id == run_id))
    db.flush()
    deleted_blobs = _delete_unreferenced_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = cleanup_render_artifact_files(artifact_store, deleted_blobs)
    return _result_from_preview(
        preview,
        deleted_blobs,
        files_deleted,
        warnings,
        deleted_run_id=run_id,
    )


def preview_site_rendered_purge(db: Session, site_id: int) -> RenderDeleteImpact | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    run_ids = list(db.scalars(select(RenderRun.id).where(RenderRun.website_property_id == site_id)))
    legacy_ids = _legacy_site_observation_ids(db, site_id)
    run_observation_ids = (
        list(
            db.scalars(
                select(RenderedObservation.id).where(RenderedObservation.render_run_id.in_(run_ids))
            )
        )
        if run_ids
        else []
    )
    base = preview_rendered_observations(db, run_observation_ids + legacy_ids, targets_requested=0)
    target_rows = (
        db.execute(
            select(
                func.count(RenderRunTarget.id),
                func.sum(func.coalesce(RenderRunTarget.evidence_deleted_at.is_not(None), False)),
            ).where(RenderRunTarget.render_run_id.in_(run_ids))
        ).one()
        if run_ids
        else (0, 0)
    )
    jobs = select(BackgroundJob.id).where(BackgroundJob.render_run_id.in_(run_ids))
    nonterminal = (
        db.scalar(
            select(func.count(RenderRun.id)).where(
                RenderRun.id.in_(run_ids), RenderRun.status.not_in(TERMINAL_JOB_STATUSES)
            )
        )
        if run_ids
        else 0
    )
    reason = base.reason or (ACTIVE_RENDER_DELETE_REASON if nonterminal else None)
    target_count = target_rows[0] or 0
    deleted_target_count = target_rows[1] or 0
    unattempted_target_count = max(
        target_count - len(run_observation_ids) - deleted_target_count, 0
    )
    return base.model_copy(
        update={
            "can_delete": reason is None,
            "reason": reason,
            "runs": len(run_ids),
            "targets_requested": target_count,
            "targets_already_without_evidence": deleted_target_count + unattempted_target_count,
            "run_targets": target_count,
            "deleted_targets": deleted_target_count,
            "unattempted_targets": unattempted_target_count,
            "legacy_observations": len(legacy_ids),
            "background_jobs": db.scalar(select(func.count()).select_from(jobs.subquery())) or 0,
            "job_events": db.scalar(
                select(func.count(JobEvent.id)).where(JobEvent.job_id.in_(jobs))
            )
            or 0,
        }
    )


def purge_site_rendered_evidence(
    db: Session,
    site_id: int,
    confirmation: str,
    artifact_store: LocalArtifactStore,
) -> RenderDeleteResult | None:
    preview = preview_site_rendered_purge(db, site_id)
    if preview is None:
        return None
    if confirmation != "DELETE RENDERED EVIDENCE":
        raise ValueError("Type DELETE RENDERED EVIDENCE to confirm.")
    _require_deletable(preview)
    run_ids = list(db.scalars(select(RenderRun.id).where(RenderRun.website_property_id == site_id)))
    observation_ids = (
        list(
            db.scalars(
                select(RenderedObservation.id).where(RenderedObservation.render_run_id.in_(run_ids))
            )
        )
        if run_ids
        else []
    )
    observation_ids += _legacy_site_observation_ids(db, site_id)
    blobs = _artifact_impact(db, observation_ids).blobs
    _delete_observation_rows(db, observation_ids)
    if run_ids:
        jobs = select(BackgroundJob.id).where(BackgroundJob.render_run_id.in_(run_ids))
        db.execute(delete(JobEvent).where(JobEvent.job_id.in_(jobs)))
        db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(jobs)))
        db.execute(
            update(RenderRun)
            .where(RenderRun.source_render_run_id.in_(run_ids))
            .values(source_render_run_id=None)
        )
        db.execute(delete(RenderRunTarget).where(RenderRunTarget.render_run_id.in_(run_ids)))
        db.execute(delete(RenderRun).where(RenderRun.id.in_(run_ids)))
    db.flush()
    deleted_blobs = _delete_unreferenced_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = cleanup_render_artifact_files(artifact_store, deleted_blobs)
    return _result_from_preview(
        preview, deleted_blobs, files_deleted, warnings, purged_site_id=site_id
    )


def preview_scan_rendered_purge(db: Session, scan_id: int) -> RenderDeleteImpact | None:
    if db.get(Scan, scan_id) is None:
        return None
    run_ids = list(
        db.scalars(
            select(RenderRun.id).where(
                RenderRun.source_scan_id == scan_id, RenderRun.website_property_id.is_(None)
            )
        )
    )
    legacy_ids = _legacy_scan_observation_ids(db, scan_id)
    run_ids_observations = (
        list(
            db.scalars(
                select(RenderedObservation.id).where(RenderedObservation.render_run_id.in_(run_ids))
            )
        )
        if run_ids
        else []
    )
    base = preview_rendered_observations(db, legacy_ids + run_ids_observations, targets_requested=0)
    nonterminal = (
        db.scalar(
            select(func.count(RenderRun.id)).where(
                RenderRun.id.in_(run_ids), RenderRun.status.not_in(TERMINAL_JOB_STATUSES)
            )
        )
        if run_ids
        else 0
    )
    reason = base.reason or (ACTIVE_RENDER_DELETE_REASON if nonterminal else None)
    jobs = select(BackgroundJob.id).where(BackgroundJob.render_run_id.in_(run_ids))
    target_rows = (
        db.execute(
            select(
                func.count(RenderRunTarget.id),
                func.sum(func.coalesce(RenderRunTarget.evidence_deleted_at.is_not(None), False)),
            ).where(RenderRunTarget.render_run_id.in_(run_ids))
        ).one()
        if run_ids
        else (0, 0)
    )
    target_count = target_rows[0] or 0
    deleted_target_count = target_rows[1] or 0
    unattempted_target_count = max(
        target_count - len(run_ids_observations) - deleted_target_count, 0
    )
    return base.model_copy(
        update={
            "can_delete": reason is None,
            "reason": reason,
            "runs": len(run_ids),
            "targets_requested": target_count,
            "targets_already_without_evidence": deleted_target_count + unattempted_target_count,
            "run_targets": target_count,
            "deleted_targets": deleted_target_count,
            "unattempted_targets": unattempted_target_count,
            "legacy_observations": len(legacy_ids),
            "background_jobs": (db.scalar(select(func.count()).select_from(jobs.subquery())) or 0),
            "job_events": (
                db.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id.in_(jobs))) or 0
            ),
        }
    )


def purge_scan_rendered_evidence(
    db: Session,
    scan_id: int,
    confirmation: str,
    artifact_store: LocalArtifactStore,
) -> RenderDeleteResult | None:
    preview = preview_scan_rendered_purge(db, scan_id)
    if preview is None:
        return None
    if confirmation != f"DELETE SCAN RENDERS {scan_id}":
        raise ValueError(f"Type DELETE SCAN RENDERS {scan_id} to confirm.")
    _require_deletable(preview)
    run_ids = list(
        db.scalars(
            select(RenderRun.id).where(
                RenderRun.source_scan_id == scan_id, RenderRun.website_property_id.is_(None)
            )
        )
    )
    observation_ids = _legacy_scan_observation_ids(db, scan_id)
    if run_ids:
        observation_ids += list(
            db.scalars(
                select(RenderedObservation.id).where(RenderedObservation.render_run_id.in_(run_ids))
            )
        )
    blobs = _artifact_impact(db, observation_ids).blobs
    _delete_observation_rows(db, observation_ids)
    if run_ids:
        jobs = select(BackgroundJob.id).where(BackgroundJob.render_run_id.in_(run_ids))
        db.execute(delete(JobEvent).where(JobEvent.job_id.in_(jobs)))
        db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(jobs)))
        db.execute(delete(RenderRunTarget).where(RenderRunTarget.render_run_id.in_(run_ids)))
        db.execute(delete(RenderRun).where(RenderRun.id.in_(run_ids)))
    db.flush()
    deleted_blobs = _delete_unreferenced_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = cleanup_render_artifact_files(artifact_store, deleted_blobs)
    return _result_from_preview(
        preview, deleted_blobs, files_deleted, warnings, purged_scan_id=scan_id
    )


def _observation_impact(db: Session, observation_ids: list[int]) -> dict[str, int]:
    if not observation_ids:
        return {}
    impact = _artifact_impact(db, observation_ids)
    return {
        "network_rows": _count(
            db,
            RenderedNetworkEntry.id,
            RenderedNetworkEntry.rendered_observation_id,
            observation_ids,
        ),
        "console_rows": _count(
            db,
            RenderedConsoleMessage.id,
            RenderedConsoleMessage.rendered_observation_id,
            observation_ids,
        ),
        "page_error_rows": _count(
            db, RenderedPageError.id, RenderedPageError.rendered_observation_id, observation_ids
        ),
        "artifact_rows": _count(
            db, RenderedArtifact.id, RenderedArtifact.rendered_observation_id, observation_ids
        ),
        "artifact_blobs_referenced": len(impact.blobs),
        "exclusive_artifact_blobs": len(impact.exclusive),
        "shared_artifact_blobs_retained": len(impact.blobs) - len(impact.exclusive),
        "raw_bytes_reclaimable": sum(blob.raw_byte_size for blob in impact.exclusive),
        "stored_bytes_reclaimable": sum(blob.stored_byte_size for blob in impact.exclusive),
    }


def _artifact_impact(db: Session, observation_ids: list[int]) -> _ArtifactImpact:
    if not observation_ids:
        return _ArtifactImpact([], [])
    blob_ids = list(
        db.scalars(
            select(distinct(RenderedArtifact.artifact_blob_id)).where(
                RenderedArtifact.rendered_observation_id.in_(observation_ids)
            )
        )
    )
    if not blob_ids:
        return _ArtifactImpact([], [])
    blobs = list(db.scalars(select(ArtifactBlob).where(ArtifactBlob.id.in_(blob_ids))))
    scoped = {
        blob_id: count
        for blob_id, count in db.execute(
            select(RenderedArtifact.artifact_blob_id, func.count())
            .where(RenderedArtifact.rendered_observation_id.in_(observation_ids))
            .group_by(RenderedArtifact.artifact_blob_id)
        )
    }
    total = {
        blob_id: count
        for blob_id, count in db.execute(
            select(RenderedArtifact.artifact_blob_id, func.count())
            .where(RenderedArtifact.artifact_blob_id.in_(blob_ids))
            .group_by(RenderedArtifact.artifact_blob_id)
        )
    }
    return _ArtifactImpact(blobs, [blob for blob in blobs if scoped[blob.id] == total[blob.id]])


def _delete_observation_rows(db: Session, observation_ids: list[int]) -> None:
    if not observation_ids:
        return
    for model in (
        RenderedNetworkEntry,
        RenderedConsoleMessage,
        RenderedPageError,
        RenderedArtifact,
    ):
        db.execute(delete(model).where(model.rendered_observation_id.in_(observation_ids)))
    db.execute(delete(RenderedObservation).where(RenderedObservation.id.in_(observation_ids)))


def _delete_unreferenced_blobs(db: Session, blobs: list[ArtifactBlob]) -> list[ArtifactBlob]:
    if not blobs:
        return []
    referenced = set(
        db.scalars(
            select(distinct(RenderedArtifact.artifact_blob_id)).where(
                RenderedArtifact.artifact_blob_id.in_([blob.id for blob in blobs])
            )
        )
    )
    deleted = [blob for blob in blobs if blob.id not in referenced]
    if deleted:
        db.execute(delete(ArtifactBlob).where(ArtifactBlob.id.in_([blob.id for blob in deleted])))
    return deleted


def cleanup_render_artifact_files(
    store: LocalArtifactStore, blobs: list[ArtifactBlob]
) -> tuple[int, list[str]]:
    deleted = 0
    warnings: list[str] = []
    for blob in blobs:
        try:
            if store.delete(blob):
                deleted += 1
            else:
                warnings.append(f"Rendered artifact file was already missing: {blob.storage_key}")
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not delete rendered artifact file {blob.storage_key}: {exc}")
    return deleted, warnings


def _result_from_preview(
    preview: RenderDeleteImpact,
    deleted_blobs: list[ArtifactBlob],
    files_deleted: int,
    warnings: list[str],
    **identities: int | None,
) -> RenderDeleteResult:
    return RenderDeleteResult(
        **identities,
        targets_requested=preview.targets_requested,
        observations_deleted=preview.observations,
        targets_already_without_evidence=preview.targets_already_without_evidence,
        runs_deleted=preview.runs,
        run_targets_deleted=preview.run_targets,
        network_rows_deleted=preview.network_rows,
        console_rows_deleted=preview.console_rows,
        page_error_rows_deleted=preview.page_error_rows,
        artifact_rows_deleted=preview.artifact_rows,
        artifact_blobs_referenced=preview.artifact_blobs_referenced,
        artifact_blob_records_deleted=len(deleted_blobs),
        artifact_blob_files_deleted=files_deleted,
        shared_artifact_blobs_retained=preview.shared_artifact_blobs_retained,
        raw_bytes_reclaimed=sum(blob.raw_byte_size for blob in deleted_blobs),
        stored_bytes_reclaimed=sum(blob.stored_byte_size for blob in deleted_blobs),
        background_jobs_deleted=preview.background_jobs,
        job_events_deleted=preview.job_events,
        child_rerender_links_detached=preview.child_rerender_links_detached,
        warnings=warnings,
    )


def _active_run_reason(db: Session, run_ids: set[int]) -> str | None:
    if not run_ids:
        return None
    active = (
        db.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.render_run_id.in_(run_ids),
                BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    nonterminal = (
        db.scalar(
            select(func.count(RenderRun.id)).where(
                RenderRun.id.in_(run_ids), RenderRun.status.not_in(TERMINAL_JOB_STATUSES)
            )
        )
        or 0
    )
    return ACTIVE_RENDER_DELETE_REASON if active or nonterminal else None


def _owned_run(db: Session, site_id: int, run_id: int) -> RenderRun | None:
    return db.scalar(
        select(RenderRun).where(RenderRun.id == run_id, RenderRun.website_property_id == site_id)
    )


def _legacy_scan_observation_ids(db: Session, scan_id: int) -> list[int]:
    return list(
        db.scalars(
            select(RenderedObservation.id)
            .join(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
            .where(
                ResourceSnapshot.scan_id == scan_id,
                RenderedObservation.render_run_id.is_(None),
            )
        )
    )


def _legacy_site_observation_ids(db: Session, site_id: int) -> list[int]:
    return list(
        db.scalars(
            select(RenderedObservation.id)
            .join(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
            .join(Scan, Scan.id == ResourceSnapshot.scan_id)
            .where(
                Scan.website_property_id == site_id,
                RenderedObservation.render_run_id.is_(None),
            )
        )
    )


def _count(db: Session, id_column: Any, owner_column: Any, ids: list[int]) -> int:
    return db.scalar(select(func.count(id_column)).where(owner_column.in_(ids))) or 0


def _bounded_ids(values: list[int], name: str) -> list[int]:
    if not values:
        raise ValueError(f"{name} must contain at least one ID.")
    if len(values) > MAX_RENDER_DELETE_SELECTION:
        raise ValueError(f"{name} supports at most {MAX_RENDER_DELETE_SELECTION} IDs.")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates.")
    return values


def _require_deletable(preview: RenderDeleteImpact) -> None:
    if not preview.can_delete:
        raise RuntimeError(preview.reason or "Rendered evidence cannot be deleted right now.")
