"""Disposable large synthetic benchmark for URL identity reconciliation tooling."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from url_identity_reconcile import (
    _decision,
    export_manifest,
    invariant_snapshot,
    manifest_checksum,
    operation_plan,
    resolution_status,
    simulate_manifest,
    verify_simulation,
)

RESOURCE_COUNT = 25_000
RELATIONSHIP_COUNT = 1_300_000
SNAPSHOT_COUNT = 5_000
SITE_PAGE_COUNT = 2_500
BATCH_SIZE = 10_000


def run_benchmark() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="site-ledger-url-reconciliation-benchmark-"
    ) as directory:
        root = Path(directory)
        database = root / "source.db"
        simulation = root / "simulation.db"
        _build_fixture(database)
        tracemalloc.start()
        export_started = time.perf_counter()
        manifest = export_manifest(database, show_urls=True)
        export_seconds = time.perf_counter() - export_started
        export_peak = tracemalloc.get_traced_memory()[1]
        _resolve_split(manifest)
        planning_started = time.perf_counter()
        plan = operation_plan(manifest, database)
        planning_seconds = time.perf_counter() - planning_started
        planning_peak = tracemalloc.get_traced_memory()[1]
        simulation_started = time.perf_counter()
        simulation_result = simulate_manifest(manifest, database, simulation)
        simulation_seconds = time.perf_counter() - simulation_started
        simulation_peak = tracemalloc.get_traced_memory()[1]
        connection = sqlite3.connect(simulation)
        connection.row_factory = sqlite3.Row
        try:
            before = invariant_snapshot(connection)
            verification_started = time.perf_counter()
            verification = verify_simulation(connection, before, {}, manifest)
            verification_seconds = time.perf_counter() - verification_started
        finally:
            connection.close()
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return {
            "fixture": {
                "web_resources": RESOURCE_COUNT,
                "link_reference_rows": RELATIONSHIP_COUNT,
                "resource_snapshots": SNAPSHOT_COUNT,
                "site_pages": SITE_PAGE_COUNT,
                "split_cases": 1,
                "rekey_cases": 1,
            },
            "export_seconds": round(export_seconds, 3),
            "planning_seconds": round(planning_seconds, 3),
            "simulation_seconds": round(simulation_seconds, 3),
            "verification_seconds": round(verification_seconds, 3),
            "export_peak_traced_bytes": export_peak,
            "planning_peak_traced_bytes": planning_peak,
            "simulation_peak_traced_bytes": simulation_peak,
            "peak_traced_bytes": peak,
            "manifest_status": resolution_status(manifest),
            "plan_operation_counts": plan["operation_counts"],
            "simulation_status": simulation_result["status"],
            "source_unchanged": simulation_result["source_unchanged"],
            "verification_passed": verification["passed"],
            "database_bytes": database.stat().st_size,
        }


def _resolve_split(manifest: dict[str, Any]) -> None:
    split = next(item for item in manifest["groups"] if item["classification"] == "split")
    candidates = [item["candidate_id"] for item in split["candidates"]]
    workspace = split["workspace"][0]
    workspace["decisions"]["primary_candidate_id"] = candidates[0]
    workspace["decisions"]["owner_label"] = _decision("RESET")
    workspace["decisions"]["workflow_status"] = _decision("RESET")
    manifest["status"] = resolution_status(manifest)
    manifest["manifest_checksum"] = manifest_checksum(manifest)


def _build_fixture(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.executescript(
        """
        CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY);
        CREATE TABLE website_properties (id INTEGER PRIMARY KEY, scope_config TEXT);
        CREATE TABLE scans (id INTEGER PRIMARY KEY, website_property_id INTEGER, scope_config TEXT);
        CREATE TABLE web_resources (
          id INTEGER PRIMARY KEY, resource_type TEXT NOT NULL, normalized_url TEXT NOT NULL UNIQUE,
          scheme TEXT, host TEXT, port INTEGER, path TEXT, query TEXT,
          UNIQUE(resource_type, normalized_url));
        CREATE TABLE resource_snapshots (
          id INTEGER PRIMARY KEY, scan_id INTEGER, resource_id INTEGER REFERENCES web_resources(id),
          requested_url TEXT, final_url TEXT, html_blob_id INTEGER, parse_artifact_id INTEGER);
        CREATE TABLE site_pages (
          id INTEGER PRIMARY KEY, website_property_id INTEGER,
          resource_id INTEGER REFERENCES web_resources(id), owner_label TEXT,
          workflow_status TEXT, UNIQUE(website_property_id, resource_id));
        CREATE TABLE resource_occurrences (
          id INTEGER PRIMARY KEY, source_snapshot_id INTEGER,
          target_resource_id INTEGER REFERENCES web_resources(id), resolved_url TEXT,
          normalized_target_url TEXT);
        CREATE TABLE background_jobs (id INTEGER PRIMARY KEY, status TEXT);
        """
    )
    connection.execute("INSERT INTO alembic_version VALUES ('202608130022')")
    connection.execute("INSERT INTO website_properties VALUES (1, '{}')")
    connection.execute("INSERT INTO scans VALUES (1, 1, '{}')")
    resource_rows = []
    for resource_id in range(1, RESOURCE_COUNT + 1):
        if resource_id == 1:
            path, query = "/", "a=1&b=2"
        elif resource_id == 2:
            path, query = "/encoded/slash", ""
        else:
            path, query = f"/page/{resource_id}", ""
        url = f"https://benchmark.invalid{path}" + (f"?{query}" if query else "")
        resource_rows.append((resource_id, "page", url, "https", "benchmark.invalid", path, query))
    connection.executemany(
        "INSERT INTO web_resources VALUES (?, ?, ?, ?, ?, NULL, ?, ?)", resource_rows
    )
    snapshots = []
    for snapshot_id in range(1, SNAPSHOT_COUNT + 1):
        resource_id = ((snapshot_id - 1) % RESOURCE_COUNT) + 1
        if snapshot_id == 1:
            raw = "https://benchmark.invalid/?a=1&b=2"
            resource_id = 1
        elif snapshot_id == 2:
            raw = "https://benchmark.invalid/?b=2&a=1"
            resource_id = 1
        elif snapshot_id == 3:
            raw = "https://benchmark.invalid/encoded%2Fslash"
            resource_id = 2
        else:
            raw = f"https://benchmark.invalid/page/{resource_id}"
        snapshots.append((snapshot_id, 1, resource_id, raw))
    connection.executemany(
        "INSERT INTO resource_snapshots (id, scan_id, resource_id, requested_url) "
        "VALUES (?, ?, ?, ?)",
        snapshots,
    )
    connection.executemany(
        "INSERT INTO site_pages VALUES (?, 1, ?, NULL, 'unreviewed')",
        ((resource_id, resource_id) for resource_id in range(1, SITE_PAGE_COUNT + 1)),
    )
    batch = []
    for row_id in range(1, RELATIONSHIP_COUNT + 1):
        target_id = ((row_id - 1) % RESOURCE_COUNT) + 1
        if target_id == 1 and row_id % 2:
            resolved = "https://benchmark.invalid/?b=2&a=1"
        elif target_id == 1:
            resolved = "https://benchmark.invalid/?a=1&b=2"
        elif target_id == 2:
            resolved = "https://benchmark.invalid/encoded%2Fslash"
        else:
            resolved = f"https://benchmark.invalid/page/{target_id}"
        batch.append((row_id, ((row_id - 1) % SNAPSHOT_COUNT) + 1, target_id, resolved, resolved))
        if len(batch) == BATCH_SIZE:
            connection.executemany("INSERT INTO resource_occurrences VALUES (?, ?, ?, ?, ?)", batch)
            batch.clear()
    if batch:
        connection.executemany("INSERT INTO resource_occurrences VALUES (?, ?, ?, ?, ?)", batch)
    connection.commit()
    connection.close()


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
