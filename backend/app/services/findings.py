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
                evaluation=_evaluation_read(db, evaluations[item.finding_evaluation_id]),
                evidence_references=[
                    _reference_read(db, ref, site_id) for ref in refs_by_assessment.get(item.id, [])
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
    items = db.scalars(
        select(FindingEvaluation)
        .where(FindingEvaluation.website_property_id == site_id)
        .order_by(FindingEvaluation.created_at.desc(), FindingEvaluation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return FindingEvaluationList(
        items=[_evaluation_read(db, item) for item in items],
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
    return _evaluation_read(db, item) if item else None


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


def _evaluation_read(db: Session, item: FindingEvaluation) -> FindingEvaluationRead:
    job_id = db.scalar(
        select(BackgroundJob.id).where(BackgroundJob.dedupe_key == f"finding-evaluation:{item.id}")
    )
    return FindingEvaluationRead.model_validate(item).model_copy(
        update={"background_job_id": job_id}
    )


def _reference_read(
    db: Session, item: FindingEvidenceReference, site_id: int
) -> FindingEvidenceReferenceRead:
    retained = False
    href: str | None = None
    if item.evidence_kind == "resource_snapshot":
        snapshot = db.get(ResourceSnapshot, item.evidence_id)
        retained = bool(snapshot and snapshot.resource_id)
        if snapshot:
            href = f"/scans/{snapshot.scan_id}/pages/{snapshot.id}"
    elif item.evidence_kind == "scan":
        scan = db.get(Scan, item.evidence_id)
        retained = bool(scan and scan.website_property_id == site_id)
        if scan:
            href = f"/scans/{scan.id}"
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
