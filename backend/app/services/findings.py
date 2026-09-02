from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    Finding,
    FindingAssessment,
    FindingEvaluation,
    FindingEvidenceReference,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.findings import (
    AssessmentOutcome,
    FindingAssessmentRead,
    FindingDetail,
    FindingEvaluationList,
    FindingEvaluationRead,
    FindingEvidenceReferenceRead,
    FindingList,
    FindingListItem,
    FindingSeverity,
    FindingState,
)
from app.services.finding_detectors import FINDING_TYPE_LABELS


def list_findings(
    db: Session,
    site_id: int,
    *,
    condition_state: str | None,
    severity: str | None,
    finding_type: str | None,
    acknowledged: bool | None,
    search: str | None,
    include_suppressed: bool,
    limit: int,
    offset: int,
) -> FindingList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    join_condition = and_(
        SitePage.website_property_id == Finding.website_property_id,
        SitePage.resource_id == Finding.web_resource_id,
    )
    query = (
        select(Finding, WebResource.normalized_url, SitePage.workspace_state, FindingAssessment)
        .join(WebResource, WebResource.id == Finding.web_resource_id)
        .outerjoin(SitePage, join_condition)
        .outerjoin(FindingAssessment, FindingAssessment.id == Finding.current_assessment_id)
        .where(Finding.website_property_id == site_id)
    )
    if not include_suppressed:
        query = query.where(SitePage.workspace_state == "active")
    if condition_state:
        query = query.where(Finding.condition_state == condition_state)
    if severity:
        query = query.where(Finding.current_severity == severity)
    if finding_type:
        query = query.where(Finding.finding_type == finding_type)
    if acknowledged is not None:
        query = query.where(
            Finding.acknowledged_at.is_not(None)
            if acknowledged
            else Finding.acknowledged_at.is_(None)
        )
    if search:
        query = query.where(WebResource.normalized_url.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.execute(
        query.order_by(
            Finding.condition_state.asc(),
            Finding.current_severity.asc(),
            Finding.last_evaluated_evidence_at.desc(),
            Finding.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return FindingList(
        items=[
            _list_item(finding, url, workspace, assessment)
            for finding, url, workspace, assessment in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_finding(db: Session, site_id: int, finding_id: int) -> FindingDetail | None:
    row = db.execute(
        select(Finding, WebResource.normalized_url, SitePage.workspace_state, FindingAssessment)
        .join(WebResource, WebResource.id == Finding.web_resource_id)
        .outerjoin(
            SitePage,
            and_(
                SitePage.website_property_id == Finding.website_property_id,
                SitePage.resource_id == Finding.web_resource_id,
            ),
        )
        .outerjoin(FindingAssessment, FindingAssessment.id == Finding.current_assessment_id)
        .where(Finding.website_property_id == site_id, Finding.id == finding_id)
    ).first()
    if row is None:
        return None
    finding, url, workspace, current = row
    assessments = list(
        db.scalars(
            select(FindingAssessment)
            .where(FindingAssessment.finding_id == finding.id)
            .order_by(FindingAssessment.evidence_observed_at.desc(), FindingAssessment.id.desc())
        )
    )
    references = list(
        db.scalars(
            select(FindingEvidenceReference)
            .where(
                FindingEvidenceReference.finding_assessment_id.in_(
                    [item.id for item in assessments] or [-1]
                )
            )
            .order_by(
                FindingEvidenceReference.finding_assessment_id, FindingEvidenceReference.position
            )
        )
    )
    refs_by_assessment: dict[int, list[FindingEvidenceReference]] = {}
    for reference in references:
        refs_by_assessment.setdefault(reference.finding_assessment_id, []).append(reference)
    evaluations = {
        item.id: item
        for item in db.scalars(
            select(FindingEvaluation).where(
                FindingEvaluation.id.in_(
                    [item.finding_evaluation_id for item in assessments] or [-1]
                )
            )
        )
    }
    evaluation_job_ids = _evaluation_job_ids(db, list(evaluations))
    snapshot_ids = {
        reference.evidence_id
        for reference in references
        if reference.evidence_kind == "resource_snapshot"
    }
    snapshot_links = (
        {
            snapshot_id: (scan_id, resource_id)
            for snapshot_id, scan_id, resource_id in db.execute(
                select(
                    ResourceSnapshot.id, ResourceSnapshot.scan_id, ResourceSnapshot.resource_id
                ).where(ResourceSnapshot.id.in_(snapshot_ids))
            )
        }
        if snapshot_ids
        else {}
    )
    scan_ids = {
        reference.evidence_id for reference in references if reference.evidence_kind == "scan"
    }
    retained_scans = (
        {
            scan_id: website_property_id
            for scan_id, website_property_id in db.execute(
                select(Scan.id, Scan.website_property_id).where(Scan.id.in_(scan_ids))
            )
        }
        if scan_ids
        else {}
    )
    base = _list_item(finding, url, workspace, current)
    return FindingDetail(
        **base.model_dump(),
        website_property_id=finding.website_property_id,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
        assessments=[
            FindingAssessmentRead(
                id=item.id,
                finding_evaluation_id=item.finding_evaluation_id,
                outcome=cast(AssessmentOutcome, item.outcome),
                severity=cast(FindingSeverity | None, item.severity),
                evidence_observed_at=item.evidence_observed_at,
                details_json=item.details_json,
                assessment_sha256=item.assessment_sha256,
                created_at=item.created_at,
                evaluation=_evaluation_read(
                    evaluations[item.finding_evaluation_id],
                    evaluation_job_ids.get(item.finding_evaluation_id),
                ),
                evidence_references=[
                    _reference_read(ref, site_id, snapshot_links, retained_scans)
                    for ref in refs_by_assessment.get(item.id, [])
                ],
            )
            for item in assessments
        ],
    )


def list_evaluations(
    db: Session, site_id: int, limit: int, offset: int
) -> FindingEvaluationList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    total = (
        db.scalar(
            select(func.count())
            .select_from(FindingEvaluation)
            .where(FindingEvaluation.website_property_id == site_id)
        )
        or 0
    )
    items = list(
        db.scalars(
            select(FindingEvaluation)
            .where(FindingEvaluation.website_property_id == site_id)
            .order_by(FindingEvaluation.created_at.desc(), FindingEvaluation.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    job_ids = _evaluation_job_ids(db, [item.id for item in items])
    return FindingEvaluationList(
        items=[_evaluation_read(item, job_ids.get(item.id)) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_evaluation(db: Session, site_id: int, evaluation_id: int) -> FindingEvaluationRead | None:
    item = db.scalar(
        select(FindingEvaluation).where(
            FindingEvaluation.id == evaluation_id,
            FindingEvaluation.website_property_id == site_id,
        )
    )
    if item is None:
        return None
    job_ids = _evaluation_job_ids(db, [item.id])
    return _evaluation_read(item, job_ids.get(item.id))


def set_acknowledged(
    db: Session, site_id: int, finding_id: int, acknowledged: bool
) -> FindingDetail | None:
    finding = db.scalar(
        select(Finding).where(Finding.id == finding_id, Finding.website_property_id == site_id)
    )
    if finding is None:
        return None
    finding.acknowledged_at = datetime.now(UTC) if acknowledged else None
    db.commit()
    return get_finding(db, site_id, finding_id)


def _list_item(
    finding: Finding, url: str, workspace: str | None, assessment: FindingAssessment | None
) -> FindingListItem:
    return FindingListItem(
        id=finding.id,
        web_resource_id=finding.web_resource_id,
        page_url=url,
        finding_type=finding.finding_type,
        finding_label=FINDING_TYPE_LABELS.get(
            finding.finding_type, finding.finding_type.replace("_", " ").title()
        ),
        logical_key_version=finding.logical_key_version,
        fingerprint_sha256=finding.fingerprint_sha256,
        condition_state=cast(FindingState, finding.condition_state),
        current_severity=cast(FindingSeverity | None, finding.current_severity),
        first_detected_at=finding.first_detected_at,
        last_detected_at=finding.last_detected_at,
        last_evaluated_evidence_at=finding.last_evaluated_evidence_at,
        resolved_at=finding.resolved_at,
        reopened_at=finding.reopened_at,
        acknowledged_at=finding.acknowledged_at,
        current_assessment_id=finding.current_assessment_id,
        page_workspace_state=workspace,
        current_evidence_summary=assessment.details_json if assessment else {},
    )


def _evaluation_read(
    item: FindingEvaluation, background_job_id: int | None
) -> FindingEvaluationRead:
    return FindingEvaluationRead.model_validate(item).model_copy(
        update={"background_job_id": background_job_id}
    )


def _evaluation_job_ids(db: Session, evaluation_ids: list[int]) -> dict[int, int]:
    if not evaluation_ids:
        return {}
    key_to_evaluation_id = {
        f"finding-evaluation:{evaluation_id}": evaluation_id for evaluation_id in evaluation_ids
    }
    return {
        key_to_evaluation_id[dedupe_key]: job_id
        for job_id, dedupe_key in db.execute(
            select(BackgroundJob.id, BackgroundJob.dedupe_key).where(
                BackgroundJob.dedupe_key.in_(key_to_evaluation_id)
            )
        )
    }


def _reference_read(
    item: FindingEvidenceReference,
    site_id: int,
    snapshot_links: dict[int, tuple[int, int]],
    retained_scans: dict[int, int],
) -> FindingEvidenceReferenceRead:
    retained = False
    href: str | None = None
    if item.evidence_kind == "resource_snapshot":
        snapshot = snapshot_links.get(item.evidence_id)
        retained = snapshot is not None
        if snapshot is not None:
            scan_id, _resource_id = snapshot
            href = f"/scans/{scan_id}/pages/{item.evidence_id}"
    elif item.evidence_kind == "scan":
        retained = retained_scans.get(item.evidence_id) == site_id
        if retained:
            href = f"/scans/{item.evidence_id}"
    return FindingEvidenceReferenceRead(
        id=item.id,
        position=item.position,
        role=item.role,
        evidence_kind=item.evidence_kind,
        evidence_id=item.evidence_id,
        evidence_observed_at=item.evidence_observed_at,
        metadata_json=item.metadata_json,
        retained=retained,
        href=href,
    )
