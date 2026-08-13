"""Build and query a deterministic synthetic Performance history."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    PerformanceObservation,
    PerformanceRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.performance_collection import execute_performance_run
from app.services.performance_providers import PerformanceProviderClient, ProviderResult
from app.services.performance_queries import (
    latest_site_performance,
    list_performance_runs,
    page_performance_history,
)

DEFAULT_PAGES = 5_000
DEFAULT_RUNS = 50
DEFAULT_OBSERVATIONS = 15_000


def run_benchmark(
    page_count: int = DEFAULT_PAGES,
    run_count: int = DEFAULT_RUNS,
    observation_count: int = DEFAULT_OBSERVATIONS,
    repetitions: int = 20,
) -> dict[str, Any]:
    if min(page_count, run_count, observation_count, repetitions) < 1:
        raise ValueError("Benchmark sizes must be positive.")
    with tempfile.TemporaryDirectory(prefix="site-ledger-performance-") as directory:
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
            runs = [
                PerformanceRun(
                    website_property_id=site.id,
                    status="completed",
                    trigger="benchmark",
                    configuration_json={"resource_ids": []},
                    target_count=0,
                    request_count=0,
                    completed_count=0,
                    ready_count=0,
                    unavailable_count=0,
                    failed_count=0,
                    created_at=now - timedelta(days=index),
                    started_at=now - timedelta(days=index),
                    finished_at=now - timedelta(days=index),
                )
                for index in range(run_count)
            ]
            db.add_all(runs)
            db.flush()
            observations = []
            per_run_seen: dict[int, int] = {}
            for index in range(observation_count):
                run = runs[index % run_count]
                sequence = per_run_seen.get(run.id, 0)
                per_run_seen[run.id] = sequence + 1
                resource = resources[sequence % page_count]
                provider = "pagespeed" if sequence % 2 == 0 else "crux"
                dimension = "mobile" if provider == "pagespeed" else "PHONE"
                observations.append(
                    PerformanceObservation(
                        performance_run_id=run.id,
                        website_property_id=site.id,
                        web_resource_id=resource.id,
                        provider=provider,
                        provider_adapter_version=f"{provider}-provider-v1",
                        normalization_version="performance-normalization-v1",
                        target_kind="url",
                        target_key=f"resource-{resource.id}",
                        requested_target=resource.normalized_url,
                        provider_target=resource.normalized_url,
                        dimension=dimension,
                        outcome="ready",
                        request_descriptor_json={},
                        metrics_json={"lcp": {"value": 2000 + index % 500, "unit": "ms"}},
                        normalized_sha256=f"{index:064x}"[-64:],
                        observed_at=run.created_at,
                    )
                )
            db.add_all(observations)
            db.commit()

            latest = _measure(
                lambda: latest_site_performance(db, site.id, provider=None, limit=500, offset=0),
                repetitions,
            )
            page_history = _measure(
                lambda: page_performance_history(db, site.id, resources[0].id, limit=100, offset=0),
                repetitions,
            )
            runs_list = _measure(
                lambda: list_performance_runs(db, site.id, limit=25, offset=0),
                repetitions,
            )
        result = {
            "fixture": {
                "pages": page_count,
                "runs": run_count,
                "observations": observation_count,
            },
            "latest_site_query_ms": _percentiles(latest),
            "page_history_query_ms": _percentiles(page_history),
            "runs_list_query_ms": _percentiles(runs_list),
            "database_bytes": database_path.stat().st_size,
        }
        engine.dispose()
        return result


def run_collection_benchmark(page_count: int = 250) -> dict[str, Any]:
    if not 1 <= page_count <= 250:
        raise ValueError("Collection benchmark Page count must be between 1 and 250.")
    with tempfile.TemporaryDirectory(prefix="site-ledger-performance-collection-") as directory:
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
            request_count = page_count * 4 + 2
            run = PerformanceRun(
                website_property_id=site.id,
                status="queued",
                trigger="benchmark",
                configuration_json={
                    "resource_ids": [resource.id for resource in resources],
                    "providers": ["crux", "pagespeed"],
                    "pagespeed_strategies": ["desktop", "mobile"],
                    "crux_form_factors": ["DESKTOP", "PHONE"],
                    "include_origin_crux": True,
                },
                target_count=page_count,
                request_count=request_count,
            )
            db.add(run)
            db.commit()
            run_id = run.id
        client = _FakeProviderClient()
        progress: list[tuple[int, int]] = []
        tracemalloc.start()
        started = time.perf_counter()
        result = execute_performance_run(
            session_factory,
            run_id,
            should_cancel=lambda: False,
            progress=lambda current, total, _counts: progress.append((current, total)),
            client_factory=lambda: client,
        )
        elapsed = time.perf_counter() - started
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        with session_factory() as db:
            persisted = (
                db.query(PerformanceObservation).filter_by(performance_run_id=run_id).count()
            )
        output = {
            "pages": page_count,
            "provider_requests": request_count,
            "fake_provider_calls": client.calls,
            "persisted_observations": persisted,
            "status": result.status,
            "final_progress": progress[-1] if progress else None,
            "elapsed_seconds": round(elapsed, 3),
            "peak_memory_bytes": peak_memory,
            "database_bytes": database_path.stat().st_size,
        }
        engine.dispose()
        return output


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
        name="Performance benchmark",
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


class _FakeProviderClient(PerformanceProviderClient):
    def __init__(self) -> None:
        self.calls = 0

    def pagespeed(self, target: str, strategy: str) -> ProviderResult:
        self.calls += 1
        return self._result(target, {"performance_score": {"value": 0.9, "unit": "ratio"}})

    def crux(self, target: str, target_kind: str, form_factor: str) -> ProviderResult:
        self.calls += 1
        return self._result(target, {"lcp": {"value": 2200, "unit": "ms"}})

    def close(self) -> None:
        pass

    @staticmethod
    def _result(target: str, metrics: dict[str, Any]) -> ProviderResult:
        return ProviderResult(
            outcome="ready",
            payload=None,
            metrics=metrics,
            provider_target=target,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--observations", type=int, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--collection-pages", type=int)
    args = parser.parse_args()
    result = (
        run_collection_benchmark(args.collection_pages)
        if args.collection_pages
        else run_benchmark(args.pages, args.runs, args.observations)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
