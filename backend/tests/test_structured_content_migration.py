import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_structured_content_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "structured-content-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608070019")
        command.upgrade(config, "202608070020")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            artifact_indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(html_structured_content_artifacts)"
                )
            }
        assert "html_structured_content_artifacts" in tables
        assert "html_structured_content_sections" in tables
        assert "ix_html_structured_content_artifacts_blob_state" in artifact_indexes

        command.downgrade(config, "202608070019")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "html_structured_content_artifacts" not in tables
        assert "html_structured_content_sections" not in tables

        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
