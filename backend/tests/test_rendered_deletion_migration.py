import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_rendered_deletion_marker_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "rendered-deletion.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608260025")
        with sqlite3.connect(database_path) as connection:
            before = {row[1] for row in connection.execute("PRAGMA table_info(render_run_targets)")}
        assert "evidence_deleted_at" not in before

        command.upgrade(config, "202608260026")
        with sqlite3.connect(database_path) as connection:
            after = {
                row[1]: row for row in connection.execute("PRAGMA table_info(render_run_targets)")
            }
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert after["evidence_deleted_at"][3] == 0
        assert revision == ("202608260026",)

        command.downgrade(config, "202608260025")
        with sqlite3.connect(database_path) as connection:
            downgraded = {
                row[1] for row in connection.execute("PRAGMA table_info(render_run_targets)")
            }
        assert "evidence_deleted_at" not in downgraded

        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
