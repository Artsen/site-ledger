from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    BackgroundJob,
    RenderedArtifact,
    RenderedObservation,
    RenderRun,
    SitePage,
    WebsiteProperty,
)
from app.schemas.rendered import (
    RenderedArtifactRead,
    RenderedObservationIndexList,
    RenderedObservationRead,
    RenderRunCreate,
    RenderRunDetail,
    RenderRunList,
    RenderRunRead,
    RenderRunRerender,
)
from app.services.background_jobs import (
    enqueue_render_run_job,
    request_cancellation,
)
from app.services.render_runs import create_render_run, create_rerender_run
from app.services.rendered_queries import (
    RenderOutcome,
    get_render_run,
    list_render_run_observations,
    list_render_runs,
    page_render_history,
)

router = APIRouter(prefix="/api", tags=["rendered"])
DbSession = Annotated[Session, Depends(get_db)]
RenderSort = Literal[
    "page_url",
    "capture_state",
    "duration",
    "navigation_status",
    "warning_count",
    "page_error_count",
    "browser_evidence",
    "capture_time",
]
RenderOutcomeFilter = Annotated[list[RenderOutcome] | None, Query()]


@router.post("/sites/{site_id}/render-runs", response_model=RenderRunRead, status_code=202)
def create_run(site_id: int, payload: RenderRunCreate, db: DbSession) -> RenderRunRead:
    try:
        run = create_render_run(db, site_id, payload)
        enqueue_render_run_job(db, run)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(404 if str(exc) == "Site not found." else 422, str(exc)) from exc
    result = get_render_run(db, site_id, run.id, limit=1)
    assert result is not None
    return RenderRunRead(**result.model_dump(exclude={"observations"}))


@router.get("/sites/{site_id}/render-runs", response_model=RenderRunList)
def runs(
    site_id: int,
    db: DbSession,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> RenderRunList:
    _site(db, site_id)
    return list_render_runs(db, site_id, limit=limit, offset=offset)


@router.get("/sites/{site_id}/render-runs/{run_id}", response_model=RenderRunDetail)
def run_detail(
    site_id: int,
    run_id: int,
    db: DbSession,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    outcome: RenderOutcomeFilter = None,
    sort: RenderSort = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RenderRunDetail:
    result = get_render_run(
        db,
        site_id,
        run_id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_viewport_screenshot=has_viewport_screenshot,
        outcomes=outcome,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Render Run not found")
    return result


@router.get(
    "/sites/{site_id}/render-runs/{run_id}/observations",
    response_model=RenderedObservationIndexList,
)
def run_observations(
    site_id: int,
    run_id: int,
    db: DbSession,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    outcome: RenderOutcomeFilter = None,
    sort: RenderSort = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RenderedObservationIndexList:
    _run(db, site_id, run_id)
    return list_render_run_observations(
        db,
        run_id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_viewport_screenshot=has_viewport_screenshot,
        outcomes=outcome,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/sites/{site_id}/render-runs/{run_id}/rerender",
    response_model=RenderRunRead,
    status_code=202,
)
def rerender(site_id: int, run_id: int, payload: RenderRunRerender, db: DbSession) -> RenderRunRead:
    try:
        run = create_rerender_run(db, site_id, run_id, payload.target_ids)
        enqueue_render_run_job(db, run)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(404 if str(exc) == "Render Run not found." else 422, str(exc)) from exc
    result = get_render_run(db, site_id, run.id, limit=1)
    assert result is not None
    return RenderRunRead(**result.model_dump(exclude={"observations"}))


@router.post("/sites/{site_id}/render-runs/{run_id}/cancel", response_model=RenderRunRead)
def cancel_run(site_id: int, run_id: int, db: DbSession) -> RenderRunRead:
    run = _run(db, site_id, run_id)
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.render_run_id == run.id))
    if job:
        request_cancellation(db, job, "Rendered capture cancellation requested.")
        if job.status == "cancelled":
            run.status = "cancelled"
            run.finished_at = job.finished_at
            db.commit()
    result = get_render_run(db, site_id, run.id, limit=1)
    assert result is not None
    return RenderRunRead(**result.model_dump(exclude={"observations"}))


@router.get(
    "/sites/{site_id}/rendered-observations/{observation_id}",
    response_model=RenderedObservationRead,
)
def observation_detail(site_id: int, observation_id: int, db: DbSession) -> RenderedObservationRead:
    observation = db.scalar(
        select(RenderedObservation)
        .join(RenderRun, RenderRun.id == RenderedObservation.render_run_id)
        .options(selectinload(RenderedObservation.artifacts).selectinload(RenderedArtifact.blob))
        .where(
            RenderedObservation.id == observation_id,
            RenderRun.website_property_id == site_id,
        )
    )
    if observation is None:
        raise HTTPException(404, "Rendered observation not found")
    data = {
        column.name: getattr(observation, column.name) for column in observation.__table__.columns
    }
    data["artifacts"] = [
        RenderedArtifactRead(
            id=item.id,
            artifact_type=item.artifact_type,
            width=item.width,
            height=item.height,
            media_type=item.blob.media_type,
            raw_byte_size=item.blob.raw_byte_size,
            stored_byte_size=item.blob.stored_byte_size,
            sha256=item.blob.sha256,
            metadata_json=item.metadata_json,
        )
        for item in observation.artifacts
    ]
    return RenderedObservationRead(**data)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/rendered-observations",
    response_model=RenderedObservationIndexList,
)
def page_history(
    site_id: int,
    resource_id: int,
    db: DbSession,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    outcome: RenderOutcomeFilter = None,
    sort: RenderSort = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> RenderedObservationIndexList:
    exists = db.scalar(
        select(SitePage.id).where(
            SitePage.website_property_id == site_id,
            SitePage.resource_id == resource_id,
        )
    )
    if exists is None:
        raise HTTPException(404, "Page not found")
    return page_render_history(
        db,
        site_id,
        resource_id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_viewport_screenshot=has_viewport_screenshot,
        outcomes=outcome,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


def _site(db: Session, site_id: int) -> WebsiteProperty:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        raise HTTPException(404, "Site not found")
    return site


def _run(db: Session, site_id: int, run_id: int) -> RenderRun:
    run = db.scalar(
        select(RenderRun).where(RenderRun.id == run_id, RenderRun.website_property_id == site_id)
    )
    if run is None:
        raise HTTPException(404, "Render Run not found")
    return run
