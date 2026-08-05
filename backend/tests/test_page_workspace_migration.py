import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_page_workspace_migration_backfills_distinct_saved_site_observations(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        command.upgrade(config, "5a2ba8ad44fd")
        connection = sqlite3.connect(database_path)
        connection.execute(
            """
            INSERT INTO website_properties (
                id, name, base_url, normalized_base_url, group_key,
                platform_key, ownership_key, scope_config, is_active
            ) VALUES (1, 'Saved', 'https://example.com/', 'https://example.com/',
                      'Other', 'Other', 'Unknown', '{}', 1)
            """
        )
        connection.executemany(
            """
            INSERT INTO web_resources (
                id, resource_type, normalized_url, scheme, host, path, query
            ) VALUES (?, 'page', ?, 'https', 'example.com', ?, '')
            """,
            [
                (1, "https://example.com/a", "/a"),
                (2, "https://example.com/b", "/b"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO scans (
                id, website_property_id, starting_url, status, scope_config,
                discovered_count, fetched_count, failed_count, skipped_count, queued_count
            ) VALUES (?, ?, 'https://example.com/', 'completed', '{}', 2, 2, 0, 0, 0)
            """,
            [(1, 1), (2, 1), (3, None)],
        )
        connection.executemany(
            """
            INSERT INTO resource_snapshots (
                scan_id, resource_id, requested_url, crawl_depth, fetched_at, fetch_state
            ) VALUES (?, ?, ?, 0, ?, 'fetched')
            """,
            [
                (1, 1, "https://example.com/a", "2026-01-02 00:00:00"),
                (2, 1, "https://example.com/a", "2026-01-01 00:00:00"),
                (2, 2, "https://example.com/b", "2026-01-03 00:00:00"),
                (3, 2, "https://example.com/b", "2025-01-01 00:00:00"),
            ],
        )
        connection.commit()
        connection.close()

        command.upgrade(config, "head")

        connection = sqlite3.connect(database_path)
        rows = connection.execute(
            """
            SELECT website_property_id, resource_id, created_at
            FROM site_pages
            ORDER BY resource_id
            """
        ).fetchall()
        connection.close()
        assert [(row[0], row[1]) for row in rows] == [(1, 1), (1, 2)]
        assert rows[0][2].startswith("2026-01-01")
    finally:
        get_settings.cache_clear()
