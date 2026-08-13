import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_accessibility_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "accessibility-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608120021")
        command.upgrade(config, "202608130022")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            columns = {row[1] for row in connection.execute("PRAGMA table_info(background_jobs)")}
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        assert {
            "accessibility_runs",
            "accessibility_observations",
            "accessibility_payload_blobs",
            "accessibility_rule_evidence",
            "accessibility_node_evidence",
        } <= tables
        assert "accessibility_run_id" in columns
        assert foreign_keys == []

        command.downgrade(config, "202608120021")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "accessibility_runs" not in tables

        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
