import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_category_rule_migration_backfills_manual_support_and_timezone_null(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "category-rule-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608060016")
        connection = sqlite3.connect(database_path)
        connection.execute(
            """INSERT INTO website_properties
               (id,name,base_url,normalized_base_url,group_key,platform_key,
                ownership_key,scope_config,is_active)
               VALUES (1,'Saved','https://example.com/','https://example.com/',
                       'Other','Other','Unknown','{}',1)"""
        )
        connection.execute(
            """INSERT INTO web_resources
               (id,resource_type,normalized_url,scheme,host,path,query)
               VALUES (1,'page','https://example.com/a','https','example.com','/a','')"""
        )
        connection.execute(
            """INSERT INTO site_pages
               (id,website_property_id,resource_id,workflow_status)
               VALUES (1,1,1,'unreviewed')"""
        )
        connection.execute(
            """INSERT INTO page_categories
               (id,website_property_id,name,normalized_name,color_key,sort_order,is_active)
               VALUES (1,1,'Legacy','legacy','stone',0,1)"""
        )
        connection.execute(
            """INSERT INTO page_category_assignments
               (id,site_page_id,category_id,assigned_at)
               VALUES (1,1,1,'2026-01-02 03:04:05')"""
        )
        connection.commit()
        connection.close()
        command.upgrade(config, "202608060017")
        connection = sqlite3.connect(database_path)
        support = connection.execute(
            "SELECT support_type, support_key, created_at FROM page_category_assignment_supports"
        ).fetchone()
        timezone = connection.execute(
            "SELECT display_timezone FROM website_properties WHERE id=1"
        ).fetchone()
        connection.close()
        assert support == ("manual", "manual", "2026-01-02 03:04:05")
        assert timezone == (None,)
        command.downgrade(config, "202608060016")
        connection = sqlite3.connect(database_path)
        assert connection.execute("SELECT COUNT(*) FROM page_category_assignments").fetchone() == (
            1,
        )
        connection.close()
        command.upgrade(config, "202608060017")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
