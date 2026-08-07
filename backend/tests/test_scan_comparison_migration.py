import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_scan_comparison_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "scan-comparison-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608060017")
        command.upgrade(config, "202608060018")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            columns = {row[1] for row in connection.execute("PRAGMA table_info(background_jobs)")}
        assert {
            "scan_comparisons",
            "scan_comparison_builds",
            "scan_comparison_page_results",
            "scan_comparison_resource_results",
            "scan_comparison_link_results",
            "scan_comparison_summaries",
        } <= tables
        assert "scan_comparison_id" in columns

        command.downgrade(config, "202608060017")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            columns = {row[1] for row in connection.execute("PRAGMA table_info(background_jobs)")}
        assert "scan_comparisons" not in tables
        assert "scan_comparison_id" not in columns

        command.upgrade(config, "202608060018")
        command.check(config)
    finally:
        get_settings.cache_clear()
