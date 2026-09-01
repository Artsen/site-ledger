from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accessibility.engine import (
    ACCESSIBILITY_INTEGRATION_VERSION,
    ACCESSIBILITY_NORMALIZATION_VERSION,
    AXE_BUNDLE_SHA256,
    AXE_CORE_VERSION,
    PROFILES,
    RULESET_PROFILE,
    RULESET_SHA256,
    ruleset_metadata,
)
from app.config import OBSERVABILITY_ABSOLUTE_PAGE_LIMIT, get_settings
from app.database import get_db
from app.models import AccessibilityObservation, AccessibilityRun, BackgroundJob, WebsiteProperty
from app.schemas.accessibility import (
    AccessibilityCapabilities,
    AccessibilityDeleteConfirmation,
    AccessibilityDeleteResult,
    AccessibilityNodeList,
    AccessibilityObservationDeletePreview,
    AccessibilityObservationList,
    AccessibilityObservationRead,
    AccessibilityPageSummaryList,
    AccessibilityRuleAggregateList,
    AccessibilityRuleDetail,
    AccessibilityRuleList,
    AccessibilityRunCreate,
    AccessibilityRunDeletePreview,
    AccessibilityRunDetail,
    AccessibilityRunList,
    AccessibilityRunRead,
    AccessibilitySiteDeletePreview,
    AccessibilitySummary,
)
from app.services.accessibility_collection import create_accessibility_run
from app.services.accessibility_deletion import (
    delete_accessibility_observation,
    delete_accessibility_run,
    preview_accessibility_observation_deletion,
    preview_accessibility_run_deletion,
    preview_accessibility_site_deletion,
    purge_accessibility_site,
)
from app.services.accessibility_queries import (
    accessibility_pages,
    accessibility_rule_detail,
    accessibility_rules,
    accessibility_summary,
    get_accessibility_run,
    latest_accessibility,
    list_accessibility_runs,
    observation_read,
    observation_rule_nodes,
    observation_rules,
    page_accessibility_history,
    page_latest_accessibility,
)
from app.services.background_jobs import enqueue_accessibility_run_job
from app.services.native_cancellation import request_native_cancellation
from app.services.site_pages import find_site_page
from app.storage.accessibility_store import (
    AccessibilityPayloadNotFoundError,
    LocalAccessibilityPayloadStore,
)

router = APIRouter(prefix="/api", tags=["accessibility"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/accessibility/capabilities", response_model=AccessibilityCapabilities)
def capabilities() -> AccessibilityCapabilities:
    settings = get_settings()
    return AccessibilityCapabilities(
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=len(ruleset_metadata()["rules"]),
        ruleset_sha256=RULESET_SHA256,
        default_page_limit=settings.accessibility_default_page_limit,
        hard_page_limit=settings.accessibility_hard_page_limit,
        absolute_page_limit=OBSERVABILITY_ABSOLUTE_PAGE_LIMIT,
        max_audit_count=settings.accessibility_max_audit_count,
        profiles=PROFILES,
    )


@router.post(
    "/sites/{site_id}/accessibility-runs", response_model=AccessibilityRunRead, status_code=202
)
def create_run(
    site_id: int, payload: AccessibilityRunCreate, db: DbSession
) -> AccessibilityRunRead:
    try:
        run = create_accessibility_run(db, site_id, payload)
        job = enqueue_accessibility_run_job(db, run.id, site_id)
        db.commit()
        db.refresh(run)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(404 if str(exc) == "Site not found." else 422, str(exc)) from exc
    return AccessibilityRunRead.model_validate(
        {
            **{column.name: getattr(run, column.name) for column in run.__table__.columns},
            "job_id": job.id,
            "presentation_status": job.status,
        }
    )


@router.get("/sites/{site_id}/accessibility-runs", response_model=AccessibilityRunList)
def list_runs(
    site_id: int, db: DbSession, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)
) -> AccessibilityRunList:
    _site(db, site_id)
    return list_accessibility_runs(db, site_id, limit=limit, offset=offset)


@router.get("/sites/{site_id}/accessibility-runs/{run_id}", response_model=AccessibilityRunDetail)
def get_run(
    site_id: int,
    run_id: int,
    db: DbSession,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AccessibilityRunDetail:
    result = get_accessibility_run(db, site_id, run_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(404, "Accessibility run not found")
    return result


@router.post(
    "/sites/{site_id}/accessibility-runs/{run_id}/cancel", response_model=AccessibilityRunRead
)
def cancel_run(site_id: int, run_id: int, db: DbSession) -> AccessibilityRunRead:
    run = db.scalar(
        select(AccessibilityRun).where(
            AccessibilityRun.id == run_id, AccessibilityRun.website_property_id == site_id
        )
    )
    if run is None:
        raise HTTPException(404, "Accessibility run not found")
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.accessibility_run_id == run_id))
    if job:
        request_native_cancellation(db, job, "Accessibility audit cancellation requested.")
    result = get_accessibility_run(db, site_id, run_id, limit=1, offset=0)
    assert result is not None
    return AccessibilityRunRead(**result.model_dump(exclude={"observations"}))


@router.get(
    "/sites/{site_id}/accessibility-runs/{run_id}/deletion-preview",
    response_model=AccessibilityRunDeletePreview,
)
def run_deletion_preview(site_id: int, run_id: int, db: DbSession) -> AccessibilityRunDeletePreview:
    result = preview_accessibility_run_deletion(db, site_id, run_id)
    if result is None:
        raise HTTPException(404, "Accessibility run not found")
    return result


@router.delete(
    "/sites/{site_id}/accessibility-runs/{run_id}",
    response_model=AccessibilityDeleteResult,
)
def remove_run(
    site_id: int,
    run_id: int,
    payload: AccessibilityDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> AccessibilityDeleteResult:
    store: LocalAccessibilityPayloadStore = request.app.state.accessibility_payload_store
    try:
        result = delete_accessibility_run(db, site_id, run_id, payload.confirmation, store)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Accessibility run not found")
    return result


@router.get("/sites/{site_id}/accessibility/latest", response_model=AccessibilityObservationList)
def latest(
    site_id: int, db: DbSession, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
) -> AccessibilityObservationList:
    _site(db, site_id)
    return latest_accessibility(db, site_id, limit=limit, offset=offset)


@router.get("/sites/{site_id}/accessibility/summary", response_model=AccessibilitySummary)
def summary(site_id: int, db: DbSession) -> AccessibilitySummary:
    _site(db, site_id)
    return accessibility_summary(db, site_id)


@router.get("/sites/{site_id}/accessibility/pages", response_model=AccessibilityPageSummaryList)
def pages(
    site_id: int,
    db: DbSession,
    search: str | None = None,
    outcome: Literal["ready", "failed"] | None = None,
    impact: Literal["critical", "serious"] | None = None,
    has_violations: bool | None = None,
    needs_review: bool | None = None,
    sort: Literal[
        "page", "audited", "desktop", "mobile", "critical", "serious", "needs_review"
    ] = "audited",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(100, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> AccessibilityPageSummaryList:
    _site(db, site_id)
    return accessibility_pages(
        db,
        site_id,
        search=search,
        outcome=outcome,
        impact=impact,
        has_violations=has_violations,
        needs_review=needs_review,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.get("/sites/{site_id}/accessibility/rules", response_model=AccessibilityRuleAggregateList)
def rules(
    site_id: int,
    db: DbSession,
    result_type: Literal["violation", "incomplete"] | None = None,
    impact: str | None = None,
    profile: Literal["desktop", "mobile"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AccessibilityRuleAggregateList:
    _site(db, site_id)
    return accessibility_rules(
        db,
        site_id,
        result_type=result_type,
        impact=impact,
        profile=profile,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sites/{site_id}/accessibility/rules/{rule_id}", response_model=AccessibilityRuleDetail
)
def rule_detail(
    site_id: int,
    rule_id: str,
    db: DbSession,
    result_type: Literal["violation", "incomplete"] = "violation",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AccessibilityRuleDetail:
    result = accessibility_rule_detail(
        db, site_id, rule_id, result_type=result_type, limit=limit, offset=offset
    )
    if result is None:
        raise HTTPException(404, "Accessibility rule evidence not found")
    return result


@router.get(
    "/sites/{site_id}/pages/{resource_id}/accessibility",
    response_model=AccessibilityObservationList,
)
def page_history(
    site_id: int,
    resource_id: int,
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AccessibilityObservationList:
    resolved_id = _page(db, site_id, resource_id)
    return page_accessibility_history(db, site_id, resolved_id, limit=limit, offset=offset)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/accessibility/latest",
    response_model=AccessibilityObservationList,
)
def page_latest(site_id: int, resource_id: int, db: DbSession) -> AccessibilityObservationList:
    resolved_id = _page(db, site_id, resource_id)
    return page_latest_accessibility(db, site_id, resolved_id)


@router.get(
    "/sites/{site_id}/accessibility-observations/{observation_id}",
    response_model=AccessibilityObservationRead,
)
def observation_detail(
    site_id: int, observation_id: int, db: DbSession
) -> AccessibilityObservationRead:
    observation = db.scalar(
        select(AccessibilityObservation)
        .options(
            selectinload(AccessibilityObservation.web_resource),
            selectinload(AccessibilityObservation.payload_blob),
        )
        .where(
            AccessibilityObservation.id == observation_id,
            AccessibilityObservation.website_property_id == site_id,
        )
    )
    if observation is None:
        raise HTTPException(404, "Accessibility observation not found")
    return observation_read(observation)


@router.get(
    "/sites/{site_id}/accessibility-observations/{observation_id}/deletion-preview",
    response_model=AccessibilityObservationDeletePreview,
)
def observation_deletion_preview(
    site_id: int, observation_id: int, db: DbSession
) -> AccessibilityObservationDeletePreview:
    result = preview_accessibility_observation_deletion(db, site_id, observation_id)
    if result is None:
        raise HTTPException(404, "Accessibility observation not found")
    return result


@router.delete(
    "/sites/{site_id}/accessibility-observations/{observation_id}",
    response_model=AccessibilityDeleteResult,
)
def remove_observation(
    site_id: int, observation_id: int, request: Request, db: DbSession
) -> AccessibilityDeleteResult:
    store: LocalAccessibilityPayloadStore = request.app.state.accessibility_payload_store
    try:
        result = delete_accessibility_observation(db, site_id, observation_id, store)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Accessibility observation not found")
    return result


@router.get(
    "/sites/{site_id}/accessibility/deletion-preview",
    response_model=AccessibilitySiteDeletePreview,
)
def site_deletion_preview(site_id: int, db: DbSession) -> AccessibilitySiteDeletePreview:
    result = preview_accessibility_site_deletion(db, site_id)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.delete("/sites/{site_id}/accessibility", response_model=AccessibilityDeleteResult)
def purge_site(
    site_id: int,
    payload: AccessibilityDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> AccessibilityDeleteResult:
    store: LocalAccessibilityPayloadStore = request.app.state.accessibility_payload_store
    try:
        result = purge_accessibility_site(db, site_id, payload.confirmation, store)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get(
    "/sites/{site_id}/accessibility-observations/{observation_id}/rules",
    response_model=AccessibilityRuleList,
)
def observation_rule_list(
    site_id: int,
    observation_id: int,
    db: DbSession,
    result_type: Literal["violation", "incomplete"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AccessibilityRuleList:
    result = observation_rules(
        db,
        site_id,
        observation_id,
        result_type=result_type,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Accessibility observation not found")
    return result


@router.get(
    "/sites/{site_id}/accessibility-observations/{observation_id}/rules/{rule_evidence_id}/nodes",
    response_model=AccessibilityNodeList,
)
def observation_node_list(
    site_id: int,
    observation_id: int,
    rule_evidence_id: int,
    db: DbSession,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AccessibilityNodeList:
    result = observation_rule_nodes(
        db,
        site_id,
        observation_id,
        rule_evidence_id,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Accessibility rule evidence not found")
    return result


@router.get("/accessibility-observations/{observation_id}/raw")
def raw_payload(observation_id: int, request: Request, db: DbSession) -> Response:
    observation = db.get(AccessibilityObservation, observation_id)
    if observation is None or observation.payload_blob is None:
        raise HTTPException(404, "Accessibility payload not found")
    store: LocalAccessibilityPayloadStore = request.app.state.accessibility_payload_store
    try:
        content = store.read(observation.payload_blob)
    except AccessibilityPayloadNotFoundError as exc:
        raise HTTPException(404, "Accessibility payload file is missing") from exc
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "X-Content-SHA256": observation.payload_blob.sha256,
        },
    )


def _site(db: Session, site_id: int) -> None:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")


def _page(db: Session, site_id: int, resource_id: int) -> int:
    page = find_site_page(db, site_id, resource_id)
    if page is None:
        raise HTTPException(404, "Page not found")
    return page.resource_id
