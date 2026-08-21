import threading
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityPayloadBlob,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    BackgroundJob,
    JobEvent,
    PerformanceObservation,
    PerformancePayloadBlob,
    PerformanceRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.accessibility_deletion import (
    delete_accessibility_observation,
    delete_accessibility_run,
    purge_accessibility_site,
)
from app.services.accessibility_queries import (
    accessibility_rules,
    accessibility_summary,
    get_accessibility_run,
    page_latest_accessibility,
)
from app.services.observability_payload_gc import (
    collect_accessibility_payload_gc,
    collect_performance_payload_gc,
)
from app.services.performance_deletion import (
    delete_performance_observation,
    delete_performance_run,
    preview_performance_observation_deletion,
    purge_performance_site,
)
from app.services.performance_queries import get_performance_run, page_latest_performance
from app.services.site_management import delete_site
from app.storage.accessibility_store import LocalAccessibilityPayloadStore
from app.storage.observability_payloads import store_payload
from app.storage.performance_store import LocalPerformancePayloadStore


def test_performance_shared_payload_survives_until_final_observation(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    runs = [_performance_run(site.id) for _ in range(2)]
    db_session.add_all(runs)
    db_session.flush()
    store = LocalPerformancePayloadStore(tmp_path / "performance")
    blob = store.put(db_session, b'{"shared":true}')
    observations = [
        _performance_observation(run.id, site.id, resource.id, blob.id, str(index))
        for index, run in enumerate(runs)
    ]
    db_session.add_all(observations)
    db_session.commit()
    payload_path = store._path(blob.storage_key)

    first = delete_performance_observation(db_session, site.id, observations[0].id, store)

    assert first is not None and first.payload_blob_records_deleted == 0
    assert db_session.get(PerformancePayloadBlob, blob.id) is not None
    assert payload_path.is_file()

    second = delete_performance_observation(db_session, site.id, observations[1].id, store)

    assert second is not None and second.payload_blob_records_deleted == 1
    assert second.payload_blob_files_deleted == 1
    assert db_session.get(PerformancePayloadBlob, blob.id) is None
    assert not payload_path.exists()


def test_accessibility_shared_payload_and_normalized_evidence_lifecycle(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    runs = [_accessibility_run(site.id) for _ in range(2)]
    db_session.add_all(runs)
    db_session.flush()
    store = LocalAccessibilityPayloadStore(tmp_path / "accessibility")
    blob = store.put(db_session, b'{"shared":true}')
    observations = [
        _accessibility_observation(run.id, site.id, resource.id, blob.id) for run in runs
    ]
    db_session.add_all(observations)
    db_session.flush()
    rule = AccessibilityRuleEvidence(
        accessibility_observation_id=observations[0].id,
        position=0,
        rule_id="image-alt",
        result_type="violation",
        impact="critical",
        description="Synthetic rule",
        help="Add alternate text",
        help_url="https://example.test/rule",
        tags_json=["wcag2a"],
        node_count=1,
        rule_evidence_sha256="a" * 64,
    )
    db_session.add(rule)
    db_session.flush()
    node = AccessibilityNodeEvidence(
        accessibility_rule_evidence_id=rule.id,
        position=0,
        impact="critical",
        target_json=["img"],
        html_snippet="<img>",
        html_original_length=5,
        html_truncated=False,
        failure_summary="Missing alternate text",
        node_evidence_sha256="b" * 64,
    )
    db_session.add(node)
    db_session.commit()
    payload_path = store._path(blob.storage_key)

    first = delete_accessibility_observation(db_session, site.id, observations[0].id, store)

    assert first is not None
    assert first.rule_rows_deleted == 1
    assert first.node_rows_deleted == 1
    assert db_session.scalar(select(func.count()).select_from(AccessibilityRuleEvidence)) == 0
    assert db_session.scalar(select(func.count()).select_from(AccessibilityNodeEvidence)) == 0
    assert db_session.get(AccessibilityPayloadBlob, blob.id) is not None
    assert payload_path.is_file()

    second = delete_accessibility_observation(db_session, site.id, observations[1].id, store)

    assert second is not None and second.payload_blob_records_deleted == 1
    assert second.payload_blob_files_deleted == 1
    assert db_session.get(AccessibilityPayloadBlob, blob.id) is None
    assert not payload_path.exists()


def test_run_deletion_preserves_collection_history_until_run_is_removed(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    performance_run = _performance_run(site.id)
    accessibility_run = _accessibility_run(site.id)
    db_session.add_all([performance_run, accessibility_run])
    db_session.flush()
    performance_observation = _performance_observation(
        performance_run.id, site.id, resource.id, 0, "history"
    )
    performance_observation.payload_blob_id = None
    accessibility_observation = _accessibility_observation(
        accessibility_run.id, site.id, resource.id, 0
    )
    accessibility_observation.payload_blob_id = None
    db_session.add_all([performance_observation, accessibility_observation])
    db_session.commit()

    delete_performance_observation(
        db_session,
        site.id,
        performance_observation.id,
        LocalPerformancePayloadStore(tmp_path / "performance"),
    )
    performance_read = get_performance_run(
        db_session, site.id, performance_run.id, limit=10, offset=0
    )
    assert performance_read is not None
    assert performance_read.completed_count == 1
    assert performance_read.retained_observation_count == 0
    assert performance_read.deleted_observation_count == 1
    assert performance_read.deleted_ready_count == 1

    delete_accessibility_observation(
        db_session,
        site.id,
        accessibility_observation.id,
        LocalAccessibilityPayloadStore(tmp_path / "accessibility"),
    )
    accessibility_read = get_accessibility_run(
        db_session, site.id, accessibility_run.id, limit=10, offset=0
    )
    assert accessibility_read is not None
    assert accessibility_read.completed_count == 1
    assert accessibility_read.retained_observation_count == 0
    assert accessibility_read.deleted_observation_count == 1
    assert accessibility_read.deleted_ready_count == 1

    performance_deleted = delete_performance_run(
        db_session,
        site.id,
        performance_run.id,
        f"DELETE PERFORMANCE RUN {performance_run.id}",
        LocalPerformancePayloadStore(tmp_path / "performance"),
    )
    accessibility_deleted = delete_accessibility_run(
        db_session,
        site.id,
        accessibility_run.id,
        f"DELETE ACCESSIBILITY RUN {accessibility_run.id}",
        LocalAccessibilityPayloadStore(tmp_path / "accessibility"),
    )
    assert performance_deleted is not None
    assert accessibility_deleted is not None
    assert db_session.get(PerformanceRun, performance_run.id) is None
    assert db_session.get(AccessibilityRun, accessibility_run.id) is None


def test_domain_active_job_guard_isolated_and_site_ownership_enforced(
    db_session: Session, tmp_path: Path
) -> None:
    site_a, resource = _site_page(db_session, "a")
    site_b, _other = _site_page(db_session, "b")
    performance_run = _performance_run(site_a.id)
    accessibility_run = _accessibility_run(site_a.id)
    db_session.add_all([performance_run, accessibility_run])
    db_session.flush()
    observation = _performance_observation(performance_run.id, site_a.id, resource.id, 0, "guard")
    observation.payload_blob_id = None
    db_session.add(observation)
    db_session.flush()
    accessibility_job = _job(
        "accessibility_run", accessibility_run_id=accessibility_run.id, site_id=site_a.id
    )
    db_session.add(accessibility_job)
    db_session.commit()

    allowed = preview_performance_observation_deletion(db_session, site_a.id, observation.id)
    assert allowed is not None and allowed.can_delete
    assert preview_performance_observation_deletion(db_session, site_b.id, observation.id) is None
    assert (
        delete_performance_observation(
            db_session,
            site_b.id,
            observation.id,
            LocalPerformancePayloadStore(tmp_path / "performance"),
        )
        is None
    )
    assert db_session.get(PerformanceObservation, observation.id) is not None

    accessibility_job.status = "completed"
    performance_job = _job(
        "performance_run", performance_run_id=performance_run.id, site_id=site_a.id
    )
    db_session.add(performance_job)
    db_session.commit()
    blocked = preview_performance_observation_deletion(db_session, site_a.id, observation.id)
    assert blocked is not None and not blocked.can_delete


def test_latest_falls_back_after_newest_observation_is_deleted(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    performance_runs = [_performance_run(site.id) for _ in range(2)]
    accessibility_runs = [_accessibility_run(site.id) for _ in range(2)]
    db_session.add_all([*performance_runs, *accessibility_runs])
    db_session.flush()
    old_performance = _performance_observation(
        performance_runs[0].id, site.id, resource.id, 0, "old"
    )
    new_performance = _performance_observation(
        performance_runs[1].id, site.id, resource.id, 0, "new"
    )
    old_accessibility = _accessibility_observation(
        accessibility_runs[0].id, site.id, resource.id, 0
    )
    new_accessibility = _accessibility_observation(
        accessibility_runs[1].id, site.id, resource.id, 0
    )
    for observation in (
        old_performance,
        new_performance,
        old_accessibility,
        new_accessibility,
    ):
        observation.payload_blob_id = None
    old_performance.observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    new_performance.observed_at = datetime(2026, 1, 2, tzinfo=UTC)
    old_accessibility.observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    new_accessibility.observed_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.add_all([old_performance, new_performance, old_accessibility, new_accessibility])
    db_session.commit()

    delete_performance_observation(
        db_session,
        site.id,
        new_performance.id,
        LocalPerformancePayloadStore(tmp_path / "performance"),
    )
    delete_accessibility_observation(
        db_session,
        site.id,
        new_accessibility.id,
        LocalAccessibilityPayloadStore(tmp_path / "accessibility"),
    )

    assert (
        page_latest_performance(db_session, site.id, resource.id).items[0].id == old_performance.id
    )
    assert (
        page_latest_accessibility(db_session, site.id, resource.id).items[0].id
        == old_accessibility.id
    )


def test_site_domain_purge_isolated_and_full_site_delete_cleans_payloads(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    performance_run = _performance_run(site.id)
    accessibility_run = _accessibility_run(site.id)
    db_session.add_all([performance_run, accessibility_run])
    db_session.flush()
    performance_store = LocalPerformancePayloadStore(tmp_path / "performance")
    accessibility_store = LocalAccessibilityPayloadStore(tmp_path / "accessibility")
    performance_blob = performance_store.put(db_session, b'{"performance":true}')
    accessibility_blob = accessibility_store.put(db_session, b'{"accessibility":true}')
    performance_observation = _performance_observation(
        performance_run.id, site.id, resource.id, performance_blob.id, "purge"
    )
    accessibility_observation = _accessibility_observation(
        accessibility_run.id, site.id, resource.id, accessibility_blob.id
    )
    db_session.add_all([performance_observation, accessibility_observation])
    db_session.commit()

    result = purge_performance_site(db_session, site.id, "DELETE PERFORMANCE", performance_store)
    assert result is not None and result.observations_deleted == 1
    assert db_session.get(WebsiteProperty, site.id) is not None
    assert db_session.get(WebResource, resource.id) is not None
    assert db_session.get(AccessibilityObservation, accessibility_observation.id) is not None

    deleted = delete_site(db_session, site.id, performance_store, accessibility_store)
    assert deleted == site.id
    assert db_session.get(AccessibilityPayloadBlob, accessibility_blob.id) is None
    assert not accessibility_store._path(accessibility_blob.storage_key).exists()


def test_gc_dry_run_and_apply_respect_layout_and_references(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    run = _performance_run(site.id)
    db_session.add(run)
    db_session.flush()
    store = LocalPerformancePayloadStore(tmp_path / "performance")
    referenced = store.put(db_session, b'{"referenced":true}')
    unreferenced = store.put(db_session, b'{"unreferenced":true}')
    observation = _performance_observation(run.id, site.id, resource.id, referenced.id, "gc")
    db_session.add(observation)
    db_session.commit()
    orphan = store_payload(store.root, b'{"orphan":true}', temporary_prefix=".test-")
    unexpected = store.root / "unexpected.txt"
    unexpected.write_text("retain", encoding="utf-8")

    dry_run = collect_performance_payload_gc(db_session, store)
    assert dry_run.unreferenced_blob_records == 1
    assert dry_run.orphan_physical_files == [orphan.storage_key]
    assert dry_run.unexpected_files == ["unexpected.txt"]
    assert db_session.get(PerformancePayloadBlob, unreferenced.id) is not None

    applied = collect_performance_payload_gc(db_session, store, apply=True)
    assert applied.deleted_blob_records == 1
    assert applied.deleted_physical_files == 2
    assert db_session.get(PerformancePayloadBlob, referenced.id) is not None
    assert db_session.get(PerformancePayloadBlob, unreferenced.id) is None
    assert unexpected.is_file()


def test_file_cleanup_failure_does_not_restore_deleted_evidence(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, resource = _site_page(db_session)
    run = _performance_run(site.id)
    db_session.add(run)
    db_session.flush()
    store = LocalPerformancePayloadStore(tmp_path / "performance")
    blob = store.put(db_session, b'{"cleanup":"fails"}')
    observation = _performance_observation(run.id, site.id, resource.id, blob.id, "cleanup")
    db_session.add(observation)
    db_session.commit()

    def fail_delete(_blob: PerformancePayloadBlob) -> bool:
        raise OSError("synthetic disk error")

    monkeypatch.setattr(store, "delete", fail_delete)
    result = delete_performance_observation(db_session, site.id, observation.id, store)

    assert result is not None and result.warnings
    assert "synthetic disk error" in result.warnings[0]
    assert db_session.get(PerformanceObservation, observation.id) is None
    assert db_session.get(PerformancePayloadBlob, blob.id) is None


def test_gc_blocks_active_domain_job_and_store_rejects_unsafe_key(
    db_session: Session, tmp_path: Path
) -> None:
    site, _resource = _site_page(db_session)
    run = _performance_run(site.id)
    db_session.add(run)
    db_session.flush()
    db_session.add(_job("performance_run", performance_run_id=run.id, site_id=site.id))
    db_session.commit()
    store = LocalPerformancePayloadStore(tmp_path / "performance")

    with pytest.raises(RuntimeError, match="blocked"):
        collect_performance_payload_gc(db_session, store)
    unsafe = PerformancePayloadBlob(
        sha256="f" * 64,
        storage_key="../../outside.json.gz",
        raw_byte_size=1,
        stored_byte_size=1,
    )
    with pytest.raises(ValueError, match="Unsafe"):
        store.delete(unsafe)


def test_deletion_routes_enforce_site_scope_and_backend_confirmation(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    performance_run = _performance_run(site.id)
    accessibility_run = _accessibility_run(site.id)
    db_session.add_all([performance_run, accessibility_run])
    db_session.flush()
    performance_observation = _performance_observation(
        performance_run.id, site.id, resource.id, 0, "route"
    )
    performance_observation.payload_blob_id = None
    accessibility_observation = _accessibility_observation(
        accessibility_run.id, site.id, resource.id, 0
    )
    accessibility_observation.payload_blob_id = None
    db_session.add_all([performance_observation, accessibility_observation])
    db_session.commit()
    app = FastAPI()
    from app.api.accessibility_routes import router as accessibility_router
    from app.api.performance_routes import router as performance_router

    app.include_router(performance_router)
    app.include_router(accessibility_router)
    app.state.performance_payload_store = LocalPerformancePayloadStore(tmp_path / "performance")
    app.state.accessibility_payload_store = LocalAccessibilityPayloadStore(
        tmp_path / "accessibility"
    )

    def override_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        assert (
            client.get(
                f"/api/sites/{site.id}/performance-observations/"
                f"{performance_observation.id}/deletion-preview"
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/sites/{site.id + 100}/performance-observations/{performance_observation.id}"
            ).status_code
            == 404
        )
        wrong = client.request(
            "DELETE",
            f"/api/sites/{site.id}/performance-runs/{performance_run.id}",
            json={"confirmation": "DELETE"},
        )
        assert wrong.status_code == 422
        deleted = client.request(
            "DELETE",
            f"/api/sites/{site.id}/accessibility-runs/{accessibility_run.id}",
            json={"confirmation": f"DELETE ACCESSIBILITY RUN {accessibility_run.id}"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted_run_id"] == accessibility_run.id


def test_concurrent_performance_payload_put_reconciles_winner(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "performance-race.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = LocalPerformancePayloadStore(tmp_path / "performance-race")
    barrier = threading.Barrier(2)
    errors: list[Exception] = []
    ids: list[int] = []
    original = store_payload

    def synchronized_store(root: Path, content: bytes, *, temporary_prefix: str):
        result = original(root, content, temporary_prefix=temporary_prefix)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr("app.storage.performance_store.store_payload", synchronized_store)

    def put() -> None:
        try:
            with factory() as db:
                blob = store.put(db, b'{"race":true}')
                db.commit()
                ids.append(blob.id)
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=put) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert errors == []
    assert len(ids) == 2 and ids[0] == ids[1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PerformancePayloadBlob)) == 1
        blob = db.scalar(select(PerformancePayloadBlob))
        assert blob is not None and store.read(blob) == b'{"race":true}'
    assert list(store.root.rglob(".performance-*")) == []


def test_concurrent_accessibility_payload_put_reconciles_winner(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "accessibility-race.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = LocalAccessibilityPayloadStore(tmp_path / "accessibility-race")
    barrier = threading.Barrier(2)
    errors: list[Exception] = []
    ids: list[int] = []
    original = store_payload

    def synchronized_store(root: Path, content: bytes, *, temporary_prefix: str):
        result = original(root, content, temporary_prefix=temporary_prefix)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr("app.storage.accessibility_store.store_payload", synchronized_store)

    def put() -> None:
        try:
            with factory() as db:
                blob = store.put(db, b'{"race":true}')
                db.commit()
                ids.append(blob.id)
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=put) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert errors == []
    assert len(ids) == 2 and ids[0] == ids[1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AccessibilityPayloadBlob)) == 1
        blob = db.scalar(select(AccessibilityPayloadBlob))
        assert blob is not None and store.read(blob) == b'{"race":true}'
    assert list(store.root.rglob(".accessibility-*")) == []


def test_accessibility_purge_isolated_and_aggregates_refresh(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    performance_run = _performance_run(site.id)
    accessibility_run = _accessibility_run(site.id)
    db_session.add_all([performance_run, accessibility_run])
    db_session.flush()
    performance_observation = _performance_observation(
        performance_run.id, site.id, resource.id, 0, "inverse"
    )
    performance_observation.payload_blob_id = None
    accessibility_observation = _accessibility_observation(
        accessibility_run.id, site.id, resource.id, 0
    )
    accessibility_observation.payload_blob_id = None
    accessibility_observation.violation_rule_count = 1
    accessibility_observation.violation_node_count = 1
    db_session.add_all([performance_observation, accessibility_observation])
    db_session.flush()
    db_session.add(
        AccessibilityRuleEvidence(
            accessibility_observation_id=accessibility_observation.id,
            position=0,
            rule_id="image-alt",
            result_type="violation",
            impact="critical",
            description="Synthetic rule",
            help="Add alternate text",
            tags_json=["wcag2a"],
            node_count=1,
            rule_evidence_sha256="e" * 64,
        )
    )
    db_session.commit()
    assert accessibility_summary(db_session, site.id).violation_rules == 1
    assert (
        accessibility_rules(
            db_session, site.id, result_type=None, impact=None, profile=None, limit=10, offset=0
        ).total
        == 1
    )

    result = purge_accessibility_site(
        db_session,
        site.id,
        "DELETE ACCESSIBILITY",
        LocalAccessibilityPayloadStore(tmp_path / "accessibility"),
    )

    assert result is not None and result.observations_deleted == 1
    assert db_session.get(PerformanceObservation, performance_observation.id) is not None
    assert db_session.get(WebResource, resource.id) is not None
    assert accessibility_summary(db_session, site.id).pages_audited == 0
    assert (
        accessibility_rules(
            db_session, site.id, result_type=None, impact=None, profile=None, limit=10, offset=0
        ).total
        == 0
    )


def test_run_delete_removes_terminal_job_events_and_active_states_block(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    run = _performance_run(site.id)
    db_session.add(run)
    db_session.flush()
    observation = _performance_observation(run.id, site.id, resource.id, 0, "job")
    observation.payload_blob_id = None
    job = _job("performance_run", performance_run_id=run.id, site_id=site.id)
    db_session.add_all([observation, job])
    db_session.flush()
    event = JobEvent(job_id=job.id, event_type="completed", message="Synthetic", data_json={})
    db_session.add(event)
    db_session.commit()

    for status in ("queued", "running"):
        job.status = status
        job.cancellation_requested_at = None
        db_session.commit()
        preview = preview_performance_observation_deletion(db_session, site.id, observation.id)
        assert preview is not None and not preview.can_delete
    job.status = "running"
    job.cancellation_requested_at = datetime.now(UTC)
    db_session.commit()
    preview = preview_performance_observation_deletion(db_session, site.id, observation.id)
    assert preview is not None and not preview.can_delete

    job.status = "completed"
    job.cancellation_requested_at = None
    db_session.commit()
    result = delete_performance_run(
        db_session,
        site.id,
        run.id,
        f"DELETE PERFORMANCE RUN {run.id}",
        LocalPerformancePayloadStore(tmp_path / "performance"),
    )
    assert result is not None
    assert result.background_jobs_deleted == 1
    assert result.job_events_deleted == 1
    assert db_session.get(JobEvent, event.id) is None


def test_site_delete_preserves_blob_shared_by_another_site(
    db_session: Session, tmp_path: Path
) -> None:
    site_a, resource_a = _site_page(db_session, "shared-a")
    site_b, resource_b = _site_page(db_session, "shared-b")
    runs = [_performance_run(site_a.id), _performance_run(site_b.id)]
    db_session.add_all(runs)
    db_session.flush()
    store = LocalPerformancePayloadStore(tmp_path / "performance")
    blob = store.put(db_session, b'{"shared-across-sites":true}')
    observations = [
        _performance_observation(runs[0].id, site_a.id, resource_a.id, blob.id, "site-a"),
        _performance_observation(runs[1].id, site_b.id, resource_b.id, blob.id, "site-b"),
    ]
    db_session.add_all(observations)
    db_session.commit()

    assert delete_site(db_session, site_a.id, store, None) == site_a.id
    assert db_session.get(PerformancePayloadBlob, blob.id) is not None
    assert store._path(blob.storage_key).is_file()
    assert db_session.get(PerformanceObservation, observations[1].id) is not None


def test_gc_reports_missing_accessibility_payload_without_deleting_reference(
    db_session: Session, tmp_path: Path
) -> None:
    site, resource = _site_page(db_session)
    run = _accessibility_run(site.id)
    db_session.add(run)
    db_session.flush()
    store = LocalAccessibilityPayloadStore(tmp_path / "accessibility")
    blob = store.put(db_session, b'{"missing":true}')
    observation = _accessibility_observation(run.id, site.id, resource.id, blob.id)
    db_session.add(observation)
    db_session.commit()
    store._path(blob.storage_key).unlink()

    report = collect_accessibility_payload_gc(db_session, store, apply=True)

    assert report.referenced_files_missing == [blob.storage_key]
    assert report.deleted_blob_records == 0
    assert db_session.get(AccessibilityPayloadBlob, blob.id) is not None


def test_full_site_delete_reports_payload_file_cleanup_warning(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, resource = _site_page(db_session)
    run = _performance_run(site.id)
    db_session.add(run)
    db_session.flush()
    store = LocalPerformancePayloadStore(tmp_path / "performance")
    blob = store.put(db_session, b'{"site-cleanup":"warning"}')
    db_session.add(_performance_observation(run.id, site.id, resource.id, blob.id, "site"))
    db_session.commit()
    monkeypatch.setattr(store, "delete", lambda _blob: (_ for _ in ()).throw(OSError("locked")))
    warnings: list[str] = []

    assert delete_site(db_session, site.id, store, None, warnings) == site.id
    assert warnings and "locked" in warnings[0]
    assert db_session.get(WebsiteProperty, site.id) is None


def _site_page(db: Session, suffix: str = "") -> tuple[WebsiteProperty, WebResource]:
    host = f"{suffix}.example.test" if suffix else "example.test"
    site = WebsiteProperty(
        name="Synthetic Site",
        base_url=f"https://{host}/",
        normalized_base_url=f"https://{host}/",
        description=None,
        group_key="test",
        locale=None,
        platform_key="test",
        ownership_key="test",
        display_timezone=None,
        scope_config={},
        is_active=True,
    )
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://{host}/page",
        scheme="https",
        host=host,
        path="/page",
        query="",
    )
    db.add_all([site, resource])
    db.flush()
    db.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    db.commit()
    return site, resource


def _performance_run(site_id: int) -> PerformanceRun:
    return PerformanceRun(
        website_property_id=site_id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=1,
        request_count=1,
        completed_count=1,
        ready_count=1,
        unavailable_count=0,
        failed_count=0,
        finished_at=datetime.now(UTC),
    )


def _performance_observation(
    run_id: int, site_id: int, resource_id: int, blob_id: int, suffix: str
) -> PerformanceObservation:
    return PerformanceObservation(
        performance_run_id=run_id,
        website_property_id=site_id,
        web_resource_id=resource_id,
        payload_blob_id=blob_id,
        provider="pagespeed",
        provider_adapter_version="pagespeed-provider-v1",
        normalization_version="performance-normalization-v1",
        target_kind="url",
        target_key=suffix.zfill(64),
        requested_target="https://example.test/page",
        dimension="mobile",
        outcome="ready",
        request_descriptor_json={},
        metrics_json={},
    )


def _accessibility_run(site_id: int) -> AccessibilityRun:
    return AccessibilityRun(
        website_property_id=site_id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=1,
        observation_count=1,
        completed_count=1,
        ready_count=1,
        failed_count=0,
        axe_core_version="4.12.1",
        detector_bundle_sha256="c" * 64,
        integration_version="accessibility-engine-v1",
        normalization_version="accessibility-normalization-v1",
        ruleset_profile="wcag22-aa-v1",
        ruleset_rule_count=62,
        ruleset_sha256="d" * 64,
        finished_at=datetime.now(UTC),
    )


def _accessibility_observation(
    run_id: int, site_id: int, resource_id: int, blob_id: int
) -> AccessibilityObservation:
    return AccessibilityObservation(
        accessibility_run_id=run_id,
        website_property_id=site_id,
        web_resource_id=resource_id,
        payload_blob_id=blob_id,
        requested_url="https://example.test/page",
        profile="desktop",
        outcome="ready",
        axe_core_version="4.12.1",
        detector_bundle_sha256="c" * 64,
        integration_version="accessibility-engine-v1",
        normalization_version="accessibility-normalization-v1",
        ruleset_profile="wcag22-aa-v1",
        ruleset_sha256="d" * 64,
        profile_json={},
    )


def _job(
    job_type: str,
    *,
    site_id: int,
    performance_run_id: int | None = None,
    accessibility_run_id: int | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        job_type=job_type,
        status="running",
        priority=100,
        performance_run_id=performance_run_id,
        accessibility_run_id=accessibility_run_id,
        website_property_id=site_id,
        dedupe_key=f"{job_type}:{performance_run_id or accessibility_run_id}",
        payload_json={},
        progress_json={},
    )
