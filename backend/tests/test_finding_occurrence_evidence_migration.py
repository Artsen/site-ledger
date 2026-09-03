import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.config import get_settings
from app.services.findings import get_finding


def test_occurrence_evidence_kind_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "finding-occurrence-evidence.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202609010030")
        assert "resource_occurrence" not in _table_sql(database_path)

        command.upgrade(config, "202609020031")
        assert "resource_occurrence" in _table_sql(database_path)
        with sqlite3.connect(database_path) as connection:
            _insert_populated_finding(connection)
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.downgrade(config, "202609010030")
        assert "resource_occurrence" not in _table_sql(database_path)
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM findings").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM finding_assessments").fetchone() == (1,)
            references = connection.execute(
                "SELECT position, evidence_kind FROM finding_evidence_references ORDER BY position"
            ).fetchall()
            assert references == [(0, "resource_snapshot"), (2, "scan")]
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO finding_evidence_references "
                    "(finding_assessment_id, position, role, evidence_kind, evidence_id, "
                    "evidence_observed_at, metadata_json) "
                    "VALUES (1, 3, 'unsupported', 'resource_occurrence', 404, ?, '{}')",
                    (_OBSERVED_AT,),
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO finding_evidence_references "
                    "(finding_assessment_id, position, role, evidence_kind, evidence_id, "
                    "evidence_observed_at, metadata_json) "
                    "VALUES (1, 2, 'duplicate_position', 'scan', 405, ?, '{}')",
                    (_OBSERVED_AT,),
                )
            assert list(connection.execute("PRAGMA foreign_key_check")) == []

        command.upgrade(config, "head")
        command.check(config)
        assert "resource_occurrence" in _table_sql(database_path)
        with sqlite3.connect(database_path) as connection:
            assert list(connection.execute("PRAGMA foreign_key_check")) == []
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            with Session(engine) as session:
                detail = get_finding(session, site_id=1, finding_id=1)
                assert detail is not None
                assert [
                    reference.position for reference in detail.assessments[0].evidence_references
                ] == [0, 2]
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def _table_sql(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'finding_evidence_references'"
        ).fetchone()
    assert row is not None
    return str(row[0])


_OBSERVED_AT = "2026-09-02 00:00:00+00:00"


def _insert_populated_finding(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "INSERT INTO website_properties "
        "(id, name, base_url, normalized_base_url, group_key, platform_key, ownership_key, "
        "scope_config) VALUES (1, 'Migration Site', 'https://example.test/', "
        "'https://example.test/', 'Other', 'Other', 'Unknown', '{}')"
    )
    connection.execute(
        "INSERT INTO web_resources "
        "(id, resource_type, normalized_url, scheme, host, path, query) "
        "VALUES (1, 'page', 'https://example.test/source', 'https', 'example.test', "
        "'/source', '')"
    )
    connection.execute(
        "INSERT INTO finding_evaluations "
        "(id, website_property_id, evaluator_version, detector_bundle_identity, "
        "input_fingerprint_sha256, evidence_horizon_at, active_page_count, "
        "active_page_universe_sha256, active_page_resource_ids_json, status, "
        "detector_summary_json) VALUES "
        "(1, 1, 'finding-evaluator-v2', 'finding-detectors-v4', ?, ?, 1, ?, '[1]', "
        "'completed', '{}')",
        ("e" * 64, _OBSERVED_AT, "u" * 64),
    )
    connection.execute(
        "INSERT INTO findings "
        "(id, website_property_id, web_resource_id, finding_type, logical_key_version, "
        "fingerprint_sha256, condition_state, current_severity, first_detected_at, "
        "last_detected_at, last_evaluated_evidence_at) VALUES "
        "(1, 1, 1, 'page_broken_internal_links', 'page-broken-internal-links-key-v1', "
        "?, 'detected', 'medium', ?, ?, ?)",
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
            (1, "broken_occurrence", "resource_occurrence", 202, _OBSERVED_AT),
            (2, "evaluation_horizon", "scan", 303, _OBSERVED_AT),
        ),
    )
    connection.commit()
