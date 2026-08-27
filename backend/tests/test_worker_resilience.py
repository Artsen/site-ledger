import asyncio
import sqlite3
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base, is_transient_database_lock
from app.models import (
    BackgroundJob,
    Scan,
    ScanComparisonBuild,
    ScanProjectionBuild,
    WorkerInstance,
)
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services import background_jobs
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
    JOB_TYPE_SCAN,
    JOB_TYPE_SCAN_COMPARISON_BUILD,
    JOB_TYPE_SCAN_PROJECTION_BUILD,
)
from app.services.scan_comparisons import create_comparison, create_comparison_build
from app.services.scan_projections import create_projection_build
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


def _locked_error() -> OperationalError:
    return OperationalError(
        "UPDATE background_jobs", {}, sqlite3.OperationalError("database is locked")
    )
