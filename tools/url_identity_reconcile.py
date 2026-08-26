"""Fail-closed URL identity reconciliation planning and disposable simulation.

This developer/operator tool is intentionally disconnected from application runtime.
It imports the candidate V2 reference auditor, but production normalization never imports it.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from url_identity_audit import (
    CandidateNormalizationError,
    _collision_reasons,
    _drop_patterns,
)

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.crawler.url_normalizer import (  # noqa: E402
    URL_NORMALIZATION_V2_VERSION,
    normalize_url_v2,
)

DEFAULT_DATABASE = ROOT / "data" / "scanner.db"
DEFAULT_LOCAL_DIR = ROOT / ".local" / "url-identity"
SCHEMA_VERSION = "url-identity-reconciliation-v1"
SOURCE_NORMALIZATION_VERSION = "url-normalization-v1"
CANDIDATE_VERSION = URL_NORMALIZATION_V2_VERSION
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_PARTIAL = "PARTIALLY_RESOLVED"
STATUS_READY = "READY_FOR_SIMULATION"
DECISION_ACTIONS = frozenset({"ASSIGN", "DUPLICATE", "RESET", "UNRESOLVED"})


class ReconciliationError(RuntimeError):
    """A fail-closed reconciliation validation or simulation error."""


@dataclass(frozen=True)
class AttributionSource:
    domain: str
    table: str
    row_id: str
    resource_column: str
    url_column: str
    joins: str = ""
    scope_column: str | None = None
    normalized_column: str | None = None
    operation_role: str = "target"
    target_table: str | None = None


ATTRIBUTION_SOURCES = (
    AttributionSource(
        "snapshot",
        "resource_snapshots rs",
        "rs.id",
        "rs.resource_id",
        "rs.requested_url",
        "LEFT JOIN scans s ON s.id = rs.scan_id",
        "s.scope_config",
    ),
    AttributionSource(
        "source_entry",
        "url_source_entries use",
        "use.id",
        "use.resource_id",
        "use.raw_url",
        "LEFT JOIN url_sources us ON us.id = use.url_source_id "
        "LEFT JOIN website_properties wp ON wp.id = us.website_property_id",
        "wp.scope_config",
        "normalized_url",
    ),
    AttributionSource(
        "scan_seed",
        "scan_seeds ss",
        "ss.id",
        "ss.resource_id",
        "ss.requested_url",
        "LEFT JOIN scans s ON s.id = ss.scan_id",
        "s.scope_config",
        "normalized_url",
    ),
    AttributionSource(
        "scan_seed_origin",
        "scan_seed_origins sso",
        "sso.id",
        "ss.resource_id",
        "sso.raw_url",
        "JOIN scan_seeds ss ON ss.id = sso.scan_seed_id LEFT JOIN scans s ON s.id = ss.scan_id",
        "s.scope_config",
    ),
    AttributionSource(
        "link_target",
        "resource_occurrences ro",
        "ro.id",
        "ro.target_resource_id",
        "ro.resolved_url",
        "LEFT JOIN resource_snapshots rs ON rs.id = ro.source_snapshot_id "
        "LEFT JOIN scans s ON s.id = rs.scan_id",
        "s.scope_config",
        "normalized_target_url",
    ),
    AttributionSource(
        "resource_reference_target",
        "resource_reference_occurrences rro",
        "rro.id",
        "rro.target_resource_id",
        "rro.resolved_url",
        "LEFT JOIN resource_snapshots rs ON rs.id = rro.source_snapshot_id "
        "LEFT JOIN scans s ON s.id = rs.scan_id",
        "s.scope_config",
        "normalized_target_url",
    ),
    AttributionSource(
        "performance_url",
        "performance_observations po",
        "po.id",
        "po.web_resource_id",
        "po.requested_target",
        "LEFT JOIN website_properties wp ON wp.id = po.website_property_id",
        "wp.scope_config",
    ),
    AttributionSource(
        "accessibility_url",
        "accessibility_observations ao",
        "ao.id",
        "ao.web_resource_id",
        "ao.requested_url",
        "LEFT JOIN website_properties wp ON wp.id = ao.website_property_id",
        "wp.scope_config",
    ),
    AttributionSource(
        "render_run_target",
        "render_run_targets rrt",
        "rrt.id",
        "rrt.web_resource_id",
        "rrt.requested_url",
        "LEFT JOIN render_runs rr ON rr.id = rrt.render_run_id "
        "LEFT JOIN website_properties wp ON wp.id = rr.website_property_id",
        "wp.scope_config",
    ),
    AttributionSource(
        "rendered_observation",
        "rendered_observations robs",
        "robs.id",
        "robs.web_resource_id",
        "robs.requested_url",
        "LEFT JOIN render_runs rr ON rr.id = robs.render_run_id "
        "LEFT JOIN website_properties wp ON wp.id = rr.website_property_id",
        "wp.scope_config",
    ),
    AttributionSource(
        "ai_document_snapshot",
        "ai_document_snapshots ads",
        "ads.id",
        "ads.resource_id",
        "ads.requested_url",
    ),
    AttributionSource(
        "ai_document_reference",
        "ai_document_references adr",
        "adr.id",
        "adr.target_resource_id",
        "adr.resolved_url",
        normalized_column="normalized_target_url",
    ),
)

FINGERPRINT_COLUMNS: dict[str, tuple[str, ...]] = {
    "web_resources": (
        "id",
        "resource_type",
        "normalization_version",
        "normalized_url",
        "scheme",
        "host",
        "port",
        "path",
        "query",
    ),
    "resource_snapshots": (
        "id",
        "resource_id",
        "requested_url",
        "final_url",
        "html_blob_id",
        "parse_artifact_id",
    ),
    "url_source_entries": (
        "id",
        "url_source_id",
        "resource_id",
        "raw_url",
        "normalized_url",
    ),
    "scan_seeds": ("id", "scan_id", "resource_id", "requested_url", "normalized_url"),
    "scan_seed_origins": ("id", "scan_seed_id", "raw_url"),
    "resource_occurrences": (
        "id",
        "source_snapshot_id",
        "target_resource_id",
        "resolved_url",
        "normalized_target_url",
    ),
    "resource_reference_occurrences": (
        "id",
        "source_snapshot_id",
        "target_resource_id",
        "resolved_url",
        "normalized_target_url",
    ),
    "performance_observations": (
        "id",
        "web_resource_id",
        "requested_target",
        "provider_target",
        "payload_id",
    ),
    "accessibility_observations": (
        "id",
        "web_resource_id",
        "requested_url",
        "final_url",
        "payload_id",
    ),
    "render_run_targets": (
        "id",
        "render_run_id",
        "web_resource_id",
        "source_snapshot_id",
        "requested_url",
        "position",
    ),
    "rendered_observations": (
        "id",
        "render_run_id",
        "render_run_target_id",
        "web_resource_id",
        "snapshot_id",
        "requested_url",
        "final_url",
        "capture_state",
        "navigation_http_status",
    ),
    "ai_document_snapshots": ("id", "resource_id", "requested_url", "final_url"),
    "ai_document_references": (
        "id",
        "target_resource_id",
        "resolved_url",
        "normalized_target_url",
    ),
    "site_pages": (
        "id",
        "website_property_id",
        "resource_id",
        "owner_label",
        "workflow_status",
    ),
    "page_category_assignments": ("id", "site_page_id", "category_id"),
    "page_category_assignment_supports": (
        "id",
        "page_category_assignment_id",
        "support_type",
        "rule_id",
        "support_key",
    ),
    "page_category_automatic_exclusions": (
        "id",
        "site_page_id",
        "category_id",
        "reason",
    ),
    "notes": ("id", "site_page_id", "body", "is_pinned"),
    "page_category_rules": (
        "id",
        "website_property_id",
        "category_id",
        "match_mode",
        "is_active",
        "current_revision_number",
    ),
    "page_category_rule_conditions": (
        "id",
        "rule_id",
        "target",
        "operator",
        "value",
        "negate",
        "case_sensitive",
        "sort_order",
    ),
}

COUNT_TABLES = tuple(FINGERPRINT_COLUMNS) + (
    "content_blobs",
    "performance_payloads",
    "accessibility_payloads",
    "html_structured_content_artifacts",
    "scan_page_projections",
    "scan_resource_projections",
    "scan_link_projections",
    "scan_comparison_page_results",
    "scan_comparison_resource_results",
    "scan_comparison_link_results",
    "background_jobs",
)

DERIVATIVE_TABLE_COLUMNS = (
    ("scan_page_projections", ("resource_id",)),
    ("scan_resource_projections", ("resource_id",)),
    ("scan_link_projections", ("source_resource_id", "target_resource_id")),
    ("scan_comparison_page_results", ("resource_id",)),
    ("scan_comparison_resource_results", ("resource_id",)),
    ("scan_comparison_link_results", ("source_resource_id", "target_resource_id")),
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_group_id(current_url: str, candidates: Iterable[str], site_ids: Iterable[int]) -> str:
    identity = {
        "current": current_url,
        "candidates": sorted(candidates),
        "site_ids": sorted(set(site_ids)),
    }
    return f"group:{sha256_value(identity)}"


def stable_candidate_id(resource_type: str, candidate_url: str) -> str:
    return f"candidate:{sha256_value({'resource_type': resource_type, 'url': candidate_url})}"


def _label(value: str, show_urls: bool) -> str:
    return value if show_urls else f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _base_table(source: AttributionSource) -> str:
    return source.table.split()[0]


def _source_available(
    connection: sqlite3.Connection, source: AttributionSource, tables: set[str]
) -> bool:
    table = _base_table(source)
    needed = {
        source.row_id.split(".")[-1],
        source.url_column.split(".")[-1],
    }
    return table in tables and needed <= _columns(connection, table)


@contextmanager
def read_only_database(database: Path) -> Iterator[sqlite3.Connection]:
    resolved = database.resolve()
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _scope_patterns(raw: Any) -> tuple[str, ...]:
    return _drop_patterns(raw) if raw is not None else ()


def _candidate(raw_url: str, scope: Any = None) -> str | None:
    try:
        return normalize_url_v2(raw_url).normalized_url
    except (CandidateNormalizationError, ValueError):
        return None


def source_fingerprint(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = _table_names(connection)
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    for table in sorted(COUNT_TABLES):
        if table not in tables:
            counts[table] = 0
            continue
        count = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        counts[table] = count
        selected = [
            name
            for name in FINGERPRINT_COLUMNS.get(table, ())
            if name in _columns(connection, table)
        ]
        if not selected:
            continue
        order = "id" if "id" in selected else "rowid"
        selected_sql = ", ".join(f'"{name}"' for name in selected)
        sql = f'SELECT {selected_sql} FROM "{table}" ORDER BY "{order}"'
        digest.update(canonical_json([table, selected]))
        for row in connection.execute(sql):
            digest.update(canonical_json(list(row)))
    alembic_head = None
    if "alembic_version" in tables:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        alembic_head = str(row[0]) if row else None
    return {
        "alembic_head": alembic_head,
        "url_normalization_version": SOURCE_NORMALIZATION_VERSION,
        "candidate_version": CANDIDATE_VERSION,
        "identity_graph_sha256": digest.hexdigest(),
        "row_counts": counts,
    }


def database_file_state(database: Path) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for suffix, label in (("", "database"), ("-wal", "wal"), ("-shm", "shm")):
        path = Path(f"{database}{suffix}")
        if path.exists():
            state[label] = {
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        else:
            state[label] = None
    return state


def _evidence_by_resource(
    connection: sqlite3.Connection,
    current_urls: dict[int, str],
) -> tuple[dict[int, dict[str, list[dict[str, Any]]]], Counter[int], Counter[str]]:
    tables = _table_names(connection)
    evidence: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    errors: Counter[int] = Counter()
    domain_counts: Counter[str] = Counter()
    for source in ATTRIBUTION_SOURCES:
        if not _source_available(connection, source, tables):
            continue
        scope_select = f", {source.scope_column} AS scope_json" if source.scope_column else ""
        sql = (
            f"SELECT {source.row_id} AS row_id, {source.resource_column} AS resource_id, "
            f"{source.url_column} AS evidence_url{scope_select} FROM {source.table} "
            f"{source.joins} WHERE {source.resource_column} IS NOT NULL "
            f"AND {source.url_column} IS NOT NULL"
        )
        for row in connection.execute(sql):
            resource_id = int(row["resource_id"])
            raw_url = str(row["evidence_url"])
            scope = row["scope_json"] if source.scope_column else None
            candidate = _candidate(raw_url, scope)
            if candidate is None:
                errors[resource_id] += 1
                continue
            evidence[resource_id][candidate]
            domain_counts[source.domain] += 1
            if candidate == current_urls.get(resource_id):
                continue
            evidence[resource_id][candidate].append(
                {
                    "domain": source.domain,
                    "table": source.target_table or _base_table(source),
                    "row_id": int(row["row_id"]),
                    "resource_column": source.resource_column.split(".")[-1],
                    "normalized_column": source.normalized_column,
                    "attribution_field": source.url_column.split(".")[-1],
                    "attribution_rule": "candidate-v2 from requested/resolved identity provenance",
                    "confidence": "deterministic",
                    "operation_role": source.operation_role,
                }
            )
    return evidence, errors, domain_counts


def _populate_split_attributions(
    connection: sqlite3.Connection,
    evidence: dict[int, dict[str, list[dict[str, Any]]]],
    split_resource_ids: set[int],
) -> None:
    if not split_resource_ids:
        return
    for resource_id in split_resource_ids:
        for values in evidence[resource_id].values():
            values.clear()
    tables = _table_names(connection)
    dedupe: set[tuple[str, int, int, str]] = set()
    for source in ATTRIBUTION_SOURCES:
        if not _source_available(connection, source, tables):
            continue
        scope_select = f", {source.scope_column} AS scope_json" if source.scope_column else ""
        sql = (
            f"SELECT {source.row_id} AS row_id, {source.resource_column} AS resource_id, "
            f"{source.url_column} AS evidence_url{scope_select} FROM {source.table} "
            f"{source.joins} WHERE {source.resource_column} IS NOT NULL "
            f"AND {source.url_column} IS NOT NULL"
        )
        for row in connection.execute(sql):
            resource_id = int(row["resource_id"])
            if resource_id not in split_resource_ids:
                continue
            scope = row["scope_json"] if source.scope_column else None
            candidate = _candidate(str(row["evidence_url"]), scope)
            if candidate is None:
                continue
            key = (source.domain, int(row["row_id"]), resource_id, candidate)
            if key in dedupe:
                continue
            dedupe.add(key)
            evidence[resource_id][candidate].append(
                {
                    "domain": source.domain,
                    "table": source.target_table or _base_table(source),
                    "row_id": int(row["row_id"]),
                    "resource_column": source.resource_column.split(".")[-1],
                    "normalized_column": source.normalized_column,
                    "attribution_field": source.url_column.split(".")[-1],
                    "attribution_rule": "candidate-v2 from requested/resolved identity provenance",
                    "confidence": "deterministic",
                    "operation_role": source.operation_role,
                }
            )


def _rows(
    connection: sqlite3.Connection, sql: str, params: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params)]


def _workspace_for_resource(
    connection: sqlite3.Connection, resource_id: int
) -> list[dict[str, Any]]:
    tables = _table_names(connection)
    if "site_pages" not in tables:
        return []
    site_columns = _columns(connection, "site_pages")
    owner = "owner_label" if "owner_label" in site_columns else "NULL AS owner_label"
    workflow = (
        "workflow_status"
        if "workflow_status" in site_columns
        else "'unreviewed' AS workflow_status"
    )
    pages = _rows(
        connection,
        f"SELECT id, website_property_id, resource_id, {owner}, {workflow} "
        "FROM site_pages WHERE resource_id = ? ORDER BY website_property_id, id",
        (resource_id,),
    )
    for page in pages:
        site_page_id = int(page["id"])
        assignments: list[dict[str, Any]] = []
        if "page_category_assignments" in tables:
            category_join = (
                "LEFT JOIN page_categories pc ON pc.id = pca.category_id"
                if "page_categories" in tables
                else ""
            )
            name_select = "pc.name AS category_name" if category_join else "NULL AS category_name"
            assignments = _rows(
                connection,
                f"SELECT pca.id, pca.category_id, {name_select} "
                f"FROM page_category_assignments pca {category_join} "
                "WHERE pca.site_page_id = ? ORDER BY pca.category_id, pca.id",
                (site_page_id,),
            )
            if "page_category_assignment_supports" in tables:
                for assignment in assignments:
                    assignment["supports"] = _rows(
                        connection,
                        "SELECT id, support_type, rule_id, support_key "
                        "FROM page_category_assignment_supports "
                        "WHERE page_category_assignment_id = ? ORDER BY support_key, id",
                        (assignment["id"],),
                    )
            else:
                for assignment in assignments:
                    assignment["supports"] = []
        exclusions = (
            _rows(
                connection,
                "SELECT id, category_id, reason FROM page_category_automatic_exclusions "
                "WHERE site_page_id = ? ORDER BY category_id, id",
                (site_page_id,),
            )
            if "page_category_automatic_exclusions" in tables
            else []
        )
        notes = (
            _rows(
                connection,
                "SELECT id, body, is_pinned FROM notes WHERE site_page_id = ? ORDER BY id",
                (site_page_id,),
            )
            if "notes" in tables
            else []
        )
        page["categories"] = assignments
        page["exclusions"] = exclusions
        page["notes"] = notes
        page["workspace_sha256"] = sha256_value(
            {
                "owner_label": page.get("owner_label"),
                "workflow_status": page.get("workflow_status"),
                "categories": assignments,
                "exclusions": exclusions,
                "notes": notes,
            }
        )
    return pages


def _latest_page_context(connection: sqlite3.Connection, resource_id: int) -> dict[str, Any]:
    tables = _table_names(connection)
    context: dict[str, Any] = {
        "latest_http_status": None,
        "latest_title": None,
    }
    if "resource_snapshots" not in tables:
        return context
    columns = _columns(connection, "resource_snapshots")
    status = "rs.http_status" if "http_status" in columns else "NULL"
    parse_join = (
        "LEFT JOIN html_parse_artifacts hpa ON hpa.id = rs.parse_artifact_id"
        if "html_parse_artifacts" in tables and "parse_artifact_id" in columns
        else ""
    )
    title = "hpa.page_title" if parse_join else "NULL"
    row = connection.execute(
        f"SELECT {status} AS http_status, {title} AS page_title FROM resource_snapshots rs "
        f"{parse_join} WHERE rs.resource_id = ? ORDER BY rs.id DESC LIMIT 1",
        (resource_id,),
    ).fetchone()
    if row:
        context["latest_http_status"] = row["http_status"]
        context["latest_title"] = row["page_title"]
    return context


def _decision(action: str = "UNRESOLVED", candidate_ids: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "action": action,
        "candidate_ids": list(candidate_ids),
        "decision_note": None,
    }


def _workspace_manifest(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "site_page_id": int(page["id"]),
        "website_property_id": int(page["website_property_id"]),
        "owner_label": page.get("owner_label"),
        "workflow_status": page.get("workflow_status", "unreviewed"),
        "workspace_sha256": page["workspace_sha256"],
        "categories": page["categories"],
        "exclusions": page["exclusions"],
        "notes": [
            {
                **note,
                "body_sha256": hashlib.sha256(str(note["body"]).encode()).hexdigest(),
            }
            for note in page["notes"]
        ],
        "decisions": {
            "primary_candidate_id": None,
            "owner_label": _decision(),
            "workflow_status": _decision(),
            "categories": {str(item["id"]): _decision() for item in page["categories"]},
            "exclusions": {str(item["id"]): _decision() for item in page["exclusions"]},
            "notes": {str(item["id"]): _decision() for item in page["notes"]},
        },
    }


def _reason_categories(candidates: set[str]) -> list[str]:
    reasons = set(_collision_reasons(candidates))
    if not reasons:
        reasons.add("other")
    return sorted(reasons)


def _insufficient_reason(
    current_url: str, baseline: str | None, observed: set[str], error_count: int
) -> str:
    if baseline is None:
        return "invalid_or_credential_bearing_current_identity"
    if error_count and not observed:
        return "retained_evidence_cannot_be_candidate_normalized"
    if urlsplit(current_url).query and not observed:
        return "query_identity_without_attributable_original_spelling"
    return "identity_evidence_insufficient_for_historical_attribution"


def _rule_suggestions(
    connection: sqlite3.Connection,
    workspace: list[dict[str, Any]],
    candidate_urls: dict[str, str],
) -> list[dict[str, Any]]:
    tables = _table_names(connection)
    needed = {"page_category_rules", "page_category_rule_conditions"}
    if not needed <= tables:
        return []
    suggestions: list[dict[str, Any]] = []
    for page in workspace:
        for assignment in page["categories"]:
            supports = assignment.get("supports", [])
            if not supports or any(item.get("support_type") == "manual" for item in supports):
                continue
            matching_candidates: set[str] = set()
            rule_ids = sorted({int(item["rule_id"]) for item in supports if item.get("rule_id")})
            for rule_id in rule_ids:
                rule = connection.execute(
                    "SELECT match_mode, is_active FROM page_category_rules WHERE id = ?",
                    (rule_id,),
                ).fetchone()
                if not rule or not bool(rule["is_active"]):
                    continue
                conditions = _rows(
                    connection,
                    "SELECT target, operator, value, negate, case_sensitive "
                    "FROM page_category_rule_conditions WHERE rule_id = ? "
                    "ORDER BY sort_order, id",
                    (rule_id,),
                )
                for candidate_id, url in candidate_urls.items():
                    results = [_condition_matches(url, item) for item in conditions]
                    if results and (all(results) if rule["match_mode"] == "all" else any(results)):
                        matching_candidates.add(candidate_id)
            if len(matching_candidates) == 1:
                suggestions.append(
                    {
                        "kind": "category_rule_target",
                        "site_page_id": page["id"],
                        "category_assignment_id": assignment["id"],
                        "candidate_id": next(iter(matching_candidates)),
                        "rationale": "current active supporting rules match exactly one candidate",
                        "operator_acceptance_required": True,
                    }
                )
    return suggestions


def _condition_matches(url: str, condition: dict[str, Any]) -> bool:
    parts = urlsplit(url)
    filename = parts.path.rstrip("/").rsplit("/", 1)[-1]
    actual = {
        "normalized_url": url,
        "host": parts.hostname or "",
        "path": parts.path,
        "query": parts.query,
        "filename": filename,
    }.get(str(condition["target"]), "")
    expected = str(condition["value"])
    if not bool(condition.get("case_sensitive")):
        actual, expected = actual.casefold(), expected.casefold()
    operator = condition["operator"]
    if operator == "equals":
        result = actual == expected
    elif operator == "starts_with":
        result = actual.startswith(expected)
    elif operator == "ends_with":
        result = actual.endswith(expected)
    elif operator == "contains":
        result = expected in actual
    elif operator == "glob":
        import fnmatch

        result = fnmatch.fnmatchcase(actual, expected)
    elif operator == "regex":
        import re

        try:
            result = re.search(expected, actual) is not None
        except re.error:
            result = False
    else:
        result = False
    return not result if bool(condition.get("negate")) else result


def export_manifest(database: Path, *, show_urls: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    with read_only_database(database) as connection:
        tables = _table_names(connection)
        if "web_resources" not in tables:
            fingerprint = source_fingerprint(connection)
            manifest = _empty_manifest(database, fingerprint, show_urls)
            manifest["summary"]["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            manifest["manifest_checksum"] = manifest_checksum(manifest)
            return manifest
        resource_columns = _columns(connection, "web_resources")
        resource_type = "resource_type" if "resource_type" in resource_columns else "'page'"
        resources = {
            int(row["id"]): (str(row["resource_type"]), str(row["normalized_url"]))
            for row in connection.execute(
                f"SELECT id, {resource_type} AS resource_type, normalized_url FROM web_resources"
            )
        }
        current_urls = {resource_id: item[1] for resource_id, item in resources.items()}
        evidence, errors, domain_counts = _evidence_by_resource(connection, current_urls)
        split_resource_ids = {
            resource_id for resource_id, candidates in evidence.items() if len(candidates) > 1
        }
        _populate_split_attributions(connection, evidence, split_resource_ids)
        baselines: dict[int, str | None] = {}
        merge_groups: dict[str, list[int]] = defaultdict(list)
        for resource_id, (_kind, current) in resources.items():
            baseline = _candidate(current)
            baselines[resource_id] = baseline
            if baseline:
                merge_groups[baseline].append(resource_id)
        merge_ids = {item for ids in merge_groups.values() if len(ids) > 1 for item in ids}
        classifications: Counter[str] = Counter()
        groups: list[dict[str, Any]] = []
        insufficient: list[dict[str, Any]] = []
        reason_counts: Counter[str] = Counter()
        suggested_count = 0
        for resource_id in sorted(resources):
            kind, current = resources[resource_id]
            observed = set(evidence.get(resource_id, {}))
            baseline = baselines[resource_id]
            if resource_id in merge_ids:
                classification = "candidate_v2_merge"
                candidates = {baseline} if baseline else set()
            elif len(observed) > 1:
                classification = "split"
                candidates = observed
            elif baseline is None or (errors[resource_id] and not observed):
                classification = "insufficient_provenance"
                candidates = observed
            elif baseline != current or (observed and next(iter(observed)) != baseline):
                classification = "rekey"
                candidates = observed or {baseline}
            elif urlsplit(current).query and not observed:
                classification = "insufficient_provenance"
                candidates = set()
            else:
                classification = "unchanged"
                candidates = {current}
            classifications[classification] += 1
            if classification == "unchanged":
                continue
            workspace = _workspace_for_resource(connection, resource_id)
            site_ids = [int(page["website_property_id"]) for page in workspace]
            group_candidates = [value for value in candidates if value]
            group_id = stable_group_id(current, group_candidates, site_ids)
            if classification == "insufficient_provenance":
                reason = _insufficient_reason(current, baseline, observed, errors[resource_id])
                insufficient.append(
                    {
                        "group_id": group_id,
                        "resource_id": resource_id,
                        "current": _label(current, show_urls),
                        "reason": reason,
                        "policy": (
                            "GRANDFATHER_V1"
                            if reason == "query_identity_without_attributable_original_spelling"
                            else "REQUIRE_REVIEW"
                        ),
                        "historical_attribution": "unknown",
                    }
                )
                continue
            candidate_items: list[dict[str, Any]] = []
            candidate_urls: dict[str, str] = {}
            for value in sorted(group_candidates):
                candidate_id = stable_candidate_id(kind, value)
                candidate_urls[candidate_id] = value
                attributions = sorted(
                    evidence.get(resource_id, {}).get(value, []),
                    key=lambda item: (item["domain"], item["row_id"]),
                )
                candidate_items.append(
                    {
                        "candidate_id": candidate_id,
                        "normalized_url": _label(value, show_urls),
                        "evidence_counts": dict(
                            sorted(Counter(item["domain"] for item in attributions).items())
                        ),
                        "attributions": attributions,
                    }
                )
            reasons = _reason_categories(set(group_candidates)) if classification == "split" else []
            reason_counts.update(reasons)
            suggestions = _rule_suggestions(connection, workspace, candidate_urls)
            suggested_count += len(suggestions)
            group = {
                "group_id": group_id,
                "classification": classification,
                "policy": (
                    "SAFE_ONE_TO_ONE_REKEY" if classification == "rekey" else "REQUIRE_REVIEW"
                ),
                "resource": {
                    "id": resource_id,
                    "resource_type": kind,
                    "current_normalized_url": _label(current, show_urls),
                },
                "reason_categories": reasons,
                "candidates": candidate_items,
                "workspace": [_workspace_manifest(page) for page in workspace],
                "context": _latest_page_context(connection, resource_id),
                "suggestions": suggestions,
                "decision_note": None,
            }
            groups.append(group)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "database_name": database.name,
                "generated_at": datetime.now(UTC).isoformat(),
                **source_fingerprint(connection),
            },
            "privacy": {
                "urls_redacted": not show_urls,
                "full_urls_required_for_plan": True,
            },
            "summary": {
                "classifications": dict(sorted(classifications.items())),
                "split_reason_groups": dict(sorted(reason_counts.items())),
                "candidate_merge_count": classifications["candidate_v2_merge"],
                "split_group_count": classifications["split"],
                "rekey_count": classifications["rekey"],
                "insufficient_provenance_count": classifications["insufficient_provenance"],
                "suggested_outcome_count": suggested_count,
                "evidence_domain_counts": dict(sorted(domain_counts.items())),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            },
            "groups": groups,
            "insufficient_provenance": insufficient,
        }
        manifest["status"] = resolution_status(manifest)
        manifest["manifest_checksum"] = manifest_checksum(manifest)
        return manifest


def _empty_manifest(database: Path, fingerprint: dict[str, Any], show_urls: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "database_name": database.name,
            "generated_at": datetime.now(UTC).isoformat(),
            **fingerprint,
        },
        "privacy": {
            "urls_redacted": not show_urls,
            "full_urls_required_for_plan": True,
        },
        "summary": {
            "classifications": {},
            "split_reason_groups": {},
            "candidate_merge_count": 0,
            "split_group_count": 0,
            "rekey_count": 0,
            "insufficient_provenance_count": 0,
            "suggested_outcome_count": 0,
            "evidence_domain_counts": {},
        },
        "groups": [],
        "insufficient_provenance": [],
        "status": STATUS_READY,
    }


def _decision_values(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for group in manifest.get("groups", []):
        if group.get("classification") != "split":
            continue
        for workspace in group.get("workspace", []):
            decisions = workspace.get("decisions", {})
            values.extend(
                item
                for key in ("owner_label", "workflow_status")
                if isinstance((item := decisions.get(key)), dict)
            )
            for key in ("categories", "exclusions", "notes"):
                values.extend(
                    item for item in decisions.get(key, {}).values() if isinstance(item, dict)
                )
    return values


def resolution_status(manifest: dict[str, Any]) -> str:
    splits = [
        group for group in manifest.get("groups", []) if group.get("classification") == "split"
    ]
    if not splits:
        return STATUS_READY
    decisions = _decision_values(manifest)
    primary = [
        workspace.get("decisions", {}).get("primary_candidate_id")
        for group in splits
        for workspace in group.get("workspace", [])
    ]
    resolved = sum(item.get("action") != "UNRESOLVED" for item in decisions) + sum(
        bool(item) for item in primary
    )
    total = len(decisions) + len(primary)
    if total == 0:
        return STATUS_READY
    if resolved == 0:
        return STATUS_UNRESOLVED
    if resolved < total:
        return STATUS_PARTIAL
    return STATUS_READY


def manifest_checksum(manifest: dict[str, Any]) -> str:
    groups = []
    for group in manifest.get("groups", []):
        groups.append(
            {
                "group_id": group.get("group_id"),
                "classification": group.get("classification"),
                "candidate_ids": sorted(
                    item.get("candidate_id") for item in group.get("candidates", [])
                ),
                "workspace": [
                    {
                        "site_page_id": item.get("site_page_id"),
                        "workspace_sha256": item.get("workspace_sha256"),
                        "decisions": item.get("decisions"),
                    }
                    for item in group.get("workspace", [])
                ],
                "decision_note": group.get("decision_note"),
            }
        )
    payload = {
        "schema_version": manifest.get("schema_version"),
        "source": {
            key: manifest.get("source", {}).get(key)
            for key in (
                "alembic_head",
                "url_normalization_version",
                "candidate_version",
                "identity_graph_sha256",
                "row_counts",
            )
        },
        "groups": groups,
        "insufficient_provenance": [
            {
                "group_id": item.get("group_id"),
                "reason": item.get("reason"),
                "policy": item.get("policy"),
            }
            for item in manifest.get("insufficient_provenance", [])
        ],
    }
    return sha256_value(payload)


def validate_manifest(
    manifest: dict[str, Any],
    database: Path | None = None,
    *,
    require_resolved: bool = True,
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        actual_version = manifest.get("schema_version")
        errors.append(f"unknown schema version: expected {SCHEMA_VERSION}, got {actual_version}")
    source = manifest.get("source", {})
    if source.get("url_normalization_version") != SOURCE_NORMALIZATION_VERSION:
        errors.append("source normalization version is not url-normalization-v1")
    if source.get("candidate_version") != CANDIDATE_VERSION:
        errors.append("candidate normalization reference version is unexpected")
    if manifest.get("manifest_checksum") != manifest_checksum(manifest):
        errors.append("manifest checksum does not match decisions/source identity")
    group_ids: set[str] = set()
    for group in manifest.get("groups", []):
        group_id = str(group.get("group_id"))
        if group_id in group_ids:
            errors.append(f"duplicate group ID: {group_id}")
        group_ids.add(group_id)
        candidates = {str(item.get("candidate_id")) for item in group.get("candidates", [])}
        if len(candidates) != len(group.get("candidates", [])):
            errors.append(f"{group_id}: duplicate candidate ID")
        if group.get("classification") == "candidate_v2_merge":
            errors.append(f"{group_id}: candidate merge is fail-closed")
        if group.get("classification") != "split":
            continue
        for workspace in group.get("workspace", []):
            prefix = f"{group_id}/site-page-{workspace.get('site_page_id')}"
            decisions = workspace.get("decisions", {})
            primary = decisions.get("primary_candidate_id")
            if group.get("classification") == "split" and not primary and require_resolved:
                errors.append(f"{prefix}: primary candidate is unresolved")
            elif primary and primary not in candidates:
                errors.append(f"{prefix}: primary candidate is unknown: {primary}")
            for field in ("owner_label", "workflow_status"):
                _validate_decision(
                    decisions.get(field),
                    candidates,
                    f"{prefix}/{field}",
                    errors,
                    allow_unresolved=not require_resolved,
                )
            for field in ("categories", "exclusions", "notes"):
                expected_ids = {str(item["id"]) for item in workspace.get(field, [])}
                actual = decisions.get(field, {})
                missing = expected_ids - set(actual)
                unknown = set(actual) - expected_ids
                if missing:
                    errors.append(f"{prefix}/{field}: missing decisions {sorted(missing)}")
                if unknown:
                    errors.append(f"{prefix}/{field}: unknown records {sorted(unknown)}")
                for row_id, decision in actual.items():
                    _validate_decision(
                        decision,
                        candidates,
                        f"{prefix}/{field}/{row_id}",
                        errors,
                        allow_reset=field != "notes",
                        allow_unresolved=not require_resolved,
                    )
    status = resolution_status(manifest)
    if require_resolved and status != STATUS_READY:
        errors.append(f"manifest status is {status}; operator decisions remain unresolved")
    if database is not None:
        with read_only_database(database) as connection:
            current = source_fingerprint(connection)
        for key in (
            "alembic_head",
            "url_normalization_version",
            "candidate_version",
            "identity_graph_sha256",
            "row_counts",
        ):
            if source.get(key) != current.get(key):
                errors.append(f"stale manifest: source {key} changed")
        if not errors:
            regenerated = export_manifest(
                database,
                show_urls=not manifest.get("privacy", {}).get("urls_redacted", True),
            )
            expected = {item["group_id"] for item in regenerated.get("groups", [])}
            actual = {item["group_id"] for item in manifest.get("groups", [])}
            if expected != actual:
                errors.append("stale manifest: split/rekey group population changed")
    return errors


def _validate_decision(
    decision: Any,
    candidate_ids: set[str],
    label: str,
    errors: list[str],
    *,
    allow_reset: bool = True,
    allow_unresolved: bool = False,
) -> None:
    if not isinstance(decision, dict):
        errors.append(f"{label}: missing decision object")
        return
    action = decision.get("action")
    targets = decision.get("candidate_ids", [])
    if action not in DECISION_ACTIONS:
        errors.append(f"{label}: unknown action {action}")
        return
    if len(targets) != len(set(targets)):
        errors.append(f"{label}: duplicate candidate target")
    unknown = set(targets) - candidate_ids
    if unknown:
        errors.append(f"{label}: unknown candidate targets {sorted(unknown)}")
    if action == "UNRESOLVED":
        if not allow_unresolved:
            errors.append(f"{label}: unresolved")
    elif action == "ASSIGN" and len(targets) != 1:
        errors.append(f"{label}: ASSIGN requires exactly one candidate")
    elif action == "DUPLICATE" and len(targets) < 2:
        errors.append(f"{label}: DUPLICATE requires at least two explicit candidates")
    elif action == "RESET" and (targets or not allow_reset):
        errors.append(f"{label}: RESET is not valid with targets or for this field")


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    os.replace(temporary, path)


def load_manifest(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def render_report(manifest: dict[str, Any]) -> str:
    split_groups = [
        item for item in manifest.get("groups", []) if item.get("classification") == "split"
    ]
    sections = []
    for group in split_groups:
        candidates = "".join(
            f"<li><code>{html.escape(str(item['normalized_url']))}</code> "
            f"<small>{html.escape(item['candidate_id'])}</small> "
            f"{html.escape(json.dumps(item['evidence_counts'], sort_keys=True))}</li>"
            for item in group["candidates"]
        )
        workspaces = []
        for page in group.get("workspace", []):
            categories = (
                ", ".join(
                    html.escape(str(item.get("category_name") or item["category_id"]))
                    for item in page["categories"]
                )
                or "None"
            )
            workspaces.append(
                "<div class='workspace'>"
                f"<strong>Site {page['website_property_id']}</strong> &middot; "
                f"Owner: {html.escape(str(page.get('owner_label') or 'None'))} &middot; "
                f"Workflow: {html.escape(str(page.get('workflow_status')))}<br>"
                f"Categories: {categories}; exclusions: {len(page['exclusions'])}; "
                f"notes: {len(page['notes'])}; decision: "
                f"{html.escape(str(page['decisions'].get('primary_candidate_id') or 'UNRESOLVED'))}"
                "</div>"
            )
        suggestions = (
            "".join(
                f"<li>{html.escape(item['rationale'])}: "
                f"<code>{html.escape(item['candidate_id'])}</code>"
                " (operator acceptance required)</li>"
                for item in group.get("suggestions", [])
            )
            or "<li>None</li>"
        )
        context = group.get("context", {})
        latest_title = html.escape(str(context.get("latest_title") or "Unavailable"))
        latest_http = html.escape(str(context.get("latest_http_status") or "Unavailable"))
        technical_id = html.escape(group["group_id"])
        sections.append(
            "<section>"
            f"<h2>{html.escape(str(group['resource']['current_normalized_url']))}</h2>"
            f"<p><strong>Reasons:</strong> {html.escape(', '.join(group['reason_categories']))}<br>"
            f"<strong>Latest title:</strong> {latest_title}<br>"
            f"<strong>Latest HTTP:</strong> {latest_http}</p>"
            f"<h3>Candidate identities</h3><ul>{candidates}</ul>"
            f"<h3>Workspace state</h3>{''.join(workspaces) or '<p>No SitePage.</p>'}"
            f"<h3>Deterministic suggestions</h3><ul>{suggestions}</ul>"
            f"<details><summary>Technical IDs</summary><code>{technical_id}</code>"
            f"<pre>{html.escape(json.dumps(group['resource'], indent=2))}</pre></details>"
            "</section>"
        )
    summary = manifest.get("summary", {})
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Site Ledger URL identity reconciliation</title>
<style>
body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222}}
section{{border-top:1px solid #bbb;padding:1rem 0}} code,pre{{overflow-wrap:anywhere}}
.workspace{{padding:.5rem 0}} small{{color:#666}} table{{border-collapse:collapse}}
td,th{{padding:.4rem;border:1px solid #ccc;text-align:left}}
</style></head>
<body><h1>URL identity reconciliation review</h1>
<p>Status: <strong>{html.escape(resolution_status(manifest))}</strong>.
This report is review-only; it never applies decisions.</p>
<table>
<tr><th>Split groups</th><td>{len(split_groups)}</td></tr>
<tr><th>One-to-one rekeys</th><td>{summary.get("rekey_count", 0)}</td></tr>
<tr><th>Insufficient provenance</th><td>{summary.get("insufficient_provenance_count", 0)}</td></tr>
<tr><th>Suggestions</th><td>{summary.get("suggested_outcome_count", 0)}</td></tr>
</table>
{"".join(sections) or "<p>No split groups.</p>"}</body></html>"""


def operation_plan(manifest: dict[str, Any], database: Path) -> dict[str, Any]:
    errors = validate_manifest(manifest, database, require_resolved=True)
    if manifest.get("privacy", {}).get("urls_redacted", True):
        errors.append("full URL manifest required for planning; export with --show-urls")
    if errors:
        raise ReconciliationError("\n".join(errors))
    operations: list[dict[str, Any]] = []
    for group in manifest["groups"]:
        if group["classification"] not in {"rekey", "split"}:
            continue
        temporary_identity = "urn:site-ledger:url-reconcile:" + group["group_id"].split(":")[1]
        operations.append(
            {
                "operation": "prepare_resource_identity",
                "group_id": group["group_id"],
                "resource_id": group["resource"]["id"],
                "temporary_identity": temporary_identity,
            }
        )
        for candidate in group["candidates"]:
            operations.append(
                {
                    "operation": "ensure_candidate_resource",
                    "group_id": group["group_id"],
                    "candidate_id": candidate["candidate_id"],
                    "normalized_url": candidate["normalized_url"],
                }
            )
            operations.extend(
                {
                    "operation": "reassign_evidence",
                    "group_id": group["group_id"],
                    "candidate_id": candidate["candidate_id"],
                    **item,
                }
                for item in candidate["attributions"]
            )
        for workspace in group.get("workspace", []):
            operations.append(
                {
                    "operation": "reconcile_site_page",
                    "group_id": group["group_id"],
                    "site_page_id": workspace["site_page_id"],
                    "decisions": workspace["decisions"],
                }
            )
    for item in manifest.get("insufficient_provenance", []):
        operations.append(
            {
                "operation": "grandfather_v1_identity",
                "group_id": item["group_id"],
                "resource_id": item["resource_id"],
                "policy": item["policy"],
            }
        )
    affected = [
        int(group["resource"]["id"])
        for group in manifest["groups"]
        if group["classification"] in {"rekey", "split"}
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_checksum": manifest_checksum(manifest),
        "status": "READY_FOR_PR30_IMPLEMENTATION",
        "source_fingerprint": manifest["source"],
        "operation_order": [
            "fail_closed_guards_and_verified_backup",
            "temporary_identity_keys",
            "create_candidate_resources",
            "reassign_mechanically_attributable_evidence",
            "create_and_reconcile_site_pages",
            "preserve_manual_categories_and_re_evaluate_rule_supports",
            "reconcile_exclusions_and_notes",
            "invalidate_and_rebuild_projections",
            "invalidate_and_rebuild_comparisons",
            "record_migration_provenance_and_aliases",
            "verify_invariants_then_commit",
        ],
        "affected_resource_ids": affected,
        "operations": operations,
        "operation_counts": dict(sorted(Counter(item["operation"] for item in operations).items())),
    }


def sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    source_connection = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _active_jobs(connection: sqlite3.Connection) -> int:
    if "background_jobs" not in _table_names(connection):
        return 0
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM background_jobs WHERE status IN ('queued','running','cancelling')"
        ).fetchone()[0]
    )


def _hash_column_set(connection: sqlite3.Connection, table: str, column: str) -> list[str]:
    if table not in _table_names(connection) or column not in _columns(connection, table):
        return []
    return sorted(
        str(row[0])
        for row in connection.execute(
            f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
        )
    )


def invariant_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = _table_names(connection)
    counts = {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in sorted(COUNT_TABLES)
        if table in tables
    }
    return {
        "counts": counts,
        "content_blob_hashes": _hash_column_set(connection, "content_blobs", "sha256"),
        "performance_payload_hashes": _hash_column_set(
            connection, "performance_payloads", "sha256"
        ),
        "accessibility_payload_hashes": _hash_column_set(
            connection, "accessibility_payloads", "sha256"
        ),
        "structured_content_hashes": _hash_column_set(
            connection, "html_structured_content_artifacts", "document_text_sha256"
        ),
    }


def _insert_candidate_resource(
    connection: sqlite3.Connection,
    source_row: sqlite3.Row,
    candidate_url: str,
) -> int:
    parts = normalize_url_v2(candidate_url)
    columns = _columns(connection, "web_resources")
    values: dict[str, Any] = {
        "resource_type": source_row["resource_type"],
        "normalization_version": URL_NORMALIZATION_V2_VERSION,
        "normalized_url": parts.normalized_url,
        "scheme": parts.scheme,
        "host": parts.host,
        "port": parts.port,
        "path": parts.path,
        "query": parts.query,
    }
    for timestamp in ("first_seen_at", "last_seen_at"):
        if timestamp in columns:
            values[timestamp] = source_row[timestamp]
    selected = [key for key in values if key in columns]
    placeholders = ", ".join("?" for _ in selected)
    connection.execute(
        f"INSERT INTO web_resources ({', '.join(selected)}) VALUES ({placeholders})",
        tuple(values[key] for key in selected),
    )
    return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])


def _update_resource_identity(
    connection: sqlite3.Connection, resource_id: int, candidate_url: str
) -> None:
    parts = normalize_url_v2(candidate_url)
    columns = _columns(connection, "web_resources")
    values = {
        "normalization_version": URL_NORMALIZATION_V2_VERSION,
        "normalized_url": parts.normalized_url,
        "scheme": parts.scheme,
        "host": parts.host,
        "port": parts.port,
        "path": parts.path,
        "query": parts.query,
    }
    selected = [key for key in values if key in columns]
    connection.execute(
        "UPDATE web_resources SET "
        + ", ".join(f'"{key}" = ?' for key in selected)
        + " WHERE id = ?",
        tuple(values[key] for key in selected) + (resource_id,),
    )


def _candidate_maps(
    group: dict[str, Any], connection: sqlite3.Connection
) -> tuple[dict[str, int], dict[str, str]]:
    source_id = int(group["resource"]["id"])
    source_row = connection.execute(
        "SELECT * FROM web_resources WHERE id = ?", (source_id,)
    ).fetchone()
    assert source_row is not None
    candidate_urls = {
        item["candidate_id"]: str(item["normalized_url"]) for item in group["candidates"]
    }
    if group["classification"] == "rekey":
        candidate_id = next(iter(candidate_urls))
        return {candidate_id: source_id}, candidate_urls
    primary_ids = {
        item["decisions"]["primary_candidate_id"]
        for item in group.get("workspace", [])
        if item.get("decisions", {}).get("primary_candidate_id")
    }
    if len(primary_ids) > 1:
        raise ReconciliationError(
            f"{group['group_id']}: SitePages disagree on old-resource primary candidate"
        )
    primary = next(iter(primary_ids), min(candidate_urls))
    mapping = {primary: source_id}
    for candidate_id in sorted(candidate_urls):
        if candidate_id != primary:
            mapping[candidate_id] = _insert_candidate_resource(
                connection, source_row, candidate_urls[candidate_id]
            )
    return mapping, candidate_urls


def _apply_attributions(
    connection: sqlite3.Connection,
    group: dict[str, Any],
    candidate_resources: dict[str, int],
    candidate_urls: dict[str, str],
) -> None:
    tables = _table_names(connection)
    seen: set[tuple[str, int, str]] = set()
    for candidate in group["candidates"]:
        candidate_id = candidate["candidate_id"]
        for item in candidate["attributions"]:
            table = item["table"]
            row_id = int(item["row_id"])
            resource_column = item["resource_column"]
            if item["domain"] == "scan_seed_origin":
                continue
            key = (table, row_id, resource_column)
            if key in seen or table not in tables:
                continue
            seen.add(key)
            assignments = [f'"{resource_column}" = ?']
            params: list[Any] = [candidate_resources[candidate_id]]
            normalized = item.get("normalized_column")
            if normalized and normalized in _columns(connection, table):
                assignments.append(f'"{normalized}" = ?')
                params.append(candidate_urls[candidate_id])
            params.append(row_id)
            connection.execute(
                f'UPDATE "{table}" SET {", ".join(assignments)} WHERE id = ?', params
            )


def _reconcile_seed_origins(
    connection: sqlite3.Connection,
    group: dict[str, Any],
    candidate_resources: dict[str, int],
    candidate_urls: dict[str, str],
) -> int:
    if not {"scan_seeds", "scan_seed_origins"} <= _table_names(connection):
        return 0
    created = 0
    seed_columns = _columns(connection, "scan_seeds")
    for candidate in group["candidates"]:
        candidate_id = candidate["candidate_id"]
        for item in candidate["attributions"]:
            if item["domain"] != "scan_seed_origin":
                continue
            origin_id = int(item["row_id"])
            parent = connection.execute(
                "SELECT ss.* FROM scan_seed_origins sso "
                "JOIN scan_seeds ss ON ss.id = sso.scan_seed_id WHERE sso.id = ?",
                (origin_id,),
            ).fetchone()
            if parent is None:
                raise ReconciliationError(f"scan seed origin disappeared: {origin_id}")
            target_url = candidate_urls[candidate_id]
            existing = connection.execute(
                "SELECT id FROM scan_seeds WHERE scan_id = ? AND normalized_url = ?",
                (parent["scan_id"], target_url),
            ).fetchone()
            if existing:
                target_seed_id = int(existing["id"])
            else:
                values = {key: parent[key] for key in seed_columns if key != "id" and key in parent}
                values["resource_id"] = candidate_resources[candidate_id]
                values["normalized_url"] = target_url
                values["requested_url"] = target_url
                selected = sorted(values)
                connection.execute(
                    f"INSERT INTO scan_seeds ({', '.join(selected)}) VALUES "
                    f"({', '.join('?' for _ in selected)})",
                    tuple(values[key] for key in selected),
                )
                target_seed_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                created += 1
            connection.execute(
                "UPDATE scan_seed_origins SET scan_seed_id = ? WHERE id = ?",
                (target_seed_id, origin_id),
            )
    return created


def _site_page_ids_for_candidates(
    connection: sqlite3.Connection,
    workspace: dict[str, Any],
    candidate_resources: dict[str, int],
) -> dict[str, int]:
    original_id = int(workspace["site_page_id"])
    website_property_id = int(workspace["website_property_id"])
    primary = workspace["decisions"]["primary_candidate_id"]
    result: dict[str, int] = {}
    columns = _columns(connection, "site_pages")
    for candidate_id, resource_id in candidate_resources.items():
        if candidate_id == primary:
            connection.execute(
                "UPDATE site_pages SET resource_id = ? WHERE id = ?",
                (resource_id, original_id),
            )
            result[candidate_id] = original_id
            continue
        values: dict[str, Any] = {
            "website_property_id": website_property_id,
            "resource_id": resource_id,
            "owner_label": None,
            "workflow_status": "unreviewed",
        }
        selected = [key for key in values if key in columns]
        connection.execute(
            f"INSERT INTO site_pages ({', '.join(selected)}) VALUES "
            f"({', '.join('?' for _ in selected)})",
            tuple(values[key] for key in selected),
        )
        result[candidate_id] = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
    return result


def _decision_targets(decision: dict[str, Any], candidate_pages: dict[str, int]) -> list[int]:
    return [candidate_pages[item] for item in decision.get("candidate_ids", [])]


def _apply_workspace(
    connection: sqlite3.Connection,
    group: dict[str, Any],
    candidate_resources: dict[str, int],
) -> None:
    tables = _table_names(connection)
    for workspace in group.get("workspace", []):
        decisions = workspace["decisions"]
        candidate_pages = _site_page_ids_for_candidates(connection, workspace, candidate_resources)
        for field, default in (
            ("owner_label", None),
            ("workflow_status", "unreviewed"),
        ):
            if field not in _columns(connection, "site_pages"):
                continue
            connection.executemany(
                f'UPDATE site_pages SET "{field}" = ? WHERE id = ?',
                [(default, page_id) for page_id in candidate_pages.values()],
            )
            decision = decisions[field]
            value = workspace.get(field)
            connection.executemany(
                f'UPDATE site_pages SET "{field}" = ? WHERE id = ?',
                [(value, page_id) for page_id in _decision_targets(decision, candidate_pages)],
            )
        _apply_categories(connection, workspace, decisions, candidate_pages, tables)
        _apply_exclusions(connection, workspace, decisions, candidate_pages, tables)
        _apply_notes(connection, workspace, decisions, candidate_pages, tables)
        _reevaluate_category_rules(
            connection,
            int(workspace["website_property_id"]),
            candidate_pages.values(),
            tables,
        )


def _apply_categories(
    connection: sqlite3.Connection,
    workspace: dict[str, Any],
    decisions: dict[str, Any],
    candidate_pages: dict[str, int],
    tables: set[str],
) -> None:
    if "page_category_assignments" not in tables:
        return
    for assignment in workspace["categories"]:
        original_id = int(assignment["id"])
        manual = any(item.get("support_type") == "manual" for item in assignment["supports"])
        if "page_category_assignment_supports" in tables:
            connection.execute(
                "DELETE FROM page_category_assignment_supports "
                "WHERE page_category_assignment_id = ?",
                (original_id,),
            )
        connection.execute("DELETE FROM page_category_assignments WHERE id = ?", (original_id,))
        targets = _decision_targets(decisions["categories"][str(original_id)], candidate_pages)
        for page_id in targets:
            connection.execute(
                "INSERT INTO page_category_assignments (site_page_id, category_id) VALUES (?, ?)",
                (page_id, assignment["category_id"]),
            )
            new_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            if manual and "page_category_assignment_supports" in tables:
                connection.execute(
                    "INSERT INTO page_category_assignment_supports "
                    "(page_category_assignment_id, support_type, rule_id, support_key) "
                    "VALUES (?, 'manual', NULL, 'manual')",
                    (new_id,),
                )


def _apply_exclusions(
    connection: sqlite3.Connection,
    workspace: dict[str, Any],
    decisions: dict[str, Any],
    candidate_pages: dict[str, int],
    tables: set[str],
) -> None:
    if "page_category_automatic_exclusions" not in tables:
        return
    for item in workspace["exclusions"]:
        row_id = int(item["id"])
        connection.execute("DELETE FROM page_category_automatic_exclusions WHERE id = ?", (row_id,))
        for page_id in _decision_targets(decisions["exclusions"][str(row_id)], candidate_pages):
            connection.execute(
                "INSERT INTO page_category_automatic_exclusions "
                "(site_page_id, category_id, reason) VALUES (?, ?, ?)",
                (page_id, item["category_id"], item.get("reason")),
            )


def _apply_notes(
    connection: sqlite3.Connection,
    workspace: dict[str, Any],
    decisions: dict[str, Any],
    candidate_pages: dict[str, int],
    tables: set[str],
) -> None:
    if "notes" not in tables:
        return
    note_columns = _columns(connection, "notes")
    for item in workspace["notes"]:
        row_id = int(item["id"])
        targets = _decision_targets(decisions["notes"][str(row_id)], candidate_pages)
        connection.execute("UPDATE notes SET site_page_id = ? WHERE id = ?", (targets[0], row_id))
        for page_id in targets[1:]:
            values = {
                "site_page_id": page_id,
                "body": item["body"],
                "is_pinned": item.get("is_pinned", False),
            }
            selected = [key for key in values if key in note_columns]
            connection.execute(
                f"INSERT INTO notes ({', '.join(selected)}) VALUES "
                f"({', '.join('?' for _ in selected)})",
                tuple(values[key] for key in selected),
            )


def _reevaluate_category_rules(
    connection: sqlite3.Connection,
    website_property_id: int,
    site_page_ids: Iterable[int],
    tables: set[str],
) -> None:
    required = {
        "page_category_rules",
        "page_category_rule_conditions",
        "page_category_assignments",
        "page_category_assignment_supports",
    }
    if not required <= tables:
        return
    rules = _rows(
        connection,
        "SELECT id, category_id, match_mode FROM page_category_rules "
        "WHERE website_property_id = ? AND is_active = 1 ORDER BY id",
        (website_property_id,),
    )
    exclusions = "page_category_automatic_exclusions" in tables
    for site_page_id in site_page_ids:
        page = connection.execute(
            "SELECT wr.normalized_url FROM site_pages sp "
            "JOIN web_resources wr ON wr.id = sp.resource_id WHERE sp.id = ?",
            (site_page_id,),
        ).fetchone()
        if not page:
            continue
        url = str(page["normalized_url"])
        for rule in rules:
            conditions = _rows(
                connection,
                "SELECT target, operator, value, negate, case_sensitive "
                "FROM page_category_rule_conditions WHERE rule_id = ? "
                "ORDER BY sort_order, id",
                (rule["id"],),
            )
            results = [_condition_matches(url, item) for item in conditions]
            matches = bool(results) and (
                all(results) if rule["match_mode"] == "all" else any(results)
            )
            if not matches:
                continue
            if exclusions:
                excluded = connection.execute(
                    "SELECT 1 FROM page_category_automatic_exclusions "
                    "WHERE site_page_id = ? AND category_id = ?",
                    (site_page_id, rule["category_id"]),
                ).fetchone()
                if excluded:
                    continue
            assignment = connection.execute(
                "SELECT id FROM page_category_assignments "
                "WHERE site_page_id = ? AND category_id = ?",
                (site_page_id, rule["category_id"]),
            ).fetchone()
            if assignment:
                assignment_id = int(assignment["id"])
            else:
                connection.execute(
                    "INSERT INTO page_category_assignments (site_page_id, category_id) "
                    "VALUES (?, ?)",
                    (site_page_id, rule["category_id"]),
                )
                assignment_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.execute(
                "INSERT OR IGNORE INTO page_category_assignment_supports "
                "(page_category_assignment_id, support_type, rule_id, support_key) "
                "VALUES (?, 'rule', ?, ?)",
                (assignment_id, rule["id"], f"rule:{rule['id']}"),
            )


def _invalidate_derivatives(
    connection: sqlite3.Connection, resource_ids: Sequence[int]
) -> dict[str, int]:
    if not resource_ids:
        return {}
    tables = _table_names(connection)
    counts: dict[str, int] = {}
    placeholders = ",".join("?" for _ in resource_ids)
    for table, columns in DERIVATIVE_TABLE_COLUMNS:
        if table not in tables:
            continue
        available = [column for column in columns if column in _columns(connection, table)]
        if not available:
            continue
        predicate = " OR ".join(f'"{column}" IN ({placeholders})' for column in available)
        params = tuple(resource_ids) * len(available)
        count = int(
            connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE {predicate}', params
            ).fetchone()[0]
        )
        connection.execute(f'DELETE FROM "{table}" WHERE {predicate}', params)
        counts[table] = count
    return counts


def simulate_manifest(
    manifest: dict[str, Any],
    source_database: Path,
    destination: Path,
) -> dict[str, Any]:
    source_before = database_file_state(source_database)
    with read_only_database(source_database) as source_connection:
        if _active_jobs(source_connection):
            raise ReconciliationError("active or queued mutating jobs block identity simulation")
        source_invariants = invariant_snapshot(source_connection)
    plan = operation_plan(manifest, source_database)
    sqlite_backup(source_database, destination)
    connection = sqlite3.connect(destination)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    derivative_removals: dict[str, int] = {}
    identity_rows_created: Counter[str] = Counter()
    try:
        connection.execute("BEGIN IMMEDIATE")
        groups = [
            item for item in manifest["groups"] if item["classification"] in {"rekey", "split"}
        ]
        for group in groups:
            resource_id = int(group["resource"]["id"])
            temporary = f"urn:site-ledger:url-reconcile:{group['group_id'].split(':')[1]}"
            connection.execute(
                "UPDATE web_resources SET normalized_url = ? WHERE id = ?",
                (temporary, resource_id),
            )
        for group in groups:
            mapping, urls = _candidate_maps(group, connection)
            _apply_attributions(connection, group, mapping, urls)
            identity_rows_created["scan_seeds"] += _reconcile_seed_origins(
                connection, group, mapping, urls
            )
            primary_id = int(group["resource"]["id"])
            primary_candidate = next(
                candidate_id
                for candidate_id, resource_id in mapping.items()
                if resource_id == primary_id
            )
            _update_resource_identity(connection, primary_id, urls[primary_candidate])
            if group["classification"] == "split":
                _apply_workspace(connection, group, mapping)
        affected = plan["affected_resource_ids"]
        derivative_removals = _invalidate_derivatives(connection, affected)
        verification = verify_simulation(
            connection,
            source_invariants,
            derivative_removals,
            manifest,
            identity_rows_created,
        )
        if not verification["passed"]:
            raise ReconciliationError(
                "simulation invariants failed: " + "; ".join(verification["errors"])
            )
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        destination.unlink(missing_ok=True)
        raise
    connection.close()
    source_after = database_file_state(source_database)
    if source_before != source_after:
        destination.unlink(missing_ok=True)
        raise ReconciliationError("source database or WAL changed during simulation")
    target_connection = sqlite3.connect(destination)
    target_connection.row_factory = sqlite3.Row
    try:
        verification = verify_simulation(
            target_connection,
            source_invariants,
            derivative_removals,
            manifest,
            identity_rows_created,
        )
    finally:
        target_connection.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "SIMULATION_PASSED" if verification["passed"] else "SIMULATION_FAILED",
        "plan_checksum": plan["plan_checksum"],
        "source_unchanged": source_before == source_after,
        "source_file_state": source_before,
        "destination": str(destination),
        "derivative_rows_invalidated": derivative_removals,
        "identity_rows_created": dict(sorted(identity_rows_created.items())),
        "verification": verification,
    }


def verify_simulation(
    connection: sqlite3.Connection,
    before: dict[str, Any],
    derivative_removals: dict[str, int],
    manifest: dict[str, Any],
    identity_rows_created: Counter[str] | dict[str, int] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    fk_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
    if fk_rows:
        errors.append(f"foreign key violations: {len(fk_rows)}")
    duplicate_resources = 0
    if "web_resources" in _table_names(connection):
        identity_columns = (
            "normalization_version, normalized_url"
            if "normalization_version" in _columns(connection, "web_resources")
            else "resource_type, normalized_url"
        )
        duplicate_resources = int(
            connection.execute(
                f"SELECT COUNT(*) FROM (SELECT {identity_columns} FROM web_resources "
                f"GROUP BY {identity_columns} HAVING COUNT(*) > 1)"
            ).fetchone()[0]
        )
    if duplicate_resources:
        errors.append(f"duplicate WebResource identities: {duplicate_resources}")
    duplicate_pages = 0
    if "site_pages" in _table_names(connection):
        duplicate_pages = int(
            connection.execute(
                "SELECT COUNT(*) FROM (SELECT website_property_id, resource_id FROM site_pages "
                "GROUP BY website_property_id, resource_id HAVING COUNT(*) > 1)"
            ).fetchone()[0]
        )
    if duplicate_pages:
        errors.append(f"duplicate SitePages: {duplicate_pages}")
    after = invariant_snapshot(connection)
    immutable_tables = (
        "resource_snapshots",
        "url_source_entries",
        "scan_seeds",
        "scan_seed_origins",
        "resource_occurrences",
        "resource_reference_occurrences",
        "performance_observations",
        "accessibility_observations",
        "render_run_targets",
        "rendered_observations",
        "ai_document_snapshots",
        "ai_document_references",
        "content_blobs",
        "performance_payloads",
        "accessibility_payloads",
        "html_structured_content_artifacts",
    )
    count_checks: dict[str, bool] = {}
    expected_additions = identity_rows_created or {}
    for table in immutable_tables:
        if table in before["counts"]:
            expected = before["counts"][table] + int(expected_additions.get(table, 0))
            count_checks[table] = expected == after["counts"].get(table)
            if not count_checks[table]:
                errors.append(f"immutable row count changed: {table}")
    hash_checks = {
        "content_blobs": before["content_blob_hashes"] == after["content_blob_hashes"],
        "performance_payloads": before["performance_payload_hashes"]
        == after["performance_payload_hashes"],
        "accessibility_payloads": before["accessibility_payload_hashes"]
        == after["accessibility_payload_hashes"],
        "structured_content": before["structured_content_hashes"]
        == after["structured_content_hashes"],
    }
    errors.extend(
        f"immutable evidence hashes changed: {name}" for name, ok in hash_checks.items() if not ok
    )
    unresolved = resolution_status(manifest) != STATUS_READY
    if unresolved:
        errors.append("unresolved workspace state survived simulation")
    return {
        "passed": not errors,
        "errors": errors,
        "foreign_key_violations": len(fk_rows),
        "web_resource_uniqueness": duplicate_resources == 0,
        "site_page_uniqueness": duplicate_pages == 0,
        "immutable_count_checks": count_checks,
        "immutable_hash_checks": hash_checks,
        "derivative_rows_invalidated": derivative_removals,
        "identity_rows_created": dict(sorted(expected_additions.items())),
        "grandfathered_identity_count": len(manifest.get("insufficient_provenance", [])),
    }


def review_manifest(path: Path) -> None:
    manifest = load_manifest(path)
    if manifest.get("privacy", {}).get("urls_redacted", True):
        raise ReconciliationError("interactive review requires a --show-urls manifest")
    try:
        for group in manifest.get("groups", []):
            if group.get("classification") != "split":
                continue
            candidates = group["candidates"]
            candidate_ids = [item["candidate_id"] for item in candidates]
            print(f"\n{group['resource']['current_normalized_url']}")
            print(f"Reasons: {', '.join(group['reason_categories'])}")
            for index, candidate in enumerate(candidates, 1):
                print(f"  {index}. {candidate['normalized_url']}")
            for workspace in group.get("workspace", []):
                decisions = workspace["decisions"]
                if decisions.get("primary_candidate_id") is None:
                    selected = _prompt_candidate(
                        "Primary candidate for existing resource ID", candidate_ids
                    )
                    if selected:
                        decisions["primary_candidate_id"] = selected
                        _save_review(path, manifest)
                for field in ("owner_label", "workflow_status"):
                    if decisions[field]["action"] == "UNRESOLVED":
                        decision = _prompt_decision(field, candidate_ids, allow_reset=True)
                        if decision:
                            decisions[field] = decision
                            _save_review(path, manifest)
                for field in ("categories", "exclusions", "notes"):
                    for row_id, current in decisions[field].items():
                        if current["action"] != "UNRESOLVED":
                            continue
                        decision = _prompt_decision(
                            f"{field} record {row_id}",
                            candidate_ids,
                            allow_reset=field != "notes",
                        )
                        if decision:
                            decisions[field][row_id] = decision
                            _save_review(path, manifest)
    except KeyboardInterrupt:
        print("\nReview stopped; prior atomic saves are intact.")
    _save_review(path, manifest)


def _prompt_candidate(label: str, candidate_ids: list[str]) -> str | None:
    raw = input(f"{label} [number, s=skip]: ").strip().lower()
    if raw == "s" or not raw:
        return None
    try:
        return candidate_ids[int(raw) - 1]
    except (ValueError, IndexError) as exc:
        raise ReconciliationError(f"invalid candidate selection: {raw}") from exc


def _prompt_decision(
    label: str, candidate_ids: list[str], *, allow_reset: bool
) -> dict[str, Any] | None:
    options = "a=assign, d=duplicate, s=skip" + (", r=reset" if allow_reset else "")
    action = input(f"{label} [{options}]: ").strip().lower()
    if not action or action == "s":
        return None
    if action == "r" and allow_reset:
        return _decision("RESET")
    if action not in {"a", "d"}:
        raise ReconciliationError(f"invalid decision action: {action}")
    raw_targets = input("Candidate numbers (comma separated): ").strip()
    try:
        targets = [candidate_ids[int(value.strip()) - 1] for value in raw_targets.split(",")]
    except (ValueError, IndexError) as exc:
        raise ReconciliationError(f"invalid candidate targets: {raw_targets}") from exc
    decision = _decision("ASSIGN" if action == "a" else "DUPLICATE", targets)
    note = input("Optional decision note: ").strip()
    decision["decision_note"] = note or None
    return decision


def _save_review(path: Path, manifest: dict[str, Any]) -> None:
    manifest["status"] = resolution_status(manifest)
    manifest["manifest_checksum"] = manifest_checksum(manifest)
    write_json_atomic(path, manifest)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="Create manifest and static HTML report")
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--output", type=Path, default=DEFAULT_LOCAL_DIR / "manifest.json")
    export.add_argument("--report", type=Path)
    export.add_argument("--show-urls", action="store_true")
    review = subparsers.add_parser("review", help="Interactively record explicit decisions")
    review.add_argument("manifest", type=Path)
    validate = subparsers.add_parser("validate", help="Validate schema, decisions, and staleness")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    validate.add_argument("--allow-unresolved", action="store_true")
    plan = subparsers.add_parser("plan", help="Generate deterministic migration operations")
    plan.add_argument("manifest", type=Path)
    plan.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    plan.add_argument("--output", type=Path, default=DEFAULT_LOCAL_DIR / "plan.json")
    simulate = subparsers.add_parser("simulate", help="Apply plan only to a SQLite backup copy")
    simulate.add_argument("manifest", type=Path)
    simulate.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    simulate.add_argument("--output-db", type=Path)
    simulate.add_argument("--report", type=Path, default=DEFAULT_LOCAL_DIR / "simulation.json")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        if args.command == "export":
            manifest = export_manifest(args.database, show_urls=args.show_urls)
            write_json_atomic(args.output, manifest)
            report_path = args.report or args.output.with_suffix(".html")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(render_report(manifest), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "manifest": str(args.output),
                        "report": str(report_path),
                        "status": manifest["status"],
                        "summary": manifest["summary"],
                    },
                    indent=2,
                )
            )
        elif args.command == "review":
            review_manifest(args.manifest)
        elif args.command == "validate":
            manifest = load_manifest(args.manifest)
            errors = validate_manifest(
                manifest, args.database, require_resolved=not args.allow_unresolved
            )
            print(json.dumps({"status": resolution_status(manifest), "errors": errors}, indent=2))
            if errors:
                raise SystemExit(2)
        elif args.command == "plan":
            plan = operation_plan(load_manifest(args.manifest), args.database)
            write_json_atomic(args.output, plan)
            print(
                json.dumps(
                    {"output": str(args.output), "counts": plan["operation_counts"]},
                    indent=2,
                )
            )
        elif args.command == "simulate":
            destination = args.output_db
            temporary: tempfile.TemporaryDirectory[str] | None = None
            if destination is None:
                temporary = tempfile.TemporaryDirectory(prefix="site-ledger-url-reconcile-")
                destination = Path(temporary.name) / "simulation.db"
            result = simulate_manifest(load_manifest(args.manifest), args.database, destination)
            write_json_atomic(args.report, result)
            print(json.dumps(result, indent=2))
            if temporary is not None:
                temporary.cleanup()
    except ReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
