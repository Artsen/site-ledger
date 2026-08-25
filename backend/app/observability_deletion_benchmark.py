"""Synthetic observability retention, deletion, and payload-GC benchmark."""

from __future__ import annotations

import tempfile
import time
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    PerformanceObservation,
    PerformanceRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.accessibility_deletion import (
    delete_accessibility_run,
    preview_accessibility_run_deletion,
)
from app.services.accessibility_queries import list_accessibility_runs
from app.services.observability_payload_gc import collect_performance_payload_gc
from app.services.performance_deletion import (
    delete_performance_run,
    preview_performance_run_deletion,
)
from app.services.performance_queries import list_performance_runs
from app.storage.accessibility_store import LocalAccessibilityPayloadStore
from app.storage.performance_store import LocalPerformancePayloadStore


def run_benchmark(
    *,
    list_run_count: int = 1_000,
    list_observation_count: int = 10_000,
    performance_observation_count: int = 1_002,
    accessibility_observation_count: int = 500,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="site-ledger-observability-delete-", ignore_cleanup_errors=True
    ) as directory:
        root = Path(directory)
        engine = create_engine(f"sqlite:///{(root / 'benchmark.db').as_posix()}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        performance_store = LocalPerformancePayloadStore(root / "performance")
        accessibility_store = LocalAccessibilityPayloadStore(root / "accessibility")
        tracemalloc.start()
        with factory() as db:
            list_site, resources = _site_with_pages(db, "list", 250)
            runs = [_performance_run(list_site.id, 10) for _ in range(list_run_count)]
            db.add_all(runs)
            db.flush()
            observations = []
            for index in range(list_observation_count):
                run = runs[index % len(runs)]
                observations.append(
                    _performance_observation(
                        run.id,
                        list_site.id,
                        resources[index % len(resources)].id,
                        f"{index:064x}",
                    )
                )
            db.add_all(observations)
            db.commit()
            performance_list_ms = _measure(
                lambda: list_performance_runs(db, list_site.id, limit=1_000, offset=0)
            )

            accessibility_list_site, accessibility_list_resources = _site_with_pages(
                db, "a11y-list", 250
            )
            accessibility_runs = [
                _accessibility_run(accessibility_list_site.id, 10) for _ in range(list_run_count)
            ]
            db.add_all(accessibility_runs)
            db.flush()
            db.add_all(
                _accessibility_observation(
                    accessibility_runs[index % len(accessibility_runs)].id,
                    accessibility_list_site.id,
                    accessibility_list_resources[
                        (index // len(accessibility_runs)) % len(accessibility_list_resources)
                    ].id,
                )
                for index in range(list_observation_count)
            )
            db.commit()
            accessibility_list_ms = _measure(
                lambda: list_accessibility_runs(
                    db, accessibility_list_site.id, limit=1_000, offset=0
                )
            )

            performance_site, performance_resources = _site_with_pages(db, "performance", 250)
            performance_run = _performance_run(performance_site.id, performance_observation_count)
            db.add(performance_run)
            db.flush()
            performance_blob = performance_store.put(db, b'{"synthetic":"performance"}')
            performance_rows = [
                _performance_observation(
                    performance_run.id,
                    performance_site.id,
                    performance_resources[index % 250].id,
                    f"{index + list_observation_count:064x}",
                    performance_blob.id,
                )
                for index in range(performance_observation_count)
            ]
            db.add_all(performance_rows)
            db.commit()
            performance_preview_ms = _measure(
                lambda: preview_performance_run_deletion(
                    db, performance_site.id, performance_run.id
                )
            )
            performance_delete_ms = _measure(
                lambda: delete_performance_run(
                    db,
                    performance_site.id,
                    performance_run.id,
                    f"DELETE PERFORMANCE RUN {performance_run.id}",
                    performance_store,
                )
            )

            accessibility_site, accessibility_resources = _site_with_pages(db, "accessibility", 250)
            accessibility_run = _accessibility_run(
                accessibility_site.id, accessibility_observation_count
            )
            db.add(accessibility_run)
            db.flush()
            accessibility_blob = accessibility_store.put(db, b'{"synthetic":"accessibility"}')
            accessibility_rows = [
                _accessibility_observation(
                    accessibility_run.id,
                    accessibility_site.id,
                    accessibility_resources[index % 250].id,
                    accessibility_blob.id,
                    "desktop" if index < 250 else "mobile",
                )
                for index in range(accessibility_observation_count)
            ]
            db.add_all(accessibility_rows)
            db.flush()
            rules = [_rule(row.id, index) for index, row in enumerate(accessibility_rows)]
            db.add_all(rules)
            db.flush()
            db.add_all(_node(rule.id, index) for index, rule in enumerate(rules))
            db.commit()
            accessibility_preview_ms = _measure(
                lambda: preview_accessibility_run_deletion(
                    db, accessibility_site.id, accessibility_run.id
                )
            )
            accessibility_delete_ms = _measure(
                lambda: delete_accessibility_run(
                    db,
                    accessibility_site.id,
                    accessibility_run.id,
                    f"DELETE ACCESSIBILITY RUN {accessibility_run.id}",
                    accessibility_store,
                )
            )

            performance_store.put(db, b'{"unreferenced":true}')
            db.commit()
            gc_ms = _measure(
                lambda: collect_performance_payload_gc(db, performance_store, apply=True)
            )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        engine.dispose()
        return {
            "fixture": {
                "run_list_runs_per_domain": list_run_count,
                "run_list_observations_per_domain": list_observation_count,
                "performance_delete_observations": performance_observation_count,
                "accessibility_delete_observations": accessibility_observation_count,
                "accessibility_rule_rows": accessibility_observation_count,
                "accessibility_node_rows": accessibility_observation_count,
            },
            "performance_run_list_ms": performance_list_ms,
            "accessibility_run_list_ms": accessibility_list_ms,
            "performance_preview_ms": performance_preview_ms,
            "performance_delete_ms": performance_delete_ms,
            "accessibility_preview_ms": accessibility_preview_ms,
            "accessibility_delete_ms": accessibility_delete_ms,
            "payload_gc_ms": gc_ms,
            "peak_traced_python_bytes": peak,
        }


def _measure(operation: Callable[[], object]) -> float:
    started = time.perf_counter()
    operation()
    return round((time.perf_counter() - started) * 1_000, 2)


def _site_with_pages(
    db: Session, suffix: str, count: int
) -> tuple[WebsiteProperty, list[WebResource]]:
    site = WebsiteProperty(
        name=f"Synthetic {suffix}",
        base_url=f"https://{suffix}.example.test/",
        normalized_base_url=f"https://{suffix}.example.test/",
        group_key="benchmark",
        platform_key="synthetic",
        ownership_key="test",
        scope_config={},
        is_active=True,
    )
    db.add(site)
    db.flush()
    resources = [
        WebResource(
            resource_type="page",
            normalized_url=f"https://{suffix}.example.test/page-{index}",
            scheme="https",
            host=f"{suffix}.example.test",
            path=f"/page-{index}",
            query="",
        )
        for index in range(count)
    ]
    db.add_all(resources)
    db.flush()
    db.add_all(SitePage(website_property_id=site.id, resource_id=item.id) for item in resources)
    db.commit()
    return site, resources


def _performance_run(site_id: int, count: int) -> PerformanceRun:
    return PerformanceRun(
        website_property_id=site_id,
        status="completed",
        trigger="benchmark",
        configuration_json={},
        target_count=min(count, 250),
        request_count=count,
        completed_count=count,
        ready_count=count,
        unavailable_count=0,
        failed_count=0,
        finished_at=datetime.now(UTC),
    )


def _performance_observation(
    run_id: int, site_id: int, resource_id: int, target_key: str, blob_id: int | None = None
) -> PerformanceObservation:
    return PerformanceObservation(
        performance_run_id=run_id,
        website_property_id=site_id,
        web_resource_id=resource_id,
        payload_blob_id=blob_id,
        provider="pagespeed",
        provider_adapter_version="pagespeed-provider-v1",
        normalization_version="performance-normalization-v1",
        target_kind="url",
        target_key=target_key,
        requested_target="https://example.test/page",
        dimension="mobile",
        outcome="ready",
        request_descriptor_json={},
        metrics_json={},
    )


def _accessibility_run(site_id: int, count: int) -> AccessibilityRun:
    return AccessibilityRun(
        website_property_id=site_id,
        status="completed",
        trigger="benchmark",
        configuration_json={},
        target_count=min(count, 250),
        observation_count=count,
        completed_count=count,
        ready_count=count,
        failed_count=0,
        axe_core_version="4.12.1",
        detector_bundle_sha256="a" * 64,
        integration_version="accessibility-engine-v1",
        normalization_version="accessibility-normalization-v1",
        ruleset_profile="wcag22-aa-v1",
        ruleset_rule_count=62,
        ruleset_sha256="b" * 64,
        finished_at=datetime.now(UTC),
    )


def _accessibility_observation(
    run_id: int,
    site_id: int,
    resource_id: int,
    blob_id: int | None = None,
    profile: str = "desktop",
) -> AccessibilityObservation:
    return AccessibilityObservation(
        accessibility_run_id=run_id,
        website_property_id=site_id,
        web_resource_id=resource_id,
        payload_blob_id=blob_id,
        requested_url="https://example.test/page",
        profile=profile,
        outcome="ready",
        axe_core_version="4.12.1",
        detector_bundle_sha256="a" * 64,
        integration_version="accessibility-engine-v1",
        normalization_version="accessibility-normalization-v1",
        ruleset_profile="wcag22-aa-v1",
        ruleset_sha256="b" * 64,
        profile_json={},
        violation_rule_count=1,
        violation_node_count=1,
    )


def _rule(observation_id: int, index: int) -> AccessibilityRuleEvidence:
    return AccessibilityRuleEvidence(
        accessibility_observation_id=observation_id,
        position=0,
        rule_id="image-alt",
        result_type="violation",
        impact="critical",
        description="Synthetic benchmark rule",
        help="Add alternate text",
        tags_json=["wcag2a"],
        node_count=1,
        rule_evidence_sha256=f"{index:064x}",
    )


def _node(rule_id: int, index: int) -> AccessibilityNodeEvidence:
    return AccessibilityNodeEvidence(
        accessibility_rule_evidence_id=rule_id,
        position=0,
        impact="critical",
        target_json=["img"],
        html_snippet="<img>",
        html_original_length=5,
        html_truncated=False,
        failure_summary="Add alternate text.",
        node_evidence_sha256=f"{index:064x}",
    )
