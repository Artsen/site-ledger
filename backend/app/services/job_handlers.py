from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import is_transient_database_lock
from app.models import BackgroundJob, PageCategoryRule, PageCategoryRuleRun, Scan, SourceRefresh
from app.services import background_jobs
from app.services.category_rules import create_followup_evaluation, reconcile_site
from app.services.job_types import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_COMPLETED_WITH_ERRORS,
    JOB_STATUS_FAILED,
    JOB_TYPE_CATEGORY_RULE_EVALUATION,
    JOB_TYPE_SCAN,
    JOB_TYPE_SCAN_COMPARISON_BUILD,
    JOB_TYPE_SCAN_PROJECTION_BUILD,
    JOB_TYPE_SOURCE_REFRESH,
)
from app.services.scan_comparisons import (
    ComparisonBuildCancelled,
    execute_comparison_build,
    mark_comparison_build_terminal,
)
from app.services.scan_execution import ScanExecutionCoordinator
from app.services.scan_projections import (
    ProjectionBuildCancelled,
    create_projection_build,
    execute_projection_build,
    mark_projection_build_terminal,
)
from app.services.source_refresh import execute_source_refresh
from app.storage.ai_document_store import LocalAiDocumentStore
from app.storage.artifact_store import LocalArtifactStore
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
            coordinator = ScanExecutionCoordinator(
                db,
                self.store,
                LocalArtifactStore(get_settings().rendered_artifact_storage_root),
                context,
            )
            await coordinator.execute(scan)
            db.refresh(scan)
            _enqueue_projection_for_terminal_scan(db, scan)
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
                ai_document_store=LocalAiDocumentStore(get_settings().ai_document_storage_root),
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


class ScanProjectionJobHandler:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        build_id = int(job.payload_json.get("projection_build_id", 0))
        if not build_id:
            raise ValueError("Projection job is missing projection_build_id.")
        try:
            with self.session_factory() as db:
                build = execute_projection_build(
                    db,
                    build_id,
                    should_cancel=context.check_cancelled,
                    progress=lambda phase, current, total: context.progress(
                        phase=phase,
                        current_operation=f"Preparing {phase}",
                        current=current,
                        total=total,
                        unit="rows",
                    ),
                )
                from app.services.scan_comparisons import (
                    queue_adjacent_comparison_for_scan,
                    queue_waiting_comparisons_for_scan,
                )

                queue_waiting_comparisons_for_scan(db, build.scan_id)
                queue_adjacent_comparison_for_scan(db, build.scan_id)
                db.commit()
                return HandlerResult(
                    result_json={
                        "scan_id": build.scan_id,
                        "projection_build_id": build.id,
                        "projection_version": build.projection_version,
                        "checksum_sha256": build.checksum_sha256,
                    }
                )
        except ProjectionBuildCancelled as exc:
            raise JobCancelled(str(exc)) from exc


class ScanComparisonJobHandler:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        build_id = int(job.payload_json.get("comparison_build_id", 0))
        if not build_id:
            raise ValueError("Comparison job is missing comparison_build_id.")
        try:
            with self.session_factory() as db:
                build = execute_comparison_build(
                    db,
                    build_id,
                    should_cancel=context.check_cancelled,
                    progress=lambda phase, current, total: context.progress(
                        phase=phase,
                        current_operation=phase.replace("_", " ").title(),
                        current=current,
                        total=total,
                        unit="rows",
                    ),
                )
                return HandlerResult(
                    result_json={
                        "comparison_id": build.scan_comparison_id,
                        "comparison_build_id": build.id,
                        "comparison_version": build.comparison_version,
                        "checksum_sha256": build.comparison_checksum_sha256,
                    }
                )
        except ComparisonBuildCancelled as exc:
            raise JobCancelled(str(exc)) from exc


class CategoryRuleEvaluationJobHandler:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        run_id = int(job.payload_json.get("run_id", 0))
        if not run_id:
            raise ValueError("Category Rule job is missing run_id.")
        try:
            with self.session_factory() as db:
                run = reconcile_site(
                    db,
                    run_id,
                    should_cancel=context.check_cancelled,
                    progress=lambda current, total: context.progress(
                        phase="reconciling",
                        current_operation="Applying Page category Rules",
                        current=current,
                        total=total,
                        unit="Pages",
                    ),
                )
                result = {
                    "run_id": run.id,
                    "site_id": run.website_property_id,
                    "rule_supports_added": run.rule_supports_added,
                    "rule_supports_removed": run.rule_supports_removed,
                }
                if run.status == "cancelled":
                    raise JobCancelled("Category Rule evaluation cancelled by user.")
        except JobCancelled:
            raise
        except Exception as exc:
            with self.session_factory() as db:
                failed_run = db.get(PageCategoryRuleRun, run_id)
                if failed_run:
                    failed_run.status = "failed"
                    failed_run.finished_at = datetime.now(UTC)
                    failed_run.error_type = type(exc).__name__
                    failed_run.error_message = str(exc)
                    db.commit()
            raise
        with self.session_factory() as db:
            current = db.get(BackgroundJob, job.id)
            if current and current.payload_json.get("rerun_requested"):
                if current.website_property_id is None:
                    raise ValueError("Category Rule job is missing site_id.")
                create_followup_evaluation(
                    db,
                    current.website_property_id,
                    str(current.payload_json.get("latest_trigger_type", "manual_recalculate")),
                    current.payload_json.get("latest_trigger_rule_id"),
                )
                db.commit()
        return HandlerResult(result_json=result)


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
            JOB_TYPE_SCAN_PROJECTION_BUILD: ScanProjectionJobHandler(session_factory),
            JOB_TYPE_SCAN_COMPARISON_BUILD: ScanComparisonJobHandler(session_factory),
            JOB_TYPE_CATEGORY_RULE_EVALUATION: CategoryRuleEvaluationJobHandler(session_factory),
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
        if job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
            mark_projection_build_terminal(
                db,
                int(job.payload_json.get("projection_build_id", 0)),
                "cancelled",
                "cancelled",
                "Projection build cancelled by user.",
            )
        elif job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
            mark_comparison_build_terminal(
                db,
                int(job.payload_json.get("comparison_build_id", 0)),
                "cancelled",
                "cancelled",
                "Comparison build cancelled by user.",
            )
        elif job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "cancelled"
                scan.stop_reason = "cancelled_by_user"
                scan.finished_at = now
                _enqueue_projection_for_terminal_scan(db, scan)
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
        if job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
            mark_projection_build_terminal(
                db,
                int(job.payload_json.get("projection_build_id", 0)),
                "failed",
                reason,
                "Worker interrupted during projection build.",
            )
        elif job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
            mark_comparison_build_terminal(
                db,
                int(job.payload_json.get("comparison_build_id", 0)),
                "failed",
                reason,
                "Worker interrupted during comparison build.",
            )
        elif job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "interrupted"
                scan.stop_reason = reason
                scan.finished_at = now
                from app.services.rendered_capture import mark_capturing_interrupted

                mark_capturing_interrupted(db, scan.id, reason)
                _enqueue_projection_for_terminal_scan(db, scan)
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
        if job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
            mark_projection_build_terminal(
                db,
                int(job.payload_json.get("projection_build_id", 0)),
                "failed",
                type(exc).__name__,
                str(exc),
            )
        elif job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
            mark_comparison_build_terminal(
                db,
                int(job.payload_json.get("comparison_build_id", 0)),
                "failed",
                type(exc).__name__,
                str(exc),
            )
        elif job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "failed"
                scan.fatal_error_message = str(exc)
                scan.finished_at = now
                _enqueue_projection_for_terminal_scan(db, scan)
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


def _enqueue_projection_for_terminal_scan(db: Session, scan: Scan) -> None:
    if scan.status not in {
        "completed",
        "completed_with_errors",
        "failed",
        "cancelled",
        "interrupted",
    }:
        return
    build = create_projection_build(db, scan.id)
    if build.status == "queued":
        background_jobs.enqueue_scan_projection_job(db, build.id, scan)
    if scan.website_property_id is not None and db.scalar(
        select(PageCategoryRule.id)
        .where(
            PageCategoryRule.website_property_id == scan.website_property_id,
            PageCategoryRule.is_active.is_(True),
        )
        .limit(1)
    ):
        from app.services.category_rules import queue_evaluation

        queue_evaluation(db, scan.website_property_id, "scan_completed")
    db.commit()
