import sqlite3
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import is_transient_database_lock
from app.services import background_jobs
from app.services.job_handlers import JobExecutionContext
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


def _locked_error() -> OperationalError:
    return OperationalError(
        "UPDATE background_jobs", {}, sqlite3.OperationalError("database is locked")
    )
