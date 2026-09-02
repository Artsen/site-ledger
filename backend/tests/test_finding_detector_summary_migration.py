from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_detector_summary_migration_upgrade_downgrade_reupgrade(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "finding-summary.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608310029")
        connection = sqlite3.connect(database_path)
        connection.execute(
            """
            INSERT INTO website_properties (
                id, name, base_url, normalized_base_url, group_key,
                platform_key, ownership_key, scope_config, is_active
            ) VALUES (1, 'Historical', 'https://example.test/', 'https://example.test/',
                      'Group', 'Platform', 'Owner', '{}', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO finding_evaluations (
                id, website_property_id, evaluator_version, detector_bundle_identity,
                input_fingerprint_sha256, evidence_horizon_at, active_page_count,
                active_page_universe_sha256, active_page_resource_ids_json, status
            ) VALUES (1, 1, 'finding-evaluator-v1', 'finding-detectors-v1', ?,
                      '2026-09-01 00:00:00', 0, ?, '[]', 'completed')
            """,
            ("a" * 64, "b" * 64),
        )
        connection.commit()
        connection.close()

        command.upgrade(config, "202609010030")
        connection = sqlite3.connect(database_path)
        assert (
            json.loads(
                connection.execute(
                    "SELECT detector_summary_json FROM finding_evaluations WHERE id = 1"
                ).fetchone()[0]
            )
            == {}
        )
        connection.close()

        command.downgrade(config, "202608310029")
        connection = sqlite3.connect(database_path)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(finding_evaluations)")}
        assert "detector_summary_json" not in columns
        connection.close()

        command.upgrade(config, "202609010030")
        connection = sqlite3.connect(database_path)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(finding_evaluations)")}
        assert "detector_summary_json" in columns
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.close()
    finally:
        get_settings.cache_clear()
