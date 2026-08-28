from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.findings import (
    FindingDetail,
    FindingEvaluationList,
    FindingEvaluationRead,
    FindingList,
)
from app.services import background_jobs
from app.services.finding_evaluations import create_evaluation
from app.services.findings import (
    get_evaluation,
    get_finding,
    list_evaluations,
    list_findings,
    set_acknowledged,
)

router = APIRouter(prefix="/api", tags=["findings"])
DbSession = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=250)]
Offset = Annotated[int, Query(ge=0)]


@router.post(
    "/sites/{site_id}/findings/evaluations", response_model=FindingEvaluationRead, status_code=202
)
def post_finding_evaluation(site_id: int, db: DbSession) -> FindingEvaluationRead:
    try:
        evaluation, created = create_evaluation(db, site_id)
        if created:
            background_jobs.enqueue_finding_evaluation_job(db, evaluation.id, site_id)
        elif evaluation.status in {"failed", "cancelled"}:
            background_jobs.requeue_finding_evaluation_job(db, evaluation.id, site_id)
        db.commit()
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409 if "terminal Scan" in str(exc) else 404, str(exc)) from exc
    result = get_evaluation(db, site_id, evaluation.id)
    assert result is not None
    return result


@router.get("/sites/{site_id}/findings/evaluations", response_model=FindingEvaluationList)
def get_finding_evaluations(
    site_id: int, db: DbSession, limit: Limit = 50, offset: Offset = 0
) -> FindingEvaluationList:
    result = list_evaluations(db, site_id, limit, offset)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get(
    "/sites/{site_id}/findings/evaluations/{evaluation_id}", response_model=FindingEvaluationRead
)
def get_finding_evaluation(
    site_id: int, evaluation_id: int, db: DbSession
) -> FindingEvaluationRead:
    result = get_evaluation(db, site_id, evaluation_id)
    if result is None:
        raise HTTPException(404, "Finding evaluation not found")
    return result


@router.get("/sites/{site_id}/findings", response_model=FindingList)
def get_findings(
    site_id: int,
    db: DbSession,
    condition_state: Literal["detected", "unknown", "resolved"] | None = None,
    severity: Literal["medium", "high"] | None = None,
    finding_type: str | None = None,
    acknowledged: bool | None = None,
    search: str | None = None,
    include_suppressed: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> FindingList:
    result = list_findings(
        db,
        site_id,
        condition_state=condition_state,
        severity=severity,
        finding_type=finding_type,
        acknowledged=acknowledged,
        search=search,
        include_suppressed=include_suppressed,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get("/sites/{site_id}/findings/{finding_id}", response_model=FindingDetail)
def get_finding_detail(site_id: int, finding_id: int, db: DbSession) -> FindingDetail:
    result = get_finding(db, site_id, finding_id)
    if result is None:
        raise HTTPException(404, "Finding not found")
    return result


@router.post("/sites/{site_id}/findings/{finding_id}/acknowledge", response_model=FindingDetail)
def acknowledge_finding(site_id: int, finding_id: int, db: DbSession) -> FindingDetail:
    result = set_acknowledged(db, site_id, finding_id, True)
    if result is None:
        raise HTTPException(404, "Finding not found")
    return result


@router.post("/sites/{site_id}/findings/{finding_id}/unacknowledge", response_model=FindingDetail)
def unacknowledge_finding(site_id: int, finding_id: int, db: DbSession) -> FindingDetail:
    result = set_acknowledged(db, site_id, finding_id, False)
    if result is None:
        raise HTTPException(404, "Finding not found")
    return result
