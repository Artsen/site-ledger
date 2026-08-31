import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_collection_plan_migration_round_trip_preserves_existing_history(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "collection-plans.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608280028")
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO website_properties "
                "(id, name, base_url, normalized_base_url, group_key, platform_key, "
                "ownership_key, scope_config, is_active) VALUES "
                "(1, 'Fixture', 'https://example.test/', 'https://example.test/', "
                "'Other', 'Other', 'Unknown', '{}', 1)"
            )
            connection.commit()

        command.upgrade(config, "202608310029")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert {
                "collection_plans",
                "collection_plan_targets",
                "collection_plan_batches",
            } <= tables
            assert connection.execute(
                "SELECT name FROM website_properties WHERE id = 1"
            ).fetchone() == ("Fixture",)
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.downgrade(config, "202608280028")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert "collection_plans" not in tables
            assert connection.execute(
                "SELECT name FROM website_properties WHERE id = 1"
            ).fetchone() == ("Fixture",)
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
