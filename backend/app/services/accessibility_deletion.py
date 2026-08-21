from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityPayloadBlob,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    BackgroundJob,
    JobEvent,
    WebsiteProperty,
)
from app.schemas.accessibility import (
    AccessibilityDeleteResult,
    AccessibilityObservationDeletePreview,
    AccessibilityRunDeletePreview,
    AccessibilitySiteDeletePreview,
)
from app.services.job_types import (
    ACTIVE_JOB_STATUSES,
    JOB_TYPE_ACCESSIBILITY_RUN,
    TERMINAL_JOB_STATUSES,
)
from app.storage.accessibility_store import LocalAccessibilityPayloadStore


@dataclass(frozen=True)
class _PayloadImpact:
    blobs: list[AccessibilityPayloadBlob]
    exclusive: list[AccessibilityPayloadBlob]

    @property
    def raw_bytes(self) -> int:
        return sum(blob.raw_byte_size for blob in self.exclusive)

    @property
    def stored_bytes(self) -> int:
        return sum(blob.stored_byte_size for blob in self.exclusive)


def preview_accessibility_observation_deletion(
    db: Session, site_id: int, observation_id: int
) -> AccessibilityObservationDeletePreview | None:
    observation = db.scalar(
        select(AccessibilityObservation).where(
            AccessibilityObservation.id == observation_id,
            AccessibilityObservation.website_property_id == site_id,
        )
    )
    if observation is None:
        return None
    run = db.get(AccessibilityRun, observation.accessibility_run_id)
    assert run is not None
    rule_ids = select(AccessibilityRuleEvidence.id).where(
        AccessibilityRuleEvidence.accessibility_observation_id == observation.id
    )
    rules = db.scalar(select(func.count()).select_from(rule_ids.subquery())) or 0
    nodes = (
        db.scalar(
            select(func.count(AccessibilityNodeEvidence.id)).where(
                AccessibilityNodeEvidence.accessibility_rule_evidence_id.in_(rule_ids)
            )
        )
        or 0
    )
    reason = _deletion_block_reason(db, run.status)
    blob = (
        db.get(AccessibilityPayloadBlob, observation.payload_blob_id)
        if observation.payload_blob_id is not None
        else None
    )
    references = _payload_reference_count(db, observation.payload_blob_id)
    reclaimable = blob is not None and references == 1
    return AccessibilityObservationDeletePreview(
        can_delete=reason is None,
        reason=reason,
        observation_id=observation.id,
        run_id=run.id,
        profile=observation.profile,
        outcome=observation.outcome,
        observed_at=observation.observed_at,
        requested_url=observation.requested_url,
        violation_rule_count=observation.violation_rule_count,
        incomplete_rule_count=observation.incomplete_rule_count,
        rule_rows_deleted=rules,
        node_rows_deleted=nodes,
        payload_present=blob is not None,
        payload_shared=references > 1,
        payload_reference_count=references,
        payload_raw_bytes=blob.raw_byte_size if blob else 0,
        payload_stored_bytes=blob.stored_byte_size if blob else 0,
        raw_bytes_reclaimable=blob.raw_byte_size if reclaimable and blob else 0,
        stored_bytes_reclaimable=blob.stored_byte_size if reclaimable and blob else 0,
    )


def delete_accessibility_observation(
    db: Session,
    site_id: int,
    observation_id: int,
    store: LocalAccessibilityPayloadStore,
) -> AccessibilityDeleteResult | None:
    preview = preview_accessibility_observation_deletion(db, site_id, observation_id)
    if preview is None:
        return None
    _require_deletable(preview.can_delete, preview.reason)
    observation = db.scalar(
        select(AccessibilityObservation).where(
            AccessibilityObservation.id == observation_id,
            AccessibilityObservation.website_property_id == site_id,
        )
    )
    assert observation is not None
    blob = (
        db.get(AccessibilityPayloadBlob, observation.payload_blob_id)
        if observation.payload_blob_id is not None
        else None
    )
    _delete_observation_rows(
        db, select(AccessibilityObservation.id).where(AccessibilityObservation.id == observation.id)
    )
    db.flush()
    deleted_blobs = _delete_unreferenced_payload_blobs(db, [blob] if blob else [])
    db.commit()
    files_deleted, warnings = _delete_payload_files(store, deleted_blobs)
    return AccessibilityDeleteResult(
        deleted_observation_id=observation_id,
        observations_deleted=1,
        rule_rows_deleted=preview.rule_rows_deleted,
        node_rows_deleted=preview.node_rows_deleted,
        payload_blob_records_deleted=len(deleted_blobs),
        payload_blob_files_deleted=files_deleted,
        raw_bytes_reclaimed=sum(item.raw_byte_size for item in deleted_blobs),
        stored_bytes_reclaimed=sum(item.stored_byte_size for item in deleted_blobs),
        warnings=warnings,
    )


def preview_accessibility_run_deletion(
    db: Session, site_id: int, run_id: int
) -> AccessibilityRunDeletePreview | None:
    run = db.scalar(
        select(AccessibilityRun).where(
            AccessibilityRun.id == run_id, AccessibilityRun.website_property_id == site_id
        )
    )
    if run is None:
        return None
    retained = _run_observation_count(db, run.id)
    rules, nodes = _evidence_counts(db, AccessibilityObservation.accessibility_run_id == run.id)
    impact = _payload_impact(db, AccessibilityObservation.accessibility_run_id == run.id)
    jobs, events = _job_counts(db, AccessibilityRun.id == run.id)
    reason = _deletion_block_reason(db, run.status)
    return AccessibilityRunDeletePreview(
        can_delete=reason is None,
        reason=reason,
        run_id=run.id,
        status=run.status,
        created_at=run.created_at,
        finished_at=run.finished_at,
        completed_count=run.completed_count,
        ready_count=run.ready_count,
        failed_count=run.failed_count,
        retained_observation_count=retained,
        deleted_observation_count=max(run.completed_count - retained, 0),
        rule_rows_removed=rules,
        node_rows_removed=nodes,
        payload_blobs_referenced=len(impact.blobs),
        exclusive_payload_blobs=len(impact.exclusive),
        shared_payload_blobs=len(impact.blobs) - len(impact.exclusive),
        raw_bytes_reclaimable=impact.raw_bytes,
        stored_bytes_reclaimable=impact.stored_bytes,
        background_jobs_removed=jobs,
        job_events_removed=events,
    )


def delete_accessibility_run(
    db: Session,
    site_id: int,
    run_id: int,
    confirmation: str,
    store: LocalAccessibilityPayloadStore,
) -> AccessibilityDeleteResult | None:
    preview = preview_accessibility_run_deletion(db, site_id, run_id)
    if preview is None:
        return None
    if confirmation != f"DELETE ACCESSIBILITY RUN {run_id}":
        raise ValueError(f"Type DELETE ACCESSIBILITY RUN {run_id} to confirm.")
    _require_deletable(preview.can_delete, preview.reason)
    blobs = _payload_impact(db, AccessibilityObservation.accessibility_run_id == run_id).blobs
    _delete_run_rows(db, AccessibilityRun.id == run_id)
    db.flush()
    deleted_blobs = _delete_unreferenced_payload_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = _delete_payload_files(store, deleted_blobs)
    return AccessibilityDeleteResult(
        deleted_run_id=run_id,
        runs_deleted=1,
        observations_deleted=preview.retained_observation_count,
        rule_rows_deleted=preview.rule_rows_removed,
        node_rows_deleted=preview.node_rows_removed,
        background_jobs_deleted=preview.background_jobs_removed,
        job_events_deleted=preview.job_events_removed,
        payload_blob_records_deleted=len(deleted_blobs),
        payload_blob_files_deleted=files_deleted,
        raw_bytes_reclaimed=sum(item.raw_byte_size for item in deleted_blobs),
        stored_bytes_reclaimed=sum(item.stored_byte_size for item in deleted_blobs),
        warnings=warnings,
    )


def preview_accessibility_site_deletion(
    db: Session, site_id: int
) -> AccessibilitySiteDeletePreview | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    run_rows = list(
        db.execute(
            select(
                AccessibilityRun.id, AccessibilityRun.status, AccessibilityRun.completed_count
            ).where(AccessibilityRun.website_property_id == site_id)
        )
    )
    retained = (
        db.scalar(
            select(func.count(AccessibilityObservation.id)).where(
                AccessibilityObservation.website_property_id == site_id
            )
        )
        or 0
    )
    rules, nodes = _evidence_counts(db, AccessibilityObservation.website_property_id == site_id)
    impact = _payload_impact(db, AccessibilityObservation.website_property_id == site_id)
    jobs, events = _site_job_counts(db, site_id)
    nonterminal = [
        status for _id, status, _completed in run_rows if status not in TERMINAL_JOB_STATUSES
    ]
    reason = (
        "Finish or cancel every Accessibility collection for this Site before deleting evidence."
        if nonterminal
        else _active_job_reason(db)
    )
    completed = sum(row.completed_count for row in run_rows)
    return AccessibilitySiteDeletePreview(
        can_delete=reason is None,
        reason=reason,
        site_id=site_id,
        runs=len(run_rows),
        retained_observations=retained,
        already_deleted_observations=max(completed - retained, 0),
        rule_rows_removed=rules,
        node_rows_removed=nodes,
        background_jobs_removed=jobs,
        job_events_removed=events,
        payload_blobs_referenced=len(impact.blobs),
        exclusive_payload_blobs=len(impact.exclusive),
        shared_payload_blobs=len(impact.blobs) - len(impact.exclusive),
        raw_bytes_reclaimable=impact.raw_bytes,
        stored_bytes_reclaimable=impact.stored_bytes,
    )


def purge_accessibility_site(
    db: Session,
    site_id: int,
    confirmation: str,
    store: LocalAccessibilityPayloadStore,
) -> AccessibilityDeleteResult | None:
    preview = preview_accessibility_site_deletion(db, site_id)
    if preview is None:
        return None
    if confirmation != "DELETE ACCESSIBILITY":
        raise ValueError("Type DELETE ACCESSIBILITY to confirm.")
    _require_deletable(preview.can_delete, preview.reason)
    blobs = _payload_impact(db, AccessibilityObservation.website_property_id == site_id).blobs
    _delete_run_rows(db, AccessibilityRun.website_property_id == site_id)
    db.flush()
    deleted_blobs = _delete_unreferenced_payload_blobs(db, blobs)
    db.commit()
    files_deleted, warnings = _delete_payload_files(store, deleted_blobs)
    return AccessibilityDeleteResult(
        purged_site_id=site_id,
        runs_deleted=preview.runs,
        observations_deleted=preview.retained_observations,
        rule_rows_deleted=preview.rule_rows_removed,
        node_rows_deleted=preview.node_rows_removed,
        background_jobs_deleted=preview.background_jobs_removed,
        job_events_deleted=preview.job_events_removed,
        payload_blob_records_deleted=len(deleted_blobs),
        payload_blob_files_deleted=files_deleted,
        raw_bytes_reclaimed=sum(item.raw_byte_size for item in deleted_blobs),
        stored_bytes_reclaimed=sum(item.stored_byte_size for item in deleted_blobs),
        warnings=warnings,
    )


def delete_unreferenced_accessibility_blobs(
    db: Session, blobs: list[AccessibilityPayloadBlob]
) -> list[AccessibilityPayloadBlob]:
    return _delete_unreferenced_payload_blobs(db, blobs)


def prepare_accessibility_site_cleanup(db: Session, site_id: int) -> list[AccessibilityPayloadBlob]:
    blobs = _payload_impact(db, AccessibilityObservation.website_property_id == site_id).blobs
    _delete_run_rows(db, AccessibilityRun.website_property_id == site_id)
    db.flush()
    return _delete_unreferenced_payload_blobs(db, blobs)


def cleanup_accessibility_payload_files(
    store: LocalAccessibilityPayloadStore, blobs: list[AccessibilityPayloadBlob]
) -> tuple[int, list[str]]:
    return _delete_payload_files(store, blobs)


def _payload_impact(db: Session, observation_filter: ColumnElement[bool]) -> _PayloadImpact:
    blob_ids = list(
        db.scalars(
            select(distinct(AccessibilityObservation.payload_blob_id)).where(
                observation_filter,
                AccessibilityObservation.payload_blob_id.is_not(None),
            )
        )
    )
    blobs = (
        list(
            db.scalars(
                select(AccessibilityPayloadBlob).where(AccessibilityPayloadBlob.id.in_(blob_ids))
            )
        )
        if blob_ids
        else []
    )
    scoped_counts: dict[int, int] = (
        {
            blob_id: count
            for blob_id, count in db.execute(
                select(AccessibilityObservation.payload_blob_id, func.count())
                .where(observation_filter, AccessibilityObservation.payload_blob_id.in_(blob_ids))
                .group_by(AccessibilityObservation.payload_blob_id)
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
                select(AccessibilityObservation.payload_blob_id, func.count())
                .where(AccessibilityObservation.payload_blob_id.in_(blob_ids))
                .group_by(AccessibilityObservation.payload_blob_id)
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


def _evidence_counts(db: Session, observation_filter: ColumnElement[bool]) -> tuple[int, int]:
    observation_ids = select(AccessibilityObservation.id).where(observation_filter)
    rule_ids = select(AccessibilityRuleEvidence.id).where(
        AccessibilityRuleEvidence.accessibility_observation_id.in_(observation_ids)
    )
    rules = db.scalar(select(func.count()).select_from(rule_ids.subquery())) or 0
    nodes = (
        db.scalar(
            select(func.count(AccessibilityNodeEvidence.id)).where(
                AccessibilityNodeEvidence.accessibility_rule_evidence_id.in_(rule_ids)
            )
        )
        or 0
    )
    return rules, nodes


def _deletion_block_reason(db: Session, run_status: str) -> str | None:
    if run_status not in TERMINAL_JOB_STATUSES:
        return "The Accessibility Run must finish or be cancelled before deleting evidence."
    return _active_job_reason(db)


def _active_job_reason(db: Session) -> str | None:
    active = (
        db.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.job_type == JOB_TYPE_ACCESSIBILITY_RUN,
                BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    return (
        "Finish or cancel active Accessibility collection before deleting evidence."
        if active
        else None
    )


def _payload_reference_count(db: Session, blob_id: int | None) -> int:
    if blob_id is None:
        return 0
    return (
        db.scalar(
            select(func.count(AccessibilityObservation.id)).where(
                AccessibilityObservation.payload_blob_id == blob_id
            )
        )
        or 0
    )


def _run_observation_count(db: Session, run_id: int) -> int:
    return (
        db.scalar(
            select(func.count(AccessibilityObservation.id)).where(
                AccessibilityObservation.accessibility_run_id == run_id
            )
        )
        or 0
    )


def _job_counts(db: Session, run_filter: ColumnElement[bool]) -> tuple[int, int]:
    run_ids = select(AccessibilityRun.id).where(run_filter)
    jobs = select(BackgroundJob.id).where(BackgroundJob.accessibility_run_id.in_(run_ids))
    return (
        db.scalar(select(func.count()).select_from(jobs.subquery())) or 0,
        db.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id.in_(jobs))) or 0,
    )


def _site_job_counts(db: Session, site_id: int) -> tuple[int, int]:
    return _job_counts(db, AccessibilityRun.website_property_id == site_id)


def _delete_observation_rows(db: Session, observation_ids: Select[tuple[int]]) -> None:
    rule_ids = select(AccessibilityRuleEvidence.id).where(
        AccessibilityRuleEvidence.accessibility_observation_id.in_(observation_ids)
    )
    db.execute(
        delete(AccessibilityNodeEvidence).where(
            AccessibilityNodeEvidence.accessibility_rule_evidence_id.in_(rule_ids)
        )
    )
    db.execute(delete(AccessibilityRuleEvidence).where(AccessibilityRuleEvidence.id.in_(rule_ids)))
    db.execute(
        delete(AccessibilityObservation).where(AccessibilityObservation.id.in_(observation_ids))
    )


def _delete_run_rows(db: Session, run_filter: ColumnElement[bool]) -> None:
    run_ids = select(AccessibilityRun.id).where(run_filter)
    job_ids = select(BackgroundJob.id).where(BackgroundJob.accessibility_run_id.in_(run_ids))
    db.execute(delete(JobEvent).where(JobEvent.job_id.in_(job_ids)))
    db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids)))
    observation_ids = select(AccessibilityObservation.id).where(
        AccessibilityObservation.accessibility_run_id.in_(run_ids)
    )
    _delete_observation_rows(db, observation_ids)
    db.execute(delete(AccessibilityRun).where(AccessibilityRun.id.in_(run_ids)))


def _delete_unreferenced_payload_blobs(
    db: Session, blobs: list[AccessibilityPayloadBlob]
) -> list[AccessibilityPayloadBlob]:
    if not blobs:
        return []
    referenced = set(
        db.scalars(
            select(distinct(AccessibilityObservation.payload_blob_id)).where(
                AccessibilityObservation.payload_blob_id.in_([blob.id for blob in blobs])
            )
        )
    )
    deleted = [blob for blob in blobs if blob.id not in referenced]
    if deleted:
        db.execute(
            delete(AccessibilityPayloadBlob).where(
                AccessibilityPayloadBlob.id.in_([blob.id for blob in deleted])
            )
        )
    return deleted


def _delete_payload_files(
    store: LocalAccessibilityPayloadStore, blobs: list[AccessibilityPayloadBlob]
) -> tuple[int, list[str]]:
    deleted = 0
    warnings: list[str] = []
    for blob in blobs:
        try:
            if store.delete(blob):
                deleted += 1
            else:
                warnings.append(
                    f"Accessibility payload file was already missing: {blob.storage_key}"
                )
        except (OSError, ValueError) as exc:
            warnings.append(
                f"Could not delete Accessibility payload file {blob.storage_key}: {exc}"
            )
    return deleted, warnings


def _require_deletable(can_delete: bool, reason: str | None) -> None:
    if not can_delete:
        raise RuntimeError(reason or "Accessibility evidence cannot be deleted right now.")
