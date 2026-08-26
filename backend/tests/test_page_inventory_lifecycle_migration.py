import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_page_inventory_lifecycle_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "lifecycle.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        command.upgrade(config, "202608140023")
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
        connection.execute(
            """
            INSERT INTO web_resources (
                id, resource_type, normalization_version, normalized_url,
                scheme, host, path, query
            ) VALUES (1, 'page', 'url-normalization-v2', 'https://example.com/a',
                      'https', 'example.com', '/a', '')
            """
        )
        connection.execute(
            "INSERT INTO site_pages (website_property_id, resource_id) VALUES (1, 1)"
        )
        connection.commit()
        connection.close()

        command.upgrade(config, "202608250024")
        connection = sqlite3.connect(database_path)
        assert connection.execute(
            "SELECT workspace_state, suppressed_at FROM site_pages"
        ).fetchone() == ("active", None)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='site_inventory_suppressions'"
        ).fetchone() == ("site_inventory_suppressions",)
        connection.close()

        command.downgrade(config, "202608140023")
        command.upgrade(config, "202608250024")
    finally:
        get_settings.cache_clear()
