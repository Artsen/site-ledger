from __future__ import annotations

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import create_app
from app.models import (
    AccessibilityRun,
    BackgroundJob,
    CollectionPlan,
    CollectionPlanBatch,
    CollectionPlanTarget,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.collection_plans import CollectionPlanRequest
from app.services.collection_plan_serialization import lock_site_for_collection_plan_change
from app.services.collection_plans import create_collection_plan
from app.services.url_identity import ensure_url_identity_state


def _factory(
    database: Path, *, busy_timeout_ms: int = 5_000
) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: Any, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        ensure_url_identity_state(db)
        db.commit()
    return engine, factory


def _seed_site(factory: sessionmaker[Session], page_count: int = 3) -> int:
    with factory() as db:
        site = WebsiteProperty(
            name="Collection Plan serialization",
            base_url="https://serialization.test/",
            normalized_base_url="https://serialization.test/",
            group_key="Other",
            platform_key="Other",
            ownership_key="Unknown",
            scope_config={},
        )
        db.add(site)
        db.flush()
        resources = [
            WebResource(
                resource_type="page",
                normalized_url=f"https://serialization.test/{position}",
                scheme="https",
                host="serialization.test",
                path=f"/{position}",
                query="",
            )
            for position in range(page_count)
        ]
        db.add_all(resources)
        db.flush()
        db.add_all(
            [SitePage(website_property_id=site.id, resource_id=item.id) for item in resources]
        )
        db.commit()
        return site.id


def _request(mode: str) -> CollectionPlanRequest:
    return CollectionPlanRequest(
        evidence_domain="accessibility",
        target_mode=mode,  # type: ignore[arg-type]
        context={"profile": "desktop"},
    )


@pytest.mark.parametrize(
    ("first_mode", "second_mode"),
    [
        pytest.param("refresh_current", "refresh_current", id="refresh-vs-refresh"),
        pytest.param("missing_current", "refresh_current", id="missing-vs-refresh"),
        pytest.param("refresh_current", "missing_current", id="refresh-vs-missing"),
    ],
)
def test_concurrent_plan_creation_serializes_before_selection(
    tmp_path: Path, first_mode: str, second_mode: str
) -> None:
    engine, factory = _factory(tmp_path / f"{first_mode}-{second_mode}.db")
    site_id = _seed_site(factory)
    first_staged = threading.Event()
    release_first = threading.Event()
    second_attempted_lock = threading.Event()
    second_finished = threading.Event()
    outcomes: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def observe_begin_immediate(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if (
            threading.current_thread().name == "collection-plan-second"
            and statement.upper().startswith("BEGIN IMMEDIATE")
        ):
            second_attempted_lock.set()

    event.listen(engine, "before_cursor_execute", observe_begin_immediate)

    def run_first() -> None:
        try:
            with factory() as db:

                @event.listens_for(db, "before_commit", once=True)
                def pause_before_commit(_session: Session) -> None:
                    first_staged.set()
                    if not release_first.wait(timeout=5):
                        raise TimeoutError("test did not release the first Plan transaction")

                outcomes["first"] = create_collection_plan(db, site_id, _request(first_mode)).id
        except BaseException as exc:  # surfaced in the owning test thread
            errors["first"] = exc

    def run_second() -> None:
        try:
            with factory() as db:
                try:
                    outcomes["second"] = create_collection_plan(
                        db, site_id, _request(second_mode)
                    ).id
                except ValueError as exc:
                    db.rollback()
                    outcomes["second_error"] = str(exc)
        except BaseException as exc:  # surfaced in the owning test thread
            errors["second"] = exc
        finally:
            second_finished.set()

    first = threading.Thread(target=run_first, name="collection-plan-first")
    second = threading.Thread(target=run_second, name="collection-plan-second")
    first.start()
    if not first_staged.wait(timeout=5):
        release_first.set()
        first.join(timeout=5)
        pytest.fail(f"first Plan did not stage work before commit; errors={errors!r}")
    second.start()
    assert second_attempted_lock.wait(timeout=2), "second Plan did not request write intent"
    assert not second_finished.is_set(), "second Plan selected while the first transaction was open"
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)
    event.remove(engine, "before_cursor_execute", observe_begin_immediate)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == {}
    assert "first" in outcomes
    assert "second" not in outcomes
    assert outcomes["second_error"] in {
        "No refreshable targets remain for this context.",
        "No missing current evidence remains for this context.",
        f"Equivalent Collection Plan {outcomes['first']} is already active.",
    }
    with factory() as db:
        assert db.scalar(select(func.count(CollectionPlan.id))) == 1
        assert db.scalar(select(func.count(CollectionPlanTarget.id))) == 3
        assert db.scalar(select(func.count(CollectionPlanBatch.id))) == 1
        assert db.scalar(select(func.count(AccessibilityRun.id))) == 1
        assert db.scalar(select(func.count(BackgroundJob.id))) == 1
    engine.dispose()


def test_plan_creation_lock_timeout_returns_conflict_without_partial_work(tmp_path: Path) -> None:
    engine, factory = _factory(tmp_path / "timeout.db", busy_timeout_ms=25)
    site_id = _seed_site(factory)
    app = create_app(session_factory=factory)

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with factory() as holder:
        holder.connection().exec_driver_sql("BEGIN IMMEDIATE")
        response = TestClient(app).post(
            f"/api/sites/{site_id}/collection-plans",
            json={
                "evidence_domain": "accessibility",
                "target_mode": "refresh_current",
                "context": {"profile": "desktop"},
            },
        )
        holder.rollback()

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Collection Plan state is being updated by another request. Try again."
    }
    with factory() as db:
        for model in (
            CollectionPlan,
            CollectionPlanTarget,
            CollectionPlanBatch,
            AccessibilityRun,
            BackgroundJob,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    engine.dispose()


def test_non_sqlite_serialization_requests_a_site_row_lock() -> None:
    db = Mock(spec=Session)
    connection = Mock()
    connection.dialect.name = "postgresql"
    db.connection.return_value = connection
    site = WebsiteProperty(id=7)
    db.scalar.return_value = site

    assert lock_site_for_collection_plan_change(db, 7) is site

    statement = db.scalar.call_args.args[0]
    assert statement._for_update_arg is not None
