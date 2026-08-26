from __future__ import annotations

import copy
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


def _load_module() -> ModuleType:
    tools = ROOT / "tools"
    sys.path.insert(0, str(tools))
    path = tools / "url_identity_reconcile.py"
    spec = importlib.util.spec_from_file_location("url_identity_reconcile", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reconcile = _load_module()


def test_manifest_is_deterministic_versioned_and_private_by_default(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    _create_full_domain_fixture(database)
    first = reconcile.export_manifest(database)
    second = reconcile.export_manifest(database)

    assert first["schema_version"] == "url-identity-reconciliation-v1"
    assert first["manifest_checksum"] == second["manifest_checksum"]
    assert first["source"]["identity_graph_sha256"] == second["source"]["identity_graph_sha256"]
    assert first["summary"]["split_group_count"] == 1
    assert first["summary"]["rekey_count"] == 1
    assert first["summary"]["insufficient_provenance_count"] == 1
    assert first["status"] == "UNRESOLVED"
    assert "example.test" not in json.dumps(first)
    assert first["groups"][0]["group_id"].startswith("group:")
    assert all(
        item["candidate_id"].startswith("candidate:") for item in first["groups"][0]["candidates"]
    )


def test_show_urls_report_escapes_evidence_and_stable_ids_do_not_change(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    _create_full_domain_fixture(database)
    redacted = reconcile.export_manifest(database)
    visible = reconcile.export_manifest(database, show_urls=True)
    report = reconcile.render_report(visible)

    assert redacted["groups"][0]["group_id"] == visible["groups"][0]["group_id"]
    assert "https://example.test/" in json.dumps(visible)
    assert "<script>" not in report
    assert "&lt;script&gt;title&lt;/script&gt;" in report


def test_validation_is_fail_closed_but_can_audit_unresolved_manifest(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    _create_full_domain_fixture(database)
    manifest = reconcile.export_manifest(database, show_urls=True)

    assert reconcile.validate_manifest(manifest, database, require_resolved=False) == []
    errors = reconcile.validate_manifest(manifest, database)
    assert any("primary candidate is unresolved" in item for item in errors)
    assert any("operator decisions remain unresolved" in item for item in errors)

    unknown = copy.deepcopy(manifest)
    workspace = _split_group(unknown)["workspace"][0]
    workspace["decisions"]["primary_candidate_id"] = "candidate:unknown"
    _refresh_checksum(unknown)
    assert any(
        "primary candidate is unknown" in item for item in reconcile.validate_manifest(unknown)
    )

    contradictory = _resolve_manifest(copy.deepcopy(manifest))
    decision = _split_group(contradictory)["workspace"][0]["decisions"]["owner_label"]
    decision["action"] = "ASSIGN"
    decision["candidate_ids"] = decision["candidate_ids"] * 2
    _refresh_checksum(contradictory)
    assert any(
        "duplicate candidate target" in item for item in reconcile.validate_manifest(contradictory)
    )


@pytest.mark.parametrize("mutation", ["site_page", "category", "evidence"])
def test_stale_manifest_detects_relevant_graph_changes(tmp_path: Path, mutation: str) -> None:
    database = tmp_path / "fixture.db"
    _create_full_domain_fixture(database)
    manifest = reconcile.export_manifest(database, show_urls=True)
    connection = sqlite3.connect(database)
    if mutation == "site_page":
        connection.execute("UPDATE site_pages SET owner_label = 'changed' WHERE id = 1")
    elif mutation == "category":
        connection.execute("INSERT INTO page_category_assignments VALUES (2, 1, 2)")
    else:
        connection.execute(
            "INSERT INTO resource_occurrences VALUES "
            "(3, 1, 'page_link', 'https://example.test/?b=2&a=1', "
            "'https://example.test/?a=1&b=2', 1)"
        )
    connection.commit()
    connection.close()

    errors = reconcile.validate_manifest(manifest, database, require_resolved=False)
    assert any("stale manifest" in item for item in errors)


def test_plan_enumerates_rekeys_splits_grandfathering_and_evidence(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    _create_full_domain_fixture(database)
    manifest = _resolve_manifest(reconcile.export_manifest(database, show_urls=True))
    plan = reconcile.operation_plan(manifest, database)

    assert plan["status"] == "READY_FOR_PR30_IMPLEMENTATION"
    assert plan["operation_counts"]["prepare_resource_identity"] == 2
    assert plan["operation_counts"]["grandfather_v1_identity"] == 1
    domains = {
        item["domain"] for item in plan["operations"] if item["operation"] == "reassign_evidence"
    }
    assert {
        "snapshot",
        "scan_seed",
        "scan_seed_origin",
        "source_entry",
        "link_target",
        "resource_reference_target",
        "performance_url",
        "accessibility_url",
        "render_run_target",
        "rendered_observation",
        "ai_document_snapshot",
        "ai_document_reference",
    } <= domains


def test_full_domain_simulation_preserves_evidence_and_source(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    destination = tmp_path / "simulation.db"
    _create_full_domain_fixture(database)
    source_before = _logical_checksum(database)
    manifest = _resolve_manifest(reconcile.export_manifest(database, show_urls=True))

    result = reconcile.simulate_manifest(manifest, database, destination)

    assert result["status"] == "SIMULATION_PASSED"
    assert result["source_unchanged"] is True
    assert _logical_checksum(database) == source_before
    verification = result["verification"]
    assert verification["foreign_key_violations"] == 0
    assert verification["web_resource_uniqueness"] is True
    assert verification["site_page_uniqueness"] is True
    assert all(verification["immutable_count_checks"].values())
    assert all(verification["immutable_hash_checks"].values())
    assert verification["grandfathered_identity_count"] == 1

    connection = sqlite3.connect(destination)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute("SELECT COUNT(*) FROM web_resources").fetchone()[0] == 6
        assert connection.execute("SELECT COUNT(*) FROM resource_snapshots").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM scan_seeds").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM scan_seed_origins").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM page_category_assignments").fetchone()[0] == 2
        )
        supports = connection.execute(
            "SELECT support_type, COUNT(*) FROM page_category_assignment_supports "
            "GROUP BY support_type ORDER BY support_type"
        ).fetchall()
        assert [tuple(row) for row in supports] == [("manual", 2), ("rule", 1)]
        assert connection.execute("SELECT COUNT(*) FROM scan_page_projections").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM scan_comparison_page_results").fetchone()[0]
            == 0
        )
        target_ids = {
            row[0]
            for row in connection.execute(
                "SELECT target_resource_id FROM resource_occurrences ORDER BY id"
            )
        }
        assert len(target_ids) == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_simulation_rejects_active_jobs_and_leaves_no_copy(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    destination = tmp_path / "blocked.db"
    _create_full_domain_fixture(database)
    manifest = _resolve_manifest(reconcile.export_manifest(database, show_urls=True))
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO background_jobs VALUES (1, 'running')")
    connection.commit()
    connection.close()

    with pytest.raises(reconcile.ReconciliationError, match="active or queued"):
        reconcile.simulate_manifest(manifest, database, destination)
    assert not destination.exists()


def test_candidate_merge_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "merge.db"
    _create_full_domain_fixture(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO web_resources "
        "(id, resource_type, normalized_url, scheme, host, path, query) "
        "VALUES (6, 'page', 'https://example.test/%41', 'https', 'example.test', '/%41', '')"
    )
    connection.execute(
        "INSERT INTO web_resources "
        "(id, resource_type, normalized_url, scheme, host, path, query) "
        "VALUES (7, 'page', 'https://example.test/A', 'https', 'example.test', '/A', '')"
    )
    connection.commit()
    connection.close()
    manifest = reconcile.export_manifest(database, show_urls=True)
    assert manifest["summary"]["candidate_merge_count"] == 2
    assert any(
        "candidate merge is fail-closed" in item
        for item in reconcile.validate_manifest(manifest, require_resolved=False)
    )


def test_insufficient_provenance_policy_does_not_invent_invalid_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "invalid.db"
    _create_full_domain_fixture(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO web_resources "
        "(id, resource_type, normalized_url, scheme, host, path, query) "
        "VALUES (6, 'page', 'https://user@example.test/', 'https', "
        "'example.test', '/', '')"
    )
    connection.commit()
    connection.close()

    manifest = reconcile.export_manifest(database, show_urls=True)
    policies = {item["reason"]: item["policy"] for item in manifest["insufficient_provenance"]}
    assert policies["query_identity_without_attributable_original_spelling"] == "GRANDFATHER_V1"
    assert policies["invalid_or_credential_bearing_current_identity"] == "REQUIRE_REVIEW"


def test_reset_decision_is_explicit_and_notes_cannot_be_reset(tmp_path: Path) -> None:
    database = tmp_path / "fixture.db"
    _create_full_domain_fixture(database)
    manifest = reconcile.export_manifest(database, show_urls=True)
    group = _split_group(manifest)
    workspace = group["workspace"][0]
    candidates = [item["candidate_id"] for item in group["candidates"]]
    workspace["decisions"]["primary_candidate_id"] = candidates[0]
    workspace["decisions"]["owner_label"] = reconcile._decision("RESET")
    workspace["decisions"]["workflow_status"] = reconcile._decision("RESET")
    for row_id in workspace["decisions"]["categories"]:
        workspace["decisions"]["categories"][row_id] = reconcile._decision("RESET")
    for row_id in workspace["decisions"]["exclusions"]:
        workspace["decisions"]["exclusions"][row_id] = reconcile._decision("RESET")
    for row_id in workspace["decisions"]["notes"]:
        workspace["decisions"]["notes"][row_id] = reconcile._decision("RESET")
    _refresh_checksum(manifest)

    assert any("RESET is not valid" in item for item in reconcile.validate_manifest(manifest))


def test_empty_database_is_supported_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    sqlite3.connect(database).close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest = reconcile.export_manifest(database)
    assert manifest["status"] == "READY_FOR_SIMULATION"
    assert manifest["groups"] == []
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def _split_group(manifest: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in manifest["groups"] if item["classification"] == "split")


def _resolve_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    group = _split_group(manifest)
    candidate_ids = [item["candidate_id"] for item in group["candidates"]]
    workspace = group["workspace"][0]
    decisions = workspace["decisions"]
    decisions["primary_candidate_id"] = candidate_ids[0]
    decisions["owner_label"] = reconcile._decision("ASSIGN", [candidate_ids[0]])
    decisions["workflow_status"] = reconcile._decision("DUPLICATE", candidate_ids)
    for row_id in decisions["categories"]:
        decisions["categories"][row_id] = reconcile._decision("DUPLICATE", candidate_ids)
    for row_id in decisions["exclusions"]:
        decisions["exclusions"][row_id] = reconcile._decision("ASSIGN", [candidate_ids[0]])
    for row_id in decisions["notes"]:
        decisions["notes"][row_id] = reconcile._decision("ASSIGN", [candidate_ids[1]])
    _refresh_checksum(manifest)
    assert reconcile.resolution_status(manifest) == "READY_FOR_SIMULATION"
    return manifest


def _refresh_checksum(manifest: dict[str, Any]) -> None:
    manifest["status"] = reconcile.resolution_status(manifest)
    manifest["manifest_checksum"] = reconcile.manifest_checksum(manifest)


def _logical_checksum(database: Path) -> str:
    connection = sqlite3.connect(database)
    try:
        state: dict[str, Any] = {}
        for table in (
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ):
            state[table] = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        return reconcile.sha256_value(state)
    finally:
        connection.close()


def _create_full_domain_fixture(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(_SCHEMA)
    resources = [
        (1, "page", "https://example.test/?a=1&b=2", "https", "example.test", "/", "a=1&b=2"),
        (2, "page", "https://example.test/a/b", "https", "example.test", "/a/b", ""),
        (3, "page", "https://example.test/?lost=1", "https", "example.test", "/", "lost=1"),
        (4, "page", "https://example.test/unchanged", "https", "example.test", "/unchanged", ""),
        (5, "asset", "https://example.test/image.png", "https", "example.test", "/image.png", ""),
    ]
    connection.executemany(
        "INSERT INTO web_resources (id, resource_type, normalized_url, scheme, host, path, query) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        resources,
    )
    connection.execute("INSERT INTO alembic_version VALUES ('202608130022')")
    connection.execute("INSERT INTO website_properties VALUES (1, '{}')")
    connection.execute("INSERT INTO scans VALUES (1, 1, '{}')")
    connection.execute("INSERT INTO url_sources VALUES (1, 1)")
    connection.executemany(
        "INSERT INTO resource_snapshots VALUES (?, 1, ?, ?, 200, NULL, NULL)",
        [
            (1, 1, "https://example.test/?a=1&b=2"),
            (2, 1, "https://example.test/?b=2&a=1"),
            (3, 2, "https://example.test/a%2Fb"),
        ],
    )
    connection.execute("INSERT INTO site_pages VALUES (1, 1, 1, 'owner', 'review', NULL, NULL)")
    connection.execute("INSERT INTO site_pages VALUES (2, 1, 2, NULL, 'unreviewed', NULL, NULL)")
    connection.executemany(
        "INSERT INTO page_categories VALUES (?, ?)", [(1, "Primary"), (2, "New")]
    )
    connection.execute("INSERT INTO page_category_assignments VALUES (1, 1, 1)")
    connection.executemany(
        "INSERT INTO page_category_assignment_supports VALUES (?, 1, ?, ?, ?)",
        [(1, "manual", None, "manual"), (2, "rule", 1, "rule:1")],
    )
    connection.execute("INSERT INTO page_category_automatic_exclusions VALUES (1, 1, 2, 'review')")
    connection.execute("INSERT INTO notes VALUES (1, 1, '<script>note</script>', 1)")
    connection.execute("INSERT INTO page_category_rules VALUES (1, 1, 1, 'all', 1, 1)")
    connection.execute(
        "INSERT INTO page_category_rule_conditions VALUES "
        "(1, 1, 'query', 'starts_with', 'a=1', 0, 1, 0)"
    )
    connection.execute(
        "INSERT INTO url_source_entries VALUES "
        "(1, 1, 1, 'https://example.test/?a=1&b=2', 'https://example.test/?a=1&b=2')"
    )
    connection.execute(
        "INSERT INTO scan_seeds VALUES "
        "(1, 1, 1, 'https://example.test/?a=1&b=2', "
        "'https://example.test/?a=1&b=2')"
    )
    connection.executemany(
        "INSERT INTO scan_seed_origins VALUES (?, 1, ?)",
        [
            (1, "https://example.test/?a=1&b=2"),
            (2, "https://example.test/?b=2&a=1"),
        ],
    )
    connection.executemany(
        "INSERT INTO resource_occurrences VALUES "
        "(?, ?, 'page_link', ?, 'https://example.test/?a=1&b=2', 1)",
        [
            (1, 1, "https://example.test/?a=1&b=2"),
            (2, 2, "https://example.test/?b=2&a=1"),
        ],
    )
    connection.execute(
        "INSERT INTO resource_reference_occurrences VALUES "
        "(1, 2, 'asset', 'https://example.test/?a=1&b=2', "
        "'https://example.test/?a=1&b=2', 1)"
    )
    connection.execute("INSERT INTO performance_payloads VALUES (1, 'perfhash')")
    connection.execute(
        "INSERT INTO performance_observations VALUES "
        "(1, 1, 1, 'https://example.test/?a=1&b=2', 'https://provider.test/', 1)"
    )
    connection.execute("INSERT INTO accessibility_payloads VALUES (1, 'accesshash')")
    connection.execute(
        "INSERT INTO accessibility_observations VALUES "
        "(1, 1, 1, 'https://example.test/?b=2&a=1', 'https://final.test/', 1)"
    )
    connection.execute("INSERT INTO render_runs VALUES (1, 1)")
    connection.execute(
        "INSERT INTO render_run_targets VALUES (1, 1, 1, 1, 'https://example.test/?b=2&a=1', 1)"
    )
    connection.execute(
        "INSERT INTO rendered_observations VALUES "
        "(1, 1, 1, 1, 1, 'https://example.test/?a=1&b=2', "
        "'https://final.test/', 'completed', 200)"
    )
    connection.execute(
        "INSERT INTO ai_document_snapshots VALUES "
        "(1, 1, 'https://example.test/?a=1&b=2', 'https://final.test/')"
    )
    connection.execute(
        "INSERT INTO ai_document_references VALUES "
        "(1, 1, 'https://example.test/?b=2&a=1', 'https://example.test/?a=1&b=2')"
    )
    connection.execute("INSERT INTO content_blobs VALUES (1, 'blobhash')")
    connection.execute("INSERT INTO html_structured_content_artifacts VALUES (1, 'dochash')")
    connection.execute("INSERT INTO html_parse_artifacts VALUES (1, '<script>title</script>')")
    connection.execute("UPDATE resource_snapshots SET parse_artifact_id = 1 WHERE id = 2")
    connection.execute("INSERT INTO scan_page_projections VALUES (1, 1)")
    connection.execute("INSERT INTO scan_resource_projections VALUES (1, 1)")
    connection.execute("INSERT INTO scan_link_projections VALUES (1, 1, 5)")
    connection.execute("INSERT INTO scan_comparison_page_results VALUES (1, 1)")
    connection.execute("INSERT INTO scan_comparison_resource_results VALUES (1, 1)")
    connection.execute("INSERT INTO scan_comparison_link_results VALUES (1, 1, 5)")
    connection.commit()
    connection.close()


_SCHEMA = """
CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY);
CREATE TABLE website_properties (id INTEGER PRIMARY KEY, scope_config TEXT NOT NULL);
CREATE TABLE scans (
 id INTEGER PRIMARY KEY, website_property_id INTEGER, scope_config TEXT NOT NULL);
CREATE TABLE web_resources (
 id INTEGER PRIMARY KEY, resource_type TEXT NOT NULL, normalized_url TEXT NOT NULL UNIQUE,
 scheme TEXT, host TEXT, port INTEGER, path TEXT, query TEXT,
 first_seen_at TEXT, last_seen_at TEXT, UNIQUE(resource_type, normalized_url));
CREATE TABLE content_blobs (id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE TABLE html_parse_artifacts (id INTEGER PRIMARY KEY, page_title TEXT);
CREATE TABLE html_structured_content_artifacts (id INTEGER PRIMARY KEY, document_text_sha256 TEXT);
CREATE TABLE resource_snapshots (
 id INTEGER PRIMARY KEY, scan_id INTEGER, resource_id INTEGER REFERENCES web_resources(id),
 requested_url TEXT, http_status INTEGER, html_blob_id INTEGER, parse_artifact_id INTEGER);
CREATE TABLE site_pages (
 id INTEGER PRIMARY KEY, website_property_id INTEGER,
 resource_id INTEGER REFERENCES web_resources(id),
 owner_label TEXT, workflow_status TEXT, created_at TEXT, updated_at TEXT,
 UNIQUE(website_property_id, resource_id));
CREATE TABLE page_categories (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE page_category_assignments (
 id INTEGER PRIMARY KEY, site_page_id INTEGER REFERENCES site_pages(id) ON DELETE CASCADE,
 category_id INTEGER, UNIQUE(site_page_id, category_id));
CREATE TABLE page_category_rules (
 id INTEGER PRIMARY KEY, website_property_id INTEGER, category_id INTEGER,
 match_mode TEXT, is_active INTEGER, current_revision_number INTEGER);
CREATE TABLE page_category_rule_conditions (
 id INTEGER PRIMARY KEY, rule_id INTEGER, target TEXT, operator TEXT, value TEXT,
 negate INTEGER, case_sensitive INTEGER, sort_order INTEGER);
CREATE TABLE page_category_assignment_supports (
 id INTEGER PRIMARY KEY,
 page_category_assignment_id INTEGER REFERENCES page_category_assignments(id) ON DELETE CASCADE,
 support_type TEXT, rule_id INTEGER, support_key TEXT,
 UNIQUE(page_category_assignment_id, support_key));
CREATE TABLE page_category_automatic_exclusions (
 id INTEGER PRIMARY KEY, site_page_id INTEGER REFERENCES site_pages(id) ON DELETE CASCADE,
 category_id INTEGER, reason TEXT, UNIQUE(site_page_id, category_id));
CREATE TABLE notes (
 id INTEGER PRIMARY KEY, site_page_id INTEGER REFERENCES site_pages(id) ON DELETE CASCADE,
 body TEXT, is_pinned INTEGER);
CREATE TABLE url_sources (id INTEGER PRIMARY KEY, website_property_id INTEGER);
CREATE TABLE url_source_entries (
 id INTEGER PRIMARY KEY, url_source_id INTEGER, resource_id INTEGER REFERENCES web_resources(id),
 raw_url TEXT, normalized_url TEXT);
CREATE TABLE scan_seeds (
 id INTEGER PRIMARY KEY, scan_id INTEGER, resource_id INTEGER REFERENCES web_resources(id),
 requested_url TEXT, normalized_url TEXT, UNIQUE(scan_id, normalized_url));
CREATE TABLE scan_seed_origins (id INTEGER PRIMARY KEY, scan_seed_id INTEGER, raw_url TEXT);
CREATE TABLE resource_occurrences (
 id INTEGER PRIMARY KEY, source_snapshot_id INTEGER, relation_type TEXT, resolved_url TEXT,
 normalized_target_url TEXT, target_resource_id INTEGER REFERENCES web_resources(id));
CREATE TABLE resource_reference_occurrences (
 id INTEGER PRIMARY KEY, source_snapshot_id INTEGER, relation_type TEXT, resolved_url TEXT,
 normalized_target_url TEXT, target_resource_id INTEGER REFERENCES web_resources(id));
CREATE TABLE performance_payloads (id INTEGER PRIMARY KEY, sha256 TEXT);
CREATE TABLE performance_observations (
 id INTEGER PRIMARY KEY, website_property_id INTEGER,
 web_resource_id INTEGER REFERENCES web_resources(id),
 requested_target TEXT, provider_target TEXT, payload_id INTEGER);
CREATE TABLE accessibility_payloads (id INTEGER PRIMARY KEY, sha256 TEXT);
CREATE TABLE accessibility_observations (
 id INTEGER PRIMARY KEY, website_property_id INTEGER,
 web_resource_id INTEGER REFERENCES web_resources(id),
 requested_url TEXT, final_url TEXT, payload_id INTEGER);
CREATE TABLE render_runs (
 id INTEGER PRIMARY KEY, website_property_id INTEGER);
CREATE TABLE render_run_targets (
 id INTEGER PRIMARY KEY, render_run_id INTEGER,
 web_resource_id INTEGER REFERENCES web_resources(id), source_snapshot_id INTEGER,
 requested_url TEXT, position INTEGER);
CREATE TABLE rendered_observations (
 id INTEGER PRIMARY KEY, render_run_id INTEGER, render_run_target_id INTEGER,
 web_resource_id INTEGER REFERENCES web_resources(id), snapshot_id INTEGER,
 requested_url TEXT, final_url TEXT, capture_state TEXT, navigation_http_status INTEGER);
CREATE TABLE ai_document_snapshots (
 id INTEGER PRIMARY KEY, resource_id INTEGER REFERENCES web_resources(id),
 requested_url TEXT, final_url TEXT);
CREATE TABLE ai_document_references (
 id INTEGER PRIMARY KEY, target_resource_id INTEGER REFERENCES web_resources(id),
 resolved_url TEXT, normalized_target_url TEXT);
CREATE TABLE scan_page_projections (id INTEGER PRIMARY KEY, resource_id INTEGER);
CREATE TABLE scan_resource_projections (id INTEGER PRIMARY KEY, resource_id INTEGER);
CREATE TABLE scan_link_projections (
 id INTEGER PRIMARY KEY, source_resource_id INTEGER, target_resource_id INTEGER);
CREATE TABLE scan_comparison_page_results (id INTEGER PRIMARY KEY, resource_id INTEGER);
CREATE TABLE scan_comparison_resource_results (id INTEGER PRIMARY KEY, resource_id INTEGER);
CREATE TABLE scan_comparison_link_results (
 id INTEGER PRIMARY KEY, source_resource_id INTEGER, target_resource_id INTEGER);
CREATE TABLE background_jobs (id INTEGER PRIMARY KEY, status TEXT);
"""
