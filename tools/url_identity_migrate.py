"""Guarded local URL identity V2 migration and rollback CLI.

The retained database is never changed by status, rebase, preflight, or simulate.
Live apply and rollback require explicit confirmation phrases.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TOOLS = ROOT / "tools"
for path in (BACKEND, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import url_identity_reconcile as reconcile  # noqa: E402

from app.crawler.url_normalizer import (  # noqa: E402
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
)

MIGRATION_IMPLEMENTATION_VERSION = "url-identity-migration-v1"
RECONCILIATION_SCHEMA_VERSION = "url-identity-reconciliation-v1"
EXPECTED_ALEMBIC_HEAD = "202608260025"
APPLY_CONFIRMATION = "APPLY URL IDENTITY V2"
ROLLBACK_CONFIRMATION = "ROLLBACK URL IDENTITY V2"
HEALTHY_WORKER_SECONDS = 20
DEFAULT_DATABASE = ROOT / "data" / "scanner.db"
DEFAULT_CONTENT_ROOTS = (
    ROOT / "data" / "html",
    ROOT / "data" / "rendered",
    ROOT / "data" / "performance",
    ROOT / "data" / "accessibility",
    ROOT / "data" / "ai-documents",
)


class MigrationError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _connect(database: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"file:{database.resolve().as_posix()}?mode=ro", uri=True, timeout=30
        )
        connection.execute("PRAGMA query_only=ON")
    else:
        connection = sqlite3.connect(database, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _identity_state(connection: sqlite3.Connection) -> dict[str, Any]:
    if "url_identity_state" not in _table_names(connection):
        return {
            "schema_ready": False,
            "active_normalization_version": URL_NORMALIZATION_V1_VERSION,
            "reconciliation_required": True,
            "active_migration_id": None,
        }
    row = connection.execute("SELECT * FROM url_identity_state WHERE id = 1").fetchone()
    if row is None:
        raise MigrationError("URL identity state singleton is missing")
    return {
        "schema_ready": True,
        "active_normalization_version": row["active_normalization_version"],
        "reconciliation_required": bool(row["reconciliation_required"]),
        "active_migration_id": row["active_migration_id"],
    }


def _alembic_head(connection: sqlite3.Connection) -> str | None:
    if "alembic_version" not in _table_names(connection):
        return None
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else None


def _active_jobs(connection: sqlite3.Connection) -> int:
    if "background_jobs" not in _table_names(connection):
        return 0
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM background_jobs WHERE status IN ('queued','running','cancelling')"
        ).fetchone()[0]
    )


def _healthy_workers(connection: sqlite3.Connection) -> int:
    if "worker_instances" not in _table_names(connection):
        return 0
    cutoff = datetime.now(UTC) - timedelta(seconds=HEALTHY_WORKER_SECONDS)
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM worker_instances "
            "WHERE status = 'online' AND stopped_at IS NULL AND last_seen_at >= ?",
            (cutoff.isoformat(sep=" "),),
        ).fetchone()[0]
    )


def _preflight(connection: sqlite3.Connection, manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    state = _identity_state(connection)
    head = _alembic_head(connection)
    if not state["schema_ready"]:
        errors.append("schema is not prepared for URL identity V2")
    if head != EXPECTED_ALEMBIC_HEAD:
        errors.append(f"Alembic head is {head}, expected {EXPECTED_ALEMBIC_HEAD}")
    if state["active_normalization_version"] != URL_NORMALIZATION_V1_VERSION:
        errors.append("runtime is not in the required V1 pre-migration state")
    if not state["reconciliation_required"]:
        errors.append("database does not report reconciliation required")
    if state["active_migration_id"] is not None:
        errors.append(
            f"migration {state['active_migration_id']} is already active; rollback or recover it"
        )
    active_jobs = _active_jobs(connection)
    healthy_workers = _healthy_workers(connection)
    if active_jobs:
        errors.append(f"active or queued mutating jobs: {active_jobs}")
    if healthy_workers:
        errors.append(f"healthy workers must be stopped: {healthy_workers}")
    if manifest.get("schema_version") != RECONCILIATION_SCHEMA_VERSION:
        errors.append("unsupported reconciliation manifest schema")
    if manifest.get("privacy", {}).get("urls_redacted", True):
        errors.append("a full local manifest exported with --show-urls is required")
    database_path = Path(connection.execute("PRAGMA database_list").fetchone()[2])
    validation = reconcile.validate_manifest(manifest, database_path)
    errors.extend(validation)
    candidate_merges = int(manifest.get("summary", {}).get("candidate_merge_count", 0))
    if candidate_merges:
        errors.append(f"candidate V2 merges require review: {candidate_merges}")
    v2_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM web_resources WHERE normalization_version = ?",
            (URL_NORMALIZATION_V2_VERSION,),
        ).fetchone()[0]
    )
    if v2_rows:
        errors.append(f"unexpected V2 WebResources before activation: {v2_rows}")
    return {
        "passed": not errors,
        "errors": errors,
        "alembic_head": head,
        "state": state,
        "active_jobs": active_jobs,
        "healthy_workers": healthy_workers,
        "manifest_status": reconcile.resolution_status(manifest),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def content_inventory(roots: Iterable[Path]) -> dict[str, Any]:
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    root_summaries: list[dict[str, Any]] = []
    for root in sorted((Path(item).resolve() for item in roots), key=str):
        root_count = 0
        root_bytes = 0
        if root.exists():
            for path in sorted((item for item in root.rglob("*") if item.is_file()), key=str):
                relative = path.relative_to(root).as_posix()
                size = path.stat().st_size
                file_hash = _file_sha256(path)
                digest.update(canonical_json([root.name, relative, size, file_hash]))
                file_count += 1
                total_bytes += size
                root_count += 1
                root_bytes += size
        root_summaries.append(
            {"root": root.name, "file_count": root_count, "total_bytes": root_bytes}
        )
    return {
        "sha256": digest.hexdigest(),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "roots": root_summaries,
    }


def verified_backup(
    source: Path, destination: Path, content_roots: Iterable[Path]
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise MigrationError(f"backup destination already exists: {destination}")
    reconcile.sqlite_backup(source, destination)
    connection = _connect(destination, read_only=True)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        if integrity != "ok" or foreign_keys:
            raise MigrationError(
                f"backup verification failed: integrity={integrity}, foreign_keys={foreign_keys}"
            )
        logical_fingerprint = reconcile.source_fingerprint(connection)
    finally:
        connection.close()
    return {
        "database_filename": destination.name,
        "database_size": destination.stat().st_size,
        "database_sha256": _file_sha256(destination),
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
        "source_fingerprint": logical_fingerprint,
        "content_inventory": content_inventory(content_roots),
    }


def _domain_fingerprint(connection: sqlite3.Connection) -> str:
    excluded = {
        "alembic_version",
        "url_identity_state",
        "url_identity_migrations",
        "url_identity_migration_mappings",
        "web_resource_aliases",
        "sqlite_sequence",
    }
    digest = hashlib.sha256()
    tables = sorted(_table_names(connection) - excluded)
    for table in tables:
        columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        if not columns:
            continue
        order = "id" if "id" in columns else "rowid"
        digest.update(canonical_json([table, columns]))
        selected = ",".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT {selected} FROM "{table}" ORDER BY "{order}"'):
            digest.update(canonical_json(list(row)))
    return digest.hexdigest()


def _semantic_group(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_id": group["group_id"],
        "classification": group["classification"],
        "current_normalized_url": group["resource"]["current_normalized_url"],
        "resource_type": group["resource"]["resource_type"],
        "candidates": sorted(
            (item["candidate_id"], item["normalized_url"]) for item in group.get("candidates", [])
        ),
        "workspace_sha256": sorted(item["workspace_sha256"] for item in group.get("workspace", [])),
    }


def rebase_manifest(
    old_manifest: dict[str, Any], database: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if old_manifest.get("schema_version") != RECONCILIATION_SCHEMA_VERSION:
        raise MigrationError("unsupported source manifest schema")
    if old_manifest.get("privacy", {}).get("urls_redacted", True):
        raise MigrationError("manifest rebase requires a full local manifest")
    current = reconcile.export_manifest(database, show_urls=True)
    old_groups = {item["group_id"]: item for item in old_manifest.get("groups", [])}
    carried = invalidated = 0
    matched: set[str] = set()
    for group in current.get("groups", []):
        old = old_groups.get(group["group_id"])
        if old is None:
            continue
        matched.add(group["group_id"])
        if sha256_value(_semantic_group(old)) != sha256_value(_semantic_group(group)):
            invalidated += 1
            continue
        old_workspace = {item["workspace_sha256"]: item for item in old.get("workspace", [])}
        for workspace in group.get("workspace", []):
            previous = old_workspace.get(workspace["workspace_sha256"])
            if previous is not None:
                workspace["decisions"] = copy.deepcopy(previous["decisions"])
        group["decision_note"] = old.get("decision_note")
        carried += 1
    removed = len(set(old_groups) - matched)
    added = len({item["group_id"] for item in current.get("groups", [])} - set(old_groups))
    current["status"] = reconcile.resolution_status(current)
    current["manifest_checksum"] = reconcile.manifest_checksum(current)
    return current, {
        "groups_carried": carried,
        "groups_invalidated": invalidated,
        "groups_added": added,
        "groups_removed": removed,
        "status": current["status"],
    }


def _mapping_kind(group: dict[str, Any], is_primary: bool) -> str:
    if group["classification"] == "rekey":
        return "REKEY_TO_V2"
    return "SPLIT_PRIMARY" if is_primary else "SPLIT_SECONDARY"


def _record_mapping(
    connection: sqlite3.Connection,
    migration_id: int,
    old_resource_id: int,
    new_resource_id: int,
    kind: str,
    candidate_id: str | None,
    is_primary: bool,
    target_version: str,
) -> None:
    candidate_hash = candidate_id.split(":", 1)[-1] if candidate_id else None
    connection.execute(
        "INSERT INTO url_identity_migration_mappings "
        "(migration_id, old_resource_id, new_resource_id, mapping_kind, "
        "candidate_identity_hash, is_primary, source_normalization_version, "
        "target_normalization_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            migration_id,
            old_resource_id,
            new_resource_id,
            kind,
            candidate_hash,
            int(is_primary),
            URL_NORMALIZATION_V1_VERSION,
            target_version,
        ),
    )


def _derivative_targets(
    connection: sqlite3.Connection, resource_ids: set[int]
) -> tuple[list[int], list[int]]:
    if not resource_ids:
        return [], []
    tables = _table_names(connection)
    placeholders = ",".join("?" for _ in resource_ids)
    params = tuple(sorted(resource_ids))
    scan_ids: set[int] = set()
    for table, columns in (
        ("scan_page_projections", ("resource_id",)),
        ("scan_resource_projections", ("resource_id",)),
        ("scan_link_projections", ("source_resource_id", "target_resource_id")),
    ):
        if table not in tables or "scan_id" not in reconcile._columns(connection, table):
            continue
        available = [
            column for column in columns if column in reconcile._columns(connection, table)
        ]
        predicate = " OR ".join(f'"{column}" IN ({placeholders})' for column in available)
        query_params = params * len(available)
        scan_ids.update(
            int(row[0])
            for row in connection.execute(
                f'SELECT DISTINCT scan_id FROM "{table}" WHERE {predicate}',
                query_params,
            )
        )
    comparison_ids: set[int] = set()
    if "scan_comparison_builds" in tables:
        for table, columns in (
            ("scan_comparison_page_results", ("resource_id",)),
            ("scan_comparison_resource_results", ("resource_id",)),
            (
                "scan_comparison_link_results",
                ("source_resource_id", "target_resource_id"),
            ),
        ):
            available_columns = reconcile._columns(connection, table) if table in tables else set()
            if "comparison_build_id" not in available_columns:
                continue
            available = [column for column in columns if column in available_columns]
            predicate = " OR ".join(f'r."{column}" IN ({placeholders})' for column in available)
            query_params = params * len(available)
            comparison_ids.update(
                int(row[0])
                for row in connection.execute(
                    f'SELECT DISTINCT b.scan_comparison_id FROM "{table}" r '
                    "JOIN scan_comparison_builds b ON b.id = r.comparison_build_id "
                    f"WHERE {predicate}",
                    query_params,
                )
            )
    return sorted(scan_ids), sorted(comparison_ids)


def _rebuild_derivatives(
    database: Path, scan_ids: list[int], comparison_ids: list[int]
) -> dict[str, Any]:
    started = time.perf_counter()
    environment = os.environ.copy()
    environment["SCANNER_DATABASE_URL"] = f"sqlite:///{database.resolve().as_posix()}"

    def run(module: str, identifier: int) -> None:
        result = subprocess.run(
            [sys.executable, "-m", module, "rebuild", str(identifier)],
            cwd=BACKEND,
            env=environment,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            raise MigrationError(f"{module} rebuild {identifier} failed: {detail}")

    for scan_id in scan_ids:
        run("app.scan_projections", scan_id)
    for comparison_id in comparison_ids:
        run("app.scan_comparisons", comparison_id)
    return {
        "scan_count": len(scan_ids),
        "comparison_count": len(comparison_ids),
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }


def _execute_core(
    connection: sqlite3.Connection,
    database: Path,
    manifest: dict[str, Any],
    backup_metadata: dict[str, Any],
) -> dict[str, Any]:
    preflight = _preflight(connection, manifest)
    if not preflight["passed"]:
        raise MigrationError("preflight failed: " + "; ".join(preflight["errors"]))
    plan = reconcile.operation_plan(manifest, database)
    plan_sha256 = sha256_value(plan["operations"])
    pre_fingerprint = _domain_fingerprint(connection)
    before = reconcile.invariant_snapshot(connection)
    connection.execute("BEGIN EXCLUSIVE")
    created: Counter[str] = Counter()
    derivative_removals: dict[str, int] = {}
    try:
        cursor = connection.execute(
            "INSERT INTO url_identity_migrations "
            "(implementation_version, reconciliation_schema_version, "
            "source_normalization_version, target_normalization_version, "
            "reconciliation_manifest_sha256, reconciliation_source_fingerprint, "
            "operation_plan_sha256, status, counts_json, backup_metadata_json, "
            "pre_migration_fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, 'applying', ?, ?, ?)",
            (
                MIGRATION_IMPLEMENTATION_VERSION,
                RECONCILIATION_SCHEMA_VERSION,
                URL_NORMALIZATION_V1_VERSION,
                URL_NORMALIZATION_V2_VERSION,
                manifest["manifest_checksum"],
                manifest["source"]["identity_graph_sha256"],
                plan_sha256,
                json.dumps({}),
                json.dumps(backup_metadata, sort_keys=True),
                pre_fingerprint,
            ),
        )
        migration_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE url_identity_state SET active_migration_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (migration_id,),
        )
        groups = [
            item for item in manifest["groups"] if item["classification"] in {"rekey", "split"}
        ]
        affected_ids = {int(item["resource"]["id"]) for item in groups}
        derivative_scan_ids, derivative_comparison_ids = _derivative_targets(
            connection, affected_ids
        )
        grandfathered_ids = {
            int(item["resource_id"]) for item in manifest.get("insufficient_provenance", [])
        }
        for group in groups:
            temporary = f"urn:site-ledger:url-reconcile:{group['group_id'].split(':')[1]}"
            connection.execute(
                "UPDATE web_resources SET normalized_url = ? WHERE id = ?",
                (temporary, int(group["resource"]["id"])),
            )
        excluded = sorted(affected_ids | grandfathered_ids)
        predicate = ""
        params: list[Any] = [URL_NORMALIZATION_V2_VERSION, URL_NORMALIZATION_V1_VERSION]
        if excluded:
            predicate = f" AND id NOT IN ({','.join('?' for _ in excluded)})"
            params.extend(excluded)
        unchanged_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT id FROM web_resources WHERE normalization_version = ?" + predicate,
                tuple(params[1:]),
            )
        ]
        connection.execute(
            "UPDATE web_resources SET normalization_version = ? "
            "WHERE normalization_version = ?" + predicate,
            tuple(params),
        )
        for resource_id in unchanged_ids:
            _record_mapping(
                connection,
                migration_id,
                resource_id,
                resource_id,
                "UNCHANGED_TO_V2",
                None,
                True,
                URL_NORMALIZATION_V2_VERSION,
            )
        for group in groups:
            old_id = int(group["resource"]["id"])
            mapping, urls = reconcile._candidate_maps(group, connection)
            reconcile._apply_attributions(connection, group, mapping, urls)
            created["scan_seeds"] += reconcile._reconcile_seed_origins(
                connection, group, mapping, urls
            )
            primary_candidate = next(
                candidate_id
                for candidate_id, resource_id in mapping.items()
                if resource_id == old_id
            )
            reconcile._update_resource_identity(connection, old_id, urls[primary_candidate])
            if group["classification"] == "split":
                reconcile._apply_workspace(connection, group, mapping)
            for candidate_id, resource_id in mapping.items():
                is_primary = resource_id == old_id
                _record_mapping(
                    connection,
                    migration_id,
                    old_id,
                    resource_id,
                    _mapping_kind(group, is_primary),
                    candidate_id,
                    is_primary,
                    URL_NORMALIZATION_V2_VERSION,
                )
        for resource_id in sorted(grandfathered_ids):
            _record_mapping(
                connection,
                migration_id,
                resource_id,
                resource_id,
                "GRANDFATHER_V1",
                None,
                True,
                URL_NORMALIZATION_V1_VERSION,
            )
        derivative_removals = reconcile._invalidate_derivatives(connection, sorted(affected_ids))
        verification = reconcile.verify_simulation(
            connection, before, derivative_removals, manifest, created
        )
        v1_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM web_resources WHERE normalization_version = ?",
                (URL_NORMALIZATION_V1_VERSION,),
            ).fetchone()[0]
        )
        if v1_count != len(grandfathered_ids):
            verification["errors"].append(
                f"grandfathered V1 count mismatch: {v1_count} != {len(grandfathered_ids)}"
            )
            verification["passed"] = False
        if not verification["passed"]:
            raise MigrationError(
                "migration invariants failed: " + "; ".join(verification["errors"])
            )
        counts = {
            "unchanged_to_v2": len(unchanged_ids),
            "rekey_to_v2": sum(item["classification"] == "rekey" for item in groups),
            "split_groups": sum(item["classification"] == "split" for item in groups),
            "grandfather_v1": len(grandfathered_ids),
            "new_resources": sum(
                len(item["candidates"]) - 1 for item in groups if item["classification"] == "split"
            ),
            "derivative_rows_invalidated": derivative_removals,
        }
        connection.execute(
            "UPDATE url_identity_migrations SET status = 'rebuilding', counts_json = ? "
            "WHERE id = ?",
            (json.dumps(counts, sort_keys=True), migration_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "status": "REBUILD_REQUIRED",
        "migration_id": migration_id,
        "implementation_version": MIGRATION_IMPLEMENTATION_VERSION,
        "counts": counts,
        "verification": verification,
        "operation_plan_sha256": plan_sha256,
        "derivative_scan_ids": derivative_scan_ids,
        "derivative_comparison_ids": derivative_comparison_ids,
    }


def _finalize(
    database: Path, core: dict[str, Any], derivative_rebuild: dict[str, Any]
) -> dict[str, Any]:
    connection = _connect(database)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        if integrity != "ok" or foreign_keys:
            raise MigrationError(
                "post-rebuild verification failed: "
                f"integrity={integrity}, foreign_keys={foreign_keys}"
            )
        migration_id = int(core["migration_id"])
        counts = dict(core["counts"])
        counts["derivative_rebuild"] = derivative_rebuild
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute(
            "UPDATE url_identity_state SET active_normalization_version = ?, "
            "reconciliation_required = 0, active_migration_id = ?, "
            "activated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (URL_NORMALIZATION_V2_VERSION, migration_id),
        )
        post_fingerprint = _domain_fingerprint(connection)
        connection.execute(
            "UPDATE url_identity_migrations SET status = 'completed', counts_json = ?, "
            "post_migration_fingerprint = ?, post_migration_write_fingerprint = ?, "
            "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (
                json.dumps(counts, sort_keys=True),
                post_fingerprint,
                post_fingerprint,
                migration_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        **core,
        "status": "MIGRATION_VERIFIED",
        "active_normalization_version": URL_NORMALIZATION_V2_VERSION,
        "counts": counts,
        "post_migration_fingerprint": post_fingerprint,
        "derivative_rebuild": derivative_rebuild,
    }


def _execute(
    database: Path, manifest: dict[str, Any], backup_metadata: dict[str, Any]
) -> dict[str, Any]:
    connection = _connect(database)
    try:
        core = _execute_core(connection, database, manifest, backup_metadata)
    finally:
        connection.close()
    derivative_rebuild = _rebuild_derivatives(
        database, core.pop("derivative_scan_ids"), core.pop("derivative_comparison_ids")
    )
    return _finalize(database, core, derivative_rebuild)


def simulate(
    source: Path,
    destination: Path,
    manifest: dict[str, Any],
    content_roots: Iterable[Path],
) -> dict[str, Any]:
    source_before = reconcile.database_file_state(source)
    backup_metadata = verified_backup(source, destination, content_roots)
    try:
        result = _execute(destination, manifest, backup_metadata)
        result["status"] = "SIMULATION_PASSED"
        result["destination"] = str(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    source_after = reconcile.database_file_state(source)
    if source_before != source_after:
        destination.unlink(missing_ok=True)
        raise MigrationError("source database or WAL changed during disposable simulation")
    result["source_unchanged"] = True
    return result


def apply_migration(
    database: Path,
    backup: Path,
    manifest: dict[str, Any],
    content_roots: Iterable[Path],
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != APPLY_CONFIRMATION:
        raise MigrationError(f'live apply requires --confirm "{APPLY_CONFIRMATION}"')
    backup_metadata = verified_backup(database, backup, content_roots)
    try:
        return _execute(database, manifest, backup_metadata)
    except Exception:
        source_connection = sqlite3.connect(backup)
        target_connection = sqlite3.connect(database)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
        raise


def rollback_migration(
    database: Path, backup: Path, migration_id: int, confirmation: str
) -> dict[str, Any]:
    if confirmation != ROLLBACK_CONFIRMATION:
        raise MigrationError(f'rollback requires --confirm "{ROLLBACK_CONFIRMATION}"')
    backup_connection = _connect(backup, read_only=True)
    try:
        if str(backup_connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            raise MigrationError("rollback backup failed integrity verification")
        if backup_connection.execute("PRAGMA foreign_key_check").fetchall():
            raise MigrationError("rollback backup has foreign-key violations")
    finally:
        backup_connection.close()
    connection = _connect(database)
    try:
        if _active_jobs(connection) or _healthy_workers(connection):
            raise MigrationError("rollback requires no active jobs and no healthy workers")
        state = _identity_state(connection)
        if state["active_migration_id"] != migration_id:
            raise MigrationError("requested migration is not the active migration")
        row = connection.execute(
            "SELECT status, post_migration_write_fingerprint, backup_metadata_json "
            "FROM url_identity_migrations WHERE id = ?",
            (migration_id,),
        ).fetchone()
        if row is None:
            raise MigrationError("active migration provenance is missing")
        backup_metadata = json.loads(row["backup_metadata_json"])
        if _file_sha256(backup) != backup_metadata.get("database_sha256"):
            raise MigrationError("rollback backup does not match recorded migration backup")
        if row["status"] == "completed" and _domain_fingerprint(connection) != row[1]:
            raise MigrationError("post-migration writes detected; automatic rollback is refused")
        if row["status"] not in {"applying", "rebuilding", "completed"}:
            raise MigrationError(f"migration status cannot be rolled back: {row['status']}")
    finally:
        connection.close()
    source_connection = sqlite3.connect(backup)
    target_connection = sqlite3.connect(database)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    return {"status": "ROLLBACK_RESTORED", "migration_id": migration_id}


def status(database: Path) -> dict[str, Any]:
    connection = _connect(database, read_only=True)
    try:
        state = _identity_state(connection)
        counts = (
            {
                row[0]: int(row[1])
                for row in connection.execute(
                    "SELECT normalization_version, COUNT(*) FROM web_resources "
                    "GROUP BY normalization_version ORDER BY normalization_version"
                )
            }
            if state["schema_ready"]
            else {}
        )
        return {
            "alembic_head": _alembic_head(connection),
            **state,
            "resource_counts_by_version": counts,
            "active_jobs": _active_jobs(connection),
            "healthy_workers": _healthy_workers(connection),
        }
    finally:
        connection.close()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    rebase = commands.add_parser("rebase")
    rebase.add_argument("manifest", type=Path)
    rebase.add_argument("--output", type=Path, required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("manifest", type=Path)
    preflight.add_argument("--backup", type=Path)
    simulate_parser = commands.add_parser("simulate")
    simulate_parser.add_argument("manifest", type=Path)
    simulate_parser.add_argument("--destination", type=Path, required=True)
    simulate_parser.add_argument("--report", type=Path)
    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("manifest", type=Path)
    apply_parser.add_argument("--backup", type=Path, required=True)
    apply_parser.add_argument("--confirm", required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--migration-id", type=int, required=True)
    rollback.add_argument("--backup", type=Path, required=True)
    rollback.add_argument("--confirm", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    database = args.database.resolve()
    try:
        if args.command == "status":
            result = status(database)
        elif args.command == "rebase":
            result, summary = rebase_manifest(_load(args.manifest), database)
            _write(args.output, result)
            result = summary
        elif args.command == "preflight":
            manifest = _load(args.manifest)
            connection = _connect(database, read_only=True)
            try:
                result = _preflight(connection, manifest)
            finally:
                connection.close()
            if result["passed"] and args.backup:
                result["backup"] = verified_backup(database, args.backup, DEFAULT_CONTENT_ROOTS)
        elif args.command == "simulate":
            result = simulate(
                database,
                args.destination.resolve(),
                _load(args.manifest),
                DEFAULT_CONTENT_ROOTS,
            )
            if args.report:
                _write(args.report, result)
        elif args.command == "apply":
            result = apply_migration(
                database,
                args.backup.resolve(),
                _load(args.manifest),
                DEFAULT_CONTENT_ROOTS,
                args.confirm,
            )
        else:
            result = rollback_migration(
                database, args.backup.resolve(), args.migration_id, args.confirm
            )
    except (
        MigrationError,
        reconcile.ReconciliationError,
        sqlite3.Error,
        OSError,
    ) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
