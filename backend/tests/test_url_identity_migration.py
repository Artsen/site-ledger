from __future__ import annotations

import copy
import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config

from alembic import command
from app.config import get_settings

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
            UPDATE alembic_version SET version_num = '202608140023';
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
