import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_populated_v1_collection_plan_upgrade_and_downgrade(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "collection-plans-v2.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202609030032")
        with sqlite3.connect(database_path) as connection:
            _insert_site_page(connection)
            _insert_plan(
                connection, plan_id=1, planner="collection-planner-v1", mode="missing_current"
            )

        command.upgrade(config, "202609040033")
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT planner_version, target_mode, active_collection_count_at_creation, "
                "missing_count_at_creation, selection_reason_counts_json "
                "FROM collection_plans WHERE id = 1"
            ).fetchone()
            assert row == (
                "collection-planner-v1",
                "missing_current",
                0,
                1,
                '{"missing_current":1}',
            )
            _insert_plan(
                connection,
                plan_id=2,
                planner="collection-planner-v2",
                mode="refresh_current",
                v2=True,
            )
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.downgrade(config, "202609030032")
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT id FROM collection_plans").fetchall() == [(1,)]
            assert connection.execute(
                "SELECT collection_plan_id FROM collection_plan_targets"
            ).fetchall() == [(1,)]
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE collection_plans SET target_mode = 'refresh_current' WHERE id = 1"
                )
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.upgrade(config, "head")
        command.check(config)
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT planner_version, target_mode FROM collection_plans"
            ).fetchall() == [("collection-planner-v1", "missing_current")]
            assert list(connection.execute("PRAGMA foreign_key_check")) == []
    finally:
        get_settings.cache_clear()


def _insert_site_page(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "INSERT INTO website_properties "
        "(id, name, base_url, normalized_base_url, group_key, platform_key, ownership_key, "
        "scope_config) VALUES "
        "(1, 'Migration Site', 'https://example.test/', 'https://example.test/', "
        "'Other', 'Other', 'Unknown', '{}')"
    )
    connection.execute(
        "INSERT INTO web_resources "
        "(id, resource_type, normalized_url, scheme, host, path, query) VALUES "
        "(1, 'page', 'https://example.test/page', 'https', 'example.test', '/page', '')"
    )
    connection.execute("INSERT INTO site_pages (website_property_id, resource_id) VALUES (1, 1)")
    connection.commit()


def _insert_plan(
    connection: sqlite3.Connection,
    *,
    plan_id: int,
    planner: str,
    mode: str,
    v2: bool = False,
) -> None:
    columns = (
        "id, website_property_id, planner_version, evidence_domain, target_mode, "
        "context_identity, context_json, active_page_count, active_page_universe_sha256, "
        "eligible_count, covered_count_at_creation, in_flight_count_at_creation, "
        "ineligible_count_at_creation, target_count, batch_size, batch_count, "
        "target_selection_sha256"
    )
    values: list[object] = [
        plan_id,
        1,
        planner,
        "accessibility",
        mode,
        f"accessibility:test:{plan_id}",
        "{}",
        1,
        str(plan_id) * 64,
        1,
        0 if not v2 else 1,
        0,
        0,
        1,
        250,
        0,
        str(plan_id + 2) * 64,
    ]
    if v2:
        columns += (
            ", active_collection_count_at_creation, missing_count_at_creation, "
            "selection_reason_counts_json"
        )
        values.extend([0, 0, '{"missing_current":0,"refresh_current":1}'])
    placeholders = ", ".join("?" for _ in values)
    connection.execute(f"INSERT INTO collection_plans ({columns}) VALUES ({placeholders})", values)
    target_columns = (
        "collection_plan_id, position, web_resource_id, requested_url, selection_reason, "
        "target_context_json"
    )
    target_values: list[object] = [
        plan_id,
        0,
        1,
        "https://example.test/page",
        mode,
        "{}",
    ]
    if v2:
        target_columns += ", latest_compatible_observed_at"
        target_values.append("2026-09-01 15:24:00+00:00")
    target_placeholders = ", ".join("?" for _ in target_values)
    connection.execute(
        f"INSERT INTO collection_plan_targets ({target_columns}) VALUES ({target_placeholders})",
        target_values,
    )
    connection.commit()
