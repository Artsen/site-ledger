import asyncio
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base, is_transient_database_lock
from app.models import (
    BackgroundJob,
    PageCategory,
    PageCategoryRule,
    PageCategoryRuleRun,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanProjectionBuild,
    ScanProjectionState,
    WebsiteProperty,
    WorkerInstance,
)
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services import background_jobs, scan_comparisons
from app.services.category_rules import create_followup_evaluation
from app.services.job_handlers import (
    CategoryRuleEvaluationJobHandler,
    HandlerResult,
    JobExecutionContext,
    JobHandlerRegistry,
    ScanComparisonJobHandler,
    ScanProjectionJobHandler,
    StructuredContentBuildJobHandler,
    _job_heartbeat_loop,
    run_claimed_job,
)
from app.services.job_types import (
    JOB_TYPE_CATEGORY_RULE_EVALUATION,
    JOB_TYPE_SCAN,
    JOB_TYPE_SCAN_COMPARISON_BUILD,
    JOB_TYPE_SCAN_PROJECTION_BUILD,
    JOB_TYPE_STRUCTURED_CONTENT_BUILD,
)
from app.services.scan_comparisons import create_comparison, create_comparison_build
from app.services.scan_projections import create_projection_build, execute_projection_build
from app.services.site_management import create_site
from app.storage.content_store import LocalContentStore
from app.worker import WorkerService


def test_sqlite_lock_is_classified_as_transient() -> None:
    assert is_transient_database_lock(_locked_error())
    assert not is_transient_database_lock(
        OperationalError("SELECT 1", {}, sqlite3.OperationalError("no such table: missing"))
    )


def test_worker_recovery_waits_while_local_job_is_active(tmp_path) -> None:
    worker = _worker(tmp_path)
    recover = Mock()
    worker._recover = recover  # type: ignore[method-assign]
    worker._running.add(Mock())  # type: ignore[arg-type]

    worker._recover_if_idle()

    recover.assert_not_called()


def test_worker_recovery_tolerates_transient_sqlite_lock(tmp_path, monkeypatch) -> None:
    worker = _worker(tmp_path)

    def locked_recovery(_db) -> int:
        raise _locked_error()

    monkeypatch.setattr(background_jobs, "recover_expired_jobs", locked_recovery)

    worker._recover()


def test_progress_tolerates_transient_sqlite_lock(tmp_path, monkeypatch) -> None:
    session_factory = _session_factory(tmp_path)
    context = JobExecutionContext(
        session_factory=session_factory,
        job_id=7,
        lease_token="lease-token",
        lease_seconds=30,
    )

    def locked_progress(_db, **_kwargs) -> None:
        raise _locked_error()

    monkeypatch.setattr(background_jobs, "update_progress", locked_progress)

    context.progress(phase="running", current=1, total=2, unit="pages")


@pytest.mark.asyncio
async def test_projection_blocking_work_keeps_tiny_lease_and_event_loop_alive(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        scan = Scan(
            starting_url="https://projection.example/",
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add(scan)
        db.flush()
        build = create_projection_build(db, scan.id)
        job = background_jobs.enqueue_scan_projection_job(db, build.id, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="projection-worker", lease_seconds=0.30
        )
        assert claimed is not None
        job_id = job.id
        build_id = build.id
        initial_lease_expires_at = claimed.job.lease_expires_at
        assert initial_lease_expires_at is not None

    blocking_started = threading.Event()
    blocking_finished_at: list[float] = []
    recovery_results: list[int] = []
    observed_lease_expiries: list[datetime] = []

    def blocking_projection(db, active_build_id, **_kwargs):
        active_build = db.get(ScanProjectionBuild, active_build_id)
        assert active_build is not None
        active_build.status = "building"
        db.commit()
        blocking_started.set()
        time.sleep(0.90)
        active_build.status = "ready"
        active_build.completed_at = datetime.now(UTC)
        active_build.checksum_sha256 = "a" * 64
        db.commit()
        blocking_finished_at.append(time.monotonic())
        return active_build

    monkeypatch.setattr("app.services.job_handlers.execute_projection_build", blocking_projection)
    monkeypatch.setattr(
        "app.services.scan_comparisons.queue_waiting_comparisons_for_scan",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.scan_comparisons.queue_adjacent_comparison_for_scan",
        lambda *_args, **_kwargs: None,
    )

    def attempt_recovery() -> None:
        assert blocking_started.wait(timeout=2)
        time.sleep(0.45)
        with session_factory() as db:
            active_job = db.get(BackgroundJob, job_id)
            assert active_job is not None and active_job.lease_expires_at is not None
            observed_lease_expiries.append(active_job.lease_expires_at)
            recovery_results.append(background_jobs.recover_expired_jobs(db))

    recovery_thread = threading.Thread(target=attempt_recovery)
    recovery_thread.start()
    loop_tick_at: list[float] = []

    async def tick_loop() -> None:
        await asyncio.sleep(0.15)
        loop_tick_at.append(time.monotonic())

    tick_task = asyncio.create_task(tick_loop())
    registry = JobHandlerRegistry(
        {JOB_TYPE_SCAN_PROJECTION_BUILD: ScanProjectionJobHandler(session_factory)}
    )
    await run_claimed_job(
        session_factory=session_factory,
        registry=registry,
        claimed_job=claimed,
        lease_seconds=0.30,
    )
    await tick_task
    recovery_thread.join(timeout=2)

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_build = db.get(ScanProjectionBuild, build_id)
        assert persisted_job is not None
        assert persisted_build is not None
        assert persisted_job.status == "completed"
        assert persisted_build.status == "ready"
        assert (
            not db.query(background_jobs.JobEvent)
            .filter_by(job_id=job_id, event_type="lease_expired")
            .count()
        )

    assert recovery_results == [0]
    assert observed_lease_expiries[0] > initial_lease_expires_at
    assert loop_tick_at and blocking_finished_at
    assert loop_tick_at[0] < blocking_finished_at[0]


@pytest.mark.asyncio
async def test_comparison_blocking_work_survives_multiple_tiny_lease_periods(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name="Comparison",
                base_url="https://comparison.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        baseline = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        target = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add_all([baseline, target])
        db.flush()
        comparison = create_comparison(db, site.id, baseline.id, target.id)
        build = create_comparison_build(db, comparison.id)
        job = background_jobs.enqueue_scan_comparison_job(db, build.id, comparison.id, site.id)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="comparison-worker", lease_seconds=0.25
        )
        assert claimed is not None
        job_id = job.id
        build_id = build.id
        initial_expiry = claimed.job.lease_expires_at
        assert initial_expiry is not None

    started = threading.Event()
    recovery_results: list[int] = []
    observed_expiries: list[datetime] = []

    def blocking_comparison(db, active_build_id, **kwargs):
        active_build = db.get(ScanComparisonBuild, active_build_id)
        assert active_build is not None
        active_build.status = "building"
        db.commit()
        kwargs["progress"]("pages", 1, 2)
        started.set()
        time.sleep(0.75)
        kwargs["progress"]("complete", 2, 2)
        active_build.status = "ready"
        active_build.finished_at = datetime.now(UTC)
        active_build.comparison_checksum_sha256 = "b" * 64
        db.commit()
        return active_build

    monkeypatch.setattr("app.services.job_handlers.execute_comparison_build", blocking_comparison)

    def attempt_recovery() -> None:
        assert started.wait(timeout=2)
        time.sleep(0.40)
        with session_factory() as db:
            active_job = db.get(BackgroundJob, job_id)
            assert active_job is not None and active_job.lease_expires_at is not None
            observed_expiries.append(active_job.lease_expires_at)
            recovery_results.append(background_jobs.recover_expired_jobs(db))

    recovery_thread = threading.Thread(target=attempt_recovery)
    recovery_thread.start()
    registry = JobHandlerRegistry(
        {
            JOB_TYPE_SCAN_COMPARISON_BUILD: ScanComparisonJobHandler(
                session_factory, LocalContentStore(tmp_path / "html")
            )
        }
    )
    await run_claimed_job(
        session_factory=session_factory,
        registry=registry,
        claimed_job=claimed,
        lease_seconds=0.25,
    )
    recovery_thread.join(timeout=2)

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_build = db.get(ScanComparisonBuild, build_id)
        assert persisted_job is not None and persisted_job.status == "completed"
        assert persisted_build is not None and persisted_build.status == "ready"
    assert recovery_results == [0]
    assert observed_expiries[0] > initial_expiry


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_kind", ["category", "structured"])
async def test_blocking_handlers_create_and_use_sessions_off_event_loop(
    tmp_path, monkeypatch, handler_kind
) -> None:
    base_session_factory = _initialized_session_factory(tmp_path)
    session_threads: list[int] = []
    execution_threads: list[int] = []
    progress_threads: list[int] = []

    def tracked_session_factory():
        session_threads.append(threading.get_ident())
        return base_session_factory()

    def record_progress(_db, **_kwargs) -> None:
        progress_threads.append(threading.get_ident())

    monkeypatch.setattr(background_jobs, "update_progress", record_progress)
    context = JobExecutionContext(
        session_factory=tracked_session_factory,
        job_id=999,
        lease_token="lease-token",
        lease_seconds=30,
    )
    event_loop_thread = threading.get_ident()

    if handler_kind == "category":

        def reconcile(_db, _run_id, **kwargs):
            execution_threads.append(threading.get_ident())
            kwargs["progress"](1, 1)
            return SimpleNamespace(
                id=1,
                website_property_id=7,
                rule_supports_added=2,
                rule_supports_removed=1,
                status="completed",
            )

        monkeypatch.setattr("app.services.job_handlers.reconcile_site", reconcile)
        handler = CategoryRuleEvaluationJobHandler(tracked_session_factory)
        job = BackgroundJob(id=999, payload_json={"run_id": 1})
    else:

        def build_structured(_db, store, **kwargs):
            execution_threads.append(threading.get_ident())
            assert store is not original_store
            assert store.root == original_store.root
            kwargs["progress"](1, 1, {"ready": 1})
            return {"ready": 1, "failed": 0}

        original_store = LocalContentStore(tmp_path / "structured-html")
        monkeypatch.setattr(
            "app.services.job_handlers.build_missing_structured_content", build_structured
        )
        handler = StructuredContentBuildJobHandler(tracked_session_factory, original_store)
        job = BackgroundJob(id=999, payload_json={"site_id": 7})

    result = await handler.execute(job, context)

    assert result.status == "completed"
    assert execution_threads and execution_threads[0] != event_loop_thread
    assert progress_threads == execution_threads
    assert session_threads and set(session_threads) == set(execution_threads)


@pytest.mark.asyncio
async def test_confirmed_stale_heartbeat_prevents_stale_owner_completion(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        scan = Scan(
            starting_url="https://stale.example/",
            status="queued",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add(scan)
        db.flush()
        job = background_jobs.enqueue_scan_job(db, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="stale-worker", lease_seconds=0.15)
        assert claimed is not None
        job_id = job.id
        scan_id = scan.id

    class SlowHandler:
        async def execute(self, _job, _context):
            await asyncio.sleep(0.20)
            return HandlerResult()

    def stale_heartbeat(_db, **_kwargs) -> None:
        raise background_jobs.StaleLeaseError("lease recovered elsewhere")

    monkeypatch.setattr(background_jobs, "heartbeat_job", stale_heartbeat)
    await run_claimed_job(
        session_factory=session_factory,
        registry=JobHandlerRegistry({JOB_TYPE_SCAN: SlowHandler()}),
        claimed_job=claimed,
        lease_seconds=0.15,
    )

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_scan = db.get(Scan, scan_id)
        assert persisted_job is not None and persisted_job.status == "running"
        assert persisted_scan is not None and persisted_scan.status == "queued"
        terminal_events = (
            db.query(background_jobs.JobEvent)
            .filter(
                background_jobs.JobEvent.job_id == job_id,
                background_jobs.JobEvent.event_type.in_(["completed", "failed"]),
            )
            .count()
        )
        assert terminal_events == 0


@pytest.mark.asyncio
async def test_recovery_prevents_stale_projection_activation(tmp_path, monkeypatch) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        scan = Scan(
            starting_url="https://projection-race.example/",
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add(scan)
        db.flush()
        build = create_projection_build(db, scan.id)
        job = background_jobs.enqueue_scan_projection_job(db, build.id, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="projection-race", lease_seconds=30)
        assert claimed is not None
        job_id, build_id, scan_id = job.id, build.id, scan.id

    started = threading.Event()
    resume = threading.Event()

    def paused_projection(db, active_build_id, **kwargs):
        active_build = db.get(ScanProjectionBuild, active_build_id)
        assert active_build is not None
        active_build.status = "building"
        kwargs["fence_domain_mutation"](db)
        db.commit()
        started.set()
        assert resume.wait(timeout=5)
        active_build.status = "ready"
        kwargs["fence_domain_mutation"](db)
        db.commit()
        return active_build

    monkeypatch.setattr("app.services.job_handlers.execute_projection_build", paused_projection)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_SCAN_PROJECTION_BUILD: ScanProjectionJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    resume.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_build = db.get(ScanProjectionBuild, build_id)
        state = db.get(ScanProjectionState, scan_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_build is not None and persisted_build.status == "failed"
        assert persisted_build.error_type == "lease_expired"
        assert state is not None and state.current_build_id is None
        assert (
            not db.query(background_jobs.JobEvent)
            .filter_by(job_id=job_id, event_type="completed")
            .count()
        )


@pytest.mark.asyncio
async def test_recovery_prevents_stale_comparison_readiness(tmp_path, monkeypatch) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name="Comparison race",
                base_url="https://comparison-race.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        baseline = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        target = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add_all([baseline, target])
        db.flush()
        comparison = create_comparison(db, site.id, baseline.id, target.id)
        build = create_comparison_build(db, comparison.id)
        job = background_jobs.enqueue_scan_comparison_job(db, build.id, comparison.id, site.id)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="comparison-race", lease_seconds=30)
        assert claimed is not None
        job_id, build_id = job.id, build.id

    started = threading.Event()
    resume = threading.Event()

    def paused_comparison(db, active_build_id, **kwargs):
        active_build = db.get(ScanComparisonBuild, active_build_id)
        assert active_build is not None
        active_build.status = "building"
        kwargs["fence_domain_mutation"](db)
        db.commit()
        started.set()
        assert resume.wait(timeout=5)
        active_build.status = "ready"
        kwargs["fence_domain_mutation"](db)
        db.commit()
        return active_build

    monkeypatch.setattr("app.services.job_handlers.execute_comparison_build", paused_comparison)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {
                    JOB_TYPE_SCAN_COMPARISON_BUILD: ScanComparisonJobHandler(
                        session_factory, LocalContentStore(tmp_path / "comparison-html")
                    )
                }
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    resume.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_build = db.get(ScanComparisonBuild, build_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_build is not None and persisted_build.status == "failed"
        assert persisted_build.error_type == "lease_expired"


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_kind", ["category", "structured"])
async def test_lease_loss_stops_subsequent_blocking_domain_work(
    tmp_path, monkeypatch, handler_kind
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name=f"{handler_kind} race",
                base_url=f"https://{handler_kind}-race.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        if handler_kind == "category":
            run = PageCategoryRuleRun(
                website_property_id=site.id,
                trigger_type="manual_recalculate",
                status="queued",
                configuration_json={},
                evaluator_version="test-v1",
            )
            db.add(run)
            db.flush()
            job = background_jobs.enqueue_category_rule_job(db, run.id, site.id)
            run_id = run.id
        else:
            job = background_jobs.enqueue_structured_content_job(db, site.id)
            run_id = None
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id=f"{handler_kind}-race", lease_seconds=30
        )
        assert claimed is not None
        job_id, site_id = job.id, site.id

    started = threading.Event()
    resume = threading.Event()

    if handler_kind == "category":

        def paused_category(db, active_run_id, **kwargs):
            active_run = db.get(PageCategoryRuleRun, active_run_id)
            assert active_run is not None
            active_run.status = "running"
            active_run.match_count = 1
            kwargs["fence_domain_mutation"](db)
            db.commit()
            started.set()
            assert resume.wait(timeout=5)
            active_run.match_count = 2
            kwargs["fence_domain_mutation"](db)
            db.commit()
            return active_run

        monkeypatch.setattr("app.services.job_handlers.reconcile_site", paused_category)
        handler = CategoryRuleEvaluationJobHandler(session_factory)
        job_type = JOB_TYPE_CATEGORY_RULE_EVALUATION
    else:

        def paused_structured(db, _store, **kwargs):
            active_site = db.get(WebsiteProperty, site_id)
            assert active_site is not None
            active_site.description = "first batch"
            db.commit()
            started.set()
            assert resume.wait(timeout=5)
            kwargs["progress"](1, 2, {"ready": 1})
            active_site.description = "second batch"
            db.commit()
            return {"ready": 2, "failed": 0}

        monkeypatch.setattr(
            "app.services.job_handlers.build_missing_structured_content", paused_structured
        )
        handler = StructuredContentBuildJobHandler(
            session_factory, LocalContentStore(tmp_path / "structured-race-html")
        )
        job_type = JOB_TYPE_STRUCTURED_CONTENT_BUILD

    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry({job_type: handler}),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    resume.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        if handler_kind == "category":
            persisted_run = db.get(PageCategoryRuleRun, run_id)
            assert persisted_run is not None and persisted_run.status == "interrupted"
            assert persisted_run.error_type == "lease_expired"
            assert persisted_run.match_count == 1
        else:
            persisted_site = db.get(WebsiteProperty, site_id)
            assert persisted_site is not None and persisted_site.description == "first batch"


@pytest.mark.asyncio
async def test_category_rule_ownership_loss_rejects_stale_followup_evaluation(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name="Category followup race",
                base_url="https://category-followup.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        run = PageCategoryRuleRun(
            website_property_id=site.id,
            trigger_type="manual_recalculate",
            status="queued",
            configuration_json={},
            evaluator_version="test-v1",
        )
        db.add(run)
        db.flush()
        job = background_jobs.enqueue_category_rule_job(db, run.id, site.id)
        payload = dict(job.payload_json)
        payload.update(
            rerun_requested=True,
            latest_trigger_type="rule_updated",
            latest_trigger_rule_id=None,
        )
        job.payload_json = payload
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="category-followup-race", lease_seconds=30
        )
        assert claimed is not None
        job_id, run_id = job.id, run.id

    followup_started = threading.Event()
    release_followup = threading.Event()

    def completed_reconcile(db, active_run_id, **kwargs):
        active = db.get(PageCategoryRuleRun, active_run_id)
        assert active is not None
        active.status = "completed"
        active.finished_at = datetime.now(UTC)
        kwargs["fence_domain_mutation"](db)
        db.commit()
        return active

    def blocked_followup(db, site_id, trigger_type, trigger_rule_id=None):
        if not followup_started.is_set():
            followup_started.set()
            assert release_followup.wait(timeout=5)
        return create_followup_evaluation(db, site_id, trigger_type, trigger_rule_id)

    monkeypatch.setattr("app.services.job_handlers.reconcile_site", completed_reconcile)
    monkeypatch.setattr("app.services.category_rules.create_followup_evaluation", blocked_followup)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {
                    JOB_TYPE_CATEGORY_RULE_EVALUATION: CategoryRuleEvaluationJobHandler(
                        session_factory
                    )
                }
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(followup_started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_followup.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_run = db.get(PageCategoryRuleRun, run_id)
        assert persisted_job is not None and persisted_job.status == "completed"
        assert persisted_run is not None and persisted_run.status == "completed"
        assert db.query(PageCategoryRuleRun).count() == 2
        assert db.query(BackgroundJob).count() == 2


@pytest.mark.asyncio
async def test_projection_ownership_loss_rejects_stale_comparison_enqueue(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name="Projection followup race",
                base_url="https://projection-followup.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        baseline = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        target = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add_all([baseline, target])
        db.flush()
        baseline_build = create_projection_build(db, baseline.id)
        db.commit()
        execute_projection_build(db, baseline_build.id)
        target_build = create_projection_build(db, target.id)
        comparison = create_comparison(db, site.id, baseline.id, target.id)
        comparison_build = create_comparison_build(db, comparison.id)
        assert comparison_build.status == "waiting_for_projections"
        job = background_jobs.enqueue_scan_projection_job(db, target_build.id, target)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="projection-followup-race", lease_seconds=30
        )
        assert claimed is not None
        job_id, comparison_id, comparison_build_id = (
            job.id,
            comparison.id,
            comparison_build.id,
        )

    enqueue_started = threading.Event()
    release_enqueue = threading.Event()
    original_queue_waiting = scan_comparisons.queue_waiting_comparisons_for_scan

    def blocked_queue_waiting(db, scan_id):
        if not enqueue_started.is_set():
            enqueue_started.set()
            assert release_enqueue.wait(timeout=5)
        return original_queue_waiting(db, scan_id)

    monkeypatch.setattr(
        scan_comparisons, "queue_waiting_comparisons_for_scan", blocked_queue_waiting
    )
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_SCAN_PROJECTION_BUILD: ScanProjectionJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(enqueue_started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_enqueue.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_build = db.get(ScanComparisonBuild, comparison_build_id)
        persisted_comparison = db.get(ScanComparison, comparison_id)
        assert persisted_job is not None and persisted_job.status == "completed"
        assert persisted_build is not None and persisted_build.status == "queued"
        assert persisted_comparison is not None and persisted_comparison.current_build_id is None
        assert (
            db.query(BackgroundJob).filter_by(job_type=JOB_TYPE_SCAN_COMPARISON_BUILD).count() == 1
        )


@pytest.mark.asyncio
async def test_recovery_winning_terminalization_guard_preserves_domain_state(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        scan = Scan(
            starting_url="https://terminal-race.example/",
            status="completed",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add(scan)
        db.flush()
        build = create_projection_build(db, scan.id)
        build.status = "building"
        job = background_jobs.enqueue_scan_projection_job(db, build.id, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="terminal-race", lease_seconds=30)
        assert claimed is not None
        job_id, build_id = job.id, build.id

    class FailingHandler:
        async def execute(self, _job, _context):
            raise RuntimeError("stale executor failure")

    original_guard = background_jobs.guard_terminalization

    def recovery_wins(db, **kwargs):
        assert _force_recovery(session_factory, job_id) == 1
        original_guard(db, **kwargs)

    monkeypatch.setattr(background_jobs, "guard_terminalization", recovery_wins)
    await run_claimed_job(
        session_factory=session_factory,
        registry=JobHandlerRegistry({JOB_TYPE_SCAN_PROJECTION_BUILD: FailingHandler()}),
        claimed_job=claimed,
        lease_seconds=30,
    )

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_build = db.get(ScanProjectionBuild, build_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_job.error_type == "lease_expired"
        assert persisted_build is not None and persisted_build.status == "failed"
        assert persisted_build.error_type == "lease_expired"
        assert "stale executor" not in (persisted_build.error_message or "")


@pytest.mark.asyncio
async def test_scan_terminalization_rolls_back_domain_and_followups_when_job_fails(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    claimed, job_id, scan_id = _claimed_scan_with_active_rule(session_factory)

    class FailingHandler:
        async def execute(self, _job, _context):
            raise RuntimeError("scan execution failed")

    def fail_before_commit(_db, **_kwargs):
        raise RuntimeError("terminal BackgroundJob persistence failed")

    monkeypatch.setattr(background_jobs, "fail_job", fail_before_commit)
    with pytest.raises(RuntimeError, match="terminal BackgroundJob persistence failed"):
        await run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry({JOB_TYPE_SCAN: FailingHandler()}),
            claimed_job=claimed,
            lease_seconds=30,
        )

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_scan = db.get(Scan, scan_id)
        assert persisted_job is not None and persisted_job.status == "running"
        assert persisted_scan is not None and persisted_scan.status == "running"
        assert persisted_scan.fatal_error_message is None
        assert db.query(ScanProjectionBuild).count() == 0
        assert db.query(PageCategoryRuleRun).count() == 0
        assert db.query(BackgroundJob).count() == 1


@pytest.mark.asyncio
async def test_scan_terminalization_commits_domain_job_and_followups_together(tmp_path) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    claimed, job_id, scan_id = _claimed_scan_with_active_rule(session_factory)

    class FailingHandler:
        async def execute(self, _job, _context):
            raise RuntimeError("scan execution failed")

    await run_claimed_job(
        session_factory=session_factory,
        registry=JobHandlerRegistry({JOB_TYPE_SCAN: FailingHandler()}),
        claimed_job=claimed,
        lease_seconds=30,
    )

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_scan = db.get(Scan, scan_id)
        projection_build = db.query(ScanProjectionBuild).one()
        category_run = db.query(PageCategoryRuleRun).one()
        assert persisted_job is not None and persisted_job.status == "failed"
        assert persisted_scan is not None and persisted_scan.status == "failed"
        assert persisted_scan.fatal_error_message == "scan execution failed"
        assert projection_build.status == "queued"
        assert category_run.status == "queued"
        followup_types = set(
            db.scalars(select(BackgroundJob.job_type).where(BackgroundJob.id != persisted_job.id))
        )
        assert followup_types == {
            JOB_TYPE_SCAN_PROJECTION_BUILD,
            JOB_TYPE_CATEGORY_RULE_EVALUATION,
        }


@pytest.mark.asyncio
async def test_user_cancellation_remains_distinct_from_lease_loss(tmp_path) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        scan = Scan(
            starting_url="https://cancel.example/",
            status="running",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add(scan)
        db.flush()
        job = background_jobs.enqueue_scan_job(db, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="cancel-worker", lease_seconds=30)
        assert claimed is not None
        background_jobs.request_cancellation(db, claimed.job)
        job_id, scan_id = job.id, scan.id

    class CancellationAwareHandler:
        async def execute(self, _job, context):
            context.raise_if_cancelled()
            return HandlerResult()

    await run_claimed_job(
        session_factory=session_factory,
        registry=JobHandlerRegistry({JOB_TYPE_SCAN: CancellationAwareHandler()}),
        claimed_job=claimed,
        lease_seconds=30,
    )

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_scan = db.get(Scan, scan_id)
        assert persisted_job is not None and persisted_job.status == "cancelled"
        assert persisted_scan is not None and persisted_scan.status == "cancelled"
        assert persisted_scan.stop_reason == "cancelled_by_user"


@pytest.mark.asyncio
async def test_worker_heartbeat_advances_off_loop_during_slow_blocking_work(
    tmp_path, monkeypatch
) -> None:
    session_factory = _initialized_session_factory(tmp_path)
    with session_factory() as db:
        background_jobs.register_worker(db, worker_id="worker-heartbeat", concurrency=1)
        worker_row = db.scalar(
            select(WorkerInstance).where(WorkerInstance.worker_id == "worker-heartbeat")
        )
        assert worker_row is not None
        original_seen_at = worker_row.last_seen_at

    heartbeat_threads: list[int] = []
    original_heartbeat = background_jobs.heartbeat_worker

    def tracked_heartbeat(db, worker_id) -> None:
        heartbeat_threads.append(threading.get_ident())
        original_heartbeat(db, worker_id)

    monkeypatch.setattr(background_jobs, "heartbeat_worker", tracked_heartbeat)
    worker = WorkerService(
        session_factory=session_factory,
        worker_id="worker-heartbeat",
        concurrency=1,
        poll_interval_seconds=1,
        heartbeat_seconds=0.05,
        lease_seconds=30,
        store=LocalContentStore(tmp_path / "worker-html"),
    )
    event_loop_thread = threading.get_ident()
    heartbeat_task = asyncio.create_task(worker._heartbeat_loop())
    await asyncio.to_thread(time.sleep, 0.18)
    heartbeat_task.cancel()
    await asyncio.gather(heartbeat_task, return_exceptions=True)

    with session_factory() as db:
        worker_row = db.scalar(
            select(WorkerInstance).where(WorkerInstance.worker_id == "worker-heartbeat")
        )
        assert worker_row is not None
        assert worker_row.last_seen_at > original_seen_at
    assert len(heartbeat_threads) >= 2
    assert all(thread_id != event_loop_thread for thread_id in heartbeat_threads)


@pytest.mark.asyncio
async def test_job_heartbeat_continues_after_transient_sqlite_lock(tmp_path, monkeypatch) -> None:
    context = JobExecutionContext(
        session_factory=_session_factory(tmp_path),
        job_id=10,
        lease_token="lease-token",
        lease_seconds=0.15,
    )
    calls = 0

    def delayed_heartbeat() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _locked_error()
        if calls == 3:
            raise background_jobs.StaleLeaseError("stop test loop")

    monkeypatch.setattr(context, "heartbeat", delayed_heartbeat)
    with pytest.raises(background_jobs.StaleLeaseError):
        await _job_heartbeat_loop(context)
    assert calls == 3


def _worker(tmp_path) -> WorkerService:
    return WorkerService(
        session_factory=_session_factory(tmp_path),
        worker_id="worker-test",
        concurrency=1,
        poll_interval_seconds=1,
        heartbeat_seconds=5,
        lease_seconds=30,
        store=LocalContentStore(tmp_path / "html"),
    )


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False}
    )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _initialized_session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker-integration.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _claimed_scan_with_active_rule(session_factory):
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name="Scan terminalization",
                base_url="https://scan-terminalization.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        category = PageCategory(
            website_property_id=site.id,
            name="Docs",
            normalized_name="docs",
            description=None,
            color_key="stone",
            sort_order=0,
            is_active=True,
        )
        db.add(category)
        db.flush()
        db.add(
            PageCategoryRule(
                website_property_id=site.id,
                category_id=category.id,
                name="Docs rule",
                description=None,
                match_mode="all",
                is_active=True,
                sort_order=0,
                current_revision_number=1,
            )
        )
        scan = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="running",
            scope_config=ScopeConfigPayload().model_dump(),
        )
        db.add(scan)
        db.flush()
        job = background_jobs.enqueue_scan_job(db, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="scan-terminalization", lease_seconds=30
        )
        assert claimed is not None
        return claimed, job.id, scan.id


def _force_recovery(session_factory, job_id: int) -> int:
    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with session_factory() as db:
        return background_jobs.recover_expired_jobs(db)


def _locked_error() -> OperationalError:
    return OperationalError(
        "UPDATE background_jobs", {}, sqlite3.OperationalError("database is locked")
    )
