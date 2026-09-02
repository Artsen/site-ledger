import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_occurrence_evidence_kind_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "finding-occurrence-evidence.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202609010030")
        assert "resource_occurrence" not in _table_sql(database_path)

        command.upgrade(config, "202609020031")
        assert "resource_occurrence" in _table_sql(database_path)
        with sqlite3.connect(database_path) as connection:
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.downgrade(config, "202609010030")
        assert "resource_occurrence" not in _table_sql(database_path)

        command.upgrade(config, "head")
        command.check(config)
        assert "resource_occurrence" in _table_sql(database_path)
        with sqlite3.connect(database_path) as connection:
            assert list(connection.execute("PRAGMA foreign_key_check")) == []
    finally:
        get_settings.cache_clear()


def _table_sql(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'finding_evidence_references'"
        ).fetchone()
    assert row is not None
    return str(row[0])
