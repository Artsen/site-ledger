from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.dependencies import DbSession, PageLimit, PageOffset, ScanListLimit
from app.models import (
    BackgroundJob,
    JobEvent,
)
from app.schemas.jobs import JobEventList, JobEventRead, JobList, JobRead, WorkerHealth
from app.services.background_jobs import (
    presentation_status,
    worker_health,
)

router = APIRouter(prefix="/api")


@router.get("/jobs/worker-health", response_model=WorkerHealth)
def get_worker_health(db: DbSession) -> WorkerHealth:
    from app.config import get_settings

    return worker_health(db, get_settings().job_worker_offline_seconds)


@router.get("/jobs", response_model=JobList)
def list_jobs(
    db: DbSession,
    job_type: str | None = None,
    status: str | None = None,
    scan_id: int | None = None,
    source_refresh_id: int | None = None,
    website_property_id: int | None = None,
    limit: ScanListLimit = 50,
    offset: PageOffset = 0,
) -> JobList:
    query = select(BackgroundJob)
    count_query = select(func.count(BackgroundJob.id))
    if job_type:
        query = query.where(BackgroundJob.job_type == job_type)
        count_query = count_query.where(BackgroundJob.job_type == job_type)
    if status:
        query = query.where(BackgroundJob.status == status)
        count_query = count_query.where(BackgroundJob.status == status)
    if scan_id is not None:
        query = query.where(BackgroundJob.scan_id == scan_id)
        count_query = count_query.where(BackgroundJob.scan_id == scan_id)
    if source_refresh_id is not None:
        query = query.where(BackgroundJob.source_refresh_id == source_refresh_id)
        count_query = count_query.where(BackgroundJob.source_refresh_id == source_refresh_id)
    if website_property_id is not None:
        query = query.where(BackgroundJob.website_property_id == website_property_id)
        count_query = count_query.where(BackgroundJob.website_property_id == website_property_id)
    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    health = get_worker_health(db)
    return JobList(
        items=[_job_read(job, health) for job in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: DbSession) -> JobRead:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _job_read(job, get_worker_health(db))


@router.get("/jobs/{job_id}/events", response_model=JobEventList)
def get_job_events(
    job_id: int,
    db: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> JobEventList:
    if db.get(BackgroundJob, job_id) is None:
        raise HTTPException(404, "Job not found")
    total = db.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id == job_id)) or 0
    events = list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
    )
    return JobEventList(
        items=[JobEventRead.model_validate(event, from_attributes=True) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )


def _job_read(job: BackgroundJob, health: WorkerHealth) -> JobRead:
    return JobRead(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        presentation_status=presentation_status(job, health),
        priority=job.priority,
        scan_id=job.scan_id,
        source_refresh_id=job.source_refresh_id,
        scan_comparison_id=job.scan_comparison_id,
        performance_run_id=job.performance_run_id,
        accessibility_run_id=job.accessibility_run_id,
        website_property_id=job.website_property_id,
        dedupe_key=job.dedupe_key,
        payload_json=job.payload_json,
        progress_version=job.progress_version,
        progress_json=job.progress_json,
        current_operation=job.current_operation,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        progress_unit=job.progress_unit,
        result_json=job.result_json,
        created_at=job.created_at,
        available_at=job.available_at,
        claimed_at=job.claimed_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        lease_expires_at=job.lease_expires_at,
        finished_at=job.finished_at,
        worker_id=job.worker_id,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        cancellation_requested_at=job.cancellation_requested_at,
        cancelled_at=job.cancelled_at,
        error_type=job.error_type,
        error_message=job.error_message,
        last_error_at=job.last_error_at,
    )
