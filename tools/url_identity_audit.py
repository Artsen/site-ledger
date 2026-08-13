"""Read-only URL identity audit and conservative candidate-v2 reference.

This module is analysis/reference tooling. It is not production normalization and must
not be imported by crawler or persistence code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "scanner.db"
UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
HEX = frozenset("0123456789abcdefABCDEF")
PATH_SAFE = "/:@!$&'()*+,;=-._~%"
QUERY_SAFE = "!$'()*+,-./:;=?@_~%[]"
MAX_GROUP_EXAMPLES = 20


class CandidateNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateUrl:
    normalized_url: str
    scheme: str
    host: str
    port: int | None
    path: str
    query: str


@dataclass(frozen=True)
class EvidenceSource:
    name: str
    table: str
    resource_column: str
    url_column: str
    joins: str = ""
    scope_column: str | None = None
    category: str = "relationship_evidence"


EVIDENCE_SOURCES = (
    EvidenceSource(
        "resource_snapshots.requested_url",
        "resource_snapshots rs",
        "rs.resource_id",
        "rs.requested_url",
        "LEFT JOIN scans s ON s.id = rs.scan_id",
        "s.scope_config",
        "immutable_scan_evidence",
    ),
    EvidenceSource(
        "url_source_entries.raw_url",
        "url_source_entries use",
        "use.resource_id",
        "use.raw_url",
        "LEFT JOIN url_sources us ON us.id = use.url_source_id "
        "LEFT JOIN website_properties wp ON wp.id = us.website_property_id",
        "wp.scope_config",
    ),
    EvidenceSource(
        "scan_seeds.requested_url",
        "scan_seeds ss",
        "ss.resource_id",
        "ss.requested_url",
        "LEFT JOIN scans s ON s.id = ss.scan_id",
        "s.scope_config",
        "immutable_scan_evidence",
    ),
    EvidenceSource(
        "scan_seed_origins.raw_url",
        "scan_seed_origins sso",
        "ss.resource_id",
        "sso.raw_url",
        "JOIN scan_seeds ss ON ss.id = sso.scan_seed_id LEFT JOIN scans s ON s.id = ss.scan_id",
        "s.scope_config",
        "immutable_scan_evidence",
    ),
    EvidenceSource(
        "resource_occurrences.resolved_url",
        "resource_occurrences ro",
        "ro.target_resource_id",
        "ro.resolved_url",
        "LEFT JOIN resource_snapshots rs ON rs.id = ro.source_snapshot_id "
        "LEFT JOIN scans s ON s.id = rs.scan_id",
        "s.scope_config",
    ),
    EvidenceSource(
        "resource_reference_occurrences.resolved_url",
        "resource_reference_occurrences rro",
        "rro.target_resource_id",
        "rro.resolved_url",
        "LEFT JOIN resource_snapshots rs ON rs.id = rro.source_snapshot_id "
        "LEFT JOIN scans s ON s.id = rs.scan_id",
        "s.scope_config",
    ),
    EvidenceSource(
        "performance_observations.requested_target",
        "performance_observations po",
        "po.web_resource_id",
        "po.requested_target",
        "LEFT JOIN website_properties wp ON wp.id = po.website_property_id",
        "wp.scope_config",
        "performance_observation",
    ),
    EvidenceSource(
        "accessibility_observations.requested_url",
        "accessibility_observations ao",
        "ao.web_resource_id",
        "ao.requested_url",
        "LEFT JOIN website_properties wp ON wp.id = ao.website_property_id",
        "wp.scope_config",
        "accessibility_observation",
    ),
    EvidenceSource(
        "ai_document_snapshots.requested_url",
        "ai_document_snapshots ads",
        "ads.resource_id",
        "ads.requested_url",
        category="immutable_scan_evidence",
    ),
    EvidenceSource(
        "ai_document_references.resolved_url",
        "ai_document_references adr",
        "adr.target_resource_id",
        "adr.resolved_url",
    ),
)

COUNT_TABLES = (
    "website_properties",
    "web_resources",
    "site_pages",
    "resource_snapshots",
    "url_source_entries",
    "scan_seeds",
    "scan_seed_origins",
    "resource_occurrences",
    "resource_reference_occurrences",
    "performance_observations",
    "accessibility_observations",
    "ai_document_snapshots",
    "ai_document_references",
)

PROVENANCE_ONLY_FIELDS = (
    ("website_properties", "base_url"),
    ("website_properties", "normalized_base_url"),
    ("scans", "starting_url"),
    ("web_resources", "normalized_url"),
    ("resource_snapshots", "final_url"),
    ("url_sources", "source_url"),
    ("url_sources", "normalized_source_url"),
    ("url_source_entries", "normalized_url"),
    ("scan_seeds", "normalized_url"),
    ("resource_occurrences", "raw_href"),
    ("resource_occurrences", "normalized_target_url"),
    ("resource_reference_occurrences", "raw_url"),
    ("resource_reference_occurrences", "normalized_target_url"),
    ("html_parse_anchors", "raw_href"),
    ("html_parse_anchors", "resolved_url"),
    ("html_parse_resource_references", "raw_url"),
    ("html_parse_resource_references", "resolved_url"),
    ("performance_observations", "provider_target"),
    ("performance_observations", "target_key"),
    ("accessibility_observations", "final_url"),
    ("ai_document_snapshots", "final_url"),
    ("ai_document_references", "raw_url"),
    ("ai_document_references", "normalized_target_url"),
)


def candidate_normalize_url(raw_url: str, drop_query_params: Iterable[str] = ()) -> CandidateUrl:
    """Return a conservative analysis-only identity candidate.

    Reserved escapes, query ordering, repeated separators, key-only parameters, and
    plus signs remain observable. Only literal path dot segments are removed.
    """
    candidate = raw_url.strip()
    if not candidate:
        raise CandidateNormalizationError("URL is empty")
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as exc:
        raise CandidateNormalizationError(str(exc)) from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise CandidateNormalizationError("absolute HTTP(S) URL required")
    if parts.username is not None or parts.password is not None:
        raise CandidateNormalizationError("credential-bearing URLs are not candidate identities")
    try:
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise CandidateNormalizationError(str(exc)) from exc
    if not host:
        raise CandidateNormalizationError("URL host is missing")
    if (scheme, port) in {("http", 80), ("https", 443)}:
        port = None
    path = _normalize_candidate_path(parts.path or "/")
    query = _normalize_candidate_query(parts.query, tuple(drop_query_params))
    authority_host = f"[{host}]" if ":" in host else host
    authority = authority_host if port is None else f"{authority_host}:{port}"
    return CandidateUrl(
        normalized_url=urlunsplit((scheme, authority, path, query, "")),
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        query=query,
    )


def _normalize_candidate_path(path: str) -> str:
    escaped = _normalize_percent_encoding(path, decode_dot=False)
    without_dots = _remove_literal_dot_segments(escaped)
    return quote(without_dots, safe=PATH_SAFE)


def _normalize_candidate_query(query: str, drop_patterns: tuple[str, ...]) -> str:
    if not query:
        return ""
    kept: list[str] = []
    for component in query.split("&"):
        raw_key = component.split("=", 1)[0]
        try:
            key = unquote_plus(raw_key)
        except UnicodeDecodeError:
            key = raw_key
        if _should_drop(key, drop_patterns):
            continue
        kept.append(quote(_normalize_percent_encoding(component), safe=QUERY_SAFE))
    return "&".join(kept)


def _normalize_percent_encoding(value: str, *, decode_dot: bool = True) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "%":
            if index + 2 < len(value) and value[index + 1] in HEX and value[index + 2] in HEX:
                octet = int(value[index + 1 : index + 3], 16)
                decoded = chr(octet)
                if decoded in UNRESERVED and (decode_dot or decoded != "."):
                    output.append(decoded)
                else:
                    output.append(f"%{octet:02X}")
                index += 3
                continue
            output.append("%25")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _remove_literal_dot_segments(path: str) -> str:
    # RFC 3986 section 5.2.4, applied before any encoded-dot decoding.
    input_buffer = path
    output = ""
    while input_buffer:
        if input_buffer.startswith("../"):
            input_buffer = input_buffer[3:]
        elif input_buffer.startswith("./"):
            input_buffer = input_buffer[2:]
        elif input_buffer.startswith("/./"):
            input_buffer = "/" + input_buffer[3:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = "/" + input_buffer[4:]
            output = output.rsplit("/", 1)[0]
        elif input_buffer == "/..":
            input_buffer = "/"
            output = output.rsplit("/", 1)[0]
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            match = re.match(r"^(/?[^/]*)", input_buffer)
            assert match is not None
            segment = match.group(1)
            output += segment
            input_buffer = input_buffer[len(segment) :]
    return output or "/"


def _should_drop(key: str, patterns: tuple[str, ...]) -> bool:
    return any(
        (pattern.endswith("*") and key.startswith(pattern[:-1])) or key == pattern
        for pattern in patterns
    )


def _drop_patterns(scope_json: Any) -> tuple[str, ...]:
    if not scope_json:
        return ()
    try:
        value = json.loads(scope_json) if isinstance(scope_json, str) else scope_json
    except (TypeError, json.JSONDecodeError):
        return ()
    patterns = value.get("drop_query_parameters", []) if isinstance(value, dict) else []
    return tuple(str(item) for item in patterns if isinstance(item, str))


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _source_available(
    connection: sqlite3.Connection, source: EvidenceSource, tables: set[str]
) -> bool:
    base_table = source.table.split()[0]
    return base_table in tables and source.url_column.split(".")[-1] in _columns(
        connection, base_table
    )


def _resource_label(url: str, show_urls: bool) -> str:
    return url if show_urls else f"sha256:{hashlib.sha256(url.encode()).hexdigest()}"


def _signal_counts(urls: Counter[str]) -> dict[str, dict[str, int]]:
    patterns = {
        "encoded_slash": re.compile(r"%2f", re.IGNORECASE),
        "encoded_question_mark": re.compile(r"%3f", re.IGNORECASE),
        "encoded_fragment_delimiter": re.compile(r"%23", re.IGNORECASE),
        "encoded_dot_segment": re.compile(r"/(?:%2e)(?:%2e)?(?:/|$)", re.IGNORECASE),
        "repeated_query_parameter": re.compile(
            r"[?&]([^&=]+)=[^&]*&(?:[^&]*&)*?\1=", re.IGNORECASE
        ),
        "key_only_query_parameter": re.compile(r"[?&][^&=]+(?:&|$)"),
        "plus_in_query": re.compile(r"\?[^#]*\+"),
        "percent_space_in_query": re.compile(r"\?[^#]*%20", re.IGNORECASE),
        "explicit_default_port": re.compile(
            r"^http://[^/]+:80(?:/|$)|^https://[^/]+:443(?:/|$)", re.IGNORECASE
        ),
        "idna_host": re.compile(r"^https?://(?:[^/@]+@)?[^/]*xn--", re.IGNORECASE),
    }
    result: dict[str, dict[str, int]] = {}
    for name, pattern in patterns.items():
        matching = [(url, count) for url, count in urls.items() if pattern.search(url)]
        result[name] = {
            "rows": sum(count for _url, count in matching),
            "distinct_spellings": len(matching),
        }
    result["plus_space_ambiguity"] = {
        "rows": result["plus_in_query"]["rows"] + result["percent_space_in_query"]["rows"],
        "distinct_spellings": result["plus_in_query"]["distinct_spellings"]
        + result["percent_space_in_query"]["distinct_spellings"],
    }
    for name, escape in (
        ("encoded_slash", "%2f"),
        ("encoded_question_mark", "%3f"),
        ("encoded_fragment_delimiter", "%23"),
    ):
        path_matches = [
            (url, count) for url, count in urls.items() if escape in urlsplit(url).path.lower()
        ]
        query_matches = [
            (url, count) for url, count in urls.items() if escape in urlsplit(url).query.lower()
        ]
        result[f"{name}_in_path"] = {
            "rows": sum(count for _url, count in path_matches),
            "distinct_spellings": len(path_matches),
        }
        result[f"{name}_in_query"] = {
            "rows": sum(count for _url, count in query_matches),
            "distinct_spellings": len(query_matches),
        }
    return result


def audit_database(database: Path, *, show_urls: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    database = database.resolve()
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    try:
        tables = _table_names(connection)
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if table in tables
            else 0
            for table in COUNT_TABLES
        }
        provenance_only_counts = _provenance_only_counts(connection, tables)
        if "web_resources" not in tables:
            return _empty_report(database, counts, started)

        resources = {
            int(row["id"]): str(row["normalized_url"])
            for row in connection.execute("SELECT id, normalized_url FROM web_resources")
        }
        evidence_candidates: dict[int, set[str]] = defaultdict(set)
        evidence_errors: Counter[int] = Counter()
        evidence_counts: Counter[str] = Counter()
        spelling_counts: Counter[str] = Counter()
        normalize_cache: dict[tuple[str, tuple[str, ...]], str | None] = {}

        for source in EVIDENCE_SOURCES:
            if not _source_available(connection, source, tables):
                continue
            scope_select = f", {source.scope_column} AS scope_json" if source.scope_column else ""
            sql = (
                f"SELECT {source.resource_column} AS resource_id, "
                f"{source.url_column} AS evidence_url{scope_select} "
                f"FROM {source.table} {source.joins} "
                f"WHERE {source.resource_column} IS NOT NULL AND {source.url_column} IS NOT NULL"
            )
            for row in connection.execute(sql):
                resource_id = int(row["resource_id"])
                raw_url = str(row["evidence_url"])
                patterns = _drop_patterns(row["scope_json"]) if source.scope_column else ()
                key = (raw_url, patterns)
                if key not in normalize_cache:
                    try:
                        normalize_cache[key] = candidate_normalize_url(
                            raw_url, patterns
                        ).normalized_url
                    except CandidateNormalizationError:
                        normalize_cache[key] = None
                candidate = normalize_cache[key]
                if candidate is None:
                    evidence_errors[resource_id] += 1
                else:
                    evidence_candidates[resource_id].add(candidate)
                evidence_counts[source.name] += 1
                spelling_counts[raw_url] += 1

        baseline_candidates: dict[int, str | None] = {}
        candidate_groups: dict[str, list[int]] = defaultdict(list)
        for resource_id, normalized_url in resources.items():
            try:
                baseline = candidate_normalize_url(normalized_url).normalized_url
            except CandidateNormalizationError:
                baseline = None
            baseline_candidates[resource_id] = baseline
            if baseline is not None:
                candidate_groups[baseline].append(resource_id)
        merge_ids = {
            resource_id for ids in candidate_groups.values() if len(ids) > 1 for resource_id in ids
        }

        classes: dict[str, list[int]] = defaultdict(list)
        overcollapse_ids: set[int] = set()
        for resource_id, current in resources.items():
            observed = evidence_candidates.get(resource_id, set())
            baseline = baseline_candidates[resource_id]
            if resource_id in merge_ids:
                classification = "candidate_v2_merge"
            elif len(observed) > 1:
                classification = "current_over_collapse_candidate"
                overcollapse_ids.add(resource_id)
            elif baseline is None or (evidence_errors[resource_id] and not observed):
                classification = "insufficient_provenance"
            elif baseline != current or (observed and next(iter(observed)) != baseline):
                classification = "re_key_only"
            elif urlsplit(current).query and not observed:
                classification = "insufficient_provenance"
            else:
                classification = "unchanged"
            classes[classification].append(resource_id)

        sorted_overcollapse_ids = sorted(
            overcollapse_ids,
            key=lambda resource_id: (
                -len(evidence_candidates[resource_id]),
                resource_id,
            ),
        )
        overcollapse_groups = [
            {
                "resource_id": resource_id,
                "current": _resource_label(resources[resource_id], show_urls),
                "candidate_identity_count": len(evidence_candidates[resource_id]),
                "candidates": sorted(
                    _resource_label(value, show_urls) for value in evidence_candidates[resource_id]
                )[:MAX_GROUP_EXAMPLES],
            }
            for resource_id in sorted_overcollapse_ids[:MAX_GROUP_EXAMPLES]
        ]
        collision_reasons: Counter[str] = Counter()
        for resource_id in overcollapse_ids:
            for reason in _collision_reasons(evidence_candidates[resource_id]):
                collision_reasons[reason] += 1
        merge_groups = [
            {
                "candidate": _resource_label(candidate, show_urls),
                "resource_ids": sorted(ids),
            }
            for candidate, ids in sorted(candidate_groups.items())
            if len(ids) > 1
        ][:MAX_GROUP_EXAMPLES]

        impacts = _dependency_impacts(connection, tables, overcollapse_ids)
        special = _signal_counts(spelling_counts)
        special.update(_distinction_counts(resources))
        return {
            "audit_contract": "url-identity-audit-v1",
            "candidate_contract": "url-normalization-v2-candidate-reference-only",
            "database": database.name,
            "read_only": True,
            "urls_redacted": not show_urls,
            "counts": counts,
            "evidence_rows": dict(sorted(evidence_counts.items())),
            "provenance_only_url_rows": provenance_only_counts,
            "identity_classifications": {
                name: len(classes.get(name, []))
                for name in (
                    "unchanged",
                    "re_key_only",
                    "current_over_collapse_candidate",
                    "candidate_v2_merge",
                    "insufficient_provenance",
                )
            },
            "over_collapse_examples": overcollapse_groups,
            "over_collapse_candidate_identity_count": sum(
                len(evidence_candidates[resource_id]) for resource_id in overcollapse_ids
            ),
            "over_collapse_reason_groups": dict(sorted(collision_reasons.items())),
            "candidate_merge_examples": merge_groups,
            "observed_adversarial_signals": special,
            "over_collapse_dependency_impact": impacts,
            "migration_severity": _severity(classes, impacts),
            "normalization_cache_entries": len(normalize_cache),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        connection.close()


def _empty_report(database: Path, counts: dict[str, int], started: float) -> dict[str, Any]:
    return {
        "audit_contract": "url-identity-audit-v1",
        "candidate_contract": "url-normalization-v2-candidate-reference-only",
        "database": database.name,
        "read_only": True,
        "urls_redacted": True,
        "counts": counts,
        "evidence_rows": {},
        "provenance_only_url_rows": {},
        "identity_classifications": {
            "unchanged": 0,
            "re_key_only": 0,
            "current_over_collapse_candidate": 0,
            "candidate_v2_merge": 0,
            "insufficient_provenance": 0,
        },
        "over_collapse_examples": [],
        "over_collapse_candidate_identity_count": 0,
        "over_collapse_reason_groups": {},
        "candidate_merge_examples": [],
        "observed_adversarial_signals": {},
        "over_collapse_dependency_impact": {},
        "migration_severity": "SAFE_TO_REKEY",
        "normalization_cache_entries": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _provenance_only_counts(connection: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for table, column in PROVENANCE_ONLY_FIELDS:
        if table not in tables or column not in _columns(connection, table):
            continue
        result[f"{table}.{column}"] = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
            ).fetchone()[0]
        )
    return dict(sorted(result.items()))


def _collision_reasons(candidates: set[str]) -> set[str]:
    parts = [urlsplit(value) for value in candidates]
    paths = {part.path for part in parts}
    queries = {part.query for part in parts}
    reasons: set[str] = set()
    if len(paths) > 1:
        lowered_paths = {path.lower() for path in paths}
        if any("%2f" in path for path in lowered_paths):
            reasons.add("encoded_slash_path")
        if any("//" in path for path in paths):
            reasons.add("repeated_slash_path")
        if len({path.endswith("/") for path in paths}) > 1:
            reasons.add("trailing_slash_path")
        if any(re.search(r"/(?:%2e)(?:%2e)?(?:/|$)", path, re.IGNORECASE) for path in paths):
            reasons.add("encoded_dot_path")
        if any(re.search(r"%3f|%23", path, re.IGNORECASE) for path in paths):
            reasons.add("other_encoded_reserved_path")
        if not reasons:
            reasons.add("other_path_difference")
    if len(queries) > 1:
        component_sets = {tuple(sorted(query.split("&"))) for query in queries}
        if len(component_sets) == 1:
            reasons.add("query_component_order")
        if any("+" in query for query in queries) and any(
            "%20" in query.lower() for query in queries
        ):
            reasons.add("query_plus_percent_space")
        if any(
            re.search(r"%(?:2f|3f|23|26|2c|2a|3b|3a|40|3d)", query, re.IGNORECASE)
            for query in queries
        ):
            reasons.add("query_encoded_reserved")
        if not reasons.intersection(
            {
                "query_component_order",
                "query_plus_percent_space",
                "query_encoded_reserved",
            }
        ):
            reasons.add("other_query_difference")
    return reasons or {"unknown"}


def _distinction_counts(resources: dict[int, str]) -> dict[str, dict[str, int]]:
    parsed = [(resource_id, urlsplit(url)) for resource_id, url in resources.items()]
    path_case_groups: dict[tuple[str, str, int | None, str, str], set[str]] = defaultdict(set)
    slash_groups: dict[tuple[str, str, int | None, str, str], set[bool]] = defaultdict(set)
    query_order_groups: dict[tuple[str, str, int | None, str, tuple[str, ...]], int] = Counter()
    for _resource_id, parts in parsed:
        path_case_groups[
            (
                parts.scheme,
                parts.hostname or "",
                parts.port,
                parts.path.lower(),
                parts.query,
            )
        ].add(parts.path)
        slash_groups[
            (
                parts.scheme,
                parts.hostname or "",
                parts.port,
                parts.path.rstrip("/"),
                parts.query,
            )
        ].add(parts.path.endswith("/"))
        components = tuple(parts.query.split("&")) if parts.query else ()
        if components:
            query_order_groups[
                (
                    parts.scheme,
                    parts.hostname or "",
                    parts.port,
                    parts.path,
                    tuple(sorted(components)),
                )
            ] += 1
    return {
        "path_case_only_distinction_groups": {
            "groups": sum(len(values) > 1 for values in path_case_groups.values())
        },
        "trailing_slash_distinction_groups": {
            "groups": sum(len(values) > 1 for values in slash_groups.values())
        },
        "reordered_query_identity_groups": {
            "groups": sum(count > 1 for count in query_order_groups.values())
        },
    }


def _dependency_impacts(
    connection: sqlite3.Connection, tables: set[str], resource_ids: set[int]
) -> dict[str, int]:
    if not resource_ids:
        return {
            "dependent_resource_snapshots": 0,
            "dependent_source_entries": 0,
            "dependent_scan_seeds": 0,
            "mechanically_attributable_immutable_evidence": 0,
            "mechanically_attributable_performance_observations": 0,
            "mechanically_attributable_accessibility_observations": 0,
            "mechanically_attributable_link_reference_evidence": 0,
            "rebuildable_projection_rows": 0,
            "rebuildable_comparison_rows": 0,
            "ambiguous_site_pages": 0,
            "ambiguous_categories": 0,
            "ambiguous_category_supports": 0,
            "ambiguous_category_exclusions": 0,
            "ambiguous_notes": 0,
            "ambiguous_workflow_rows": 0,
            "ambiguous_notes_or_workflow": 0,
        }
    placeholders = ",".join("?" for _ in resource_ids)
    params = tuple(sorted(resource_ids))

    def count(table: str, predicate: str) -> int:
        if table not in tables:
            return 0
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {predicate}", params
            ).fetchone()[0]
        )

    snapshots = count("resource_snapshots", f"resource_id IN ({placeholders})")
    ai_snapshots = count("ai_document_snapshots", f"resource_id IN ({placeholders})")
    source_entries = count("url_source_entries", f"resource_id IN ({placeholders})")
    scan_seeds = count("scan_seeds", f"resource_id IN ({placeholders})")
    performance = count("performance_observations", f"web_resource_id IN ({placeholders})")
    accessibility = count("accessibility_observations", f"web_resource_id IN ({placeholders})")
    occurrences = count("resource_occurrences", f"target_resource_id IN ({placeholders})")
    references = count("resource_reference_occurrences", f"target_resource_id IN ({placeholders})")
    ai_references = count("ai_document_references", f"target_resource_id IN ({placeholders})")
    projections = sum(
        count(table, f"{column} IN ({placeholders})")
        for table, column in (
            ("scan_page_projections", "resource_id"),
            ("scan_resource_projections", "resource_id"),
            ("scan_link_projections", "source_resource_id"),
            ("scan_link_projections", "target_resource_id"),
        )
    )
    comparisons = sum(
        count(table, f"{column} IN ({placeholders})")
        for table, column in (
            ("scan_comparison_page_results", "resource_id"),
            ("scan_comparison_resource_results", "resource_id"),
            ("scan_comparison_link_results", "source_resource_id"),
            ("scan_comparison_link_results", "target_resource_id"),
        )
    )
    site_pages = count("site_pages", f"resource_id IN ({placeholders})")
    category_count = 0
    category_support_count = 0
    category_exclusion_count = 0
    note_count = 0
    workflow_count = site_pages
    if site_pages and "site_pages" in tables:
        site_page_ids = tuple(
            row[0]
            for row in connection.execute(
                f"SELECT id FROM site_pages WHERE resource_id IN ({placeholders})",
                params,
            )
        )
        site_placeholders = ",".join("?" for _ in site_page_ids)
        if "page_category_assignments" in tables:
            category_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM page_category_assignments "
                    f"WHERE site_page_id IN ({site_placeholders})",
                    site_page_ids,
                ).fetchone()[0]
            )
            if "page_category_assignment_supports" in tables:
                category_support_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM page_category_assignment_supports "
                        "WHERE page_category_assignment_id IN ("
                        "SELECT id FROM page_category_assignments "
                        f"WHERE site_page_id IN ({site_placeholders}))",
                        site_page_ids,
                    ).fetchone()[0]
                )
        if "page_category_automatic_exclusions" in tables:
            category_exclusion_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM page_category_automatic_exclusions "
                    f"WHERE site_page_id IN ({site_placeholders})",
                    site_page_ids,
                ).fetchone()[0]
            )
        if "notes" in tables:
            note_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM notes WHERE site_page_id IN ({site_placeholders})",
                    site_page_ids,
                ).fetchone()[0]
            )
    return {
        "dependent_resource_snapshots": snapshots,
        "dependent_source_entries": source_entries,
        "dependent_scan_seeds": scan_seeds,
        "mechanically_attributable_immutable_evidence": snapshots + ai_snapshots + scan_seeds,
        "mechanically_attributable_performance_observations": performance,
        "mechanically_attributable_accessibility_observations": accessibility,
        "mechanically_attributable_link_reference_evidence": occurrences
        + references
        + ai_references,
        "rebuildable_projection_rows": projections,
        "rebuildable_comparison_rows": comparisons,
        "ambiguous_site_pages": site_pages,
        "ambiguous_categories": category_count,
        "ambiguous_category_supports": category_support_count,
        "ambiguous_category_exclusions": category_exclusion_count,
        "ambiguous_notes": note_count,
        "ambiguous_workflow_rows": workflow_count,
        "ambiguous_notes_or_workflow": note_count + workflow_count,
    }


def _severity(classes: dict[str, list[int]], impacts: dict[str, int]) -> str:
    if classes.get("candidate_v2_merge"):
        return "CANDIDATE_MERGE_REQUIRES_REVIEW"
    if classes.get("current_over_collapse_candidate"):
        if impacts.get("ambiguous_site_pages", 0):
            return "SPLIT_WITH_AMBIGUOUS_WORKSPACE_STATE"
        return "SPLIT_MECHANICALLY_RECOVERABLE"
    if classes.get("insufficient_provenance"):
        return "INSUFFICIENT_PROVENANCE"
    return "SAFE_TO_REKEY"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--show-urls",
        action="store_true",
        help="Include URL values. Default output contains only SHA-256 URL labels.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"database does not exist: {args.database}")
    report = audit_database(args.database, show_urls=args.show_urls)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    else:
        sys.stdout.write(f"{rendered}\n")


if __name__ == "__main__":
    main()
