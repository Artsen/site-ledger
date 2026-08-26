import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_render_run_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "render-runs.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608250024")
        command.upgrade(config, "202608260025")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            observation_columns = {
                row[1]: row
                for row in connection.execute("PRAGMA table_info(rendered_observations)")
            }
            job_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(background_jobs)")
            }
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        assert {"render_runs", "render_run_targets"} <= tables
        assert observation_columns["snapshot_id"][3] == 0
        assert {"render_run_id", "render_run_target_id", "web_resource_id"} <= set(
            observation_columns
        )
        assert "render_run_id" in job_columns
        assert foreign_keys == []

        command.downgrade(config, "202608250024")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
