from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, PageCategoryRule, PageCategoryRuleRun, Scan
from app.services import background_jobs
from app.services.job_types import (
    JOB_TYPE_CATEGORY_RULE_EVALUATION,
    JOB_TYPE_SCAN,
    JOB_TYPE_SCAN_PROJECTION_BUILD,
)
from app.services.scan_projections import create_projection_build


def ensure_required_followups(db: Session, job: BackgroundJob) -> None:
    """Idempotently stage required work after a legitimate terminal domain commit."""
    if job.job_type == JOB_TYPE_SCAN and job.scan_id:
        scan = db.get(Scan, job.scan_id)
        if scan is not None:
            ensure_terminal_scan_followups(db, scan)
    elif job.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD:
        _ensure_projection_followups(db, job)
    elif job.job_type == JOB_TYPE_CATEGORY_RULE_EVALUATION:
        _ensure_category_rerun(db, job)


def ensure_terminal_scan_followups(db: Session, scan: Scan) -> None:
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


def _ensure_projection_followups(db: Session, job: BackgroundJob) -> None:
    from app.models import ScanProjectionBuild
    from app.services.scan_comparisons import (
        queue_adjacent_comparison_for_scan,
        queue_waiting_comparisons_for_scan,
    )

    build = db.get(ScanProjectionBuild, int(job.payload_json.get("projection_build_id", 0)))
    if build is None or build.status != "ready":
        return
    queue_waiting_comparisons_for_scan(db, build.scan_id)
    queue_adjacent_comparison_for_scan(db, build.scan_id)


def _ensure_category_rerun(db: Session, job: BackgroundJob) -> None:
    payload = dict(job.payload_json)
    if not payload.get("rerun_requested"):
        return
    run = db.get(PageCategoryRuleRun, int(payload.get("run_id", 0)))
    if run is None or run.status != "completed" or job.website_property_id is None:
        return
    from app.services.category_rules import create_followup_evaluation

    create_followup_evaluation(
        db,
        job.website_property_id,
        str(payload.get("latest_trigger_type", "manual_recalculate")),
        payload.get("latest_trigger_rule_id"),
    )
    payload["rerun_requested"] = False
    job.payload_json = payload
