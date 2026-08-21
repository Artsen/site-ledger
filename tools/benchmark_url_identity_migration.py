"""Disposable large synthetic benchmark for the guarded URL identity migration engine."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Self

import benchmark_url_identity_reconciliation as fixture
import url_identity_migrate as migrate
import url_identity_reconcile as reconcile


class _MemorySampler:
    def __init__(self) -> None:
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join()

    def _sample(self) -> None:
        while not self._stop.wait(0.05):
            self.peak_bytes = max(self.peak_bytes, _resident_bytes())


def _resident_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory.restype = wintypes.BOOL
        if not get_memory(get_process(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _prepare_schema(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "ALTER TABLE web_resources ADD COLUMN normalization_version TEXT NOT NULL "
            "DEFAULT 'url-normalization-v1'"
        )
        connection.execute(
            "ALTER TABLE scans ADD COLUMN url_normalization_version TEXT NOT NULL "
            "DEFAULT 'url-normalization-v1'"
        )
        connection.executescript(
            """
            CREATE TABLE url_identity_migrations (
              id INTEGER PRIMARY KEY, implementation_version TEXT NOT NULL,
              reconciliation_schema_version TEXT NOT NULL,
              source_normalization_version TEXT NOT NULL,
              target_normalization_version TEXT NOT NULL,
              reconciliation_manifest_sha256 TEXT NOT NULL,
              reconciliation_source_fingerprint TEXT NOT NULL,
              operation_plan_sha256 TEXT NOT NULL, status TEXT NOT NULL,
              counts_json TEXT NOT NULL, backup_metadata_json TEXT NOT NULL,
              pre_migration_fingerprint TEXT NOT NULL,
              post_migration_fingerprint TEXT, post_migration_write_fingerprint TEXT,
              started_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
            CREATE TABLE url_identity_state (
              id INTEGER PRIMARY KEY, active_normalization_version TEXT NOT NULL,
              reconciliation_required INTEGER NOT NULL, active_migration_id INTEGER,
              activated_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE url_identity_migration_mappings (
              id INTEGER PRIMARY KEY, migration_id INTEGER NOT NULL,
              old_resource_id INTEGER NOT NULL, new_resource_id INTEGER NOT NULL,
              mapping_kind TEXT NOT NULL, candidate_identity_hash TEXT,
              is_primary INTEGER NOT NULL, source_normalization_version TEXT NOT NULL,
              target_normalization_version TEXT NOT NULL,
              UNIQUE(migration_id, old_resource_id, new_resource_id));
            CREATE TABLE web_resource_aliases (
              legacy_resource_id INTEGER PRIMARY KEY, target_resource_id INTEGER NOT NULL,
              migration_id INTEGER NOT NULL, alias_reason TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE worker_instances (
              id INTEGER PRIMARY KEY, status TEXT, stopped_at TEXT, last_seen_at TEXT);
            INSERT INTO url_identity_state
              (id, active_normalization_version, reconciliation_required)
              VALUES (1, 'url-normalization-v1', 1);
            UPDATE alembic_version SET version_num = '202608140023';
            """
        )
        connection.commit()


def run_benchmark() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="site-ledger-url-migration-benchmark-", ignore_cleanup_errors=True
    ) as directory:
        root = Path(directory)
        source = root / "source.db"
        apply_database = root / "apply.db"
        simulation = root / "simulation.db"
        simulation_backup = root / "simulation-backup.db"
        apply_backup = root / "apply-backup.db"
        fixture._build_fixture(source)
        _prepare_schema(source)
        manifest = reconcile.export_manifest(source, show_urls=True)
        fixture._resolve_split(manifest)
        shutil.copy2(source, apply_database)

        with _MemorySampler() as memory:
            backup_started = time.perf_counter()
            backup = migrate.verified_backup(source, simulation_backup, ())
            backup_seconds = time.perf_counter() - backup_started

            simulation_started = time.perf_counter()
            simulation_result = migrate.simulate(source, simulation, manifest, ())
            simulation_seconds = time.perf_counter() - simulation_started

            apply_started = time.perf_counter()
            apply_result = migrate.apply_migration(
                apply_database,
                apply_backup,
                manifest,
                (),
                migrate.APPLY_CONFIRMATION,
            )
            apply_seconds = time.perf_counter() - apply_started

            verification_started = time.perf_counter()
            with sqlite3.connect(apply_database) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            verification_seconds = time.perf_counter() - verification_started
        return {
            "fixture": {
                "web_resources": fixture.RESOURCE_COUNT,
                "link_reference_rows": fixture.RELATIONSHIP_COUNT,
                "resource_snapshots": fixture.SNAPSHOT_COUNT,
                "site_pages": fixture.SITE_PAGE_COUNT,
            },
            "backup_seconds": round(backup_seconds, 3),
            "simulation_seconds": round(simulation_seconds, 3),
            "apply_seconds": round(apply_seconds, 3),
            "derivative_rebuild_seconds": round(
                apply_result["derivative_rebuild"]["duration_ms"] / 1000, 3
            ),
            "verification_seconds": round(verification_seconds, 3),
            "peak_resident_bytes": memory.peak_bytes,
            "backup_integrity": backup["integrity_check"],
            "backup_foreign_key_violations": backup["foreign_key_violations"],
            "simulation_status": simulation_result["status"],
            "apply_status": apply_result["status"],
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
        }


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
