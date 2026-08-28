import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_findings_migration_round_trip_preserves_existing_jobs(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "findings.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608270027")
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO website_properties "
                "(id, name, base_url, normalized_base_url, group_key, platform_key, "
                "ownership_key, scope_config, is_active) VALUES "
                "(1, 'Fixture', 'https://example.test/', 'https://example.test/', "
                "'Other', 'Other', 'Unknown', '{}', 1)"
            )
            columns = [row[1] for row in connection.execute("PRAGMA table_info(background_jobs)")]
            values = {
                "job_type": "category_rule_evaluation",
                "status": "queued",
                "priority": 100,
                "website_property_id": 1,
                "dedupe_key": "category-rule:fixture",
                "payload_json": "{}",
                "progress_version": 1,
                "progress_json": "{}",
                "created_at": "2026-08-28 00:00:00",
                "available_at": "2026-08-28 00:00:00",
                "attempt_count": 0,
                "max_attempts": 1,
            }
            required = [name for name in columns if name in values]
            connection.execute(
                f"INSERT INTO background_jobs ({', '.join(required)}) "
                f"VALUES ({', '.join('?' for _ in required)})",
                [values[name] for name in required],
            )
            connection.commit()

        command.upgrade(config, "202608280028")
        with sqlite3.connect(database_path) as connection:
            preserved = connection.execute(
                "SELECT job_type, dedupe_key FROM background_jobs"
            ).fetchall()
            connection.execute(
                "INSERT INTO background_jobs "
                "(job_type, status, priority, website_property_id, dedupe_key, payload_json, "
                "progress_version, progress_json, created_at, available_at, attempt_count, "
                "max_attempts) VALUES "
                "('finding_evaluation', 'queued', 115, 1, 'finding:fixture', '{}', 1, '{}', "
                "'2026-08-28 00:00:00', '2026-08-28 00:00:00', 0, 1)"
            )
            connection.rollback()
            assert preserved == [("category_rule_evaluation", "category-rule:fixture")]
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.downgrade(config, "202608270027")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
