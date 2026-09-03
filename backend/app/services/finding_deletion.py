from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    Finding,
    FindingAssessment,
    FindingEvaluation,
    FindingEvidenceReference,
    JobEvent,
    WebsiteProperty,
)
from app.services.job_types import (
    ACTIVE_JOB_STATUSES,
    JOB_TYPE_FINDING_EVALUATION,
    TERMINAL_JOB_STATUSES,
)


class ActiveFindingEvaluationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FindingResetCounts:
    site_id: int
    deleted_finding_count: int
    deleted_assessment_count: int
    deleted_evidence_reference_count: int
    deleted_evaluation_count: int
    deleted_job_count: int
    deleted_job_event_count: int


def delete_finding(db: Session, site_id: int, finding_id: int) -> bool | None:
    """Stage deletion of one Finding while retaining its frozen evaluation history."""
    if _lock_site(db, site_id) is None:
        return None
    finding = db.scalar(
        select(Finding).where(
            Finding.id == finding_id,
            Finding.website_property_id == site_id,
        )
    )
    if finding is None:
        return False
    _raise_if_active_finding_work(db, site_id)

    assessment_ids = select(FindingAssessment.id).where(FindingAssessment.finding_id == finding_id)
    db.execute(
        delete(FindingEvidenceReference).where(
            FindingEvidenceReference.finding_assessment_id.in_(assessment_ids)
        )
    )
    db.execute(delete(FindingAssessment).where(FindingAssessment.finding_id == finding_id))
    db.execute(
        delete(Finding).where(
            Finding.id == finding_id,
            Finding.website_property_id == site_id,
        )
    )
    return True


def reset_site_findings(db: Session, site_id: int) -> FindingResetCounts | None:
    """Stage an atomic reset of one Site's rebuildable Finding interpretation layer."""
    if _lock_site(db, site_id) is None:
        return None
    _raise_if_active_finding_work(db, site_id)

    finding_ids = select(Finding.id).where(Finding.website_property_id == site_id)
    assessment_ids = select(FindingAssessment.id).where(
        FindingAssessment.finding_id.in_(finding_ids)
    )
    evaluation_ids = select(FindingEvaluation.id).where(
        FindingEvaluation.website_property_id == site_id
    )
    job_ids = select(BackgroundJob.id).where(
        BackgroundJob.website_property_id == site_id,
        BackgroundJob.job_type == JOB_TYPE_FINDING_EVALUATION,
        BackgroundJob.status.in_(TERMINAL_JOB_STATUSES),
    )

    counts = FindingResetCounts(
        site_id=site_id,
        deleted_finding_count=_count(db, Finding.id, Finding.website_property_id == site_id),
        deleted_assessment_count=_count(
            db, FindingAssessment.id, FindingAssessment.finding_id.in_(finding_ids)
        ),
        deleted_evidence_reference_count=_count(
            db,
            FindingEvidenceReference.id,
            FindingEvidenceReference.finding_assessment_id.in_(assessment_ids),
        ),
        deleted_evaluation_count=_count(
            db, FindingEvaluation.id, FindingEvaluation.website_property_id == site_id
        ),
        deleted_job_count=_count(
            db,
            BackgroundJob.id,
            BackgroundJob.website_property_id == site_id,
            BackgroundJob.job_type == JOB_TYPE_FINDING_EVALUATION,
            BackgroundJob.status.in_(TERMINAL_JOB_STATUSES),
        ),
        deleted_job_event_count=_count(db, JobEvent.id, JobEvent.job_id.in_(job_ids)),
    )

    db.execute(
        delete(FindingEvidenceReference).where(
            FindingEvidenceReference.finding_assessment_id.in_(assessment_ids)
        )
    )
    db.execute(delete(FindingAssessment).where(FindingAssessment.finding_id.in_(finding_ids)))
    db.execute(delete(Finding).where(Finding.website_property_id == site_id))
    db.execute(delete(JobEvent).where(JobEvent.job_id.in_(job_ids)))
    db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids)))
    db.execute(delete(FindingEvaluation).where(FindingEvaluation.id.in_(evaluation_ids)))
    return counts


def _raise_if_active_finding_work(db: Session, site_id: int) -> None:
    active_evaluation = db.scalar(
        select(FindingEvaluation.id)
        .where(
            FindingEvaluation.website_property_id == site_id,
            FindingEvaluation.status.in_(ACTIVE_JOB_STATUSES),
        )
        .limit(1)
    )
    active_job = db.scalar(
        select(BackgroundJob.id)
        .where(
            BackgroundJob.website_property_id == site_id,
            BackgroundJob.job_type == JOB_TYPE_FINDING_EVALUATION,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .limit(1)
    )
    if active_evaluation is not None or active_job is not None:
        raise ActiveFindingEvaluationError(
            "Finding deletion is unavailable while a Finding evaluation is queued or running. "
            "Wait for it to finish or cancel it first."
        )


def _lock_site(db: Session, site_id: int) -> WebsiteProperty | None:
    return db.scalar(select(WebsiteProperty).where(WebsiteProperty.id == site_id).with_for_update())


def _count(db: Session, column: Any, *conditions: Any) -> int:
    return db.scalar(select(func.count(column)).where(*conditions)) or 0
