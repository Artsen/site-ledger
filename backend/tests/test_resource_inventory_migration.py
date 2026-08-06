from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_resource_inventory_migration_upgrade_downgrade_reupgrade(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "resource-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        command.upgrade(config, "202608060013")
        connection = sqlite3.connect(database_path)
        connection.execute(
            """
            INSERT INTO website_properties (
                id, name, base_url, normalized_base_url, group_key,
                platform_key, ownership_key, scope_config, is_active
            ) VALUES (1, 'Saved', 'https://example.test/', 'https://example.test/',
                      'Group', 'Platform', 'Owner', '{}', 1)
            """
        )
        connection.executemany(
            """
            INSERT INTO web_resources (
                id, resource_type, normalized_url, scheme, host, path, query
            ) VALUES (?, 'page', ?, 'https', 'example.test', ?, '')
            """,
            [
                (1, "https://example.test/", "/"),
                (2, "https://example.test/guide.pdf", "/guide.pdf"),
                (3, "https://example.test/logo.png", "/logo.png"),
                (4, "https://example.test/timeout", "/timeout"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO scans (
                id, website_property_id, starting_url, status, scope_config,
                discovered_count, fetched_count, failed_count, skipped_count, queued_count
            ) VALUES (?, 1, 'https://example.test/', ?, '{}', ?, ?, ?, ?, 0)
            """,
            [(1, "completed_with_errors", 3, 1, 2, 2), (2, "completed_with_errors", 1, 0, 1, 0)],
        )
        connection.executemany(
            """
            INSERT INTO resource_snapshots (
                id, scan_id, resource_id, requested_url, final_url, http_status,
                content_type, crawl_depth, fetch_state, error_type, error_message,
                retrieval_method, parse_method, response_headers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    1,
                    1,
                    "https://example.test/",
                    "https://example.test/",
                    200,
                    "text/html; charset=utf-8",
                    "fetched",
                    None,
                    None,
                    "fresh_http",
                    "parsed",
                    "{}",
                ),
                (
                    2,
                    1,
                    2,
                    "https://example.test/guide.pdf",
                    "https://example.test/guide.pdf",
                    200,
                    "application/pdf",
                    "skipped",
                    "unsupported_content_type",
                    "Response was not HTML",
                    "non_html",
                    None,
                    '{"content-length":"321"}',
                ),
                (
                    3,
                    1,
                    3,
                    "https://example.test/logo.png",
                    "https://example.test/logo.png",
                    200,
                    "image/png",
                    "skipped",
                    "unsupported_content_type",
                    "Response was not HTML",
                    "non_html",
                    None,
                    "{}",
                ),
                (
                    4,
                    2,
                    4,
                    "https://example.test/timeout",
                    None,
                    None,
                    None,
                    "failed",
                    "connection_timeout",
                    "Timed out",
                    "fresh_http",
                    None,
                    "{}",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO site_pages (
                id, website_property_id, resource_id, owner_label, workflow_status
            ) VALUES (1, 1, 1, 'Jane', 'reviewed')
            """
        )
        connection.commit()
        connection.close()

        command.upgrade(config, "head")
        connection = sqlite3.connect(database_path)
        snapshots = connection.execute(
            """
            SELECT id, representation_kind, representation_rule, normalized_mime_type,
                   declared_content_length, fetch_state, error_type, parse_method
            FROM resource_snapshots ORDER BY id
            """
        ).fetchall()
        scans = connection.execute(
            """
            SELECT id, status, failed_count, html_page_observed_count, resource_observed_count
            FROM scans ORDER BY id
            """
        ).fetchall()
        metadata = connection.execute(
            "SELECT owner_label, workflow_status FROM site_pages WHERE id=1"
        ).fetchone()
        connection.close()

        assert snapshots[0][1:4] == ("html_page", "mime_text_html", "text/html")
        assert snapshots[1][1:] == (
            "document",
            "mime_pdf",
            "application/pdf",
            321,
            "fetched",
            None,
            "not_applicable",
        )
        assert snapshots[2][1] == "image"
        assert snapshots[2][5:8] == ("fetched", None, "not_applicable")
        assert snapshots[3][1] == "unknown"
        assert snapshots[3][6] == "connection_timeout"
        assert scans == [
            (1, "completed", 0, 1, 2),
            (2, "completed_with_errors", 1, 0, 0),
        ]
        assert metadata == ("Jane", "reviewed")

        command.downgrade(config, "202608060013")
        connection = sqlite3.connect(database_path)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(resource_snapshots)")}
        assert "representation_kind" not in columns
        assert connection.execute(
            "SELECT error_type FROM resource_snapshots WHERE id=2"
        ).fetchone() == ("unsupported_content_type",)
        connection.close()

        command.upgrade(config, "head")
        connection = sqlite3.connect(database_path)
        assert connection.execute(
            "SELECT representation_kind, error_type FROM resource_snapshots WHERE id=2"
        ).fetchone() == ("document", None)
        connection.close()
    finally:
        get_settings.cache_clear()
