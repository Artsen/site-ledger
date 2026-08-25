from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    BackgroundJob,
    JobEvent,
    PerformanceObservation,
    PerformancePayloadBlob,
    PerformanceRun,
    WebsiteProperty,
)
from app.schemas.performance import (
    PerformanceDeleteResult,
    PerformanceObservationDeletePreview,
    PerformanceRunDeletePreview,
    PerformanceSiteDeletePreview,
)
from app.services.job_types import (
    ACTIVE_JOB_STATUSES,
    JOB_TYPE_PERFORMANCE_RUN,
    TERMINAL_JOB_STATUSES,
)
from app.storage.performance_store import LocalPerformancePayloadStore


@dataclass(frozen=True)
class _PayloadImpact:
    blobs: list[PerformancePayloadBlob]
    exclusive: list[PerformancePayloadBlob]

    @property
    def raw_bytes(self) -> int:
        return sum(blob.raw_byte_size for blob in self.exclusive)

    @property
    def stored_bytes(self) -> int:
        return sum(blob.stored_byte_size for blob in self.exclusive)


def preview_performance_observation_deletion(
    db: Session, site_id: int, observation_id: int
) -> PerformanceObservationDeletePreview | None:
    observation = db.scalar(
        select(PerformanceObservation).where(
            PerformanceObservation.id == observation_id,
            PerformanceObservation.website_property_id == site_id,
        )
    )
    if observation is None:
        return None
    run = db.get(PerformanceRun, observation.performance_run_id)
    assert run is not None
    reason = _deletion_block_reason(db, run.status)
    blob = (
        db.get(PerformancePayloadBlob, observation.payload_blob_id)
        if observation.payload_blob_id is not None
        else None
    )
    references = _payload_reference_count(db, observation.payload_blob_id)
    reclaimable = blob is not None and references == 1
    return PerformanceObservationDeletePreview(
        can_delete=reason is None,
        reason=reason,
        observation_id=observation.id,
        run_id=run.id,
        provider=observation.provider,
        dimension=observation.dimension,
        outcome=observation.outcome,
        observed_at=observation.observed_at,
        target_kind=observation.target_kind,
        requested_target=observation.requested_target,
        payload_present=blob is not None,
        payload_shared=references > 1,
        payload_reference_count=references,
        payload_raw_bytes=blob.raw_byte_size if blob else 0,
        payload_stored_bytes=blob.stored_byte_size if blob else 0,
        raw_bytes_reclaimable=blob.raw_byte_size if reclaimable and blob else 0,
        stored_bytes_reclaimable=blob.stored_byte_size if reclaimable and blob else 0,
    )


def delete_performance_observation(
    db: Session,
    site_id: int,
    observation_id: int,
    store: LocalPerformancePayloadStore,
) -> PerformanceDeleteResult | None:
    preview = preview_performance_observation_deletion(db, site_id, observation_id)
    if preview is None:
        return None
    _require_deletable(preview.can_delete, preview.reason)
    observation = db.scalar(
        select(PerformanceObservation).where(
            PerformanceObservation.id == observation_id,
            PerformanceObservation.website_property_id == site_id,
        )
    )
    assert observation is not None
    blob = (
        db.get(PerformancePayloadBlob, observation.payload_blob_id)
        if observation.payload_blob_id is not None
        else None
    )
    db.execute(delete(PerformanceObservation).where(PerformanceObservation.id == observation.id))
    db.flush()
    deleted_blobs = _delete_unreferenced_payload_blobs(db, [blob] if blob else [])
    db.commit()
    files_deleted, warnings = _delete_payload_files(store, deleted_blobs)
    return PerformanceDeleteResult(
        deleted_observation_id=observation_id,
        observations_deleted=1,
        payload_blob_records_deleted=len(deleted_blobs),
        payload_blob_files_deleted=files_deleted,
        raw_bytes_reclaimed=sum(item.raw_byte_size for item in deleted_blobs),
        stored_bytes_reclaimed=sum(item.stored_byte_size for item in deleted_blobs),
        warnings=warnings,
    )


def preview_performance_run_deletion(
    db: Session, site_id: int, run_id: int
) -> PerformanceRunDeletePreview | None:
    run = db.scalar(
        select(PerformanceRun).where(
            PerformanceRun.id == run_id, PerformanceRun.website_property_id == site_id
        )
    )
    if run is None:
        return None
    retained = _run_observation_count(db, run.id)
    impact = _payload_impact(db, PerformanceObservation.performance_run_id == run.id)
    jobs, events = _job_counts(db, PerformanceRun.id == run.id)
    reason = _deletion_block_reason(db, run.status)
    return PerformanceRunDeletePreview(
        can_delete=reason is None,
        reason=reason,
        run_id=run.id,
        status=run.status,
        created_at=run.created_at,
        finished_at=run.finished_at,
        completed_count=run.completed_count,
        ready_count=run.ready_count,
        unavailable_count=run.unavailable_count,
        failed_count=run.failed_count,
        retained_observation_count=retained,
        deleted_observation_count=max(run.completed_count - retained, 0),
        payload_blobs_referenced=len(impact.blobs),
        exclusive_payload_blobs=len(impact.exclusive),
        shared_payload_blobs=len(impact.blobs) - len(impact.exclusive),
        raw_bytes_reclaimable=impact.raw_bytes,
        stored_bytes_reclaimable=impact.stored_bytes,
        background_jobs_removed=jobs,
        job_events_removed=events,
    )


def delete_performance_run(
    db: Session,
    site_id: int,
    run_id: int,
    confirmation: str,
    store: LocalPerformancePayloadStore,
) -> PerformanceDeleteResult | None:
    preview = preview_performance_run_deletion(db, site_id, run_id)
    if preview is None:
        return None
    if confirmation != f"DELETE PERFORMANCE RUN {run_id}":
        raise ValueError(f"Type DELETE PERFORMANCE RUN {run_id} to confirm.")
    _require_deletable(preview.can_delete, preview.reason)
    blobs = _payload_impact(db, PerformanceObservation.performance_run_id == run_id).blobs
    _delete_run_rows(db, PerformanceRun.id == run_id)
    db.flush()
    deleted_blobs = _delete_unreferenced_payload_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = _delete_payload_files(store, deleted_blobs)
    return PerformanceDeleteResult(
        deleted_run_id=run_id,
        runs_deleted=1,
        observations_deleted=preview.retained_observation_count,
        background_jobs_deleted=preview.background_jobs_removed,
        job_events_deleted=preview.job_events_removed,
        payload_blob_records_deleted=len(deleted_blobs),
        payload_blob_files_deleted=files_deleted,
        raw_bytes_reclaimed=sum(item.raw_byte_size for item in deleted_blobs),
        stored_bytes_reclaimed=sum(item.stored_byte_size for item in deleted_blobs),
        warnings=warnings,
    )


def preview_performance_site_deletion(
    db: Session, site_id: int
) -> PerformanceSiteDeletePreview | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    run_rows = list(
        db.execute(
            select(PerformanceRun.id, PerformanceRun.status, PerformanceRun.completed_count).where(
                PerformanceRun.website_property_id == site_id
            )
        )
    )
    retained = (
        db.scalar(
            select(func.count(PerformanceObservation.id)).where(
                PerformanceObservation.website_property_id == site_id
            )
        )
        or 0
    )
    impact = _payload_impact(db, PerformanceObservation.website_property_id == site_id)
    jobs, events = _site_job_counts(db, site_id)
    nonterminal = [
        status for _id, status, _completed in run_rows if status not in TERMINAL_JOB_STATUSES
    ]
    reason = (
        "Finish or cancel every Performance collection for this Site before deleting evidence."
        if nonterminal
        else _active_job_reason(db)
    )
    completed = sum(row.completed_count for row in run_rows)
    return PerformanceSiteDeletePreview(
        can_delete=reason is None,
        reason=reason,
        site_id=site_id,
        runs=len(run_rows),
        retained_observations=retained,
        already_deleted_observations=max(completed - retained, 0),
        background_jobs_removed=jobs,
        job_events_removed=events,
        payload_blobs_referenced=len(impact.blobs),
        exclusive_payload_blobs=len(impact.exclusive),
        shared_payload_blobs=len(impact.blobs) - len(impact.exclusive),
        raw_bytes_reclaimable=impact.raw_bytes,
        stored_bytes_reclaimable=impact.stored_bytes,
    )


def purge_performance_site(
    db: Session,
    site_id: int,
    confirmation: str,
    store: LocalPerformancePayloadStore,
) -> PerformanceDeleteResult | None:
    preview = preview_performance_site_deletion(db, site_id)
    if preview is None:
        return None
    if confirmation != "DELETE PERFORMANCE":
        raise ValueError("Type DELETE PERFORMANCE to confirm.")
    _require_deletable(preview.can_delete, preview.reason)
    blobs = _payload_impact(db, PerformanceObservation.website_property_id == site_id).blobs
    _delete_run_rows(db, PerformanceRun.website_property_id == site_id)
    db.flush()
    deleted_blobs = _delete_unreferenced_payload_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = _delete_payload_files(store, deleted_blobs)
    return PerformanceDeleteResult(
        purged_site_id=site_id,
        runs_deleted=preview.runs,
        observations_deleted=preview.retained_observations,
        background_jobs_deleted=preview.background_jobs_removed,
        job_events_deleted=preview.job_events_removed,
        payload_blob_records_deleted=len(deleted_blobs),
        payload_blob_files_deleted=files_deleted,
        raw_bytes_reclaimed=sum(item.raw_byte_size for item in deleted_blobs),
        stored_bytes_reclaimed=sum(item.stored_byte_size for item in deleted_blobs),
        warnings=warnings,
    )


def delete_unreferenced_performance_blobs(
    db: Session, blobs: list[PerformancePayloadBlob]
) -> list[PerformancePayloadBlob]:
    return _delete_unreferenced_payload_blobs(db, blobs)


def prepare_performance_site_cleanup(db: Session, site_id: int) -> list[PerformancePayloadBlob]:
    blobs = _payload_impact(db, PerformanceObservation.website_property_id == site_id).blobs
    _delete_run_rows(db, PerformanceRun.website_property_id == site_id)
    db.flush()
    return _delete_unreferenced_payload_blobs(db, blobs)


def cleanup_performance_payload_files(
    store: LocalPerformancePayloadStore, blobs: list[PerformancePayloadBlob]
) -> tuple[int, list[str]]:
    return _delete_payload_files(store, blobs)


def _payload_impact(db: Session, observation_filter: ColumnElement[bool]) -> _PayloadImpact:
    blob_ids = list(
        db.scalars(
            select(distinct(PerformanceObservation.payload_blob_id)).where(
                observation_filter,
                PerformanceObservation.payload_blob_id.is_not(None),
            )
        )
    )
    blobs = (
        list(
            db.scalars(
                select(PerformancePayloadBlob).where(PerformancePayloadBlob.id.in_(blob_ids))
            )
        )
        if blob_ids
        else []
    )
    scoped_counts: dict[int, int] = (
        {
            blob_id: count
            for blob_id, count in db.execute(
                select(PerformanceObservation.payload_blob_id, func.count())
                .where(observation_filter, PerformanceObservation.payload_blob_id.in_(blob_ids))
                .group_by(PerformanceObservation.payload_blob_id)
            )
            if blob_id is not None
        }
        if blob_ids
        else {}
    )
    total_counts: dict[int, int] = (
        {
            blob_id: count
            for blob_id, count in db.execute(
                select(PerformanceObservation.payload_blob_id, func.count())
                .where(PerformanceObservation.payload_blob_id.in_(blob_ids))
                .group_by(PerformanceObservation.payload_blob_id)
            )
            if blob_id is not None
        }
        if blob_ids
        else {}
    )
    exclusive = [
        blob for blob in blobs if scoped_counts.get(blob.id, 0) == total_counts.get(blob.id, 0)
    ]
    return _PayloadImpact(blobs, exclusive)


def _deletion_block_reason(db: Session, run_status: str) -> str | None:
    if run_status not in TERMINAL_JOB_STATUSES:
        return "The Performance Run must finish or be cancelled before deleting evidence."
    return _active_job_reason(db)


def _active_job_reason(db: Session) -> str | None:
    active = (
        db.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.job_type == JOB_TYPE_PERFORMANCE_RUN,
                BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    return (
        "Finish or cancel active Performance collection before deleting evidence."
        if active
        else None
    )


def _payload_reference_count(db: Session, blob_id: int | None) -> int:
    if blob_id is None:
        return 0
    return (
        db.scalar(
            select(func.count(PerformanceObservation.id)).where(
                PerformanceObservation.payload_blob_id == blob_id
            )
        )
        or 0
    )


def _run_observation_count(db: Session, run_id: int) -> int:
    return (
        db.scalar(
            select(func.count(PerformanceObservation.id)).where(
                PerformanceObservation.performance_run_id == run_id
            )
        )
        or 0
    )


def _job_counts(db: Session, run_filter: ColumnElement[bool]) -> tuple[int, int]:
    run_ids = select(PerformanceRun.id).where(run_filter)
    jobs = select(BackgroundJob.id).where(BackgroundJob.performance_run_id.in_(run_ids))
    return (
        db.scalar(select(func.count()).select_from(jobs.subquery())) or 0,
        db.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id.in_(jobs))) or 0,
    )


def _site_job_counts(db: Session, site_id: int) -> tuple[int, int]:
    return _job_counts(db, PerformanceRun.website_property_id == site_id)


def _delete_run_rows(db: Session, run_filter: ColumnElement[bool]) -> None:
    run_ids = select(PerformanceRun.id).where(run_filter)
    job_ids = select(BackgroundJob.id).where(BackgroundJob.performance_run_id.in_(run_ids))
    db.execute(delete(JobEvent).where(JobEvent.job_id.in_(job_ids)))
    db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids)))
    db.execute(
        delete(PerformanceObservation).where(PerformanceObservation.performance_run_id.in_(run_ids))
    )
    db.execute(delete(PerformanceRun).where(PerformanceRun.id.in_(run_ids)))


def _delete_unreferenced_payload_blobs(
    db: Session, blobs: list[PerformancePayloadBlob]
) -> list[PerformancePayloadBlob]:
    if not blobs:
        return []
    referenced = set(
        db.scalars(
            select(distinct(PerformanceObservation.payload_blob_id)).where(
                PerformanceObservation.payload_blob_id.in_([blob.id for blob in blobs])
            )
        )
    )
    deleted = [blob for blob in blobs if blob.id not in referenced]
    if deleted:
        db.execute(
            delete(PerformancePayloadBlob).where(
                PerformancePayloadBlob.id.in_([blob.id for blob in deleted])
            )
        )
    return deleted


def _delete_payload_files(
    store: LocalPerformancePayloadStore, blobs: list[PerformancePayloadBlob]
) -> tuple[int, list[str]]:
    deleted = 0
    warnings: list[str] = []
    for blob in blobs:
        try:
            if store.delete(blob):
                deleted += 1
            else:
                warnings.append(f"Performance payload file was already missing: {blob.storage_key}")
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not delete Performance payload file {blob.storage_key}: {exc}")
    return deleted, warnings


def _require_deletable(can_delete: bool, reason: str | None) -> None:
    if not can_delete:
        raise RuntimeError(reason or "Performance evidence cannot be deleted right now.")
