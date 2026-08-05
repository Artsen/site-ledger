from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.crawler.static_crawler import StaticPageCrawler
from app.database import is_transient_database_lock
from app.models import BackgroundJob, Scan, SourceRefresh
from app.services import background_jobs
from app.services.job_types import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_COMPLETED_WITH_ERRORS,
    JOB_STATUS_FAILED,
    JOB_TYPE_SCAN,
    JOB_TYPE_SOURCE_REFRESH,
)
from app.services.source_refresh import execute_source_refresh
from app.storage.content_store import LocalContentStore

logger = logging.getLogger("site_ledger.jobs")


class JobCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class HandlerResult:
    status: str = JOB_STATUS_COMPLETED
    result_json: dict[str, Any] | None = None


class JobHandler(Protocol):
    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        pass


class JobExecutionContext:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        job_id: int,
        lease_token: str,
        lease_seconds: float,
    ):
        self.session_factory = session_factory
        self.job_id = job_id
        self.lease_token = lease_token
        self.lease_seconds = lease_seconds

    def check_cancelled(self) -> bool:
        with self.session_factory() as db:
            job = db.get(BackgroundJob, self.job_id)
            return bool(job and job.cancellation_requested_at is not None)

    def raise_if_cancelled(self) -> None:
        if self.check_cancelled():
            raise JobCancelled("Cancellation requested.")

    def heartbeat(self) -> None:
        with self.session_factory() as db:
            background_jobs.heartbeat_job(
                db,
                job_id=self.job_id,
                lease_token=self.lease_token,
                lease_seconds=self.lease_seconds,
            )

    def progress(
        self,
        *,
        phase: str,
        current_operation: str | None = None,
        current: int | None = None,
        total: int | None = None,
        unit: str | None = None,
        counters: dict[str, int] | None = None,
    ) -> None:
        try:
            with self.session_factory() as db:
                background_jobs.update_progress(
                    db,
                    job_id=self.job_id,
                    lease_token=self.lease_token,
                    phase=phase,
                    current_operation=current_operation,
                    current=current,
                    total=total,
                    unit=unit,
                    counters=counters,
                )
        except OperationalError as exc:
            if not is_transient_database_lock(exc):
                raise
            logger.warning("job progress delayed by database lock", extra={"job_id": self.job_id})

    def event(
        self,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> None:
        with self.session_factory() as db:
            background_jobs.emit_event(db, self.job_id, event_type, level, message, data)
            db.commit()


class ScanJobHandler:
    def __init__(self, session_factory: Callable[[], Session], store: LocalContentStore):
        self.session_factory = session_factory
        self.store = store

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        if job.scan_id is None:
            raise ValueError("Scan job is missing scan_id.")
        context.raise_if_cancelled()
        with self.session_factory() as db:
            scan = db.get(Scan, job.scan_id)
            if scan is None:
                raise ValueError("Scan not found.")
            crawler = StaticPageCrawler(
                db,
                self.store,
                should_cancel=context.check_cancelled,
                progress_callback=lambda active_scan: context.progress(
                    phase="running",
                    current_operation="Crawling pages",
                    current=active_scan.fetched_count,
                    total=active_scan.discovered_count or None,
                    unit="pages",
                    counters={
                        "discovered": active_scan.discovered_count,
                        "queued": active_scan.queued_count,
                        "fetched": active_scan.fetched_count,
                        "failed": active_scan.failed_count,
                        "skipped": active_scan.skipped_count,
                    },
                ),
            )
            await crawler.run(scan)
            db.refresh(scan)
            if scan.status == JOB_STATUS_CANCELLED:
                return HandlerResult(status=JOB_STATUS_CANCELLED, result_json=_scan_result(scan))
            if scan.status == JOB_STATUS_COMPLETED_WITH_ERRORS:
                return HandlerResult(
                    status=JOB_STATUS_COMPLETED_WITH_ERRORS,
                    result_json=_scan_result(scan),
                )
            if scan.status == JOB_STATUS_COMPLETED:
                return HandlerResult(status=JOB_STATUS_COMPLETED, result_json=_scan_result(scan))
            return HandlerResult(status=JOB_STATUS_FAILED, result_json=_scan_result(scan))


class SourceRefreshJobHandler:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        if job.source_refresh_id is None:
            raise ValueError("Source refresh job is missing source_refresh_id.")
        context.raise_if_cancelled()
        with self.session_factory() as db:
            refresh = await execute_source_refresh(
                db,
                job.source_refresh_id,
                should_cancel=context.check_cancelled,
                progress_callback=lambda active_refresh: context.progress(
                    phase="running",
                    current_operation="Refreshing URL source",
                    current=active_refresh.discovered_entry_count,
                    total=None,
                    unit="urls",
                    counters={
                        "discovered": active_refresh.discovered_entry_count,
                        "accepted": active_refresh.accepted_entry_count,
                        "rejected": active_refresh.rejected_entry_count,
                        "child_sources": active_refresh.child_source_count,
                    },
                ),
            )
            if refresh is None:
                raise ValueError("Source refresh not found.")
            if refresh.status == JOB_STATUS_CANCELLED:
                return HandlerResult(
                    status=JOB_STATUS_CANCELLED,
                    result_json=_refresh_result(refresh),
                )
            if refresh.status == JOB_STATUS_COMPLETED_WITH_ERRORS:
                return HandlerResult(
                    status=JOB_STATUS_COMPLETED_WITH_ERRORS,
                    result_json=_refresh_result(refresh),
                )
            if refresh.status == JOB_STATUS_COMPLETED:
                return HandlerResult(
                    status=JOB_STATUS_COMPLETED,
                    result_json=_refresh_result(refresh),
                )
            return HandlerResult(status=JOB_STATUS_FAILED, result_json=_refresh_result(refresh))


class JobHandlerRegistry:
    def __init__(self, handlers: dict[str, JobHandler]):
        self.handlers = handlers

    def get(self, job_type: str) -> JobHandler:
        handler = self.handlers.get(job_type)
        if handler is None:
            raise ValueError(f"No handler registered for job type: {job_type}")
        return handler


def build_handler_registry(
    session_factory: Callable[[], Session], store: LocalContentStore
) -> JobHandlerRegistry:
    return JobHandlerRegistry(
        {
            JOB_TYPE_SCAN: ScanJobHandler(session_factory, store),
            JOB_TYPE_SOURCE_REFRESH: SourceRefreshJobHandler(session_factory),
        }
    )


async def run_claimed_job(
    *,
    session_factory: Callable[[], Session],
    registry: JobHandlerRegistry,
    claimed_job: background_jobs.ClaimedJob,
    lease_seconds: float,
) -> None:
    context = JobExecutionContext(
        session_factory=session_factory,
        job_id=claimed_job.job.id,
        lease_token=claimed_job.lease_token,
        lease_seconds=lease_seconds,
    )
    context.event("started", "Job execution started.")
    heartbeat_task = asyncio.create_task(_job_heartbeat_loop(context))
    try:
        if claimed_job.job.cancellation_requested_at is not None:
            raise JobCancelled("Cancellation requested before job started.")
        result = await registry.get(claimed_job.job.job_type).execute(claimed_job.job, context)
        with session_factory() as db:
            background_jobs.complete_job(
                db,
                job_id=claimed_job.job.id,
                lease_token=claimed_job.lease_token,
                status=result.status,
                result_json=result.result_json,
            )
    except JobCancelled as exc:
        _mark_domain_cancelled(session_factory, claimed_job.job)
        with session_factory() as db:
            background_jobs.complete_job(
                db,
                job_id=claimed_job.job.id,
                lease_token=claimed_job.lease_token,
                status=JOB_STATUS_CANCELLED,
                result_json={"message": str(exc)},
            )
    except asyncio.CancelledError:
        _mark_domain_interrupted(session_factory, claimed_job.job, "worker_shutdown")
        with session_factory() as db:
            background_jobs.fail_job(
                db,
                job_id=claimed_job.job.id,
                lease_token=claimed_job.lease_token,
                error_type="worker_shutdown",
                error_message="Worker stopped during execution.",
                interrupted=True,
            )
        raise
    except Exception as exc:
        _mark_domain_failed(session_factory, claimed_job.job, exc)
        with session_factory() as db:
            background_jobs.fail_job(
                db,
                job_id=claimed_job.job.id,
                lease_token=claimed_job.lease_token,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _job_heartbeat_loop(context: JobExecutionContext) -> None:
    while True:
        await asyncio.sleep(max(1.0, context.lease_seconds / 3))
        try:
            context.heartbeat()
        except OperationalError as exc:
            if not is_transient_database_lock(exc):
                raise
            logger.warning(
                "job heartbeat delayed by database lock", extra={"job_id": context.job_id}
            )


def _scan_result(scan: Scan) -> dict[str, Any]:
    return {
        "scan_id": scan.id,
        "discovered": scan.discovered_count,
        "fetched": scan.fetched_count,
        "failed": scan.failed_count,
        "skipped": scan.skipped_count,
    }


def _refresh_result(refresh: SourceRefresh) -> dict[str, Any]:
    return {
        "source_refresh_id": refresh.id,
        "discovered": refresh.discovered_entry_count,
        "accepted": refresh.accepted_entry_count,
        "rejected": refresh.rejected_entry_count,
        "child_sources": refresh.child_source_count,
    }


def _mark_domain_cancelled(session_factory: Callable[[], Session], job: BackgroundJob) -> None:
    with session_factory() as db:
        now = datetime.now(UTC)
        if job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "cancelled"
                scan.stop_reason = "cancelled_by_user"
                scan.finished_at = now
        if job.source_refresh_id:
            refresh = db.get(SourceRefresh, job.source_refresh_id)
            if refresh:
                refresh.status = "cancelled"
                refresh.error_type = "cancelled"
                refresh.error_message = "Refresh cancelled by user."
                refresh.finished_at = now
                if refresh.url_source:
                    refresh.url_source.last_refresh_status = "cancelled"
                    refresh.url_source.last_refresh_finished_at = now
        db.commit()


def _mark_domain_interrupted(
    session_factory: Callable[[], Session], job: BackgroundJob, reason: str
) -> None:
    with session_factory() as db:
        now = datetime.now(UTC)
        if job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "interrupted"
                scan.stop_reason = reason
                scan.finished_at = now
        if job.source_refresh_id:
            refresh = db.get(SourceRefresh, job.source_refresh_id)
            if refresh:
                refresh.status = "interrupted"
                refresh.error_type = reason
                refresh.error_message = "Worker interrupted before completion."
                refresh.finished_at = now
                if refresh.url_source:
                    refresh.url_source.last_refresh_status = "interrupted"
                    refresh.url_source.last_refresh_finished_at = now
        db.commit()


def _mark_domain_failed(
    session_factory: Callable[[], Session], job: BackgroundJob, exc: Exception
) -> None:
    with session_factory() as db:
        now = datetime.now(UTC)
        if job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "failed"
                scan.fatal_error_message = str(exc)
                scan.finished_at = now
        if job.source_refresh_id:
            refresh = db.get(SourceRefresh, job.source_refresh_id)
            if refresh:
                refresh.status = "failed"
                refresh.error_type = type(exc).__name__
                refresh.error_message = str(exc)
                refresh.finished_at = now
                if refresh.url_source:
                    refresh.url_source.last_refresh_status = "failed"
                    refresh.url_source.last_error_type = refresh.error_type
                    refresh.url_source.last_error_message = refresh.error_message
                    refresh.url_source.last_refresh_finished_at = now
        db.commit()
