from typing import get_args

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import BackgroundJob, Scan, WebsiteProperty
from app.services import background_jobs
from app.services.category_rules import queue_evaluation
from app.services.job_handlers import _terminalize_failed_job, build_handler_registry
from app.services.job_lifecycle import JOB_LIFECYCLES, lifecycle_for
from app.services.job_types import JOB_TYPE_LABELS, JobType
from app.services.scan_projections import create_projection_build
from app.storage.content_store import LocalContentStore


def test_job_type_labels_handlers_and_lifecycles_are_exhaustive(db_session, tmp_path) -> None:
    job_types = set(get_args(JobType))
    handlers = build_handler_registry(
        lambda: db_session, LocalContentStore(tmp_path / "html")
    ).handlers

    assert set(JOB_TYPE_LABELS) == job_types
    assert set(handlers) == job_types
    assert set(JOB_LIFECYCLES) == job_types
    assert {spec.job_type for spec in JOB_LIFECYCLES.values()} == job_types


@pytest.mark.parametrize(
    ("job_type", "capabilities"),
    [
        pytest.param("scan", (1, 1, 1, 1, 1, 1), id="scan"),
        pytest.param("source_refresh", (1, 1, 1, 1, 1, 0), id="source-refresh"),
        pytest.param("scan_projection_build", (1, 1, 1, 1, 1, 1), id="projection"),
        pytest.param("scan_comparison_build", (1, 1, 1, 1, 1, 0), id="comparison"),
        pytest.param("category_rule_evaluation", (1, 1, 1, 1, 1, 1), id="category"),
        pytest.param("structured_content_build", (0, 0, 0, 0, 0, 0), id="structured"),
        pytest.param("performance_run", (1, 1, 1, 1, 1, 0), id="performance"),
        pytest.param("accessibility_run", (1, 1, 1, 1, 1, 0), id="accessibility"),
        pytest.param("render_run", (1, 1, 1, 1, 1, 0), id="render"),
        pytest.param("finding_evaluation", (1, 1, 1, 1, 1, 0), id="finding"),
    ],
)
def test_lifecycle_capability_decisions_are_explicit(
    job_type: str, capabilities: tuple[int, int, int, int, int, int]
) -> None:
    spec = lifecycle_for(job_type)

    assert (
        tuple(
            int(hook is not None)
            for hook in (
                spec.queued_cancel,
                spec.mark_cancelled,
                spec.mark_interrupted,
                spec.mark_failed,
                spec.reconcile_domain_status,
                spec.ensure_followups,
            )
        )
        == capabilities
    )


def test_unknown_job_type_has_no_implicit_lifecycle() -> None:
    with pytest.raises(ValueError, match="No lifecycle registered"):
        lifecycle_for("unknown")


def test_queued_projection_cancellation_stages_domain_and_job_together(db_session) -> None:
    scan = Scan(
        starting_url="https://projection-cancel.example/",
        status="completed",
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    build = create_projection_build(db_session, scan.id)
    job = background_jobs.enqueue_scan_projection_job(db_session, build.id, scan)
    db_session.commit()

    background_jobs.request_cancellation(db_session, job)

    assert job.status == "cancelled"
    assert build.status == "cancelled"
    assert build.active_key is None


def test_queued_category_cancellation_stages_domain_and_job_together(db_session) -> None:
    site = WebsiteProperty(
        name="Category cancellation",
        base_url="https://category-cancel.example/",
        normalized_base_url="https://category-cancel.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    run = queue_evaluation(db_session, site.id, "test")
    job = db_session.scalar(
        select(BackgroundJob).where(BackgroundJob.website_property_id == site.id)
    )
    assert job is not None
    db_session.commit()

    background_jobs.request_cancellation(db_session, job)

    assert job.status == "cancelled"
    assert run.status == "cancelled"
    assert run.error_type == "cancelled"


def test_category_failure_and_job_terminalization_share_one_transaction(
    db_session, monkeypatch
) -> None:
    site = WebsiteProperty(
        name="Category failure",
        base_url="https://category-failure.example/",
        normalized_base_url="https://category-failure.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    run = queue_evaluation(db_session, site.id, "test")
    db_session.commit()
    claimed = background_jobs.claim_next_job(
        db_session, worker_id="category-worker", lease_seconds=30
    )
    assert claimed is not None
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    real_fail_job = background_jobs.fail_job

    def fail_before_commit(*_args, **_kwargs):
        raise RuntimeError("forced terminal persistence failure")

    monkeypatch.setattr(background_jobs, "fail_job", fail_before_commit)
    with pytest.raises(RuntimeError, match="forced terminal"):
        _terminalize_failed_job(factory, claimed, 30, ValueError("category failed"))

    db_session.expire_all()
    assert db_session.get(type(run), run.id).status == "queued"
    assert db_session.get(BackgroundJob, claimed.job.id).status == "running"

    monkeypatch.setattr(background_jobs, "fail_job", real_fail_job)
    _terminalize_failed_job(factory, claimed, 30, ValueError("category failed"))

    db_session.expire_all()
    assert db_session.get(type(run), run.id).status == "failed"
    assert db_session.get(BackgroundJob, claimed.job.id).status == "failed"
