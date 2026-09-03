from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    BackgroundJob,
    Finding,
    FindingEvaluation,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services import background_jobs
from app.services.finding_deletion import (
    ActiveFindingEvaluationError,
    delete_finding,
    reset_site_findings,
)
from app.services.finding_evaluations import create_evaluation, execute_evaluation


def _factory(database: Path) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: Any, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed_completed_evaluation(factory: sessionmaker[Session]) -> tuple[int, int, str]:
    moment = datetime(2026, 9, 3, tzinfo=UTC)
    with factory() as db:
        site = WebsiteProperty(
            name="Finding serialization",
            base_url="https://serialization.test/",
            normalized_base_url="https://serialization.test/",
            group_key="Other",
            platform_key="Other",
            ownership_key="Unknown",
            scope_config={},
        )
        resource = WebResource(
            resource_type="page",
            normalized_url="https://serialization.test/page",
            scheme="https",
            host="serialization.test",
            path="/page",
            query="",
        )
        db.add_all([site, resource])
        db.flush()
        db.add(SitePage(website_property_id=site.id, resource_id=resource.id))
        _add_scan(db, site.id, resource.id, moment)
        db.commit()

        evaluation, created = create_evaluation(db, site.id)
        assert created
        job = background_jobs.enqueue_finding_evaluation_job(db, evaluation.id, site.id)
        execute_evaluation(db, evaluation.id)
        job.status = "completed"
        job.finished_at = moment
        db.commit()
        finding_id = db.scalar(select(Finding.id))
        assert finding_id is not None
        return site.id, finding_id, evaluation.input_fingerprint_sha256


def _add_scan(db: Session, site_id: int, resource_id: int, moment: datetime) -> Scan:
    scan = Scan(
        website_property_id=site_id,
        starting_url="https://serialization.test/",
        status="completed",
        scope_config={},
        created_at=moment,
        finished_at=moment,
    )
    db.add(scan)
    db.flush()
    db.add(
        ResourceSnapshot(
            scan_id=scan.id,
            resource_id=resource_id,
            requested_url="https://serialization.test/page",
            final_url="https://serialization.test/page",
            http_status=404,
            crawl_depth=0,
            fetched_at=moment,
            fetch_state="fetched",
            page_title="Missing",
            parsed_head_json={"links": []},
            representation_kind="html_page",
        )
    )
    return scan


def _start_contender(
    engine: Engine,
    action: Callable[[], None],
) -> tuple[threading.Thread, threading.Event, threading.Event, dict[str, BaseException]]:
    attempted = threading.Event()
    finished = threading.Event()
    errors: dict[str, BaseException] = {}

    def before_cursor_execute(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if threading.current_thread().name == "finding-contender" and statement.upper().startswith(
            "BEGIN IMMEDIATE"
        ):
            attempted.set()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)

    def run() -> None:
        try:
            action()
        except BaseException as exc:  # surfaced in the owning test thread
            errors["error"] = exc
        finally:
            finished.set()
            event.remove(engine, "before_cursor_execute", before_cursor_execute)

    thread = threading.Thread(target=run, name="finding-contender")
    thread.start()
    return thread, attempted, finished, errors


@pytest.mark.parametrize("operation", ["reset", "delete"])
def test_evaluation_creation_serializes_before_destructive_check(
    tmp_path: Path, operation: str
) -> None:
    engine, factory = _factory(tmp_path / f"evaluation-first-{operation}.db")
    site_id, finding_id, _fingerprint = _seed_completed_evaluation(factory)
    with factory() as setup:
        resource_id = setup.scalar(select(SitePage.resource_id))
        assert resource_id is not None
        next_scan_at = datetime(2026, 9, 3, tzinfo=UTC) + timedelta(hours=1)
        _add_scan(setup, site_id, resource_id, next_scan_at)
        setup.commit()

    outcome: dict[str, object] = {}
    with factory() as creator:
        evaluation, created = create_evaluation(creator, site_id)
        assert created
        background_jobs.enqueue_finding_evaluation_job(creator, evaluation.id, site_id)

        def destructive_action() -> None:
            with factory() as contender:
                try:
                    outcome["result"] = (
                        reset_site_findings(contender, site_id)
                        if operation == "reset"
                        else delete_finding(contender, site_id, finding_id)
                    )
                    contender.commit()
                except ActiveFindingEvaluationError:
                    contender.rollback()
                    outcome["conflict"] = True

        thread, attempted, finished, errors = _start_contender(engine, destructive_action)
        assert attempted.wait(timeout=2), "contender did not reach the SQLite write boundary"
        assert not finished.is_set(), "destructive check bypassed the held SQLite write transaction"
        creator.commit()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == {}
    assert outcome == {"conflict": True}
    with factory() as verification:
        assert verification.get(Finding, finding_id) is not None
        assert verification.scalar(select(func.count(FindingEvaluation.id))) == 2
        assert verification.scalar(select(func.count(BackgroundJob.id))) == 2
    engine.dispose()


def test_reset_serializes_before_new_evaluation_creation(tmp_path: Path) -> None:
    engine, factory = _factory(tmp_path / "reset-first.db")
    site_id, finding_id, fingerprint = _seed_completed_evaluation(factory)
    outcome: dict[str, object] = {}

    with factory() as resetter:
        result = reset_site_findings(resetter, site_id)
        assert result is not None
        assert result.deleted_finding_count > 0
        assert result.deleted_evaluation_count == 1
        assert result.deleted_job_count == 1

        def evaluation_action() -> None:
            with factory() as contender:
                evaluation, created = create_evaluation(contender, site_id)
                assert created
                background_jobs.enqueue_finding_evaluation_job(contender, evaluation.id, site_id)
                contender.commit()
                outcome["fingerprint"] = evaluation.input_fingerprint_sha256

        thread, attempted, finished, errors = _start_contender(engine, evaluation_action)
        assert attempted.wait(timeout=2), "contender did not reach the SQLite write boundary"
        assert not finished.is_set(), (
            "evaluation creation bypassed the held SQLite reset transaction"
        )
        resetter.commit()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == {}
    assert outcome == {"fingerprint": fingerprint}
    with factory() as verification:
        assert verification.get(Finding, finding_id) is None
        evaluations = list(verification.scalars(select(FindingEvaluation)))
        jobs = list(verification.scalars(select(BackgroundJob)))
        assert len(evaluations) == 1
        assert evaluations[0].status == "queued"
        assert len(jobs) == 1
        assert jobs[0].status == "queued"
    engine.dispose()
