from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_audit_module() -> ModuleType:
    path = ROOT / "tools" / "url_identity_audit.py"
    spec = importlib.util.spec_from_file_location("url_identity_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_audit_module()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTP://EXAMPLE.COM:80/a/../b#fragment", "http://example.com/b"),
        ("https://example.com/a%2fb", "https://example.com/a%2Fb"),
        ("https://example.com/a%3fb", "https://example.com/a%3Fb"),
        ("https://example.com/a%23b", "https://example.com/a%23b"),
        ("https://example.com/%2e/", "https://example.com/%2E/"),
        ("https://example.com/a//b", "https://example.com/a//b"),
        ("https://example.com/a/", "https://example.com/a/"),
        ("https://example.com/%41", "https://example.com/A"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
        ("https://[2001:DB8::1]/", "https://[2001:db8::1]/"),
        ("https://example.com/?b=2&a=1", "https://example.com/?b=2&a=1"),
        ("https://example.com/?id=2&id=1", "https://example.com/?id=2&id=1"),
        ("https://example.com/?a", "https://example.com/?a"),
        ("https://example.com/?a=", "https://example.com/?a="),
        ("https://example.com/?q=+", "https://example.com/?q=+"),
        ("https://example.com/?q=%20", "https://example.com/?q=%20"),
        ("https://example.com/?a=1&&b=2", "https://example.com/?a=1&&b=2"),
    ],
)
def test_candidate_reference_is_conservative(raw: str, expected: str) -> None:
    assert audit.candidate_normalize_url(raw).normalized_url == expected


def test_candidate_drop_query_is_deterministic_without_reordering_survivors() -> None:
    raw = "https://example.com/?z=2&utm_source=a&b=1&utm_medium=x&a=0"
    result = audit.candidate_normalize_url(raw, ("utm_*",))
    assert result.normalized_url == "https://example.com/?z=2&b=1&a=0"


def test_candidate_rejects_userinfo_instead_of_silently_discarding_it() -> None:
    with pytest.raises(audit.CandidateNormalizationError):
        audit.candidate_normalize_url("https://user:password@example.com/")


@pytest.mark.parametrize(
    "seed",
    [
        "https://example.com/a%2Fb?b=2&a=1",
        "https://example.com/a//b?id=2&id=1",
        "https://example.com/%2E/a?q=hello+world",
        "https://bücher.example:8443/Page/",
    ],
)
def test_candidate_reference_is_idempotent(seed: str) -> None:
    first = audit.candidate_normalize_url(seed).normalized_url
    assert audit.candidate_normalize_url(first).normalized_url == first


def test_candidate_generation_is_deterministic_for_adversarial_matrix() -> None:
    paths = ["/a/b", "/a%2Fb", "/a//b", "/%2E/a", "/Page", "/page"]
    queries = ["", "a=1&b=2", "b=2&a=1", "id=1&id=2", "a", "q=+"]
    values = [f"https://example.com{path}?{query}" for path in paths for query in queries]
    first = [audit.candidate_normalize_url(value).normalized_url for value in values]
    second = [audit.candidate_normalize_url(value).normalized_url for value in values]
    assert len(values) == 36
    assert first == second


def test_candidate_reference_has_no_production_runtime_wiring() -> None:
    production_files = (ROOT / "backend" / "app").rglob("*.py")
    assert all(
        "url_identity_audit" not in path.read_text(encoding="utf-8") for path in production_files
    )


def test_empty_database_is_supported_and_read_only(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    sqlite3.connect(database).close()
    before = _database_checksum(database)
    report = audit.audit_database(database)
    assert report["counts"]["web_resources"] == 0
    assert report["read_only"] is True
    assert _database_checksum(database) == before


def test_audit_classifies_collisions_dependencies_and_redacts_urls(tmp_path: Path) -> None:
    database = tmp_path / "audit.db"
    _create_fixture_database(database)
    before = _database_checksum(database)

    report = audit.audit_database(database)

    assert report["identity_classifications"] == {
        "unchanged": 1,
        "re_key_only": 1,
        "current_over_collapse_candidate": 2,
        "candidate_v2_merge": 2,
        "insufficient_provenance": 1,
    }
    assert report["migration_severity"] == "CANDIDATE_MERGE_REQUIRES_REVIEW"
    assert report["urls_redacted"] is True
    assert all(
        str(item["current"]).startswith("sha256:") for item in report["over_collapse_examples"]
    )
    impact = report["over_collapse_dependency_impact"]
    assert impact["ambiguous_site_pages"] == 1
    assert impact["ambiguous_categories"] == 1
    assert impact["ambiguous_category_supports"] == 1
    assert impact["ambiguous_category_exclusions"] == 1
    assert impact["ambiguous_notes_or_workflow"] == 2
    assert impact["mechanically_attributable_performance_observations"] == 1
    assert impact["mechanically_attributable_accessibility_observations"] == 1
    assert _database_checksum(database) == before


def test_show_urls_requires_explicit_opt_in(tmp_path: Path) -> None:
    database = tmp_path / "audit.db"
    _create_fixture_database(database)
    report = audit.audit_database(database, show_urls=True)
    assert report["urls_redacted"] is False
    assert any(
        str(item["current"]).startswith("https://") for item in report["over_collapse_examples"]
    )


def _database_checksum(database: Path) -> str:
    connection = sqlite3.connect(database)
    try:
        state: dict[str, Any] = {}
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        for table in tables:
            state[table] = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    finally:
        connection.close()


def _create_fixture_database(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE web_resources (id INTEGER PRIMARY KEY, normalized_url TEXT NOT NULL);
        CREATE TABLE scans (id INTEGER PRIMARY KEY, scope_config TEXT);
        CREATE TABLE resource_snapshots (
            id INTEGER PRIMARY KEY, scan_id INTEGER, resource_id INTEGER, requested_url TEXT
        );
        CREATE TABLE site_pages (
            id INTEGER PRIMARY KEY, resource_id INTEGER, workflow_status TEXT
        );
        CREATE TABLE page_category_assignments (
            id INTEGER PRIMARY KEY, site_page_id INTEGER, category_id INTEGER
        );
        CREATE TABLE page_category_assignment_supports (
            id INTEGER PRIMARY KEY, page_category_assignment_id INTEGER
        );
        CREATE TABLE page_category_automatic_exclusions (
            id INTEGER PRIMARY KEY, site_page_id INTEGER, category_id INTEGER
        );
        CREATE TABLE notes (id INTEGER PRIMARY KEY, site_page_id INTEGER, body TEXT);
        CREATE TABLE performance_observations (
            id INTEGER PRIMARY KEY, website_property_id INTEGER,
            web_resource_id INTEGER, requested_target TEXT
        );
        CREATE TABLE accessibility_observations (
            id INTEGER PRIMARY KEY, website_property_id INTEGER,
            web_resource_id INTEGER, requested_url TEXT
        );
        CREATE TABLE resource_occurrences (
            id INTEGER PRIMARY KEY, source_snapshot_id INTEGER,
            target_resource_id INTEGER, resolved_url TEXT
        );
        CREATE TABLE resource_reference_occurrences (
            id INTEGER PRIMARY KEY, source_snapshot_id INTEGER,
            target_resource_id INTEGER, resolved_url TEXT
        );
        CREATE TABLE website_properties (id INTEGER PRIMARY KEY, scope_config TEXT);
        """
    )
    resources = [
        (1, "https://example.com/a/b"),
        (2, "https://example.com/?a=1&b=2"),
        (3, "https://example.com/a;b"),
        (4, "https://example.com/a/./c"),
        (5, "https://example.com/a/c"),
        (6, "https://user@example.com/"),
        (7, "https://example.com/unchanged"),
    ]
    connection.executemany("INSERT INTO web_resources VALUES (?, ?)", resources)
    connection.execute("INSERT INTO scans VALUES (1, '{}')")
    snapshots = [
        (1, 1, 1, "https://example.com/a%2Fb"),
        (2, 1, 1, "https://example.com/a/b"),
        (3, 1, 2, "https://example.com/?a=1&b=2"),
        (4, 1, 2, "https://example.com/?b=2&a=1"),
        (5, 1, 3, "https://example.com/a%3Bb"),
        (6, 1, 7, "https://example.com/unchanged"),
    ]
    connection.executemany("INSERT INTO resource_snapshots VALUES (?, ?, ?, ?)", snapshots)
    connection.execute("INSERT INTO site_pages VALUES (1, 1, 'review')")
    connection.execute("INSERT INTO page_category_assignments VALUES (1, 1, 10)")
    connection.execute("INSERT INTO page_category_assignment_supports VALUES (1, 1)")
    connection.execute("INSERT INTO page_category_automatic_exclusions VALUES (1, 1, 10)")
    connection.execute("INSERT INTO notes VALUES (1, 1, 'human state')")
    connection.execute(
        "INSERT INTO performance_observations VALUES (1, 1, 1, 'https://example.com/a%2Fb')"
    )
    connection.execute(
        "INSERT INTO accessibility_observations VALUES (1, 1, 1, 'https://example.com/a/b')"
    )
    connection.execute("INSERT INTO website_properties VALUES (1, '{}')")
    connection.commit()
    connection.close()
