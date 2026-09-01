from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import OBSERVABILITY_ABSOLUTE_PAGE_LIMIT, get_settings
from app.database import get_db
from app.models import BackgroundJob, PerformanceObservation, PerformanceRun, WebsiteProperty
from app.schemas.performance import (
    PageSpeedAuditPresentation,
    PerformanceDeleteConfirmation,
    PerformanceDeleteResult,
    PerformanceLatestList,
    PerformanceObservationDeletePreview,
    PerformanceObservationList,
    PerformanceObservationPresentation,
    PerformanceObservationRead,
    PerformanceProviderCapabilities,
    PerformanceProviderState,
    PerformanceRunCreate,
    PerformanceRunDeletePreview,
    PerformanceRunDetail,
    PerformanceRunList,
    PerformanceRunRead,
    PerformanceSiteDeletePreview,
)
from app.services.background_jobs import enqueue_performance_run_job
from app.services.native_cancellation import request_native_cancellation
from app.services.performance_collection import create_performance_run
from app.services.performance_deletion import (
    delete_performance_observation,
    delete_performance_run,
    preview_performance_observation_deletion,
    preview_performance_run_deletion,
    preview_performance_site_deletion,
    purge_performance_site,
)
from app.services.performance_presentation import metric_presentations, parse_pagespeed_presentation
from app.services.performance_providers import (
    CRUX_ADAPTER_VERSION,
    PAGESPEED_ADAPTER_VERSION,
    PERFORMANCE_NORMALIZATION_VERSION,
)
from app.services.performance_queries import (
    get_performance_run,
    latest_site_performance,
    list_performance_runs,
    page_latest_performance,
    page_performance_history,
    performance_observation_read,
)
from app.services.site_pages import find_site_page
from app.storage.performance_store import (
    LocalPerformancePayloadStore,
    PerformancePayloadNotFoundError,
)

router = APIRouter(prefix="/api", tags=["performance"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get(
    "/sites/{site_id}/performance/providers", response_model=PerformanceProviderCapabilities
)
def provider_capabilities(site_id: int, db: DbSession) -> PerformanceProviderCapabilities:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    settings = get_settings()
    configured = bool(settings.google_api_key)
    return PerformanceProviderCapabilities(
        pagespeed=PerformanceProviderState(
            configured=configured, adapter_version=PAGESPEED_ADAPTER_VERSION
        ),
        crux=PerformanceProviderState(configured=configured, adapter_version=CRUX_ADAPTER_VERSION),
        normalization_version=PERFORMANCE_NORMALIZATION_VERSION,
        default_page_limit=settings.performance_default_page_limit,
        hard_page_limit=settings.performance_hard_page_limit,
        absolute_page_limit=OBSERVABILITY_ABSOLUTE_PAGE_LIMIT,
        max_provider_requests=settings.performance_max_provider_requests,
        crux_queries_per_minute=settings.performance_crux_queries_per_minute,
    )


@router.post(
    "/sites/{site_id}/performance-runs", response_model=PerformanceRunRead, status_code=202
)
def create_run(site_id: int, payload: PerformanceRunCreate, db: DbSession) -> PerformanceRunRead:
    try:
        run = create_performance_run(db, site_id, payload)
        job = enqueue_performance_run_job(db, run.id, site_id)
        db.commit()
        db.refresh(run)
    except ValueError as exc:
        db.rollback()
        status = 404 if str(exc) == "Site not found." else 422
        raise HTTPException(status, str(exc)) from exc
    return PerformanceRunRead.model_validate(
        {
            **{column.name: getattr(run, column.name) for column in run.__table__.columns},
            "job_id": job.id,
            "presentation_status": job.status,
        }
    )


@router.get("/sites/{site_id}/performance-runs", response_model=PerformanceRunList)
def list_runs(
    site_id: int,
    db: DbSession,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PerformanceRunList:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    return list_performance_runs(db, site_id, limit=limit, offset=offset)


@router.get("/sites/{site_id}/performance-runs/{run_id}", response_model=PerformanceRunDetail)
def get_run(
    site_id: int,
    run_id: int,
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PerformanceRunDetail:
    result = get_performance_run(db, site_id, run_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(404, "Performance run not found")
    return result


@router.post("/sites/{site_id}/performance-runs/{run_id}/cancel", response_model=PerformanceRunRead)
def cancel_run(site_id: int, run_id: int, db: DbSession) -> PerformanceRunRead:
    run = db.scalar(
        select(PerformanceRun).where(
            PerformanceRun.id == run_id, PerformanceRun.website_property_id == site_id
        )
    )
    if run is None:
        raise HTTPException(404, "Performance run not found")
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.performance_run_id == run_id))
    if job is not None:
        request_native_cancellation(db, job, "Performance collection cancellation requested.")
    result = get_performance_run(db, site_id, run_id, limit=1, offset=0)
    assert result is not None
    return PerformanceRunRead(**result.model_dump(exclude={"observations"}))


@router.get(
    "/sites/{site_id}/performance-runs/{run_id}/deletion-preview",
    response_model=PerformanceRunDeletePreview,
)
def run_deletion_preview(site_id: int, run_id: int, db: DbSession) -> PerformanceRunDeletePreview:
    result = preview_performance_run_deletion(db, site_id, run_id)
    if result is None:
        raise HTTPException(404, "Performance run not found")
    return result


@router.delete("/sites/{site_id}/performance-runs/{run_id}", response_model=PerformanceDeleteResult)
def remove_run(
    site_id: int,
    run_id: int,
    payload: PerformanceDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> PerformanceDeleteResult:
    store: LocalPerformancePayloadStore = request.app.state.performance_payload_store
    try:
        result = delete_performance_run(db, site_id, run_id, payload.confirmation, store)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Performance run not found")
    return result


@router.get("/sites/{site_id}/performance/latest", response_model=PerformanceLatestList)
def latest(
    site_id: int,
    db: DbSession,
    provider: Literal["pagespeed", "crux"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PerformanceLatestList:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    return latest_site_performance(db, site_id, provider=provider, limit=limit, offset=offset)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/performance",
    response_model=PerformanceObservationList,
)
def page_history(
    site_id: int,
    resource_id: int,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PerformanceObservationList:
    page = find_site_page(db, site_id, resource_id)
    if page is None:
        raise HTTPException(404, "Page not found")
    return page_performance_history(db, site_id, page.resource_id, limit=limit, offset=offset)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/performance/latest",
    response_model=PerformanceObservationList,
)
def page_latest(site_id: int, resource_id: int, db: DbSession) -> PerformanceObservationList:
    page = find_site_page(db, site_id, resource_id)
    if page is None:
        raise HTTPException(404, "Page not found")
    return page_latest_performance(db, site_id, page.resource_id)


@router.get(
    "/sites/{site_id}/performance-observations/{observation_id}",
    response_model=PerformanceObservationRead,
)
def observation_detail(
    site_id: int, observation_id: int, db: DbSession
) -> PerformanceObservationRead:
    observation = db.scalar(
        select(PerformanceObservation)
        .options(
            selectinload(PerformanceObservation.web_resource),
            selectinload(PerformanceObservation.payload_blob),
        )
        .where(
            PerformanceObservation.id == observation_id,
            PerformanceObservation.website_property_id == site_id,
        )
    )
    if observation is None:
        raise HTTPException(404, "Performance observation not found")
    return performance_observation_read(observation)


@router.get(
    "/sites/{site_id}/performance-observations/{observation_id}/deletion-preview",
    response_model=PerformanceObservationDeletePreview,
)
def observation_deletion_preview(
    site_id: int, observation_id: int, db: DbSession
) -> PerformanceObservationDeletePreview:
    result = preview_performance_observation_deletion(db, site_id, observation_id)
    if result is None:
        raise HTTPException(404, "Performance observation not found")
    return result


@router.delete(
    "/sites/{site_id}/performance-observations/{observation_id}",
    response_model=PerformanceDeleteResult,
)
def remove_observation(
    site_id: int, observation_id: int, request: Request, db: DbSession
) -> PerformanceDeleteResult:
    store: LocalPerformancePayloadStore = request.app.state.performance_payload_store
    try:
        result = delete_performance_observation(db, site_id, observation_id, store)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Performance observation not found")
    return result


@router.get(
    "/sites/{site_id}/performance/deletion-preview",
    response_model=PerformanceSiteDeletePreview,
)
def site_deletion_preview(site_id: int, db: DbSession) -> PerformanceSiteDeletePreview:
    result = preview_performance_site_deletion(db, site_id)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.delete("/sites/{site_id}/performance", response_model=PerformanceDeleteResult)
def purge_site(
    site_id: int,
    payload: PerformanceDeleteConfirmation,
    request: Request,
    db: DbSession,
) -> PerformanceDeleteResult:
    store: LocalPerformancePayloadStore = request.app.state.performance_payload_store
    try:
        result = purge_performance_site(db, site_id, payload.confirmation, store)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get(
    "/sites/{site_id}/performance-observations/{observation_id}/presentation",
    response_model=PerformanceObservationPresentation,
)
def observation_presentation(
    site_id: int, observation_id: int, request: Request, db: DbSession
) -> PerformanceObservationPresentation:
    observation = db.scalar(
        select(PerformanceObservation)
        .options(
            selectinload(PerformanceObservation.web_resource),
            selectinload(PerformanceObservation.payload_blob),
        )
        .where(
            PerformanceObservation.id == observation_id,
            PerformanceObservation.website_property_id == site_id,
        )
    )
    if observation is None:
        raise HTTPException(404, "Performance observation not found")
    origin_context = None
    if (
        observation.provider == "crux"
        and observation.target_kind == "url"
        and observation.outcome == "unavailable"
    ):
        origin_context = db.scalar(
            select(PerformanceObservation)
            .options(
                selectinload(PerformanceObservation.web_resource),
                selectinload(PerformanceObservation.payload_blob),
            )
            .where(
                PerformanceObservation.performance_run_id == observation.performance_run_id,
                PerformanceObservation.provider == "crux",
                PerformanceObservation.target_kind == "origin",
                PerformanceObservation.dimension == observation.dimension,
            )
            .order_by(PerformanceObservation.id.desc())
        )
    opportunities: list[PageSpeedAuditPresentation] = []
    diagnostics: list[PageSpeedAuditPresentation] = []
    presentation_error = None
    if observation.provider == "pagespeed" and observation.payload_blob is not None:
        store: LocalPerformancePayloadStore = request.app.state.performance_payload_store
        try:
            opportunities, diagnostics, presentation_error = parse_pagespeed_presentation(
                store.read(observation.payload_blob)
            )
        except PerformancePayloadNotFoundError:
            presentation_error = "The retained PageSpeed payload file is missing."
    return PerformanceObservationPresentation(
        observation=performance_observation_read(observation),
        metrics=metric_presentations(observation.provider, observation.metrics_json),
        opportunities=opportunities,
        diagnostics=diagnostics,
        origin_context=(performance_observation_read(origin_context) if origin_context else None),
        origin_metrics=(
            metric_presentations(origin_context.provider, origin_context.metrics_json)
            if origin_context
            else []
        ),
        presentation_error=presentation_error,
    )


@router.get("/performance-observations/{observation_id}/payload")
def raw_payload(observation_id: int, request: Request, db: DbSession) -> Response:
    observation = db.get(PerformanceObservation, observation_id)
    if observation is None or observation.payload_blob is None:
        raise HTTPException(404, "Performance payload not found")
    store: LocalPerformancePayloadStore = request.app.state.performance_payload_store
    try:
        content = store.read(observation.payload_blob)
    except PerformancePayloadNotFoundError as exc:
        raise HTTPException(404, "Performance payload file is missing") from exc
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "X-Content-SHA256": observation.payload_blob.sha256,
        },
    )
