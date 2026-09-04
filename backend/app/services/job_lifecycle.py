from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal

from sqlalchemy.orm import Session

from app.models import (
    AccessibilityRun,
    BackgroundJob,
    FindingEvaluation,
    PageCategoryRuleRun,
    PerformanceRun,
    RenderRun,
    Scan,
    ScanComparisonBuild,
    ScanProjectionBuild,
    SourceRefresh,
)
from app.services.job_types import (
    JOB_STATUS_COMPLETED,
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
    TERMINAL_JOB_STATUSES,
    JobType,
)

InterruptionReason = Literal["worker_shutdown", "lease_expired"]
QueuedCancelHook = Callable[[Session, BackgroundJob, datetime, str], None]
TerminalHook = Callable[[Session, BackgroundJob, datetime], None]
InterruptionHook = Callable[[Session, BackgroundJob, datetime, InterruptionReason], None]
FailureHook = Callable[[Session, BackgroundJob, datetime, Exception], None]
ReconcileHook = Callable[[Session, BackgroundJob], str | None]
FollowupHook = Callable[[Session, BackgroundJob], None]


@dataclass(frozen=True)
class JobLifecycleSpec:
    job_type: JobType
    queued_cancel: QueuedCancelHook | None
    mark_cancelled: TerminalHook | None
    mark_interrupted: InterruptionHook | None
    mark_failed: FailureHook | None
    reconcile_domain_status: ReconcileHook | None
    ensure_followups: FollowupHook | None


def lifecycle_for(job_type: str) -> JobLifecycleSpec:
    spec = JOB_LIFECYCLES.get(job_type)
    if spec is None:
        raise ValueError(f"No lifecycle registered for job type: {job_type}")
    return spec


def stage_queued_cancellation(
    db: Session, job: BackgroundJob, message: str, *, now: datetime | None = None
) -> None:
    hook = lifecycle_for(job.job_type).queued_cancel
    if hook is not None:
        hook(db, job, now or datetime.now(UTC), message)


def stage_domain_cancelled(db: Session, job: BackgroundJob, *, now: datetime | None = None) -> None:
    hook = lifecycle_for(job.job_type).mark_cancelled
    if hook is not None:
        hook(db, job, now or datetime.now(UTC))


def stage_domain_interrupted(
    db: Session,
    job: BackgroundJob,
    reason: InterruptionReason,
    *,
    now: datetime | None = None,
) -> None:
    hook = lifecycle_for(job.job_type).mark_interrupted
    if hook is not None:
        hook(db, job, now or datetime.now(UTC), reason)


def stage_domain_failed(
    db: Session, job: BackgroundJob, exc: Exception, *, now: datetime | None = None
) -> None:
    hook = lifecycle_for(job.job_type).mark_failed
    if hook is not None:
        hook(db, job, now or datetime.now(UTC), exc)


def reconcile_domain_status(db: Session, job: BackgroundJob) -> str | None:
    hook = lifecycle_for(job.job_type).reconcile_domain_status
    return hook(db, job) if hook is not None else None


def stage_required_followups(db: Session, job: BackgroundJob) -> None:
    hook = lifecycle_for(job.job_type).ensure_followups
    if hook is not None:
        hook(db, job)


def _queued_scan_cancel(db: Session, job: BackgroundJob, now: datetime, _message: str) -> None:
    scan = db.get(Scan, job.scan_id) if job.scan_id else None
    if scan is not None and scan.status == "queued":
        scan.status = "cancelled"
        scan.stop_reason = "cancelled_by_user"
        scan.finished_at = now


def _queued_refresh_cancel(db: Session, job: BackgroundJob, now: datetime, _message: str) -> None:
    refresh = db.get(SourceRefresh, job.source_refresh_id) if job.source_refresh_id else None
    if refresh is None or refresh.status != "queued":
        return
    refresh.status = "cancelled"
    refresh.error_type = "cancelled"
    refresh.error_message = "Refresh cancelled by user."
    refresh.finished_at = now
    if refresh.url_source is not None:
        refresh.url_source.last_refresh_status = "cancelled"
        refresh.url_source.last_refresh_started_at = refresh.started_at
        refresh.url_source.last_refresh_finished_at = now
        refresh.url_source.last_error_type = refresh.error_type
        refresh.url_source.last_error_message = refresh.error_message


def _queued_projection_cancel(
    db: Session, job: BackgroundJob, _now: datetime, _message: str
) -> None:
    from app.services.scan_projections import mark_projection_build_terminal

    mark_projection_build_terminal(
        db,
        _payload_id(job, "projection_build_id"),
        "cancelled",
        "cancelled",
        "Projection build cancelled before execution.",
        commit=False,
    )


def _queued_comparison_cancel(
    db: Session, job: BackgroundJob, _now: datetime, _message: str
) -> None:
    from app.services.scan_comparisons import mark_comparison_build_terminal

    mark_comparison_build_terminal(
        db,
        _payload_id(job, "comparison_build_id"),
        "cancelled",
        "cancelled",
        "Comparison build cancelled by user.",
        commit=False,
    )


def _queued_category_cancel(db: Session, job: BackgroundJob, now: datetime, _message: str) -> None:
    run = db.get(PageCategoryRuleRun, _payload_id(job, "run_id"))
    if run is not None and run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now
        run.error_type = "cancelled"
        run.error_message = "Category Rule evaluation cancelled before execution."


def _queued_performance_cancel(
    db: Session, job: BackgroundJob, now: datetime, _message: str
) -> None:
    run = _performance_run(db, job)
    if run is not None and run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now


def _queued_accessibility_cancel(
    db: Session, job: BackgroundJob, now: datetime, _message: str
) -> None:
    run = _accessibility_run(db, job)
    if run is not None and run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now


def _queued_render_cancel(db: Session, job: BackgroundJob, now: datetime, _message: str) -> None:
    run = _render_run(db, job)
    if run is not None and run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now


def _queued_finding_cancel(db: Session, job: BackgroundJob, _now: datetime, _message: str) -> None:
    from app.services.finding_evaluations import mark_evaluation_terminal

    mark_evaluation_terminal(
        db,
        _payload_id(job, "finding_evaluation_id"),
        "cancelled",
        error_type="cancelled",
        error_message="Finding evaluation cancelled before execution.",
    )


def _cancel_scan(db: Session, job: BackgroundJob, now: datetime) -> None:
    scan = db.get(Scan, job.scan_id) if job.scan_id else None
    if scan is None:
        return
    scan.status = "cancelled"
    scan.stop_reason = "cancelled_by_user"
    scan.finished_at = now
    _scan_followups(db, job)


def _cancel_refresh(db: Session, job: BackgroundJob, now: datetime) -> None:
    refresh = db.get(SourceRefresh, job.source_refresh_id) if job.source_refresh_id else None
    if refresh is None:
        return
    refresh.status = "cancelled"
    refresh.error_type = "cancelled"
    refresh.error_message = "Refresh cancelled by user."
    refresh.finished_at = now
    if refresh.url_source is not None:
        refresh.url_source.last_refresh_status = "cancelled"
        refresh.url_source.last_refresh_finished_at = now


def _cancel_projection(db: Session, job: BackgroundJob, _now: datetime) -> None:
    from app.services.scan_projections import mark_projection_build_terminal

    mark_projection_build_terminal(
        db,
        _payload_id(job, "projection_build_id"),
        "cancelled",
        "cancelled",
        "Projection build cancelled by user.",
        commit=False,
    )


def _cancel_comparison(db: Session, job: BackgroundJob, _now: datetime) -> None:
    from app.services.scan_comparisons import mark_comparison_build_terminal

    mark_comparison_build_terminal(
        db,
        _payload_id(job, "comparison_build_id"),
        "cancelled",
        "cancelled",
        "Comparison build cancelled by user.",
        commit=False,
    )


def _cancel_category(db: Session, job: BackgroundJob, now: datetime) -> None:
    run = db.get(PageCategoryRuleRun, _payload_id(job, "run_id"))
    if run is not None and run.status not in TERMINAL_JOB_STATUSES:
        run.status = "cancelled"
        run.finished_at = now
        run.error_type = "cancelled"
        run.error_message = "Category Rule evaluation cancelled by user."


def _cancel_performance(db: Session, job: BackgroundJob, now: datetime) -> None:
    run = _performance_run(db, job)
    if run is not None:
        run.status = "cancelled"
        run.finished_at = now


def _cancel_accessibility(db: Session, job: BackgroundJob, now: datetime) -> None:
    run = _accessibility_run(db, job)
    if run is not None:
        run.status = "cancelled"
        run.finished_at = now


def _cancel_render(db: Session, job: BackgroundJob, now: datetime) -> None:
    run = _render_run(db, job)
    if run is not None:
        run.status = "cancelled"
        run.finished_at = now


def _cancel_finding(db: Session, job: BackgroundJob, _now: datetime) -> None:
    from app.services.finding_evaluations import mark_evaluation_terminal

    mark_evaluation_terminal(
        db,
        _payload_id(job, "finding_evaluation_id"),
        "cancelled",
        error_type="cancelled",
        error_message="Finding evaluation cancelled by user.",
    )


def _interrupt_scan(
    db: Session, job: BackgroundJob, now: datetime, reason: InterruptionReason
) -> None:
    scan = db.get(Scan, job.scan_id) if job.scan_id else None
    if scan is None or (reason == "lease_expired" and scan.status in TERMINAL_JOB_STATUSES):
        return
    stop_reason = "worker_lease_expired" if reason == "lease_expired" else reason
    scan.status = "interrupted"
    scan.stop_reason = stop_reason
    scan.finished_at = now
    if reason == "worker_shutdown":
        from app.services.rendered_capture import mark_capturing_interrupted

        mark_capturing_interrupted(db, scan.id, reason, commit=False)
        _scan_followups(db, job)


def _interrupt_refresh(
    db: Session, job: BackgroundJob, now: datetime, reason: InterruptionReason
) -> None:
    refresh = db.get(SourceRefresh, job.source_refresh_id) if job.source_refresh_id else None
    if refresh is None or (reason == "lease_expired" and refresh.status in TERMINAL_JOB_STATUSES):
        return
    stop_reason = "worker_lease_expired" if reason == "lease_expired" else reason
    refresh.status = "interrupted"
    refresh.error_type = stop_reason
    refresh.error_message = "Worker interrupted before completion."
    refresh.finished_at = now
    if refresh.url_source is not None:
        refresh.url_source.last_refresh_status = "interrupted"
        refresh.url_source.last_refresh_finished_at = now
    if (
        reason == "lease_expired"
        and refresh.ai_document_refresh is not None
        and refresh.ai_document_refresh.status not in TERMINAL_JOB_STATUSES
    ):
        refresh.ai_document_refresh.status = "interrupted"
        refresh.ai_document_refresh.stop_reason = "worker_lease_expired"


def _interrupt_projection(
    db: Session, job: BackgroundJob, _now: datetime, reason: InterruptionReason
) -> None:
    from app.services.scan_projections import mark_projection_build_terminal

    mark_projection_build_terminal(
        db,
        _payload_id(job, "projection_build_id"),
        "failed",
        reason,
        (
            "Worker lease expired during projection build."
            if reason == "lease_expired"
            else "Worker interrupted during projection build."
        ),
        commit=False,
    )


def _interrupt_comparison(
    db: Session, job: BackgroundJob, _now: datetime, reason: InterruptionReason
) -> None:
    from app.services.scan_comparisons import mark_comparison_build_terminal

    mark_comparison_build_terminal(
        db,
        _payload_id(job, "comparison_build_id"),
        "failed",
        reason,
        (
            "Worker lease expired during comparison build."
            if reason == "lease_expired"
            else "Worker interrupted during comparison build."
        ),
        commit=False,
    )


def _interrupt_category(
    db: Session, job: BackgroundJob, now: datetime, reason: InterruptionReason
) -> None:
    if reason != "lease_expired":
        return
    run = db.get(PageCategoryRuleRun, _payload_id(job, "run_id"))
    if run is not None and run.status not in TERMINAL_JOB_STATUSES:
        run.status = "interrupted"
        run.finished_at = now
        run.error_type = "lease_expired"
        run.error_message = "Worker lease expired during Category Rule evaluation."


def _interrupt_performance(
    db: Session, job: BackgroundJob, now: datetime, reason: InterruptionReason
) -> None:
    run = _performance_run(db, job)
    if run is None or (reason == "lease_expired" and run.status in TERMINAL_JOB_STATUSES):
        return
    run.status = "failed"
    run.finished_at = now
    run.error_summary = (
        "Worker lease expired during Performance collection."
        if reason == "lease_expired"
        else "Worker interrupted during Performance collection."
    )


def _interrupt_accessibility(
    db: Session, job: BackgroundJob, now: datetime, reason: InterruptionReason
) -> None:
    run = _accessibility_run(db, job)
    if run is None or (reason == "lease_expired" and run.status in TERMINAL_JOB_STATUSES):
        return
    run.status = "interrupted"
    run.finished_at = now
    run.error_summary = (
        "Worker lease expired during Accessibility collection."
        if reason == "lease_expired"
        else "Worker interrupted during Accessibility collection."
    )


def _interrupt_render(
    db: Session, job: BackgroundJob, now: datetime, reason: InterruptionReason
) -> None:
    run = _render_run(db, job)
    if run is None or (reason == "lease_expired" and run.status in TERMINAL_JOB_STATUSES):
        return
    run.status = "interrupted"
    run.finished_at = now
    run.error_summary = (
        "Worker lease expired during rendered capture."
        if reason == "lease_expired"
        else "Worker interrupted during rendered capture."
    )
    from app.services.rendered_capture import mark_render_run_capturing_interrupted

    mark_render_run_capturing_interrupted(db, run.id, reason, commit=False)


def _interrupt_finding(
    db: Session, job: BackgroundJob, _now: datetime, reason: InterruptionReason
) -> None:
    from app.services.finding_evaluations import mark_evaluation_terminal

    mark_evaluation_terminal(
        db,
        _payload_id(job, "finding_evaluation_id"),
        "failed",
        error_type=reason,
        error_message=(
            "Worker lease expired during Finding evaluation."
            if reason == "lease_expired"
            else "Worker interrupted during Finding evaluation."
        ),
    )


def _fail_scan(db: Session, job: BackgroundJob, now: datetime, exc: Exception) -> None:
    scan = db.get(Scan, job.scan_id) if job.scan_id else None
    if scan is None:
        return
    scan.status = "failed"
    scan.fatal_error_message = str(exc)
    scan.finished_at = now
    _scan_followups(db, job)


def _fail_refresh(db: Session, job: BackgroundJob, now: datetime, exc: Exception) -> None:
    refresh = db.get(SourceRefresh, job.source_refresh_id) if job.source_refresh_id else None
    if refresh is None:
        return
    refresh.status = "failed"
    refresh.error_type = type(exc).__name__
    refresh.error_message = str(exc)
    refresh.finished_at = now
    if refresh.url_source is not None:
        refresh.url_source.last_refresh_status = "failed"
        refresh.url_source.last_error_type = refresh.error_type
        refresh.url_source.last_error_message = refresh.error_message
        refresh.url_source.last_refresh_finished_at = now


def _fail_projection(db: Session, job: BackgroundJob, _now: datetime, exc: Exception) -> None:
    from app.services.scan_projections import mark_projection_build_terminal

    mark_projection_build_terminal(
        db,
        _payload_id(job, "projection_build_id"),
        "failed",
        type(exc).__name__,
        str(exc),
        commit=False,
    )


def _fail_comparison(db: Session, job: BackgroundJob, _now: datetime, exc: Exception) -> None:
    from app.services.scan_comparisons import mark_comparison_build_terminal

    mark_comparison_build_terminal(
        db,
        _payload_id(job, "comparison_build_id"),
        "failed",
        type(exc).__name__,
        str(exc),
        commit=False,
    )


def _fail_category(db: Session, job: BackgroundJob, now: datetime, exc: Exception) -> None:
    run = db.get(PageCategoryRuleRun, _payload_id(job, "run_id"))
    if run is not None and run.status not in TERMINAL_JOB_STATUSES:
        run.status = "failed"
        run.finished_at = now
        run.error_type = type(exc).__name__
        run.error_message = str(exc)


def _fail_performance(db: Session, job: BackgroundJob, _now: datetime, exc: Exception) -> None:
    from app.services.performance_collection import mark_performance_run_failed

    run_id = job.performance_run_id or _payload_id(job, "performance_run_id")
    if run_id:
        mark_performance_run_failed(db, run_id, exc, commit=False)


def _fail_accessibility(db: Session, job: BackgroundJob, _now: datetime, exc: Exception) -> None:
    from app.services.accessibility_collection import mark_accessibility_run_failed

    run_id = job.accessibility_run_id or _payload_id(job, "accessibility_run_id")
    if run_id:
        mark_accessibility_run_failed(db, run_id, exc, commit=False)


def _fail_render(db: Session, job: BackgroundJob, _now: datetime, exc: Exception) -> None:
    from app.services.render_runs import mark_render_run_failed

    run_id = job.render_run_id or _payload_id(job, "render_run_id")
    if run_id:
        mark_render_run_failed(db, run_id, exc, commit=False)


def _fail_finding(db: Session, job: BackgroundJob, _now: datetime, exc: Exception) -> None:
    from app.services.finding_evaluations import mark_evaluation_terminal

    mark_evaluation_terminal(
        db,
        _payload_id(job, "finding_evaluation_id"),
        "failed",
        error_type=type(exc).__name__,
        error_message=str(exc),
    )


def _reconcile_scan(db: Session, job: BackgroundJob) -> str | None:
    scan = db.get(Scan, job.scan_id) if job.scan_id else None
    return scan.status if scan is not None else JOB_STATUS_FAILED


def _reconcile_refresh(db: Session, job: BackgroundJob) -> str | None:
    refresh = db.get(SourceRefresh, job.source_refresh_id) if job.source_refresh_id else None
    return refresh.status if refresh is not None else JOB_STATUS_FAILED


def _reconcile_projection(db: Session, job: BackgroundJob) -> str | None:
    build = db.get(ScanProjectionBuild, _payload_id(job, "projection_build_id"))
    if build is None:
        return JOB_STATUS_FAILED
    if build.status == "ready":
        return JOB_STATUS_COMPLETED
    return build.status if build.status in {"failed", "cancelled"} else None


def _reconcile_comparison(db: Session, job: BackgroundJob) -> str | None:
    build = db.get(ScanComparisonBuild, _payload_id(job, "comparison_build_id"))
    if build is None:
        return JOB_STATUS_FAILED
    if build.status == "ready":
        return JOB_STATUS_COMPLETED
    return build.status if build.status in {"failed", "cancelled"} else None


def _reconcile_category(db: Session, job: BackgroundJob) -> str | None:
    run = db.get(PageCategoryRuleRun, _payload_id(job, "run_id"))
    return run.status if run is not None else JOB_STATUS_FAILED


def _reconcile_performance(db: Session, job: BackgroundJob) -> str | None:
    run = _performance_run(db, job)
    return run.status if run is not None else JOB_STATUS_FAILED


def _reconcile_accessibility(db: Session, job: BackgroundJob) -> str | None:
    run = _accessibility_run(db, job)
    return run.status if run is not None else JOB_STATUS_FAILED


def _reconcile_render(db: Session, job: BackgroundJob) -> str | None:
    run = _render_run(db, job)
    return run.status if run is not None else JOB_STATUS_FAILED


def _reconcile_finding(db: Session, job: BackgroundJob) -> str | None:
    evaluation = db.get(FindingEvaluation, _payload_id(job, "finding_evaluation_id"))
    if evaluation is not None and evaluation.status in {"completed", "cancelled"}:
        return evaluation.status
    return None


def _scan_followups(db: Session, job: BackgroundJob) -> None:
    from app.services.job_followups import ensure_terminal_scan_followups

    scan = db.get(Scan, job.scan_id) if job.scan_id else None
    if scan is not None:
        ensure_terminal_scan_followups(db, scan)


def _projection_followups(db: Session, job: BackgroundJob) -> None:
    from app.services.job_followups import ensure_projection_followups

    ensure_projection_followups(db, job)


def _category_followups(db: Session, job: BackgroundJob) -> None:
    from app.services.job_followups import ensure_category_rerun

    ensure_category_rerun(db, job)


def _payload_id(job: BackgroundJob, key: str) -> int:
    return int(job.payload_json.get(key, 0))


def _performance_run(db: Session, job: BackgroundJob) -> PerformanceRun | None:
    return db.get(PerformanceRun, job.performance_run_id or _payload_id(job, "performance_run_id"))


def _accessibility_run(db: Session, job: BackgroundJob) -> AccessibilityRun | None:
    return db.get(
        AccessibilityRun, job.accessibility_run_id or _payload_id(job, "accessibility_run_id")
    )


def _render_run(db: Session, job: BackgroundJob) -> RenderRun | None:
    return db.get(RenderRun, job.render_run_id or _payload_id(job, "render_run_id"))


def _spec(
    job_type: JobType,
    *,
    queued_cancel: QueuedCancelHook | None,
    mark_cancelled: TerminalHook | None,
    mark_interrupted: InterruptionHook | None,
    mark_failed: FailureHook | None,
    reconcile: ReconcileHook | None,
    followups: FollowupHook | None,
) -> JobLifecycleSpec:
    return JobLifecycleSpec(
        job_type=job_type,
        queued_cancel=queued_cancel,
        mark_cancelled=mark_cancelled,
        mark_interrupted=mark_interrupted,
        mark_failed=mark_failed,
        reconcile_domain_status=reconcile,
        ensure_followups=followups,
    )


JOB_LIFECYCLES: Mapping[str, JobLifecycleSpec] = MappingProxyType(
    {
        JOB_TYPE_SCAN: _spec(
            JOB_TYPE_SCAN,
            queued_cancel=_queued_scan_cancel,
            mark_cancelled=_cancel_scan,
            mark_interrupted=_interrupt_scan,
            mark_failed=_fail_scan,
            reconcile=_reconcile_scan,
            followups=_scan_followups,
        ),
        JOB_TYPE_SOURCE_REFRESH: _spec(
            JOB_TYPE_SOURCE_REFRESH,
            queued_cancel=_queued_refresh_cancel,
            mark_cancelled=_cancel_refresh,
            mark_interrupted=_interrupt_refresh,
            mark_failed=_fail_refresh,
            reconcile=_reconcile_refresh,
            followups=None,
        ),
        JOB_TYPE_SCAN_PROJECTION_BUILD: _spec(
            JOB_TYPE_SCAN_PROJECTION_BUILD,
            queued_cancel=_queued_projection_cancel,
            mark_cancelled=_cancel_projection,
            mark_interrupted=_interrupt_projection,
            mark_failed=_fail_projection,
            reconcile=_reconcile_projection,
            followups=_projection_followups,
        ),
        JOB_TYPE_SCAN_COMPARISON_BUILD: _spec(
            JOB_TYPE_SCAN_COMPARISON_BUILD,
            queued_cancel=_queued_comparison_cancel,
            mark_cancelled=_cancel_comparison,
            mark_interrupted=_interrupt_comparison,
            mark_failed=_fail_comparison,
            reconcile=_reconcile_comparison,
            followups=None,
        ),
        JOB_TYPE_CATEGORY_RULE_EVALUATION: _spec(
            JOB_TYPE_CATEGORY_RULE_EVALUATION,
            queued_cancel=_queued_category_cancel,
            mark_cancelled=_cancel_category,
            mark_interrupted=_interrupt_category,
            mark_failed=_fail_category,
            reconcile=_reconcile_category,
            followups=_category_followups,
        ),
        JOB_TYPE_STRUCTURED_CONTENT_BUILD: _spec(
            JOB_TYPE_STRUCTURED_CONTENT_BUILD,
            queued_cancel=None,
            mark_cancelled=None,
            mark_interrupted=None,
            mark_failed=None,
            reconcile=None,
            followups=None,
        ),
        JOB_TYPE_PERFORMANCE_RUN: _spec(
            JOB_TYPE_PERFORMANCE_RUN,
            queued_cancel=_queued_performance_cancel,
            mark_cancelled=_cancel_performance,
            mark_interrupted=_interrupt_performance,
            mark_failed=_fail_performance,
            reconcile=_reconcile_performance,
            followups=None,
        ),
        JOB_TYPE_ACCESSIBILITY_RUN: _spec(
            JOB_TYPE_ACCESSIBILITY_RUN,
            queued_cancel=_queued_accessibility_cancel,
            mark_cancelled=_cancel_accessibility,
            mark_interrupted=_interrupt_accessibility,
            mark_failed=_fail_accessibility,
            reconcile=_reconcile_accessibility,
            followups=None,
        ),
        JOB_TYPE_RENDER_RUN: _spec(
            JOB_TYPE_RENDER_RUN,
            queued_cancel=_queued_render_cancel,
            mark_cancelled=_cancel_render,
            mark_interrupted=_interrupt_render,
            mark_failed=_fail_render,
            reconcile=_reconcile_render,
            followups=None,
        ),
        JOB_TYPE_FINDING_EVALUATION: _spec(
            JOB_TYPE_FINDING_EVALUATION,
            queued_cancel=_queued_finding_cancel,
            mark_cancelled=_cancel_finding,
            mark_interrupted=_interrupt_finding,
            mark_failed=_fail_finding,
            reconcile=_reconcile_finding,
            followups=None,
        ),
    }
)
