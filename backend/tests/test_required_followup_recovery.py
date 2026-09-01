from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    BackgroundJob,
    PageCategory,
    PageCategoryRule,
    PageCategoryRuleRun,
    Scan,
    ScanProjectionBuild,
    WebsiteProperty,
)
from app.services import background_jobs, job_followups
from app.services.category_rules import create_followup_evaluation
from app.services.job_handlers import (
    HandlerResult,
    RequiredFollowupPersistenceError,
    _persist_handler_result,
)
from app.services.scan_comparisons import create_comparison, create_comparison_build
from app.services.scan_projections import create_projection_build, execute_projection_build


def test_scan_terminal_recovery_creates_projection_and_category_followups_once(db_session) -> None:
    site = _site(db_session, "scan-followup")
    category = PageCategory(
        website_property_id=site.id,
        name="Tracked",
        normalized_name="tracked",
        color_key="stone",
    )
    db_session.add(category)
    db_session.flush()
    db_session.add(
        PageCategoryRule(
            website_property_id=site.id,
            category_id=category.id,
            name="Tracked Pages",
            match_mode="all",
            is_active=True,
        )
    )
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        stop_reason="queue_empty",
        finished_at=datetime.now(UTC),
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    job = background_jobs.enqueue_scan_job(db_session, scan)
    _expire_running(job)
    db_session.commit()

    assert background_jobs.recover_expired_jobs(db_session) == 1
    first_counts = _followup_counts(db_session)

    assert job.status == "completed"
    assert first_counts == (1, 1, 1, 1)
    assert background_jobs.recover_expired_jobs(db_session) == 0
    assert _followup_counts(db_session) == first_counts


def test_projection_ready_recovery_queues_waiting_comparison_once(db_session) -> None:
    site = _site(db_session, "projection-followup")
    baseline = _terminal_scan(db_session, site, "baseline")
    target = _terminal_scan(db_session, site, "target")
    baseline_build = create_projection_build(db_session, baseline.id)
    db_session.commit()
    execute_projection_build(db_session, baseline_build.id)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    waiting = create_comparison_build(db_session, comparison.id)
    assert waiting.status == "waiting_for_projections"
    target_build = create_projection_build(db_session, target.id)
    projection_job = background_jobs.enqueue_scan_projection_job(
        db_session, target_build.id, target
    )
    db_session.commit()
    execute_projection_build(db_session, target_build.id)
    _expire_running(projection_job)
    db_session.commit()

    assert background_jobs.recover_expired_jobs(db_session) == 1
    db_session.refresh(waiting)
    comparison_jobs = _job_count(db_session, "scan_comparison_build")

    assert projection_job.status == "completed"
    assert waiting.status == "queued"
    assert comparison_jobs == 1
    assert background_jobs.recover_expired_jobs(db_session) == 0
    assert _job_count(db_session, "scan_comparison_build") == comparison_jobs


def test_category_completed_recovery_creates_requested_rerun_once(db_session) -> None:
    site = _site(db_session, "category-followup")
    parent = create_followup_evaluation(db_session, site.id, "manual_recalculate")
    parent.status = "completed"
    parent.finished_at = datetime.now(UTC)
    parent_job = db_session.scalar(
        select(BackgroundJob).where(BackgroundJob.website_property_id == site.id)
    )
    assert parent_job is not None
    parent_job.payload_json = {
        **parent_job.payload_json,
        "rerun_requested": True,
        "latest_trigger_type": "rule_updated",
        "latest_trigger_rule_id": 42,
    }
    _expire_running(parent_job)
    db_session.commit()

    assert background_jobs.recover_expired_jobs(db_session) == 1
    run_count = db_session.scalar(select(func.count()).select_from(PageCategoryRuleRun))
    job_count = _job_count(db_session, "category_rule_evaluation")
    db_session.refresh(parent_job)

    assert parent_job.status == "completed"
    assert parent_job.payload_json["rerun_requested"] is False
    assert (run_count, job_count) == (2, 2)
    assert background_jobs.recover_expired_jobs(db_session) == 0
    assert db_session.scalar(select(func.count()).select_from(PageCategoryRuleRun)) == run_count
    assert _job_count(db_session, "category_rule_evaluation") == job_count


def test_followup_creation_failure_leaves_terminal_domain_recoverable(
    db_session, monkeypatch
) -> None:
    site = _site(db_session, "followup-retry")
    scan = _terminal_scan(db_session, site, "scan")
    job = background_jobs.enqueue_scan_job(db_session, scan)
    _expire_running(job)
    db_session.commit()
    original = job_followups.create_projection_build

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("forced follow-up creation failure")

    monkeypatch.setattr(job_followups, "create_projection_build", fail_projection)
    with pytest.raises(RuntimeError, match="forced follow-up"):
        background_jobs.recover_expired_jobs(db_session)
    db_session.rollback()
    db_session.refresh(job)
    db_session.refresh(scan)

    assert scan.status == "completed"
    assert job.status == "running"
    assert _job_count(db_session, "scan_projection_build") == 0

    monkeypatch.setattr(job_followups, "create_projection_build", original)
    assert background_jobs.recover_expired_jobs(db_session) == 1
    assert job.status == "completed"
    assert _job_count(db_session, "scan_projection_build") == 1


def test_normal_completion_followup_failure_defers_to_recovery(db_session, monkeypatch) -> None:
    site = _site(db_session, "normal-followup-retry")
    scan = _terminal_scan(db_session, site, "scan")
    job = background_jobs.enqueue_scan_job(db_session, scan)
    db_session.commit()
    claimed = background_jobs.claim_next_job(
        db_session, worker_id="normal-followup-worker", lease_seconds=30
    )
    assert claimed is not None
    session_factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    original = job_followups.create_projection_build

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("forced normal follow-up creation failure")

    monkeypatch.setattr(job_followups, "create_projection_build", fail_projection)
    with pytest.raises(RequiredFollowupPersistenceError):
        _persist_handler_result(session_factory, claimed, HandlerResult())

    db_session.expire_all()
    assert scan.status == "completed"
    assert job.status == "running"
    assert _job_count(db_session, "scan_projection_build") == 0

    monkeypatch.setattr(job_followups, "create_projection_build", original)
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert background_jobs.recover_expired_jobs(db_session) == 1
    assert job.status == "completed"
    assert _job_count(db_session, "scan_projection_build") == 1


def _site(db, label: str) -> WebsiteProperty:
    site = WebsiteProperty(
        name=label,
        base_url=f"https://{label}.example/",
        normalized_base_url=f"https://{label}.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db.add(site)
    db.flush()
    return site


def _terminal_scan(db, site: WebsiteProperty, suffix: str) -> Scan:
    scan = Scan(
        website_property_id=site.id,
        starting_url=f"{site.base_url}{suffix}",
        status="completed",
        stop_reason="queue_empty",
        finished_at=datetime.now(UTC),
        scope_config={},
    )
    db.add(scan)
    db.flush()
    return scan


def _expire_running(job: BackgroundJob) -> None:
    job.status = "running"
    job.worker_id = "crashed-worker"
    job.lease_token = "expired-token"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)


def _job_count(db, job_type: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.job_type == job_type)
        )
        or 0
    )


def _followup_counts(db) -> tuple[int, int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(ScanProjectionBuild)) or 0,
        _job_count(db, "scan_projection_build"),
        db.scalar(select(func.count()).select_from(PageCategoryRuleRun)) or 0,
        _job_count(db, "category_rule_evaluation"),
    )
