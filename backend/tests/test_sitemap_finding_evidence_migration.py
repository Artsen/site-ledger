import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_populated_sitemap_evidence_downgrade_preserves_compatible_history(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "sitemap-finding-evidence.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202609030032")
        with sqlite3.connect(database_path) as connection:
            _insert_populated_sitemap_finding(connection)
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.downgrade(config, "202609020031")
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM findings").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM finding_assessments").fetchone() == (1,)
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='source_entry_observations'"
                ).fetchone()
                is None
            )
            assert "evidence_manifest_json" not in {
                row[1] for row in connection.execute("PRAGMA table_info(finding_evaluations)")
            }
            refresh_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(source_refreshes)")
            }
            assert "sitemap_document_type" not in refresh_columns
            assert "child_refresh_ids_json" not in refresh_columns
            references = connection.execute(
                "SELECT position, evidence_kind FROM finding_evidence_references ORDER BY position"
            ).fetchall()
            assert references == [
                (0, "resource_snapshot"),
                (2, "resource_occurrence"),
                (3, "scan"),
            ]
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO finding_evidence_references "
                    "(finding_assessment_id, position, role, evidence_kind, evidence_id, "
                    "evidence_observed_at, metadata_json) VALUES "
                    "(1, 4, 'unsupported', 'source_entry_observation', 1, ?, '{}')",
                    (_OBSERVED_AT,),
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO finding_evidence_references "
                    "(finding_assessment_id, position, role, evidence_kind, evidence_id, "
                    "evidence_observed_at, metadata_json) VALUES "
                    "(1, 2, 'duplicate', 'scan', 2, ?, '{}')",
                    (_OBSERVED_AT,),
                )
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.upgrade(config, "head")
        command.check(config)
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM findings").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM finding_assessments").fetchone() == (1,)
            assert list(connection.execute("PRAGMA foreign_key_check")) == []
    finally:
        get_settings.cache_clear()


_OBSERVED_AT = "2026-09-03 00:00:00+00:00"


def _insert_populated_sitemap_finding(connection: sqlite3.Connection) -> None:
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
        "(1, 'page', 'https://example.test/error', 'https', 'example.test', '/error', '')"
    )
    connection.execute(
        "INSERT INTO url_sources "
        "(id, website_property_id, source_type, name, source_url, normalized_source_url, "
        "is_active, discovery_mode, settings_json) VALUES "
        "(1, 1, 'sitemap', 'Sitemap', 'https://example.test/sitemap.xml', "
        "'https://example.test/sitemap.xml', 1, 'configured', '{}')"
    )
    connection.execute(
        "INSERT INTO source_refreshes "
        "(id, url_source_id, status, started_at, finished_at, response_bytes, "
        "discovered_entry_count, accepted_entry_count, rejected_entry_count, child_source_count, "
        "entries_added, entries_updated, entries_no_longer_current, warnings_json, "
        "membership_materialized, sitemap_document_type, child_refresh_ids_json) VALUES "
        "(1, 1, 'completed', ?, ?, 100, 1, 1, 0, 0, 1, 0, 0, '[]', 1, "
        "'urlset', '[]')",
        (_OBSERVED_AT, _OBSERVED_AT),
    )
    connection.execute(
        "INSERT INTO source_entry_observations "
        "(id, source_refresh_id, position, resource_id, raw_url, normalized_url, "
        "normalization_version, source_metadata_json, validation_state, scope_decision) VALUES "
        "(1, 1, 0, 1, 'https://example.test/error', 'https://example.test/error', "
        "'url-normalization-v1', '{}', 'valid', 'crawlable')"
    )
    connection.execute(
        "INSERT INTO finding_evaluations "
        "(id, website_property_id, evaluator_version, detector_bundle_identity, "
        "input_fingerprint_sha256, evidence_horizon_at, active_page_count, "
        "active_page_universe_sha256, active_page_resource_ids_json, evidence_manifest_json, "
        "status, detector_summary_json) VALUES "
        "(1, 1, 'finding-evaluator-v3', 'finding-detectors-v5', ?, ?, 1, ?, '[1]', "
        "?, 'completed', '{}')",
        (
            "e" * 64,
            _OBSERVED_AT,
            "u" * 64,
            '{"schema":"finding-evidence-manifest-v1","static":{"scan_id":1},'
            '"sitemap_roots":[{"url_source_id":1,"refresh_tree":{'
            '"url_source_id":1,"source_refresh_id":1,"sitemap_document_type":"urlset",'
            '"status":"completed","membership_materialized":true,"children":[]}}]}',
        ),
    )
    connection.execute(
        "INSERT INTO findings "
        "(id, website_property_id, web_resource_id, finding_type, logical_key_version, "
        "fingerprint_sha256, condition_state, current_severity, first_detected_at, "
        "last_detected_at, last_evaluated_evidence_at) VALUES "
        "(1, 1, 1, 'sitemap_page_http_error', 'sitemap-page-http-error-key-v1', ?, "
        "'detected', 'medium', ?, ?, ?)",
        ("f" * 64, _OBSERVED_AT, _OBSERVED_AT, _OBSERVED_AT),
    )
    connection.execute(
        "INSERT INTO finding_assessments "
        "(id, finding_id, finding_evaluation_id, outcome, severity, evidence_observed_at, "
        "details_json, assessment_sha256) VALUES "
        "(1, 1, 1, 'detected', 'medium', ?, '{}', ?)",
        (_OBSERVED_AT, "a" * 64),
    )
    connection.execute("UPDATE findings SET current_assessment_id = 1 WHERE id = 1")
    connection.executemany(
        "INSERT INTO finding_evidence_references "
        "(finding_assessment_id, position, role, evidence_kind, evidence_id, "
        "evidence_observed_at, metadata_json) VALUES (1, ?, ?, ?, ?, ?, '{}')",
        (
            (0, "primary", "resource_snapshot", 101, _OBSERVED_AT),
            (1, "sitemap_membership", "source_entry_observation", 1, _OBSERVED_AT),
            (2, "link", "resource_occurrence", 202, _OBSERVED_AT),
            (3, "evaluation_horizon", "scan", 303, _OBSERVED_AT),
        ),
    )
    connection.commit()
