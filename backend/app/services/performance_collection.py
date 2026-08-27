from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    PerformanceObservation,
    PerformanceRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.performance import PerformanceRunCreate
from app.services.performance_providers import (
    CRUX_ADAPTER_VERSION,
    PAGESPEED_ADAPTER_VERSION,
    PERFORMANCE_NORMALIZATION_VERSION,
    PerformanceProviderClient,
    ProviderResult,
)
from app.storage.performance_store import LocalPerformancePayloadStore


@dataclass(frozen=True)
class PerformanceTask:
    provider: str
    target_kind: str
    target: str
    target_key: str
    dimension: str
    web_resource_id: int | None


class PerformanceCollectionCancelled(RuntimeError):
    pass


class CruxRateLimiter:
    def __init__(
        self,
        queries_per_minute: int,
        *,
        should_cancel: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.minimum_interval = 60.0 / queries_per_minute
        self.should_cancel = should_cancel
        self.clock = clock
        self.sleep = sleep
        self.next_request_at: float | None = None

    def wait(self) -> None:
        while self.next_request_at is not None:
            if self.should_cancel():
                raise PerformanceCollectionCancelled
            remaining = self.next_request_at - self.clock()
            if remaining <= 0:
                break
            self.sleep(min(remaining, 0.25))
        if self.should_cancel():
            raise PerformanceCollectionCancelled
        self.next_request_at = self.clock() + self.minimum_interval


def create_performance_run(
    db: Session, site_id: int, payload: PerformanceRunCreate
) -> PerformanceRun:
    settings = get_settings()
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        raise ValueError("Site not found.")
    if not settings.google_api_key:
        raise ValueError("Google provider collection is not configured.")
    if len(payload.resource_ids) > settings.performance_hard_page_limit:
        raise ValueError(
            f"A Performance run supports at most {settings.performance_hard_page_limit} Pages."
        )
    pages = list(
        db.execute(
            select(SitePage.resource_id, WebResource.normalized_url)
            .join(WebResource, WebResource.id == SitePage.resource_id)
            .where(
                SitePage.website_property_id == site_id,
                SitePage.resource_id.in_(payload.resource_ids),
                SitePage.workspace_state == "active",
                WebResource.resource_type == "page",
            )
        )
    )
    if len(pages) != len(payload.resource_ids):
        raise ValueError("One or more selected Pages do not belong to this Site.")
    configuration: dict[str, Any] = {
        "resource_ids": sorted(payload.resource_ids),
        "providers": sorted(payload.providers),
        "pagespeed_strategies": (
            sorted(payload.pagespeed_strategies) if "pagespeed" in payload.providers else []
        ),
        "crux_form_factors": (
            sorted(payload.crux_form_factors) if "crux" in payload.providers else []
        ),
        "include_origin_crux": payload.include_origin_crux and "crux" in payload.providers,
    }
    requests_per_page = len(configuration["pagespeed_strategies"]) + len(
        configuration["crux_form_factors"]
    )
    origin_requests = (
        len(configuration["crux_form_factors"]) if configuration["include_origin_crux"] else 0
    )
    request_count = len(pages) * requests_per_page + origin_requests
    if request_count > settings.performance_max_provider_requests:
        raise ValueError(
            f"This Performance run requires {request_count} provider requests; the configured "
            f"maximum is {settings.performance_max_provider_requests}."
        )
    run = PerformanceRun(
        website_property_id=site_id,
        status="queued",
        trigger=payload.trigger,
        configuration_json=configuration,
        target_count=len(pages),
        request_count=request_count,
    )
    db.add(run)
    db.flush()
    return run


def execute_performance_run(
    session_factory: Callable[[], Session],
    run_id: int,
    *,
    should_cancel: Callable[[], bool],
    progress: Callable[[int, int, dict[str, int]], None],
    client_factory: Callable[[], PerformanceProviderClient] | None = None,
) -> PerformanceRun:
    settings = get_settings()
    with session_factory() as db:
        run = db.get(PerformanceRun, run_id)
        if run is None:
            raise ValueError("Performance run not found.")
        if run.status in {"completed", "completed_with_errors", "cancelled"}:
            return run
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)
        tasks = _tasks(db, run)
        db.commit()
    crux_limiter = CruxRateLimiter(
        settings.performance_crux_queries_per_minute,
        should_cancel=should_cancel,
    )
    factory = client_factory or (
        lambda: PerformanceProviderClient(
            settings.google_api_key or "",
            timeout_seconds=settings.performance_provider_timeout_seconds,
            max_response_bytes=settings.performance_provider_max_response_bytes,
            max_attempts=settings.performance_provider_max_attempts,
            before_crux_attempt=crux_limiter.wait,
        )
    )
    client = factory()
    try:
        for task in tasks:
            if should_cancel():
                with session_factory() as db:
                    current = db.get(PerformanceRun, run_id)
                    assert current is not None
                    current.status = "cancelled"
                    current.finished_at = datetime.now(UTC)
                    db.commit()
                    return current
            with session_factory() as db:
                exists = db.scalar(
                    select(PerformanceObservation.id).where(
                        PerformanceObservation.performance_run_id == run_id,
                        PerformanceObservation.provider == task.provider,
                        PerformanceObservation.target_kind == task.target_kind,
                        PerformanceObservation.target_key == task.target_key,
                        PerformanceObservation.dimension == task.dimension,
                    )
                )
            if exists is None:
                requested_at = datetime.now(UTC)
                try:
                    result = (
                        client.pagespeed(task.target, task.dimension)
                        if task.provider == "pagespeed"
                        else client.crux(task.target, task.target_kind, task.dimension)
                    )
                except PerformanceCollectionCancelled:
                    return _mark_cancelled(session_factory, run_id)
                _persist_result(session_factory, run_id, task, result, requested_at)
            counters = _refresh_run_counts(session_factory, run_id)
            progress(counters["completed"], len(tasks), counters)
        with session_factory() as db:
            run = db.get(PerformanceRun, run_id)
            assert run is not None
            run.status = "completed_with_errors" if run.failed_count else "completed"
            run.finished_at = datetime.now(UTC)
            db.commit()
            db.refresh(run)
            return run
    finally:
        client.close()


def mark_performance_run_failed(
    db: Session, run_id: int, exc: Exception, *, commit: bool = True
) -> None:
    run = db.get(PerformanceRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.error_summary = f"{type(exc).__name__}: {str(exc)[:800]}"
    if commit:
        db.commit()


def _mark_cancelled(session_factory: Callable[[], Session], run_id: int) -> PerformanceRun:
    with session_factory() as db:
        run = db.get(PerformanceRun, run_id)
        assert run is not None
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run


def _tasks(db: Session, run: PerformanceRun) -> list[PerformanceTask]:
    config = run.configuration_json
    rows = list(
        db.execute(
            select(WebResource.id, WebResource.normalized_url)
            .where(WebResource.id.in_(config["resource_ids"]))
            .order_by(WebResource.id)
        )
    )
    tasks: list[PerformanceTask] = []
    for resource_id, url in rows:
        target_key = hashlib.sha256(f"page:{resource_id}".encode()).hexdigest()
        for strategy in config["pagespeed_strategies"]:
            tasks.append(
                PerformanceTask("pagespeed", "url", url, target_key, strategy, resource_id)
            )
        for form_factor in config["crux_form_factors"]:
            tasks.append(PerformanceTask("crux", "url", url, target_key, form_factor, resource_id))
    if config["include_origin_crux"]:
        site = db.get(WebsiteProperty, run.website_property_id)
        assert site is not None
        origin = _origin(site.normalized_base_url)
        target_key = hashlib.sha256(f"origin:{origin}".encode()).hexdigest()
        for form_factor in config["crux_form_factors"]:
            tasks.append(PerformanceTask("crux", "origin", origin, target_key, form_factor, None))
    return tasks


def _persist_result(
    session_factory: Callable[[], Session],
    run_id: int,
    task: PerformanceTask,
    result: ProviderResult,
    requested_at: datetime,
) -> None:
    with session_factory() as db:
        run = db.get(PerformanceRun, run_id)
        assert run is not None
        blob = None
        if result.payload is not None:
            blob = LocalPerformancePayloadStore(
                get_settings().performance_payload_storage_root
            ).put(db, result.payload)
        descriptor = {
            "provider": task.provider,
            "target": task.target,
            "target_kind": task.target_kind,
            "dimension": task.dimension,
            "metric_set": "performance" if task.provider == "pagespeed" else "core-web-vitals",
            "endpoint_version": "v5" if task.provider == "pagespeed" else "v1",
            "requested_at": requested_at.isoformat(),
        }
        db.add(
            PerformanceObservation(
                performance_run_id=run_id,
                website_property_id=run.website_property_id,
                web_resource_id=task.web_resource_id,
                payload_blob_id=blob.id if blob else None,
                provider=task.provider,
                provider_adapter_version=(
                    PAGESPEED_ADAPTER_VERSION
                    if task.provider == "pagespeed"
                    else CRUX_ADAPTER_VERSION
                ),
                normalization_version=PERFORMANCE_NORMALIZATION_VERSION,
                target_kind=task.target_kind,
                target_key=task.target_key,
                requested_target=task.target,
                provider_target=result.provider_target,
                dimension=task.dimension,
                outcome=result.outcome,
                request_descriptor_json=descriptor,
                metrics_json=result.metrics,
                normalized_sha256=result.normalized_sha256,
                provider_analysis_at=result.provider_analysis_at,
                provider_period_json=result.provider_period,
                provider_product_version=result.provider_product_version,
                observed_at=datetime.now(UTC),
                error_type=result.error_type,
                error_message=result.error_message,
            )
        )
        db.commit()


def _refresh_run_counts(session_factory: Callable[[], Session], run_id: int) -> dict[str, int]:
    with session_factory() as db:
        rows = db.execute(
            select(PerformanceObservation.outcome, func.count())
            .where(PerformanceObservation.performance_run_id == run_id)
            .group_by(PerformanceObservation.outcome)
        ).all()
        counts: dict[str, int] = {outcome: count for outcome, count in rows}
        run = db.get(PerformanceRun, run_id)
        assert run is not None
        run.ready_count = counts.get("ready", 0)
        run.unavailable_count = counts.get("unavailable", 0)
        run.failed_count = counts.get("failed", 0)
        run.completed_count = sum(counts.values())
        db.commit()
        return {
            "completed": run.completed_count,
            "ready": run.ready_count,
            "unavailable": run.unavailable_count,
            "failed": run.failed_count,
        }


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"
