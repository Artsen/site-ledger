from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    BackgroundJob,
    RenderedArtifact,
    RenderedObservation,
    RenderRun,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebsiteProperty,
)
from app.schemas.rendered import (
    LegacyRenderDeleteSelection,
    RenderDeleteConfirmation,
    RenderDeleteImpact,
    RenderDeleteResult,
    RenderDeleteSelection,
    RenderedArtifactRead,
    RenderedObservationIndexList,
    RenderedObservationRead,
    RenderRunCreate,
    RenderRunDetail,
    RenderRunList,
    RenderRunRead,
    RenderRunRerender,
    RenderRunTargetList,
)
from app.services.background_jobs import (
    enqueue_render_run_job,
    request_cancellation,
)
from app.services.render_runs import create_render_run, create_rerender_run
from app.services.rendered_deletion import (
    delete_render_run,
    delete_rendered_observations,
    delete_run_target_evidence,
    preview_render_run_deletion,
    preview_rendered_observations,
    preview_run_target_deletion,
    preview_scan_rendered_purge,
    preview_site_rendered_purge,
    purge_scan_rendered_evidence,
    purge_site_rendered_evidence,
)
from app.services.rendered_queries import (
    RenderOutcome,
    get_render_run,
    list_render_run_observations,
    list_render_run_targets,
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


@router.get(
    "/sites/{site_id}/render-runs/{run_id}/targets",
    response_model=RenderRunTargetList,
)
def run_targets(
    site_id: int,
    run_id: int,
    db: DbSession,
    search: str | None = None,
    outcome: RenderOutcomeFilter = None,
    sort: RenderSort = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RenderRunTargetList:
    _run(db, site_id, run_id)
    return list_render_run_targets(
        db,
        run_id,
        search=search,
        outcomes=outcome,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/sites/{site_id}/render-runs/{run_id}/evidence-deletion-preview",
    response_model=RenderDeleteImpact,
)
def target_deletion_preview(
    site_id: int, run_id: int, payload: RenderDeleteSelection, db: DbSession
) -> RenderDeleteImpact:
    try:
        result = preview_run_target_deletion(db, site_id, run_id, payload.target_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Render Run not found")
    return result


@router.post(
    "/sites/{site_id}/render-runs/{run_id}/delete-evidence",
    response_model=RenderDeleteResult,
)
def delete_target_evidence(
    site_id: int,
    run_id: int,
    payload: RenderDeleteSelection,
    request: Request,
    db: DbSession,
) -> RenderDeleteResult:
    try:
        result = delete_run_target_evidence(
            db, site_id, run_id, payload.target_ids, request.app.state.artifact_store
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Render Run not found")
    return result


@router.get(
    "/sites/{site_id}/render-runs/{run_id}/deletion-preview",
    response_model=RenderDeleteImpact,
)
def run_deletion_preview(site_id: int, run_id: int, db: DbSession) -> RenderDeleteImpact:
    result = preview_render_run_deletion(db, site_id, run_id)
    if result is None:
        raise HTTPException(404, "Render Run not found")
    return result


@router.delete("/sites/{site_id}/render-runs/{run_id}", response_model=RenderDeleteResult)
def remove_run(
    site_id: int,
    run_id: int,
    payload: RenderDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> RenderDeleteResult:
    try:
        result = delete_render_run(
            db, site_id, run_id, payload.confirmation, request.app.state.artifact_store
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Render Run not found")
    return result


@router.get(
    "/sites/{site_id}/rendered-evidence/deletion-preview",
    response_model=RenderDeleteImpact,
)
def site_deletion_preview(site_id: int, db: DbSession) -> RenderDeleteImpact:
    result = preview_site_rendered_purge(db, site_id)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.delete("/sites/{site_id}/rendered-evidence", response_model=RenderDeleteResult)
def purge_site_evidence(
    site_id: int,
    payload: RenderDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> RenderDeleteResult:
    try:
        result = purge_site_rendered_evidence(
            db, site_id, payload.confirmation, request.app.state.artifact_store
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get(
    "/scans/{scan_id}/rendered-evidence/deletion-preview",
    response_model=RenderDeleteImpact,
)
def scan_deletion_preview(scan_id: int, db: DbSession) -> RenderDeleteImpact:
    result = preview_scan_rendered_purge(db, scan_id)
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.delete("/scans/{scan_id}/rendered-evidence", response_model=RenderDeleteResult)
def purge_scan_evidence(
    scan_id: int,
    payload: RenderDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> RenderDeleteResult:
    try:
        result = purge_scan_rendered_evidence(
            db, scan_id, payload.confirmation, request.app.state.artifact_store
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.post(
    "/scans/{scan_id}/rendered-observations/deletion-preview",
    response_model=RenderDeleteImpact,
)
def legacy_deletion_preview(
    scan_id: int, payload: LegacyRenderDeleteSelection, db: DbSession
) -> RenderDeleteImpact:
    ids = _legacy_scan_selection(db, scan_id, payload.observation_ids)
    return preview_rendered_observations(db, ids)


@router.post(
    "/scans/{scan_id}/rendered-observations/delete",
    response_model=RenderDeleteResult,
)
def delete_legacy_selection(
    scan_id: int,
    payload: LegacyRenderDeleteSelection,
    request: Request,
    db: DbSession,
) -> RenderDeleteResult:
    ids = _legacy_scan_selection(db, scan_id, payload.observation_ids)
    try:
        return delete_rendered_observations(
            db, ids, artifact_store=request.app.state.artifact_store
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


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
    "/sites/{site_id}/rendered-observations/{observation_id}/deletion-preview",
    response_model=RenderDeleteImpact,
)
def observation_deletion_preview(
    site_id: int, observation_id: int, db: DbSession
) -> RenderDeleteImpact:
    _site_observation(db, site_id, observation_id)
    return preview_rendered_observations(db, [observation_id])


@router.delete(
    "/sites/{site_id}/rendered-observations/{observation_id}",
    response_model=RenderDeleteResult,
)
def remove_observation(
    site_id: int,
    observation_id: int,
    request: Request,
    db: DbSession,
) -> RenderDeleteResult:
    _site_observation(db, site_id, observation_id)
    try:
        return delete_rendered_observations(
            db, [observation_id], artifact_store=request.app.state.artifact_store
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


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


def _site_observation(db: Session, site_id: int, observation_id: int) -> int:
    owned_run_ids = select(RenderRun.id).where(RenderRun.website_property_id == site_id)
    owned_snapshot_ids = (
        select(ResourceSnapshot.id)
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .where(Scan.website_property_id == site_id)
    )
    result = db.scalar(
        select(RenderedObservation.id).where(
            RenderedObservation.id == observation_id,
            or_(
                RenderedObservation.render_run_id.in_(owned_run_ids),
                RenderedObservation.snapshot_id.in_(owned_snapshot_ids),
            ),
        )
    )
    if result is None:
        raise HTTPException(404, "Rendered observation not found")
    return result


def _legacy_scan_selection(db: Session, scan_id: int, observation_ids: list[int]) -> list[int]:
    if db.get(Scan, scan_id) is None:
        raise HTTPException(404, "Scan not found")
    ids = list(
        db.scalars(
            select(RenderedObservation.id)
            .join(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
            .where(
                ResourceSnapshot.scan_id == scan_id,
                RenderedObservation.render_run_id.is_(None),
                RenderedObservation.id.in_(observation_ids),
            )
        )
    )
    if len(ids) != len(observation_ids):
        raise HTTPException(404, "One or more rendered observations were not found")
    return ids
