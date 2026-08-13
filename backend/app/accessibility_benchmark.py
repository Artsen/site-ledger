"""Build and query a deterministic synthetic Accessibility history."""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.accessibility_queries import (
    accessibility_pages,
    accessibility_rule_detail,
    accessibility_rules,
    list_accessibility_runs,
    page_accessibility_history,
)

DEFAULT_PAGES = 5_000
DEFAULT_RUNS = 20
DEFAULT_OBSERVATIONS = 20_000


def run_benchmark(
    page_count: int = DEFAULT_PAGES,
    run_count: int = DEFAULT_RUNS,
    observation_count: int = DEFAULT_OBSERVATIONS,
    repetitions: int = 20,
) -> dict[str, Any]:
    if min(page_count, run_count, observation_count, repetitions) < 1:
        raise ValueError("Benchmark sizes must be positive.")
    if observation_count > page_count * 2 * run_count:
        raise ValueError("Observation count exceeds unique run/Page/profile capacity.")
    with tempfile.TemporaryDirectory(prefix="site-ledger-accessibility-") as directory:
        database_path = Path(directory) / "benchmark.db"
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as db:
            site = _site()
            db.add(site)
            db.flush()
            resources = [_resource(index) for index in range(page_count)]
            db.add_all(resources)
            db.flush()
            db.add_all(
                SitePage(website_property_id=site.id, resource_id=resource.id)
                for resource in resources
            )
            now = datetime.now(UTC)
            runs = [_run(site.id, now - timedelta(hours=index)) for index in range(run_count)]
            db.add_all(runs)
            db.flush()
            per_run_seen: dict[int, int] = {}
            observations = []
            for index in range(observation_count):
                run_index = index % run_count
                run = runs[run_index]
                sequence = per_run_seen.get(run.id, 0)
                per_run_seen[run.id] = sequence + 1
                resource = resources[(run_index * 997 + sequence // 2) % page_count]
                profile = "desktop" if sequence % 2 == 0 else "mobile"
                observations.append(
                    AccessibilityObservation(
                        accessibility_run_id=run.id,
                        website_property_id=site.id,
                        web_resource_id=resource.id,
                        requested_url=resource.normalized_url,
                        final_url=resource.normalized_url,
                        profile=profile,
                        outcome="ready",
                        observed_at=run.created_at,
                        axe_core_version="4.12.1",
                        detector_bundle_sha256="a" * 64,
                        integration_version="accessibility-engine-v1",
                        normalization_version="accessibility-normalization-v1",
                        ruleset_profile="wcag22-aa-v1",
                        ruleset_sha256="b" * 64,
                        browser_engine="chromium",
                        browser_version="benchmark",
                        playwright_version="benchmark",
                        profile_json={"viewport_width": 1440 if profile == "desktop" else 390},
                        violation_rule_count=1,
                        violation_node_count=1,
                        incomplete_rule_count=0,
                        incomplete_node_count=0,
                        pass_rule_count=40,
                        inapplicable_rule_count=21,
                        normalized_sha256=f"{index:064x}"[-64:],
                    )
                )
            db.add_all(observations)
            db.flush()
            rules = [
                AccessibilityRuleEvidence(
                    accessibility_observation_id=observation.id,
                    position=1,
                    rule_id="image-alt",
                    result_type="violation",
                    impact="critical",
                    description="Ensure images have alternate text",
                    help="Images must have alternate text",
                    help_url="https://dequeuniversity.com/rules/axe/4.12/image-alt",
                    tags_json=["wcag111", "wcag2a"],
                    node_count=1,
                    rule_evidence_sha256=f"{observation.id:064x}"[-64:],
                )
                for observation in observations
            ]
            db.add_all(rules)
            db.flush()
            db.add_all(
                AccessibilityNodeEvidence(
                    accessibility_rule_evidence_id=rule.id,
                    position=1,
                    impact="critical",
                    target_json=["img"],
                    html_snippet='<img src="pixel.gif">',
                    html_original_length=21,
                    html_truncated=False,
                    failure_summary="Add alternate text.",
                    node_evidence_sha256=f"{rule.id:064x}"[-64:],
                )
                for rule in rules
            )
            db.commit()

            latest_pages = _measure(
                lambda: accessibility_pages(
                    db,
                    site.id,
                    search=None,
                    outcome=None,
                    impact=None,
                    has_violations=None,
                    needs_review=None,
                    sort="audited",
                    direction="desc",
                    limit=100,
                    offset=0,
                ),
                repetitions,
            )
            rule_aggregation = _measure(
                lambda: accessibility_rules(
                    db,
                    site.id,
                    result_type=None,
                    impact=None,
                    profile=None,
                    limit=50,
                    offset=0,
                ),
                repetitions,
            )
            page_history = _measure(
                lambda: page_accessibility_history(
                    db, site.id, resources[0].id, limit=100, offset=0
                ),
                repetitions,
            )
            rule_occurrences = _measure(
                lambda: accessibility_rule_detail(
                    db,
                    site.id,
                    "image-alt",
                    result_type="violation",
                    limit=50,
                    offset=0,
                ),
                repetitions,
            )
            runs_list = _measure(
                lambda: list_accessibility_runs(db, site.id, limit=25, offset=0),
                repetitions,
            )
        raw = json.dumps(_sample_payload(), sort_keys=True, separators=(",", ":")).encode()
        result = {
            "fixture": {
                "pages": page_count,
                "runs": run_count,
                "observations": observation_count,
                "rule_rows": observation_count,
                "node_rows": observation_count,
            },
            "latest_page_summary_query_ms": _percentiles(latest_pages),
            "rule_aggregation_query_ms": _percentiles(rule_aggregation),
            "page_history_query_ms": _percentiles(page_history),
            "rule_occurrence_query_ms": _percentiles(rule_occurrences),
            "runs_list_query_ms": _percentiles(runs_list),
            "sample_payload_raw_bytes": len(raw),
            "sample_payload_gzip_bytes": len(gzip.compress(raw, mtime=0)),
            "database_bytes": database_path.stat().st_size,
        }
        engine.dispose()
        return result


def _measure(operation: Callable[[], Any], repetitions: int) -> list[float]:
    timings = []
    for _ in range(repetitions):
        started = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, round(len(ordered) * 0.95) - 1))
    return {"p50": round(statistics.median(ordered), 3), "p95": round(ordered[p95_index], 3)}


def _site() -> WebsiteProperty:
    return WebsiteProperty(
        name="Accessibility benchmark",
        base_url="https://benchmark.example/",
        normalized_base_url="https://benchmark.example/",
        group_key="benchmark",
        locale="en-US",
        platform_key="fixture",
        ownership_key="fixture",
        scope_config={},
        is_active=True,
    )


def _resource(index: int) -> WebResource:
    return WebResource(
        resource_type="page",
        normalized_url=f"https://benchmark.example/page-{index}",
        scheme="https",
        host="benchmark.example",
        path=f"/page-{index}",
        query="",
    )


def _run(site_id: int, created_at: datetime) -> AccessibilityRun:
    return AccessibilityRun(
        website_property_id=site_id,
        status="completed",
        trigger="benchmark",
        configuration_json={"resource_ids": [], "profiles": ["desktop", "mobile"]},
        target_count=0,
        observation_count=0,
        completed_count=0,
        ready_count=0,
        failed_count=0,
        axe_core_version="4.12.1",
        detector_bundle_sha256="a" * 64,
        integration_version="accessibility-engine-v1",
        normalization_version="accessibility-normalization-v1",
        ruleset_profile="wcag22-aa-v1",
        ruleset_rule_count=62,
        ruleset_sha256="b" * 64,
        created_at=created_at,
        started_at=created_at,
        finished_at=created_at,
    )


def _sample_payload() -> dict[str, Any]:
    return {
        "testEngine": {"name": "axe-core", "version": "4.12.1"},
        "violations": [{"id": "image-alt", "impact": "critical", "nodes": [{"target": ["img"]}]}],
        "incomplete": [],
        "passes": [{"id": f"pass-{index}", "nodes": []} for index in range(40)],
        "inapplicable": [{"id": f"na-{index}", "nodes": []} for index in range(21)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--observations", type=int, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(
            run_benchmark(args.pages, args.runs, args.observations, args.repetitions), indent=2
        )
    )


if __name__ == "__main__":
    main()
