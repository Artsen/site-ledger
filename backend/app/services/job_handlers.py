from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import is_transient_database_lock
from app.models import (
    AccessibilityRun,
    BackgroundJob,
    PageCategoryRuleRun,
    PerformanceRun,
    RenderRun,
    Scan,
    SourceRefresh,
)
from app.services import background_jobs
from app.services.accessibility_collection import (
    execute_accessibility_run,
    mark_accessibility_run_failed,
)
from app.services.category_rules import reconcile_site
from app.services.finding_evaluations import execute_evaluation, mark_evaluation_terminal
from app.services.job_followups import ensure_required_followups, ensure_terminal_scan_followups
from app.services.job_types import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_COMPLETED_WITH_ERRORS,
    JOB_STATUS_FAILED,
    JOB_TYPE_ACCESSIBILITY_RUN,
    JOB_TYPE_CATEGORY_RULE_EVALUATION,
    JOB_TYPE_FINDING_EVALUATION,
    JOB_TYPE_PERFORMANCE_RUN,
    JOB_TYPE_RENDER_RUN,
    JOB_TYPE_SCAN,
    JOB_TYPE_SCAN_COMPARISON_BUILD,
    JOB_TYPE_SCAN_PROJECTION_BUILD,
    JOB_TYPE_SOURCE_REFRESH,
    JOB_TYPE_STRUCTURED_CONTENT_BUILD,
    ExecutionOwnershipLost,
)
from app.services.performance_collection import execute_performance_run, mark_performance_run_failed
from app.services.render_runs import execute_render_run, mark_render_run_failed
from app.services.scan_comparisons import (
    ComparisonBuildCancelled,
    execute_comparison_build,
    mark_comparison_build_terminal,
)
from app.services.scan_execution import ScanExecutionCoordinator
from app.services.scan_projections import (
    ProjectionBuildCancelled,
    execute_projection_build,
    mark_projection_build_terminal,
)
from app.services.source_refresh import execute_source_refresh
from app.services.structured_content import build_missing_structured_content
from app.storage.ai_document_store import LocalAiDocumentStore
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore

logger = logging.getLogger("site_ledger.jobs")


class JobCancelled(RuntimeError):
    pass


class RequiredFollowupPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class HandlerResult:
    status: str = JOB_STATUS_COMPLETED
    result_json: dict[str, Any] | None = None


class JobHandler(Protocol):
    async def execute(
        self, job: BackgroundJob, context: JobExecutionContext
    ) -> HandlerResult | None:
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
        self._lease_lost = threading.Event()

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def mark_lease_lost(self) -> None:
        self._lease_lost.set()

    def raise_if_lease_lost(self) -> None:
        if self.lease_lost:
            raise ExecutionOwnershipLost("Job lease ownership was lost.")

    def fence_domain_mutation(self, db: Session) -> None:
        """Fence collector writes in the transaction that owns their domain mutation."""
        self.raise_if_lease_lost()
        try:
            background_jobs.guard_execution_ownership(
                db,
                job_id=self.job_id,
                lease_token=self.lease_token,
                lease_seconds=self.lease_seconds,
            )
        except background_jobs.StaleLeaseError as exc:
            self.mark_lease_lost()
            raise ExecutionOwnershipLost("Job lease ownership was lost.") from exc

    def check_cancelled(self) -> bool:
        self.raise_if_lease_lost()
        with self.session_factory() as db:
            job = db.get(BackgroundJob, self.job_id)
            cancelled = bool(job and job.cancellation_requested_at is not None)
        self.raise_if_lease_lost()
        return cancelled

    def raise_if_cancelled(self) -> None:
        if self.check_cancelled():
            raise JobCancelled("Cancellation requested.")

    def heartbeat(self) -> None:
        try:
            with self.session_factory() as db:
                background_jobs.heartbeat_job(
                    db,
                    job_id=self.job_id,
                    lease_token=self.lease_token,
                    lease_seconds=self.lease_seconds,
                )
        except background_jobs.StaleLeaseError:
            self.mark_lease_lost()
            raise

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
        self.raise_if_lease_lost()
        try:
            with self.session_factory() as db:
                background_jobs.update_progress(
                    db,
                    job_id=self.job_id,
                    lease_token=self.lease_token,
                    lease_seconds=self.lease_seconds,
                    phase=phase,
                    current_operation=current_operation,
                    current=current,
                    total=total,
                    unit=unit,
                    counters=counters,
                )
        except background_jobs.StaleLeaseError as exc:
            if not self.lease_lost:
                self.mark_lease_lost()
                logger.warning("job lease ownership lost", extra={"job_id": self.job_id})
            raise ExecutionOwnershipLost("Job lease ownership was lost.") from exc
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
                fence_domain_mutation=context.fence_domain_mutation,
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
        return await asyncio.to_thread(self._execute_blocking, build_id, context)

    def _execute_blocking(self, build_id: int, context: JobExecutionContext) -> HandlerResult:
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
                    fence_domain_mutation=context.fence_domain_mutation,
                )
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
    def __init__(self, session_factory: Callable[[], Session], store: LocalContentStore):
        self.session_factory = session_factory
        self.store_root = store.root

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        build_id = int(job.payload_json.get("comparison_build_id", 0))
        if not build_id:
            raise ValueError("Comparison job is missing comparison_build_id.")
        return await asyncio.to_thread(self._execute_blocking, build_id, context)

    def _execute_blocking(self, build_id: int, context: JobExecutionContext) -> HandlerResult:
        try:
            with self.session_factory() as db:
                build = execute_comparison_build(
                    db,
                    build_id,
                    store=LocalContentStore(self.store_root),
                    should_cancel=context.check_cancelled,
                    progress=lambda phase, current, total: context.progress(
                        phase=phase,
                        current_operation=phase.replace("_", " ").title(),
                        current=current,
                        total=total,
                        unit="rows",
                    ),
                    fence_domain_mutation=context.fence_domain_mutation,
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
        return await asyncio.to_thread(self._execute_blocking, run_id, context)

    def _execute_blocking(self, run_id: int, context: JobExecutionContext) -> HandlerResult:
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
                    fence_domain_mutation=context.fence_domain_mutation,
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
        except ExecutionOwnershipLost:
            raise
        except Exception as exc:
            with self.session_factory() as db:
                failed_run = db.get(PageCategoryRuleRun, run_id)
                if failed_run:
                    failed_run.status = "failed"
                    failed_run.finished_at = datetime.now(UTC)
                    failed_run.error_type = type(exc).__name__
                    failed_run.error_message = str(exc)
                    context.fence_domain_mutation(db)
                    db.commit()
            raise
        return HandlerResult(result_json=result)


class StructuredContentBuildJobHandler:
    def __init__(self, session_factory: Callable[[], Session], store: LocalContentStore) -> None:
        self.session_factory = session_factory
        self.store_root = store.root

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        site_id = int(job.payload_json.get("site_id", 0))
        if not site_id:
            raise ValueError("Structured content job is missing site_id.")
        scan_id_value = job.payload_json.get("scan_id")
        limit_value = job.payload_json.get("limit")
        content_blob_ids_value = job.payload_json.get("content_blob_ids")
        return await asyncio.to_thread(
            self._execute_blocking,
            site_id,
            int(scan_id_value) if scan_id_value is not None else None,
            int(limit_value) if limit_value is not None else None,
            [int(value) for value in content_blob_ids_value]
            if content_blob_ids_value is not None
            else None,
            context,
        )

    def _execute_blocking(
        self,
        site_id: int,
        scan_id: int | None,
        limit: int | None,
        content_blob_ids: list[int] | None,
        context: JobExecutionContext,
    ) -> HandlerResult:
        with self.session_factory() as db:
            result = build_missing_structured_content(
                db,
                LocalContentStore(self.store_root),
                site_id=site_id,
                scan_id=scan_id,
                limit=limit,
                content_blob_ids=content_blob_ids,
                fence_domain_mutation=context.fence_domain_mutation,
                should_cancel=context.check_cancelled,
                progress=lambda current, total, counters: context.progress(
                    phase="preparing",
                    current_operation="Preparing structured Page content",
                    current=current,
                    total=total,
                    unit="ContentBlobs",
                    counters=counters,
                ),
            )
        if context.check_cancelled():
            raise JobCancelled("Structured content preparation cancelled by user.")
        return HandlerResult(
            status=(JOB_STATUS_COMPLETED_WITH_ERRORS if result["failed"] else JOB_STATUS_COMPLETED),
            result_json=result,
        )


class PerformanceRunJobHandler:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        run_id = job.performance_run_id or int(job.payload_json.get("performance_run_id", 0))
        if not run_id:
            raise ValueError("Performance job is missing performance_run_id.")
        run = await asyncio.to_thread(
            execute_performance_run,
            self.session_factory,
            run_id,
            should_cancel=context.check_cancelled,
            fence_domain_mutation=context.fence_domain_mutation,
            progress=lambda current, total, counters: context.progress(
                phase="collecting",
                current_operation="Collecting external Performance evidence",
                current=current,
                total=total,
                unit="provider requests",
                counters=counters,
            ),
        )
        if run.status == "cancelled":
            raise JobCancelled("Performance run cancelled by user.")
        return HandlerResult(
            status=(JOB_STATUS_COMPLETED_WITH_ERRORS if run.failed_count else JOB_STATUS_COMPLETED),
            result_json={
                "performance_run_id": run.id,
                "ready": run.ready_count,
                "unavailable": run.unavailable_count,
                "failed": run.failed_count,
            },
        )


class AccessibilityRunJobHandler:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        run_id = job.accessibility_run_id or int(job.payload_json.get("accessibility_run_id", 0))
        if not run_id:
            raise ValueError("Accessibility job is missing accessibility_run_id.")
        run = await execute_accessibility_run(
            self.session_factory,
            run_id,
            should_cancel=context.check_cancelled,
            fence_domain_mutation=context.fence_domain_mutation,
            progress=lambda current, total, counters: context.progress(
                phase="auditing",
                current_operation="Collecting automated Accessibility evidence",
                current=current,
                total=total,
                unit="browser audits",
                counters=counters,
            ),
        )
        if run.status == "cancelled":
            raise JobCancelled("Accessibility run cancelled by user.")
        return HandlerResult(
            status=(JOB_STATUS_COMPLETED_WITH_ERRORS if run.failed_count else JOB_STATUS_COMPLETED),
            result_json={
                "accessibility_run_id": run.id,
                "ready": run.ready_count,
                "failed": run.failed_count,
            },
        )


class RenderRunJobHandler:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: BackgroundJob, context: JobExecutionContext) -> HandlerResult:
        run_id = job.render_run_id or int(job.payload_json.get("render_run_id", 0))
        if not run_id:
            raise ValueError("Rendered capture job is missing render_run_id.")
        run = await execute_render_run(
            self.session_factory,
            run_id,
            should_cancel=context.check_cancelled,
            fence_domain_mutation=context.fence_domain_mutation,
            progress=lambda current, total, counters: context.progress(
                phase="capturing",
                current_operation="Capturing rendered Page evidence",
                current=current,
                total=total,
                unit="Pages",
                counters=counters,
            ),
        )
        if run.status == "cancelled":
            raise JobCancelled("Render Run cancelled by user.")
        return HandlerResult(
            status=(
                JOB_STATUS_COMPLETED_WITH_ERRORS
                if run.failed_count or run.skipped_count
                else JOB_STATUS_COMPLETED
            ),
            result_json={
                "render_run_id": run.id,
                "successful": run.completed_count,
                "failed": run.failed_count,
                "skipped": run.skipped_count,
            },
        )


class FindingEvaluationJobHandler:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def execute(
        self, job: BackgroundJob, context: JobExecutionContext
    ) -> HandlerResult | None:
        evaluation_id = int(job.payload_json.get("finding_evaluation_id", 0))
        if not evaluation_id:
            raise ValueError("Finding job is missing finding_evaluation_id.")
        context.raise_if_cancelled()
        return await asyncio.to_thread(self._execute_blocking, job, evaluation_id, context)

    def _execute_blocking(
        self, job: BackgroundJob, evaluation_id: int, context: JobExecutionContext
    ) -> None:
        with self.session_factory() as db:
            background_jobs.guard_terminalization(
                db,
                job_id=job.id,
                lease_token=context.lease_token,
                lease_seconds=context.lease_seconds,
            )
            result = execute_evaluation(
                db, evaluation_id, check_ownership=context.raise_if_lease_lost
            )
            background_jobs.complete_job(
                db,
                job_id=job.id,
                lease_token=context.lease_token,
                status=JOB_STATUS_COMPLETED,
                result_json={
                    "finding_evaluation_id": result.evaluation_id,
                    "detected": result.detected,
                    "clear": result.clear,
                    "unknown": result.unknown,
                    "created_findings": result.created_findings,
                    "resolved_findings": result.resolved_findings,
                    "reopened_findings": result.reopened_findings,
                    "assessments": result.assessments,
                    "checksum_sha256": result.checksum_sha256,
                },
            )


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
            JOB_TYPE_SCAN_COMPARISON_BUILD: ScanComparisonJobHandler(session_factory, store),
            JOB_TYPE_CATEGORY_RULE_EVALUATION: CategoryRuleEvaluationJobHandler(session_factory),
            JOB_TYPE_STRUCTURED_CONTENT_BUILD: StructuredContentBuildJobHandler(
                session_factory, store
            ),
            JOB_TYPE_PERFORMANCE_RUN: PerformanceRunJobHandler(session_factory),
            JOB_TYPE_ACCESSIBILITY_RUN: AccessibilityRunJobHandler(session_factory),
            JOB_TYPE_RENDER_RUN: RenderRunJobHandler(session_factory),
            JOB_TYPE_FINDING_EVALUATION: FindingEvaluationJobHandler(session_factory),
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
    await asyncio.to_thread(context.event, "started", "Job execution started.")
    try:
        if claimed_job.job.cancellation_requested_at is not None:
            raise JobCancelled("Cancellation requested before job started.")
        result = await _execute_with_lease_monitor(
            registry.get(claimed_job.job.job_type), claimed_job.job, context
        )
        if result is None:
            return
        await asyncio.to_thread(
            _persist_handler_result,
            session_factory,
            claimed_job,
            result,
        )
    except JobCancelled as exc:
        if context.lease_lost:
            return
        try:
            await asyncio.to_thread(
                _terminalize_cancelled_job,
                session_factory,
                claimed_job,
                lease_seconds,
                str(exc),
            )
        except background_jobs.StaleLeaseError:
            _log_lease_loss(context)
    except asyncio.CancelledError:
        if not context.lease_lost:
            try:
                await asyncio.to_thread(
                    _terminalize_interrupted_job,
                    session_factory,
                    claimed_job,
                    lease_seconds,
                )
            except background_jobs.StaleLeaseError:
                _log_lease_loss(context)
        raise
    except background_jobs.StaleLeaseError:
        _log_lease_loss(context)
    except ExecutionOwnershipLost:
        context.mark_lease_lost()
        _log_lease_loss(context)
    except RequiredFollowupPersistenceError:
        logger.exception(
            "required follow-up persistence failed; lease recovery will retry",
            extra={"job_id": context.job_id},
        )
    except Exception as exc:
        logger.exception(
            "unexpected background job execution failure",
            extra={
                "job_id": context.job_id,
                "job_type": claimed_job.job.job_type,
            },
        )
        try:
            await asyncio.to_thread(
                _terminalize_failed_job,
                session_factory,
                claimed_job,
                lease_seconds,
                exc,
            )
        except background_jobs.StaleLeaseError:
            _log_lease_loss(context)


async def _execute_with_lease_monitor(
    handler: JobHandler, job: BackgroundJob, context: JobExecutionContext
) -> HandlerResult | None:
    handler_task = asyncio.create_task(handler.execute(job, context))
    heartbeat_task = asyncio.create_task(_job_heartbeat_loop(context))
    done, _pending = await asyncio.wait(
        {handler_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if heartbeat_task in done:
        heartbeat_error = heartbeat_task.exception()
        if isinstance(heartbeat_error, background_jobs.StaleLeaseError):
            context.mark_lease_lost()
            _log_lease_loss(context)
            try:
                await handler_task
            except Exception:
                logger.warning(
                    "job handler stopped after lease ownership loss",
                    extra={"job_id": context.job_id},
                )
            return None
        if heartbeat_error is not None:
            handler_task.cancel()
            await asyncio.gather(handler_task, return_exceptions=True)
            raise heartbeat_error
    heartbeat_task.cancel()
    heartbeat_outcomes = await asyncio.gather(heartbeat_task, return_exceptions=True)
    if any(isinstance(value, background_jobs.StaleLeaseError) for value in heartbeat_outcomes):
        context.mark_lease_lost()
    if context.lease_lost:
        _log_lease_loss(context)
        await asyncio.gather(handler_task, return_exceptions=True)
        return None
    return await handler_task


async def _job_heartbeat_loop(context: JobExecutionContext) -> None:
    while True:
        await asyncio.sleep(max(0.05, context.lease_seconds / 3))
        try:
            await asyncio.to_thread(context.heartbeat)
        except OperationalError as exc:
            if not is_transient_database_lock(exc):
                raise
            logger.warning(
                "job heartbeat delayed by database lock", extra={"job_id": context.job_id}
            )


def _persist_handler_result(
    session_factory: Callable[[], Session],
    claimed_job: background_jobs.ClaimedJob,
    result: HandlerResult,
) -> None:
    with session_factory() as db:
        current = db.get(BackgroundJob, claimed_job.job.id)
        if current is None:
            raise ValueError("Background job not found.")
        try:
            ensure_required_followups(db, current)
        except Exception as exc:
            raise RequiredFollowupPersistenceError(
                "Required follow-up work could not be persisted."
            ) from exc
        if result.status == JOB_STATUS_FAILED:
            result_json = result.result_json or {}
            background_jobs.fail_job(
                db,
                job_id=claimed_job.job.id,
                lease_token=claimed_job.lease_token,
                error_type=str(result_json.get("stop_reason") or "job_failed"),
                error_message=str(result_json.get("fatal_error_message") or "Job failed."),
            )
        else:
            background_jobs.complete_job(
                db,
                job_id=claimed_job.job.id,
                lease_token=claimed_job.lease_token,
                status=result.status,
                result_json=result.result_json,
            )


def _terminalize_cancelled_job(
    session_factory: Callable[[], Session],
    claimed_job: background_jobs.ClaimedJob,
    lease_seconds: float,
    message: str,
) -> None:
    with session_factory() as db:
        background_jobs.guard_terminalization(
            db,
            job_id=claimed_job.job.id,
            lease_token=claimed_job.lease_token,
            lease_seconds=lease_seconds,
        )
        _mark_domain_cancelled(db, claimed_job.job, commit=False)
        background_jobs.complete_job(
            db,
            job_id=claimed_job.job.id,
            lease_token=claimed_job.lease_token,
            status=JOB_STATUS_CANCELLED,
            result_json={"message": message},
        )


def _terminalize_interrupted_job(
    session_factory: Callable[[], Session],
    claimed_job: background_jobs.ClaimedJob,
    lease_seconds: float,
) -> None:
    with session_factory() as db:
        background_jobs.guard_terminalization(
            db,
            job_id=claimed_job.job.id,
            lease_token=claimed_job.lease_token,
            lease_seconds=lease_seconds,
        )
        _mark_domain_interrupted(db, claimed_job.job, "worker_shutdown", commit=False)
        background_jobs.fail_job(
            db,
            job_id=claimed_job.job.id,
            lease_token=claimed_job.lease_token,
            error_type="worker_shutdown",
            error_message="Worker stopped during execution.",
            interrupted=True,
        )


def _terminalize_failed_job(
    session_factory: Callable[[], Session],
    claimed_job: background_jobs.ClaimedJob,
    lease_seconds: float,
    exc: Exception,
) -> None:
    with session_factory() as db:
        background_jobs.guard_terminalization(
            db,
            job_id=claimed_job.job.id,
            lease_token=claimed_job.lease_token,
            lease_seconds=lease_seconds,
        )
        _mark_domain_failed(db, claimed_job.job, exc, commit=False)
        background_jobs.fail_job(
            db,
            job_id=claimed_job.job.id,
            lease_token=claimed_job.lease_token,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


def _log_lease_loss(context: JobExecutionContext) -> None:
    logger.warning("job lease ownership lost", extra={"job_id": context.job_id})


def _scan_result(scan: Scan) -> dict[str, Any]:
    return {
        "scan_id": scan.id,
        "status": scan.status,
        "stop_reason": scan.stop_reason,
        "fatal_error_message": scan.fatal_error_message,
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


def _mark_domain_cancelled(
    db_or_factory: Session | Callable[[], Session], job: BackgroundJob, *, commit: bool = True
) -> None:
    context = nullcontext(db_or_factory) if isinstance(db_or_factory, Session) else db_or_factory()
    with context as db:
        now = datetime.now(UTC)
        if job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
            mark_projection_build_terminal(
                db,
                int(job.payload_json.get("projection_build_id", 0)),
                "cancelled",
                "cancelled",
                "Projection build cancelled by user.",
                commit=commit,
            )
        elif job.job_type == JOB_TYPE_FINDING_EVALUATION:
            mark_evaluation_terminal(
                db,
                int(job.payload_json.get("finding_evaluation_id", 0)),
                "cancelled",
                error_type="cancelled",
                error_message="Finding evaluation cancelled by user.",
            )
        elif job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
            mark_comparison_build_terminal(
                db,
                int(job.payload_json.get("comparison_build_id", 0)),
                "cancelled",
                "cancelled",
                "Comparison build cancelled by user.",
                commit=commit,
            )
        elif job.job_type == JOB_TYPE_PERFORMANCE_RUN and job.performance_run_id:
            performance_run = db.get(PerformanceRun, job.performance_run_id)
            if performance_run:
                performance_run.status = "cancelled"
                performance_run.finished_at = now
        elif job.job_type == JOB_TYPE_ACCESSIBILITY_RUN and job.accessibility_run_id:
            accessibility_run = db.get(AccessibilityRun, job.accessibility_run_id)
            if accessibility_run:
                accessibility_run.status = "cancelled"
                accessibility_run.finished_at = now
        elif job.job_type == JOB_TYPE_RENDER_RUN and job.render_run_id:
            render_run = db.get(RenderRun, job.render_run_id)
            if render_run:
                render_run.status = "cancelled"
                render_run.finished_at = now
        elif job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "cancelled"
                scan.stop_reason = "cancelled_by_user"
                scan.finished_at = now
                _enqueue_projection_for_terminal_scan(db, scan, commit=commit)
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
        if commit:
            db.commit()


def _mark_domain_interrupted(
    db_or_factory: Session | Callable[[], Session],
    job: BackgroundJob,
    reason: str,
    *,
    commit: bool = True,
) -> None:
    context = nullcontext(db_or_factory) if isinstance(db_or_factory, Session) else db_or_factory()
    with context as db:
        now = datetime.now(UTC)
        if job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
            mark_projection_build_terminal(
                db,
                int(job.payload_json.get("projection_build_id", 0)),
                "failed",
                reason,
                "Worker interrupted during projection build.",
                commit=commit,
            )
        elif job.job_type == JOB_TYPE_FINDING_EVALUATION:
            mark_evaluation_terminal(
                db,
                int(job.payload_json.get("finding_evaluation_id", 0)),
                "failed",
                error_type=reason,
                error_message="Worker interrupted during Finding evaluation.",
            )
        elif job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
            mark_comparison_build_terminal(
                db,
                int(job.payload_json.get("comparison_build_id", 0)),
                "failed",
                reason,
                "Worker interrupted during comparison build.",
                commit=commit,
            )
        elif job.job_type == JOB_TYPE_PERFORMANCE_RUN and job.performance_run_id:
            performance_run = db.get(PerformanceRun, job.performance_run_id)
            if performance_run:
                performance_run.status = "failed"
                performance_run.finished_at = now
                performance_run.error_summary = "Worker interrupted during Performance collection."
        elif job.job_type == JOB_TYPE_ACCESSIBILITY_RUN and job.accessibility_run_id:
            accessibility_run = db.get(AccessibilityRun, job.accessibility_run_id)
            if accessibility_run:
                accessibility_run.status = "interrupted"
                accessibility_run.finished_at = now
                accessibility_run.error_summary = (
                    "Worker interrupted during Accessibility collection."
                )
        elif job.job_type == JOB_TYPE_RENDER_RUN and job.render_run_id:
            render_run = db.get(RenderRun, job.render_run_id)
            if render_run:
                render_run.status = "interrupted"
                render_run.finished_at = now
                render_run.error_summary = "Worker interrupted during rendered capture."
                from app.services.rendered_capture import mark_render_run_capturing_interrupted

                mark_render_run_capturing_interrupted(db, render_run.id, reason, commit=commit)
        elif job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "interrupted"
                scan.stop_reason = reason
                scan.finished_at = now
                from app.services.rendered_capture import mark_capturing_interrupted

                mark_capturing_interrupted(db, scan.id, reason, commit=commit)
                _enqueue_projection_for_terminal_scan(db, scan, commit=commit)
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
        if commit:
            db.commit()


def _mark_domain_failed(
    db_or_factory: Session | Callable[[], Session],
    job: BackgroundJob,
    exc: Exception,
    *,
    commit: bool = True,
) -> None:
    context = nullcontext(db_or_factory) if isinstance(db_or_factory, Session) else db_or_factory()
    with context as db:
        now = datetime.now(UTC)
        if job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
            mark_projection_build_terminal(
                db,
                int(job.payload_json.get("projection_build_id", 0)),
                "failed",
                type(exc).__name__,
                str(exc),
                commit=commit,
            )
        elif job.job_type == JOB_TYPE_FINDING_EVALUATION:
            mark_evaluation_terminal(
                db,
                int(job.payload_json.get("finding_evaluation_id", 0)),
                "failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        elif job.job_type == JOB_TYPE_SCAN_COMPARISON_BUILD:
            mark_comparison_build_terminal(
                db,
                int(job.payload_json.get("comparison_build_id", 0)),
                "failed",
                type(exc).__name__,
                str(exc),
                commit=commit,
            )
        elif job.job_type == JOB_TYPE_PERFORMANCE_RUN and job.performance_run_id:
            mark_performance_run_failed(db, job.performance_run_id, exc, commit=commit)
        elif job.job_type == JOB_TYPE_ACCESSIBILITY_RUN and job.accessibility_run_id:
            mark_accessibility_run_failed(db, job.accessibility_run_id, exc, commit=commit)
        elif job.job_type == JOB_TYPE_RENDER_RUN and job.render_run_id:
            mark_render_run_failed(db, job.render_run_id, exc, commit=commit)
        elif job.scan_id:
            scan = db.get(Scan, job.scan_id)
            if scan:
                scan.status = "failed"
                scan.fatal_error_message = str(exc)
                scan.finished_at = now
                _enqueue_projection_for_terminal_scan(db, scan, commit=commit)
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
        if commit:
            db.commit()


def _enqueue_projection_for_terminal_scan(db: Session, scan: Scan, *, commit: bool = True) -> None:
    ensure_terminal_scan_followups(db, scan)
    if commit:
        db.commit()
