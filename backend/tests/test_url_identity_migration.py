from __future__ import annotations

import copy
import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import get_settings
from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
    normalize_url_v1,
    normalize_url_v2,
)
from app.database import get_db
from app.main import create_app
from app.models import (
    BackgroundJob,
    JobEvent,
    Scan,
    UrlIdentityMigration,
    UrlIdentityState,
    WebResource,
)
from app.services.background_jobs import claim_next_job, enqueue_scan_job
from app.services.repositories import get_or_create_resource
from app.services.url_identity import (
    UrlIdentityMaintenanceRequired,
    ensure_url_identity_state,
    inspect_url_identity_state,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reconciliation_tests = _load(
    "url_identity_reconciliation_fixture",
    Path(__file__).with_name("test_url_identity_reconciliation.py"),
)
migrate = _load("url_identity_migrate_test", ROOT / "tools" / "url_identity_migrate.py")


def _config(database: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    return config


def test_schema_initializes_fresh_v2_and_populated_v1_and_controls_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = tmp_path / "fresh.db"
    fresh_config = _config(fresh, monkeypatch)
    command.upgrade(fresh_config, "head")
    with sqlite3.connect(fresh) as connection:
        assert connection.execute(
            "SELECT active_normalization_version, reconciliation_required FROM url_identity_state"
        ).fetchone() == ("url-normalization-v2", 0)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    command.check(fresh_config)

    legacy = tmp_path / "legacy.db"
    legacy_config = _config(legacy, monkeypatch)
    command.upgrade(legacy_config, "202608130022")
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "INSERT INTO web_resources "
            "(resource_type, normalized_url, scheme, host, path, query) "
            "VALUES ('page', 'https://example.com/', 'https', 'example.com', '/', '')"
        )
        connection.commit()
    command.upgrade(legacy_config, "head")
    with sqlite3.connect(legacy) as connection:
        assert connection.execute(
            "SELECT active_normalization_version, reconciliation_required FROM url_identity_state"
        ).fetchone() == ("url-normalization-v1", 1)
        assert (
            connection.execute("SELECT normalization_version FROM web_resources").fetchone()[0]
            == "url-normalization-v1"
        )
    command.downgrade(legacy_config, "202608130022")
    command.upgrade(legacy_config, "head")
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "UPDATE url_identity_state SET active_normalization_version = 'url-normalization-v2'"
        )
        connection.commit()
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(legacy_config, "202608130022")
    get_settings.cache_clear()


def _prepare_executor_fixture(database: Path) -> dict:
    reconciliation_tests._create_full_domain_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "ALTER TABLE web_resources ADD COLUMN normalization_version TEXT NOT NULL "
            "DEFAULT 'url-normalization-v1'"
        )
        connection.execute(
            "ALTER TABLE scans ADD COLUMN url_normalization_version TEXT NOT NULL "
            "DEFAULT 'url-normalization-v1'"
        )
        connection.executescript(
            """
            CREATE TABLE url_identity_migrations (
              id INTEGER PRIMARY KEY, implementation_version TEXT NOT NULL,
              reconciliation_schema_version TEXT NOT NULL,
              source_normalization_version TEXT NOT NULL,
              target_normalization_version TEXT NOT NULL,
              reconciliation_manifest_sha256 TEXT NOT NULL,
              reconciliation_source_fingerprint TEXT NOT NULL,
              operation_plan_sha256 TEXT NOT NULL, status TEXT NOT NULL,
              counts_json TEXT NOT NULL, backup_metadata_json TEXT NOT NULL,
              pre_migration_fingerprint TEXT NOT NULL,
              post_migration_fingerprint TEXT,
              post_migration_write_fingerprint TEXT,
              started_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
            CREATE TABLE url_identity_state (
              id INTEGER PRIMARY KEY, active_normalization_version TEXT NOT NULL,
              reconciliation_required INTEGER NOT NULL, active_migration_id INTEGER,
              activated_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE url_identity_migration_mappings (
              id INTEGER PRIMARY KEY, migration_id INTEGER NOT NULL,
              old_resource_id INTEGER NOT NULL, new_resource_id INTEGER NOT NULL,
              mapping_kind TEXT NOT NULL, candidate_identity_hash TEXT,
              is_primary INTEGER NOT NULL, source_normalization_version TEXT NOT NULL,
              target_normalization_version TEXT NOT NULL,
              UNIQUE(migration_id, old_resource_id, new_resource_id));
            CREATE TABLE web_resource_aliases (
              legacy_resource_id INTEGER PRIMARY KEY, target_resource_id INTEGER NOT NULL,
              migration_id INTEGER NOT NULL, alias_reason TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE worker_instances (
              id INTEGER PRIMARY KEY, status TEXT, stopped_at TEXT, last_seen_at TEXT);
            INSERT INTO url_identity_state
              (id, active_normalization_version, reconciliation_required)
              VALUES (1, 'url-normalization-v1', 1);
            UPDATE alembic_version SET version_num = '202608260025';
            """
        )
        connection.commit()
    manifest = reconciliation_tests.reconcile.export_manifest(database, show_urls=True)
    return reconciliation_tests._resolve_manifest(manifest)


def test_rebase_carries_only_unchanged_decisions(tmp_path: Path) -> None:
    database = tmp_path / "rebase.db"
    manifest = _prepare_executor_fixture(database)
    rebased, summary = migrate.rebase_manifest(manifest, database)
    assert summary["groups_carried"] == 2
    assert summary["groups_invalidated"] == 0
    assert rebased["status"] == "READY_FOR_SIMULATION"

    changed = copy.deepcopy(manifest)
    split = next(item for item in changed["groups"] if item["classification"] == "split")
    split["workspace"][0]["owner_label"] = "different"
    split["workspace"][0]["workspace_sha256"] = "changed-workspace"
    rebased, summary = migrate.rebase_manifest(changed, database)
    assert summary["groups_invalidated"] == 1
    assert summary["groups_carried"] == 1
    assert rebased["status"] == "UNRESOLVED"


def test_rebase_carries_decisions_when_only_new_evidence_rows_change(tmp_path: Path) -> None:
    database = tmp_path / "evidence-rebase.db"
    manifest = _prepare_executor_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO resource_occurrences VALUES "
            "(3, 1, 'page_link', 'https://example.test/?a=1&b=2', "
            "'https://example.test/?a=1&b=2', 1)"
        )
        connection.commit()

    rebased, summary = migrate.rebase_manifest(manifest, database)

    assert summary["groups_carried"] == 2
    assert summary["groups_invalidated"] == 0
    split = next(item for item in rebased["groups"] if item["classification"] == "split")
    assert split["workspace"][0]["decisions"]["primary_candidate_id"] is not None


def test_same_engine_simulation_apply_and_immediate_rollback(tmp_path: Path) -> None:
    database = tmp_path / "apply.db"
    simulation = tmp_path / "simulation.db"
    backup = tmp_path / "backup.db"
    manifest = _prepare_executor_fixture(database)
    source_before = reconciliation_tests._logical_checksum(database)

    result = migrate.simulate(database, simulation, manifest, ())
    assert result["status"] == "SIMULATION_PASSED"
    assert result["source_unchanged"] is True
    assert reconciliation_tests._logical_checksum(database) == source_before
    with sqlite3.connect(simulation) as connection:
        assert (
            connection.execute(
                "SELECT active_normalization_version FROM url_identity_state"
            ).fetchone()[0]
            == "url-normalization-v2"
        )
        assert connection.execute("SELECT COUNT(*) FROM web_resources").fetchone()[0] == 6
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    result = migrate.apply_migration(database, backup, manifest, (), migrate.APPLY_CONFIRMATION)
    assert result["status"] == "MIGRATION_VERIFIED"
    assert result["counts"]["grandfather_v1"] == 1
    migration_id = result["migration_id"]
    rolled_back = migrate.rollback_migration(
        database, backup, migration_id, migrate.ROLLBACK_CONFIRMATION
    )
    assert rolled_back["status"] == "ROLLBACK_RESTORED"
    assert reconciliation_tests._logical_checksum(database) == source_before


def test_executor_guards_jobs_workers_stale_manifest_and_confirmation(tmp_path: Path) -> None:
    database = tmp_path / "guard.db"
    manifest = _prepare_executor_fixture(database)
    with pytest.raises(migrate.MigrationError, match="requires --confirm"):
        migrate.apply_migration(database, tmp_path / "no.db", manifest, (), "wrong")

    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO background_jobs VALUES (1, 'queued')")
        connection.commit()
    with pytest.raises(migrate.MigrationError, match="active or queued"):
        migrate.simulate(database, tmp_path / "job.db", manifest, ())
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM background_jobs")
        connection.execute(
            "INSERT INTO worker_instances VALUES "
            "(1, 'online', NULL, strftime('%Y-%m-%d %H:%M:%f', 'now'))"
        )
        connection.commit()
    with pytest.raises(migrate.MigrationError, match="healthy workers"):
        migrate.simulate(database, tmp_path / "worker.db", manifest, ())

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM worker_instances")
        connection.execute("UPDATE notes SET body = 'changed' WHERE id = 1")
        connection.commit()
    with pytest.raises(migrate.MigrationError, match="stale manifest"):
        migrate.simulate(database, tmp_path / "stale.db", manifest, ())


def test_verified_backup_rejects_corrupt_destination_and_rollback_rejects_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    manifest = _prepare_executor_fixture(source)
    existing = tmp_path / "existing.db"
    existing.write_text("not a database", encoding="ascii")
    with pytest.raises(migrate.MigrationError, match="already exists"):
        migrate.verified_backup(source, existing, ())

    backup = tmp_path / "backup.db"
    result = migrate.apply_migration(source, backup, manifest, (), migrate.APPLY_CONFIRMATION)
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE notes SET body = 'post migration write' WHERE id = 1")
        connection.commit()
    with pytest.raises(migrate.MigrationError, match="post-migration writes"):
        migrate.rollback_migration(
            source, backup, result["migration_id"], migrate.ROLLBACK_CONFIRMATION
        )


def test_apply_restores_verified_backup_when_derivative_rebuild_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "restore-on-failure.db"
    backup = tmp_path / "restore-on-failure-backup.db"
    manifest = _prepare_executor_fixture(database)
    before = reconciliation_tests._logical_checksum(database)

    def fail_rebuild(*_args: object) -> dict:
        raise migrate.MigrationError("injected derivative rebuild failure")

    monkeypatch.setattr(migrate, "_rebuild_derivatives", fail_rebuild)
    with pytest.raises(migrate.MigrationError, match="injected derivative"):
        migrate.apply_migration(database, backup, manifest, (), migrate.APPLY_CONFIRMATION)

    assert reconciliation_tests._logical_checksum(database) == before


def test_rollback_rejects_a_different_valid_database_backup(tmp_path: Path) -> None:
    database = tmp_path / "backup-binding.db"
    backup = tmp_path / "recorded.db"
    wrong_backup = tmp_path / "wrong.db"
    manifest = _prepare_executor_fixture(database)
    result = migrate.apply_migration(database, backup, manifest, (), migrate.APPLY_CONFIRMATION)
    migrate.verified_backup(database, wrong_backup, ())

    with pytest.raises(migrate.MigrationError, match="does not match recorded"):
        migrate.rollback_migration(
            database,
            wrong_backup,
            result["migration_id"],
            migrate.ROLLBACK_CONFIRMATION,
        )


def _add_migration(db: Session, status: str) -> UrlIdentityMigration:
    migration = UrlIdentityMigration(
        implementation_version="url-identity-migration-v1",
        reconciliation_schema_version="url-identity-reconciliation-v1",
        source_normalization_version=URL_NORMALIZATION_V1_VERSION,
        target_normalization_version=URL_NORMALIZATION_V2_VERSION,
        reconciliation_manifest_sha256="a" * 64,
        reconciliation_source_fingerprint="b" * 64,
        operation_plan_sha256="c" * 64,
        status=status,
        counts_json={},
        backup_metadata_json={},
        pre_migration_fingerprint="d" * 64,
    )
    db.add(migration)
    db.flush()
    return migration


def _set_runtime_state(
    db: Session,
    *,
    version: str,
    reconciliation_required: bool,
    migration_status: str | None = None,
) -> UrlIdentityState:
    state = ensure_url_identity_state(db)
    migration = _add_migration(db, migration_status) if migration_status is not None else None
    state.active_normalization_version = version
    state.reconciliation_required = reconciliation_required
    state.active_migration_id = migration.id if migration is not None else None
    db.commit()
    return state


@pytest.mark.parametrize(
    ("version", "reconciliation_required", "migration_status", "maintenance_required"),
    [
        (URL_NORMALIZATION_V1_VERSION, True, None, False),
        (URL_NORMALIZATION_V2_VERSION, False, None, False),
        (URL_NORMALIZATION_V2_VERSION, False, "completed", False),
        (URL_NORMALIZATION_V1_VERSION, True, "applying", True),
        (URL_NORMALIZATION_V1_VERSION, True, "rebuilding", True),
        (URL_NORMALIZATION_V1_VERSION, True, "future-status", True),
        (URL_NORMALIZATION_V1_VERSION, True, "completed", True),
        (URL_NORMALIZATION_V2_VERSION, False, "rebuilding", True),
        ("url-normalization-future", False, None, True),
    ],
)
def test_runtime_state_machine_fails_closed(
    db_session: Session,
    version: str,
    reconciliation_required: bool,
    migration_status: str | None,
    maintenance_required: bool,
) -> None:
    _set_runtime_state(
        db_session,
        version=version,
        reconciliation_required=reconciliation_required,
        migration_status=migration_status,
    )

    status = inspect_url_identity_state(db_session)

    assert status.maintenance_required is maintenance_required
    assert status.migration_status == migration_status


def test_missing_active_migration_provenance_fails_closed(db_session: Session) -> None:
    state = ensure_url_identity_state(db_session)
    state.active_normalization_version = URL_NORMALIZATION_V1_VERSION
    state.reconciliation_required = True
    state.active_migration_id = 123
    db_session.commit()

    status = inspect_url_identity_state(db_session)

    assert status.maintenance_required is True
    assert status.migration_status == "missing"
    assert status.maintenance_reason == "active_migration_missing"


def test_completed_migration_with_inconsistent_version_provenance_fails_closed(
    db_session: Session,
) -> None:
    state = _set_runtime_state(
        db_session,
        version=URL_NORMALIZATION_V2_VERSION,
        reconciliation_required=False,
        migration_status="completed",
    )
    migration = db_session.get(UrlIdentityMigration, state.active_migration_id)
    assert migration is not None
    migration.target_normalization_version = URL_NORMALIZATION_V1_VERSION
    db_session.commit()

    status = inspect_url_identity_state(db_session)

    assert status.maintenance_required is True
    assert status.maintenance_reason == "inconsistent_identity_state"


def test_resource_creation_and_worker_claim_fail_without_mutation_during_maintenance(
    db_session: Session,
) -> None:
    normalized = normalize_url_v1("https://example.com/existing")
    existing = WebResource(
        resource_type="page",
        normalization_version=URL_NORMALIZATION_V1_VERSION,
        normalized_url=normalized.normalized_url,
        scheme=normalized.scheme,
        host=normalized.host,
        port=normalized.port,
        path=normalized.path,
        query=normalized.query,
    )
    scan = Scan(
        starting_url="https://example.com/",
        status="queued",
        scope_config={},
        url_normalization_version=URL_NORMALIZATION_V1_VERSION,
    )
    db_session.add_all([existing, scan])
    db_session.flush()
    job = enqueue_scan_job(db_session, scan)
    db_session.commit()
    _set_runtime_state(
        db_session,
        version=URL_NORMALIZATION_V1_VERSION,
        reconciliation_required=True,
        migration_status="rebuilding",
    )
    before = (
        db_session.scalar(select(func.count(WebResource.id))),
        existing.last_seen_at,
        job.status,
        job.worker_id,
        job.lease_token,
        job.attempt_count,
        db_session.scalar(select(func.count(JobEvent.id))),
    )

    with pytest.raises(UrlIdentityMaintenanceRequired, match="rebuilding"):
        get_or_create_resource(
            db_session,
            normalize_url_v1("https://example.com/new"),
            normalization_version=URL_NORMALIZATION_V1_VERSION,
        )
    assert claim_next_job(db_session, worker_id="blocked-worker", lease_seconds=30) is None
    db_session.expire_all()

    assert (
        db_session.scalar(select(func.count(WebResource.id))),
        db_session.get(WebResource, existing.id).last_seen_at,
        db_session.get(BackgroundJob, job.id).status,
        db_session.get(BackgroundJob, job.id).worker_id,
        db_session.get(BackgroundJob, job.id).lease_token,
        db_session.get(BackgroundJob, job.id).attempt_count,
        db_session.scalar(select(func.count(JobEvent.id))),
    ) == before

    migration = db_session.get(
        UrlIdentityMigration, ensure_url_identity_state(db_session).active_migration_id
    )
    assert migration is not None
    migration.status = "completed"
    state = ensure_url_identity_state(db_session)
    state.active_normalization_version = URL_NORMALIZATION_V2_VERSION
    state.reconciliation_required = False
    db_session.commit()
    assert get_or_create_resource(db_session, normalize_url_v2("https://example.com/new"))
    assert claim_next_job(db_session, worker_id="recovered-worker", lease_seconds=30) is not None


def test_api_blocks_product_traffic_but_health_reports_maintenance(
    db_session: Session,
) -> None:
    state = _set_runtime_state(
        db_session,
        version=URL_NORMALIZATION_V1_VERSION,
        reconciliation_required=True,
        migration_status="rebuilding",
    )
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    application = create_app(session_factory=factory)

    def override_db():
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = override_db
    payload = {"starting_url": "https://example.com/", "scope_config": {}}
    with TestClient(application) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "maintenance_required"
        assert health.json()["url_identity"] == {
            "active_version": URL_NORMALIZATION_V1_VERSION,
            "maintenance_required": True,
            "migration_id": state.active_migration_id,
            "migration_status": "rebuilding",
        }
        for method, path, json in (
            ("get", "/api/scans", None),
            ("post", "/api/scans", payload),
            ("patch", "/api/sites/1", {}),
            ("delete", "/api/scans/1", None),
        ):
            response = client.request(method, path, json=json)
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "url_identity_maintenance_required"

    assert db_session.scalar(select(func.count(Scan.id))) == 0
    assert db_session.scalar(select(func.count(BackgroundJob.id))) == 0

    migration = db_session.get(UrlIdentityMigration, state.active_migration_id)
    assert migration is not None
    migration.status = "completed"
    state.active_normalization_version = URL_NORMALIZATION_V2_VERSION
    state.reconciliation_required = False
    db_session.commit()
    with TestClient(application) as client:
        response = client.post("/api/scans", json=payload)
    assert response.status_code == 202
    assert db_session.scalar(select(func.count(Scan.id))) == 1
    assert db_session.scalar(select(func.count(BackgroundJob.id))) == 1


def test_real_core_commit_enters_maintenance_and_verified_rollback_recovers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "interrupted.db"
    backup = tmp_path / "interrupted-backup.db"
    manifest = _prepare_executor_fixture(database)
    backup_metadata = migrate.verified_backup(database, backup, ())
    connection = migrate._connect(database)
    try:
        core = migrate._execute_core(connection, database, manifest, backup_metadata)
    finally:
        connection.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT active_normalization_version, active_migration_id FROM url_identity_state"
        ).fetchone() == (URL_NORMALIZATION_V1_VERSION, core["migration_id"])
        assert (
            connection.execute(
                "SELECT status FROM url_identity_migrations WHERE id = ?",
                (core["migration_id"],),
            ).fetchone()[0]
            == "rebuilding"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM web_resources WHERE normalization_version = ?",
                (URL_NORMALIZATION_V2_VERSION,),
            ).fetchone()[0]
            > 0
        )
        before_resources = connection.execute(
            "SELECT id, normalization_version, normalized_url, last_seen_at "
            "FROM web_resources ORDER BY id"
        ).fetchall()
        before_scans = connection.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
        before_jobs = connection.execute("SELECT COUNT(*) FROM background_jobs").fetchone()[0]

    engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        runtime = inspect_url_identity_state(db)
        assert runtime.maintenance_required is True
        with pytest.raises(UrlIdentityMaintenanceRequired, match="rebuilding"):
            get_or_create_resource(db, normalize_url_v1("https://blocked.example/new"))

    application = create_app(session_factory=factory)

    def override_db():
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        assert client.get("/api/health").json()["status"] == "maintenance_required"
        response = client.post(
            "/api/scans",
            json={"starting_url": "https://example.com/", "scope_config": {}},
        )
        assert response.status_code == 503
    assert migrate.status(database)["active_migration_id"] == core["migration_id"]

    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT id, normalization_version, normalized_url, last_seen_at "
                "FROM web_resources ORDER BY id"
            ).fetchall()
            == before_resources
        )
        assert connection.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == before_scans
        assert (
            connection.execute("SELECT COUNT(*) FROM background_jobs").fetchone()[0] == before_jobs
        )
    engine.dispose()

    result = migrate.rollback_migration(
        database,
        backup,
        core["migration_id"],
        migrate.ROLLBACK_CONFIRMATION,
    )
    assert result["status"] == "ROLLBACK_RESTORED"
    recovered_engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    with Session(recovered_engine) as db:
        runtime = inspect_url_identity_state(db)
        assert runtime.maintenance_required is False
        assert runtime.active_normalization_version == URL_NORMALIZATION_V1_VERSION
        created = get_or_create_resource(db, normalize_url_v1("https://recovered.example/new"))
        assert created.normalization_version == URL_NORMALIZATION_V1_VERSION
    recovered_engine.dispose()
