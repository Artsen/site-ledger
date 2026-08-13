"""Disposable synthetic benchmark for the read-only URL identity auditor."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from pathlib import Path

from url_identity_audit import audit_database

RESOURCE_COUNT = 5_000
EVIDENCE_COUNT = 50_000


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="site-ledger-url-audit-benchmark-") as directory:
        database = Path(directory) / "benchmark.db"
        _build_fixture(database)
        started = time.perf_counter()
        first = audit_database(database)
        first_elapsed = time.perf_counter() - started
        started = time.perf_counter()
        second = audit_database(database)
        second_elapsed = time.perf_counter() - started
        deterministic = _stable_result(first) == _stable_result(second)
        print(
            json.dumps(
                {
                    "web_resources": RESOURCE_COUNT,
                    "url_bearing_evidence_rows": EVIDENCE_COUNT,
                    "first_seconds": round(first_elapsed, 3),
                    "second_seconds": round(second_elapsed, 3),
                    "deterministic_aggregate_result": deterministic,
                    "classifications": first["identity_classifications"],
                },
                indent=2,
                sort_keys=True,
            )
        )


def _build_fixture(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE web_resources (id INTEGER PRIMARY KEY, normalized_url TEXT NOT NULL);
        CREATE TABLE scans (id INTEGER PRIMARY KEY, scope_config TEXT);
        CREATE TABLE resource_snapshots (
            id INTEGER PRIMARY KEY, scan_id INTEGER, resource_id INTEGER, requested_url TEXT
        );
        """
    )
    connection.execute("INSERT INTO scans VALUES (1, '{}')")
    connection.executemany(
        "INSERT INTO web_resources VALUES (?, ?)",
        (
            (resource_id, f"https://example.com/page/{resource_id}?a=1&b=2")
            for resource_id in range(1, RESOURCE_COUNT + 1)
        ),
    )
    rows = []
    for evidence_id in range(1, EVIDENCE_COUNT + 1):
        resource_id = ((evidence_id - 1) % RESOURCE_COUNT) + 1
        query = "b=2&a=1" if evidence_id % 7 == 0 else "a=1&b=2"
        path = f"/page/{resource_id}"
        if evidence_id % 11 == 0:
            path = f"/page%2F{resource_id}"
        rows.append((evidence_id, 1, resource_id, f"https://example.com{path}?{query}"))
    connection.executemany("INSERT INTO resource_snapshots VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _stable_result(report: dict[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in report.items() if key not in {"elapsed_seconds", "database"}
    }


if __name__ == "__main__":
    main()
