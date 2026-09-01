from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import (
    AccessibilityRun,
    BackgroundJob,
    PerformanceRun,
    RenderRun,
    Scan,
    SourceRefresh,
)
from app.services.background_jobs import request_cancellation
from app.services.job_types import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_QUEUED,
    JOB_TYPE_ACCESSIBILITY_RUN,
    JOB_TYPE_PERFORMANCE_RUN,
    JOB_TYPE_RENDER_RUN,
    JOB_TYPE_SCAN,
    JOB_TYPE_SCAN_COMPARISON_BUILD,
    JOB_TYPE_SOURCE_REFRESH,
)
from app.services.scan_comparisons import mark_comparison_build_terminal


def request_native_cancellation(
    db: Session,
    job: BackgroundJob,
    message: str = "Cancellation requested.",
) -> BackgroundJob:
    """Cancel queued native work atomically; running work remains cooperative."""
    was_queued = job.status == JOB_STATUS_QUEUED
    request_cancellation(db, job, message, commit=False)
    if was_queued and job.status == JOB_STATUS_CANCELLED:
        _stage_queued_native_cancellation(db, job)
    db.commit()
    db.refresh(job)
    return job


def _stage_queued_native_cancellation(db: Session, job: BackgroundJob) -> None:
    now = job.finished_at or datetime.now(UTC)
    if job.job_type == JOB_TYPE_SCAN and job.scan_id:
        scan = db.get(Scan, job.scan_id)
        if scan is not None and scan.status == JOB_STATUS_QUEUED:
            scan.status = JOB_STATUS_CANCELLED
            scan.stop_reason = "cancelled_by_user"
            scan.finished_at = now
        return
    if job.job_type == JOB_TYPE_SOURCE_REFRESH and job.source_refresh_id:
        refresh = db.get(SourceRefresh, job.source_refresh_id)
        if refresh is not None and refresh.status == JOB_STATUS_QUEUED:
            refresh.status = JOB_STATUS_CANCELLED
            refresh.error_type = "cancelled"
            refresh.error_message = "Refresh cancelled by user."
            refresh.finished_at = now
            if refresh.url_source is not None:
                refresh.url_source.last_refresh_status = JOB_STATUS_CANCELLED
                refresh.url_source.last_refresh_started_at = refresh.started_at
                refresh.url_source.last_refresh_finished_at = now
                refresh.url_source.last_error_type = refresh.error_type
                refresh.url_source.last_error_message = refresh.error_message
        return
    if job.job_type == JOB_TYPE_PERFORMANCE_RUN and job.performance_run_id:
        performance_run = db.get(PerformanceRun, job.performance_run_id)
        if performance_run is not None and performance_run.status == JOB_STATUS_QUEUED:
            performance_run.status = JOB_STATUS_CANCELLED
            performance_run.finished_at = now
        return
    if job.job_type == JOB_TYPE_ACCESSIBILITY_RUN and job.accessibility_run_id:
        accessibility_run = db.get(AccessibilityRun, job.accessibility_run_id)
        if accessibility_run is not None and accessibility_run.status == JOB_STATUS_QUEUED:
            accessibility_run.status = JOB_STATUS_CANCELLED
            accessibility_run.finished_at = now
        return
    if job.job_type == JOB_TYPE_RENDER_RUN and job.render_run_id:
        render_run = db.get(RenderRun, job.render_run_id)
        if render_run is not None and render_run.status == JOB_STATUS_QUEUED:
            render_run.status = JOB_STATUS_CANCELLED
            render_run.finished_at = now
        return
    if job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
        mark_comparison_build_terminal(
            db,
            int(job.payload_json.get("comparison_build_id", 0)),
            JOB_STATUS_CANCELLED,
            "cancelled",
            "Comparison build cancelled by user.",
            commit=False,
        )
