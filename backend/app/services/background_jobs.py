from __future__ import annotations

import os
import secrets
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models import BackgroundJob, JobEvent, Scan, SourceRefresh, WorkerInstance
from app.schemas.jobs import WorkerHealth
from app.services.job_types import (
    ACTIVE_JOB_STATUSES,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_COMPLETED_WITH_ERRORS,
    JOB_STATUS_FAILED,
    JOB_STATUS_INTERRUPTED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SCAN,
    JOB_TYPE_SOURCE_REFRESH,
    TERMINAL_JOB_STATUSES,
    ensure_transition,
)


class StaleLeaseError(RuntimeError):
    pass


class DuplicateActiveJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedJob:
    job: BackgroundJob
    lease_token: str


def presentation_status(job: BackgroundJob, worker_health: WorkerHealth | None = None) -> str:
    if job.status == JOB_STATUS_RUNNING and job.cancellation_requested_at is not None:
        return "cancelling"
    if (
        job.status == JOB_STATUS_QUEUED
        and worker_health is not None
        and not worker_health.queued_work_has_worker
    ):
        return "waiting_for_worker"
    return job.status


def enqueue_scan_job(
    db: Session,
    scan: Scan,
    *,
    priority: int = 100,
    payload: dict[str, Any] | None = None,
) -> BackgroundJob:
    return _enqueue_job(
        db,
        job_type=JOB_TYPE_SCAN,
        dedupe_key=f"scan:{scan.id}",
        scan_id=scan.id,
        website_property_id=scan.website_property_id,
        priority=priority,
        payload=payload or {"scan_id": scan.id},
    )


def enqueue_source_refresh_job(
    db: Session,
    refresh: SourceRefresh,
    *,
    priority: int = 100,
    payload: dict[str, Any] | None = None,
) -> BackgroundJob:
    source = refresh.url_source
    payload_json = payload or {"source_refresh_id": refresh.id}
    if source is not None:
        payload_json = {**payload_json, "source_id": source.id}
    return _enqueue_job(
        db,
        job_type=JOB_TYPE_SOURCE_REFRESH,
        dedupe_key=f"source-refresh:{refresh.id}",
        source_refresh_id=refresh.id,
        website_property_id=source.website_property_id if source else None,
        priority=priority,
        payload=payload_json,
    )


def _enqueue_job(
    db: Session,
    *,
    job_type: str,
    dedupe_key: str,
    priority: int,
    payload: dict[str, Any],
    scan_id: int | None = None,
    source_refresh_id: int | None = None,
    website_property_id: int | None = None,
) -> BackgroundJob:
    existing = db.scalar(select(BackgroundJob).where(BackgroundJob.dedupe_key == dedupe_key))
    if existing is not None:
        if existing.status in ACTIVE_JOB_STATUSES:
            return existing
        raise DuplicateActiveJobError(f"Job {dedupe_key} already exists.")
    now = datetime.now(UTC)
    job = BackgroundJob(
        job_type=job_type,
        status=JOB_STATUS_QUEUED,
        priority=priority,
        scan_id=scan_id,
        source_refresh_id=source_refresh_id,
        website_property_id=website_property_id,
        dedupe_key=dedupe_key,
        payload_json=payload,
        progress_version=1,
        progress_json={"version": 1, "phase": "queued", "updated_at": now.isoformat()},
        available_at=now,
        attempt_count=0,
        max_attempts=1,
    )
    db.add(job)
    db.flush()
    emit_event(db, job.id, "queued", "info", "Job queued.")
    return job


def claim_next_job(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: float,
    now: datetime | None = None,
) -> ClaimedJob | None:
    now = now or datetime.now(UTC)
    candidate = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.status == JOB_STATUS_QUEUED, BackgroundJob.available_at <= now)
        .order_by(
            BackgroundJob.priority.asc(),
            BackgroundJob.available_at.asc(),
            BackgroundJob.created_at.asc(),
            BackgroundJob.id.asc(),
        )
        .limit(1)
    )
    if candidate is None:
        return None
    lease_token = secrets.token_urlsafe(32)
    statement = (
        update(BackgroundJob)
        .where(BackgroundJob.id == candidate.id, BackgroundJob.status == JOB_STATUS_QUEUED)
        .values(
            status=JOB_STATUS_RUNNING,
            worker_id=worker_id,
            lease_token=lease_token,
            claimed_at=now,
            started_at=func.coalesce(BackgroundJob.started_at, now),
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            attempt_count=BackgroundJob.attempt_count + 1,
        )
    )
    result = cast(CursorResult[Any], db.execute(statement))
    if result.rowcount != 1:
        db.rollback()
        return None
    emit_event(
        db,
        candidate.id,
        "claimed",
        "info",
        "Job claimed by worker.",
        {"worker_id": worker_id},
    )
    db.commit()
    job = db.get(BackgroundJob, candidate.id)
    assert job is not None
    return ClaimedJob(job=job, lease_token=lease_token)


def heartbeat_job(
    db: Session,
    *,
    job_id: int,
    lease_token: str,
    lease_seconds: float,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    statement = (
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == JOB_STATUS_RUNNING,
            BackgroundJob.lease_token == lease_token,
        )
        .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
    )
    result = cast(CursorResult[Any], db.execute(statement))
    if result.rowcount != 1:
        db.rollback()
        raise StaleLeaseError("Job lease is no longer active.")
    _touch_assigned_worker(db, job_id, now)
    db.commit()


def update_progress(
    db: Session,
    *,
    job_id: int,
    lease_token: str,
    phase: str,
    current_operation: str | None = None,
    current: int | None = None,
    total: int | None = None,
    unit: str | None = None,
    counters: dict[str, int] | None = None,
) -> None:
    now = datetime.now(UTC)
    payload = {
        "version": 1,
        "phase": phase,
        "current_operation": current_operation,
        "current": current,
        "total": total,
        "unit": unit,
        "counters": counters or {},
        "updated_at": now.isoformat(),
    }
    statement = (
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == JOB_STATUS_RUNNING,
            BackgroundJob.lease_token == lease_token,
        )
        .values(
            progress_json=payload,
            current_operation=current_operation,
            progress_current=current,
            progress_total=total,
            progress_unit=unit,
            heartbeat_at=now,
        )
    )
    result = cast(CursorResult[Any], db.execute(statement))
    if result.rowcount != 1:
        db.rollback()
        raise StaleLeaseError("Job lease is no longer active.")
    _touch_assigned_worker(db, job_id, now)
    db.commit()


def _touch_assigned_worker(db: Session, job_id: int, now: datetime) -> None:
    worker_id = db.scalar(select(BackgroundJob.worker_id).where(BackgroundJob.id == job_id))
    if worker_id:
        db.execute(
            update(WorkerInstance)
            .where(WorkerInstance.worker_id == worker_id)
            .values(last_seen_at=now, status="online", stopped_at=None)
        )


def complete_job(
    db: Session,
    *,
    job_id: int,
    lease_token: str,
    status: str,
    result_json: dict[str, Any] | None = None,
) -> BackgroundJob:
    if status not in {JOB_STATUS_COMPLETED, JOB_STATUS_COMPLETED_WITH_ERRORS, JOB_STATUS_CANCELLED}:
        raise ValueError(f"Unsupported completion status: {status}")
    job = _locked_running_job(db, job_id, lease_token)
    ensure_transition(job.status, status)
    now = datetime.now(UTC)
    job.status = status
    job.result_json = result_json or {}
    job.finished_at = now
    job.lease_expires_at = None
    job.heartbeat_at = now
    if status == JOB_STATUS_CANCELLED:
        job.cancelled_at = now
    emit_event(db, job.id, status, "info", f"Job {status}.")
    db.commit()
    db.refresh(job)
    return job


def fail_job(
    db: Session,
    *,
    job_id: int,
    lease_token: str,
    error_type: str,
    error_message: str,
    interrupted: bool = False,
) -> BackgroundJob:
    job = _locked_running_job(db, job_id, lease_token)
    status = JOB_STATUS_INTERRUPTED if interrupted else JOB_STATUS_FAILED
    ensure_transition(job.status, status)
    now = datetime.now(UTC)
    job.status = status
    job.error_type = error_type
    job.error_message = error_message
    job.last_error_at = now
    job.finished_at = now
    job.lease_expires_at = None
    emit_event(db, job.id, status, "error", error_message, {"error_type": error_type})
    db.commit()
    db.refresh(job)
    return job


def request_cancellation(
    db: Session, job: BackgroundJob, message: str = "Cancellation requested."
) -> BackgroundJob:
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    now = datetime.now(UTC)
    if job.cancellation_requested_at is None:
        job.cancellation_requested_at = now
        emit_event(db, job.id, "cancellation_requested", "info", message)
    if job.status == JOB_STATUS_QUEUED:
        ensure_transition(job.status, JOB_STATUS_CANCELLED)
        job.status = JOB_STATUS_CANCELLED
        job.cancelled_at = now
        job.finished_at = now
        emit_event(db, job.id, "cancelled", "info", "Queued job cancelled.")
    db.commit()
    db.refresh(job)
    return job


def latest_job_for_scan(db: Session, scan_id: int) -> BackgroundJob | None:
    return db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.scan_id == scan_id)
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def latest_job_for_refresh(db: Session, refresh_id: int) -> BackgroundJob | None:
    return db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.source_refresh_id == refresh_id)
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def active_job_for_scan(db: Session, scan_id: int) -> BackgroundJob | None:
    return db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.scan_id == scan_id, BackgroundJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def active_job_for_source_refresh(db: Session, refresh_id: int) -> BackgroundJob | None:
    return db.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.source_refresh_id == refresh_id,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def register_worker(
    db: Session,
    *,
    worker_id: str,
    concurrency: int,
    metadata: dict[str, Any] | None = None,
) -> WorkerInstance:
    now = datetime.now(UTC)
    worker = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == worker_id))
    if worker is None:
        worker = WorkerInstance(
            worker_id=worker_id,
            hostname=socket.gethostname(),
            process_id=os.getpid(),
            application_version=None,
            concurrency=concurrency,
            started_at=now,
            last_seen_at=now,
            status="online",
            metadata_json=metadata or {},
        )
        db.add(worker)
    else:
        worker.hostname = socket.gethostname()
        worker.process_id = os.getpid()
        worker.concurrency = concurrency
        worker.last_seen_at = now
        worker.stopped_at = None
        worker.status = "online"
        worker.metadata_json = metadata or {}
    db.commit()
    db.refresh(worker)
    return worker


def heartbeat_worker(db: Session, worker_id: str) -> None:
    worker = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == worker_id))
    if worker:
        worker.last_seen_at = datetime.now(UTC)
        worker.status = "online"
        db.commit()


def stop_worker(db: Session, worker_id: str) -> None:
    worker = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == worker_id))
    if worker:
        worker.stopped_at = datetime.now(UTC)
        worker.status = "stopped"
        db.commit()


def worker_health(db: Session, offline_threshold_seconds: float) -> WorkerHealth:
    cutoff = datetime.now(UTC) - timedelta(seconds=offline_threshold_seconds)
    online_workers = list(
        db.scalars(
            select(WorkerInstance).where(
                WorkerInstance.status == "online",
                WorkerInstance.last_seen_at >= cutoff,
            )
        )
    )
    queued_jobs = db.scalar(
        select(func.count(BackgroundJob.id)).where(BackgroundJob.status == JOB_STATUS_QUEUED)
    )
    return WorkerHealth(
        online_workers=len(online_workers),
        total_concurrency=sum(worker.concurrency for worker in online_workers),
        last_worker_heartbeat=max((worker.last_seen_at for worker in online_workers), default=None),
        queued_work_has_worker=not queued_jobs or bool(online_workers),
        offline_threshold_seconds=offline_threshold_seconds,
        worker_capabilities=[worker.metadata_json for worker in online_workers],
    )


def recover_expired_jobs(
    db: Session,
    *,
    lease_expired_before: datetime | None = None,
) -> int:
    now = datetime.now(UTC)
    cutoff = lease_expired_before or now
    jobs = list(
        db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.status == JOB_STATUS_RUNNING,
                BackgroundJob.lease_expires_at.is_not(None),
                BackgroundJob.lease_expires_at < cutoff,
            )
        )
    )
    recovered = 0
    for job in jobs:
        if reconcile_job_with_domain(db, job):
            recovered += 1
            continue
        ensure_transition(job.status, JOB_STATUS_INTERRUPTED)
        job.status = JOB_STATUS_INTERRUPTED
        job.finished_at = now
        job.error_type = "lease_expired"
        job.error_message = "Worker lease expired before completion."
        if job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan and scan.status not in TERMINAL_JOB_STATUSES:
                scan.status = "interrupted"
                scan.stop_reason = "worker_lease_expired"
                scan.finished_at = now
        if job.source_refresh_id:
            refresh = db.get(SourceRefresh, job.source_refresh_id)
            if refresh and refresh.status not in TERMINAL_JOB_STATUSES:
                refresh.status = "interrupted"
                refresh.error_type = "worker_lease_expired"
                refresh.error_message = "Worker lease expired before completion."
                refresh.finished_at = now
                if refresh.url_source:
                    refresh.url_source.last_refresh_status = "interrupted"
                    refresh.url_source.last_refresh_finished_at = now
        emit_event(db, job.id, "lease_expired", "warning", "Worker lease expired.")
        emit_event(db, job.id, "interrupted", "warning", "Job interrupted by recovery.")
        recovered += 1
    db.commit()
    return recovered


def reconcile_job_with_domain(db: Session, job: BackgroundJob) -> bool:
    domain_status: str | None = None
    if job.scan_id:
        scan = db.get(Scan, job.scan_id)
        domain_status = scan.status if scan else JOB_STATUS_FAILED
    elif job.source_refresh_id:
        refresh = db.get(SourceRefresh, job.source_refresh_id)
        domain_status = refresh.status if refresh else JOB_STATUS_FAILED
    if domain_status not in TERMINAL_JOB_STATUSES:
        return False
    if job.status in TERMINAL_JOB_STATUSES:
        return False
    ensure_transition(job.status, domain_status)
    job.status = domain_status
    job.finished_at = datetime.now(UTC)
    job.lease_expires_at = None
    emit_event(db, job.id, "reconciled", "info", "Job reconciled from domain status.")
    db.commit()
    return True


def emit_event(
    db: Session,
    job_id: int,
    event_type: str,
    level: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        JobEvent(
            job_id=job_id,
            event_type=event_type,
            level=level,
            message=message,
            data_json=data or {},
        )
    )


def with_session(session_factory: Callable[[], Session], fn: Callable[[Session], Any]) -> Any:
    with session_factory() as db:
        return fn(db)


def _locked_running_job(db: Session, job_id: int, lease_token: str) -> BackgroundJob:
    job = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == JOB_STATUS_RUNNING,
            BackgroundJob.lease_token == lease_token,
        )
    )
    if job is None:
        raise StaleLeaseError("Job lease is no longer active.")
    return job
