from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from app.config import get_settings
from app.models import BackgroundJob, PerformanceObservation, PerformanceRun
from app.schemas.jobs import WorkerHealth
from app.schemas.performance import (
    PerformanceLatestList,
    PerformanceObservationList,
    PerformanceObservationRead,
    PerformanceRunDetail,
    PerformanceRunList,
    PerformanceRunRead,
)
from app.services.background_jobs import presentation_status, worker_health


def list_performance_runs(
    db: Session, site_id: int, *, limit: int, offset: int
) -> PerformanceRunList:
    base = select(PerformanceRun).where(PerformanceRun.website_property_id == site_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    runs = list(
        db.scalars(
            base.order_by(PerformanceRun.created_at.desc(), PerformanceRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    jobs = {
        job.performance_run_id: job
        for job in db.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.performance_run_id.in_([run.id for run in runs]))
            .order_by(BackgroundJob.id.desc())
        )
        if job.performance_run_id is not None
    }
    health = worker_health(db, get_settings().job_worker_offline_seconds)
    return PerformanceRunList(
        items=[_run_read(run, jobs.get(run.id), health) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_performance_run(
    db: Session, site_id: int, run_id: int, *, limit: int, offset: int
) -> PerformanceRunDetail | None:
    run = db.scalar(
        select(PerformanceRun).where(
            PerformanceRun.id == run_id, PerformanceRun.website_property_id == site_id
        )
    )
    if run is None:
        return None
    observations = _observation_list(
        db,
        select(PerformanceObservation).where(PerformanceObservation.performance_run_id == run_id),
        limit=limit,
        offset=offset,
    )
    job = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.performance_run_id == run.id)
        .order_by(BackgroundJob.id.desc())
        .limit(1)
    )
    health = worker_health(db, get_settings().job_worker_offline_seconds)
    return PerformanceRunDetail(
        **_run_read(run, job, health).model_dump(), observations=observations
    )


def latest_site_performance(
    db: Session,
    site_id: int,
    *,
    provider: str | None,
    limit: int,
    offset: int,
) -> PerformanceLatestList:
    filters = [PerformanceObservation.website_property_id == site_id]
    if provider:
        filters.append(PerformanceObservation.provider == provider)
    ranked = (
        select(
            PerformanceObservation.id.label("observation_id"),
            func.row_number()
            .over(
                partition_by=(
                    PerformanceObservation.target_kind,
                    PerformanceObservation.target_key,
                    PerformanceObservation.provider,
                    PerformanceObservation.dimension,
                ),
                order_by=(
                    PerformanceObservation.observed_at.desc(),
                    PerformanceObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(*filters)
        .subquery()
    )
    latest_ids = select(ranked.c.observation_id).where(ranked.c.position == 1)
    base = select(PerformanceObservation).where(PerformanceObservation.id.in_(latest_ids))
    result = _observation_list(db, base, limit=limit, offset=offset)
    measured_page_count = (
        db.scalar(
            select(func.count(func.distinct(PerformanceObservation.web_resource_id))).where(
                PerformanceObservation.website_property_id == site_id,
                PerformanceObservation.web_resource_id.is_not(None),
            )
        )
        or 0
    )
    field_available_page_count = (
        db.scalar(
            select(func.count(func.distinct(PerformanceObservation.web_resource_id))).where(
                PerformanceObservation.website_property_id == site_id,
                PerformanceObservation.provider == "crux",
                PerformanceObservation.outcome == "ready",
                PerformanceObservation.web_resource_id.is_not(None),
            )
        )
        or 0
    )
    return PerformanceLatestList(
        **result.model_dump(),
        measured_page_count=measured_page_count,
        field_available_page_count=field_available_page_count,
    )


def page_performance_history(
    db: Session, site_id: int, resource_id: int, *, limit: int, offset: int
) -> PerformanceObservationList:
    return _observation_list(
        db,
        select(PerformanceObservation).where(
            PerformanceObservation.website_property_id == site_id,
            PerformanceObservation.web_resource_id == resource_id,
        ),
        limit=limit,
        offset=offset,
    )


def page_latest_performance(
    db: Session, site_id: int, resource_id: int
) -> PerformanceObservationList:
    ranked = (
        select(
            PerformanceObservation.id.label("observation_id"),
            func.row_number()
            .over(
                partition_by=(
                    PerformanceObservation.provider,
                    PerformanceObservation.dimension,
                    PerformanceObservation.target_kind,
                ),
                order_by=(
                    PerformanceObservation.observed_at.desc(),
                    PerformanceObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            PerformanceObservation.website_property_id == site_id,
            PerformanceObservation.web_resource_id == resource_id,
            PerformanceObservation.target_kind == "url",
        )
        .subquery()
    )
    latest_ids = select(ranked.c.observation_id).where(ranked.c.position == 1)
    return _observation_list(
        db,
        select(PerformanceObservation).where(PerformanceObservation.id.in_(latest_ids)),
        limit=10,
        offset=0,
    )


def _observation_list(
    db: Session,
    base: Select[tuple[PerformanceObservation]],
    *,
    limit: int,
    offset: int,
) -> PerformanceObservationList:
    statement = base.options(
        selectinload(PerformanceObservation.web_resource),
        selectinload(PerformanceObservation.payload_blob),
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    observations = list(
        db.scalars(
            statement.order_by(
                PerformanceObservation.observed_at.desc(), PerformanceObservation.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return PerformanceObservationList(
        items=[performance_observation_read(item) for item in observations],
        total=total,
        limit=limit,
        offset=offset,
    )


def _run_read(
    run: PerformanceRun, job: BackgroundJob | None, health: WorkerHealth
) -> PerformanceRunRead:
    return PerformanceRunRead(
        **{column.name: getattr(run, column.name) for column in run.__table__.columns},
        job_id=job.id if job else None,
        presentation_status=presentation_status(job, health) if job else run.status,
    )


def performance_observation_read(
    observation: PerformanceObservation,
) -> PerformanceObservationRead:
    return PerformanceObservationRead(
        **{
            column.name: getattr(observation, column.name)
            for column in observation.__table__.columns
            if column.name not in {"target_key", "request_descriptor_json", "payload_blob_id"}
        },
        page_url=(observation.web_resource.normalized_url if observation.web_resource else None),
        payload_sha256=(observation.payload_blob.sha256 if observation.payload_blob else None),
        payload_raw_byte_size=(
            observation.payload_blob.raw_byte_size if observation.payload_blob else None
        ),
        payload_stored_byte_size=(
            observation.payload_blob.stored_byte_size if observation.payload_blob else None
        ),
    )
