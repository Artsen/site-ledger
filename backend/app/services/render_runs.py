from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.browser.capture import BrowserRenderer, CaptureResult
from app.browser.config import validate_render_config
from app.browser.outcomes import (
    HostRateLimitCircuitBreaker,
    host_rate_limit_skip_result,
    is_successful_page_capture,
    main_navigation_retry_after,
)
from app.config import get_settings
from app.crawler.scope import ScopeConfig
from app.models import (
    RenderedArtifact,
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.rendered import RenderRunCreate
from app.services.rendered_capture import create_observation, persist_capture
from app.services.url_identity import active_url_normalization_version, resolve_resource_id
from app.storage.artifact_store import LocalArtifactStore

TERMINAL_RENDER_RUN_STATUSES = {
    "completed",
    "completed_with_errors",
    "cancelled",
    "failed",
    "interrupted",
}
RENDER_CONFIGURATION_FIELDS = {
    name for name in ScopeConfig.__dataclass_fields__ if name.startswith("render_")
}


def create_render_run(db: Session, site_id: int, payload: RenderRunCreate) -> RenderRun:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        raise ValueError("Site not found.")
    resolved = [resolve_resource_id(db, resource_id) for resource_id in payload.resource_ids]
    if any(item is None for item in resolved) or len(set(resolved)) != len(payload.resource_ids):
        raise ValueError("One or more selected Pages do not belong to this Site.")
    resource_ids = [int(item) for item in resolved if item is not None]
    rows = list(
        db.execute(
            select(WebResource.id, WebResource.normalized_url)
            .join(SitePage, SitePage.resource_id == WebResource.id)
            .where(
                SitePage.website_property_id == site_id,
                SitePage.workspace_state == "active",
                WebResource.resource_type == "page",
                WebResource.id.in_(resource_ids),
            )
            .order_by(WebResource.id)
        )
    )
    if len(rows) != len(resource_ids):
        raise ValueError("One or more selected Pages do not belong to this Site or are suppressed.")
    configuration = _effective_configuration(db, site, payload.configuration, len(rows))
    return _create_frozen_run(
        db,
        site_id=site_id,
        trigger=payload.trigger,
        configuration=configuration,
        targets=[(resource_id, url, None) for resource_id, url in rows],
    )


def create_rerender_run(
    db: Session, site_id: int, source_run_id: int, target_ids: list[int]
) -> RenderRun:
    source = db.scalar(
        select(RenderRun).where(
            RenderRun.id == source_run_id, RenderRun.website_property_id == site_id
        )
    )
    if source is None:
        raise ValueError("Render Run not found.")
    targets = list(
        db.scalars(
            select(RenderRunTarget)
            .where(
                RenderRunTarget.render_run_id == source.id,
                RenderRunTarget.id.in_(target_ids),
            )
            .order_by(RenderRunTarget.position)
        )
    )
    if len(targets) != len(target_ids):
        raise ValueError("One or more selected targets do not belong to this Render Run.")
    return _create_frozen_run(
        db,
        site_id=site_id,
        trigger="rerender",
        configuration={
            **source.configuration_json,
            "render_max_pages": len(targets),
            "max_pages": len(targets),
        },
        targets=[(target.web_resource_id, target.requested_url, None) for target in targets],
        source_render_run_id=source.id,
    )


def create_scan_render_run(db: Session, scan: Scan, snapshots: list[ResourceSnapshot]) -> RenderRun:
    config = ScopeConfig.from_dict(scan.scope_config)
    configuration = config.to_dict()
    configuration["render_mode"] = "all_eligible"
    configuration["render_max_pages"] = len(snapshots)
    configuration["max_pages"] = max(len(snapshots), 1)
    configuration["url_normalization_version"] = scan.url_normalization_version
    return _create_frozen_run(
        db,
        site_id=scan.website_property_id,
        trigger="scan",
        configuration=configuration,
        targets=[
            (snapshot.resource_id, snapshot.final_url or snapshot.requested_url, snapshot.id)
            for snapshot in snapshots
        ],
        source_scan_id=scan.id,
    )


def _create_frozen_run(
    db: Session,
    *,
    site_id: int | None,
    trigger: str,
    configuration: dict[str, Any],
    targets: list[tuple[int, str, int | None]],
    source_scan_id: int | None = None,
    source_render_run_id: int | None = None,
) -> RenderRun:
    if not targets:
        raise ValueError("Select at least one Page.")
    if len(targets) > 1_000:
        raise ValueError("A Render Run supports at most 1000 Pages.")
    if trigger == "scan":
        if source_scan_id is None:
            raise ValueError("A Scan-triggered Render Run requires Scan provenance.")
    elif site_id is None:
        raise ValueError("A manual or rerendered Render Run requires a saved Site.")
    run = RenderRun(
        website_property_id=site_id,
        source_scan_id=source_scan_id,
        source_render_run_id=source_render_run_id,
        status="queued",
        trigger=trigger,
        configuration_json=configuration,
        target_count=len(targets),
    )
    db.add(run)
    db.flush()
    for position, (resource_id, requested_url, snapshot_id) in enumerate(targets, 1):
        db.add(
            RenderRunTarget(
                render_run_id=run.id,
                web_resource_id=resource_id,
                source_snapshot_id=snapshot_id,
                requested_url=requested_url,
                position=position,
            )
        )
    db.flush()
    return run


def _effective_configuration(
    db: Session, site: WebsiteProperty, overrides: dict[str, Any], target_count: int
) -> dict[str, Any]:
    unknown = set(overrides) - RENDER_CONFIGURATION_FIELDS
    if unknown:
        raise ValueError(f"Unsupported render configuration: {', '.join(sorted(unknown))}.")
    values = ScopeConfig.from_dict(site.scope_config).to_dict()
    values.update(overrides)
    values["render_mode"] = "all_eligible"
    values["render_max_pages"] = target_count
    values["max_pages"] = max(target_count, 1)
    validate_render_config(values)
    values["url_normalization_version"] = active_url_normalization_version(db)
    return values


async def execute_render_run(
    session_factory: Callable[[], Session],
    run_id: int,
    *,
    should_cancel: Callable[[], bool],
    progress: Callable[[int, int, dict[str, int]], None],
    fence_domain_mutation: Callable[[Session], None] | None = None,
    renderer_factory: Callable[[ScopeConfig, str, str], BrowserRenderer] = BrowserRenderer,
) -> RenderRun:
    with session_factory() as db:
        run = db.get(RenderRun, run_id)
        if run is None:
            raise ValueError("Render Run not found.")
        if run.status in TERMINAL_RENDER_RUN_STATUSES:
            return run
        config = ScopeConfig.from_dict(run.configuration_json)
        target_rows = list(
            db.execute(
                select(RenderRunTarget.id, RenderRunTarget.requested_url)
                .where(RenderRunTarget.render_run_id == run.id)
                .order_by(RenderRunTarget.position)
            )
        )
        configuration = dict(run.configuration_json)
        _fence(db, fence_domain_mutation)
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)
        db.commit()
    if not target_rows:
        raise ValueError("Render Run has no targets.")
    normalization_version = str(
        configuration.get("url_normalization_version") or "url-normalization-v1"
    )
    renderer = renderer_factory(config, target_rows[0].requested_url, normalization_version)
    breaker = HostRateLimitCircuitBreaker()
    store = LocalArtifactStore(get_settings().rendered_artifact_storage_root)
    async with renderer:
        for target_id, requested_url in target_rows:
            if should_cancel():
                return _mark_cancelled(session_factory, run_id, fence_domain_mutation)
            with session_factory() as db:
                existing = db.scalar(
                    select(RenderedObservation.id).where(
                        RenderedObservation.render_run_target_id == target_id
                    )
                )
                if existing is not None:
                    continue
                current_target = db.get(RenderRunTarget, target_id)
                assert current_target is not None
                _fence(db, fence_domain_mutation)
                observation = create_observation(
                    db, current_target.source_snapshot, config, target=current_target
                )
                observation_id = observation.id
            if breaker.is_open(requested_url):
                result: CaptureResult | None = host_rate_limit_skip_result()
            else:
                _increment_attempted(session_factory, run_id, fence_domain_mutation)
                result = await _bounded_capture(renderer, requested_url, config, should_cancel)
            if result is None:
                _mark_observation_cancelled(session_factory, observation_id, fence_domain_mutation)
                return _mark_cancelled(session_factory, run_id, fence_domain_mutation)
            with session_factory() as db:
                _fence(db, fence_domain_mutation)
                saved = persist_capture(db, observation_id, result, renderer, store)
                breaker.record(
                    requested_url,
                    status=saved.navigation_http_status,
                    error_type=saved.error_type,
                    retry_after=main_navigation_retry_after(result.network),
                )
            counters = refresh_render_run_counts(session_factory, run_id, fence_domain_mutation)
            progress(
                sum((counters["successful"], counters["failed"], counters["skipped"])),
                len(target_rows),
                counters,
            )
    with session_factory() as db:
        run = db.get(RenderRun, run_id)
        assert run is not None
        _fence(db, fence_domain_mutation)
        run.status = (
            "completed_with_errors" if run.failed_count or run.skipped_count else "completed"
        )
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run


async def _bounded_capture(
    renderer: BrowserRenderer,
    url: str,
    config: ScopeConfig,
    should_cancel: Callable[[], bool],
) -> CaptureResult | None:
    task = asyncio.create_task(renderer.capture(url))
    deadline = time.monotonic() + config.render_max_page_duration_seconds
    while not task.done():
        if should_cancel():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return None
        if time.monotonic() >= deadline:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return CaptureResult(
                state="failed",
                error_type="capture_timeout",
                error_message="Browser capture exceeded the configured Page duration.",
                duration_ms=int(config.render_max_page_duration_seconds * 1000),
            )
        await asyncio.sleep(0.25)
    return await task


def _increment_attempted(
    session_factory: Callable[[], Session],
    run_id: int,
    fence_domain_mutation: Callable[[Session], None] | None = None,
) -> None:
    with session_factory() as db:
        run = db.get(RenderRun, run_id)
        assert run is not None
        _fence(db, fence_domain_mutation)
        run.attempted_count += 1
        db.commit()


def refresh_render_run_counts(
    session_factory: Callable[[], Session],
    run_id: int,
    fence_domain_mutation: Callable[[Session], None] | None = None,
) -> dict[str, int]:
    with session_factory() as db:
        observations = list(
            db.scalars(
                select(RenderedObservation).where(RenderedObservation.render_run_id == run_id)
            )
        )
        run = db.get(RenderRun, run_id)
        assert run is not None
        _fence(db, fence_domain_mutation)
        run.completed_count = sum(
            is_successful_page_capture(item.capture_state, item.navigation_http_status)
            for item in observations
        )
        run.skipped_count = sum(item.capture_state == "skipped" for item in observations)
        run.failed_count = len(observations) - run.completed_count - run.skipped_count
        run.blocked_request_count = sum(item.blocked_request_count for item in observations)
        run.artifact_count = (
            db.scalar(
                select(func.count(RenderedArtifact.id))
                .join(RenderedObservation)
                .where(RenderedObservation.render_run_id == run_id)
            )
            or 0
        )
        db.commit()
        return {
            "attempted": run.attempted_count,
            "successful": run.completed_count,
            "failed": run.failed_count,
            "skipped": run.skipped_count,
            "rate_limited": sum(
                item.navigation_http_status == 429 or item.error_type == "navigation_rate_limited"
                for item in observations
            ),
            "artifacts": run.artifact_count,
        }


def _mark_observation_cancelled(
    session_factory: Callable[[], Session],
    observation_id: int,
    fence_domain_mutation: Callable[[Session], None] | None = None,
) -> None:
    with session_factory() as db:
        observation = db.get(RenderedObservation, observation_id)
        if observation:
            _fence(db, fence_domain_mutation)
            observation.capture_state = "cancelled"
            observation.error_type = "cancelled"
            observation.error_message = "Capture cancelled by user."
            observation.finished_at = datetime.now(UTC)
            db.commit()


def _mark_cancelled(
    session_factory: Callable[[], Session],
    run_id: int,
    fence_domain_mutation: Callable[[Session], None] | None = None,
) -> RenderRun:
    with session_factory() as db:
        run = db.get(RenderRun, run_id)
        assert run is not None
        _fence(db, fence_domain_mutation)
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run


def _fence(db: Session, fence_domain_mutation: Callable[[Session], None] | None) -> None:
    if fence_domain_mutation is not None:
        fence_domain_mutation(db)


def mark_render_run_failed(
    db: Session, run_id: int, exc: Exception, *, commit: bool = True
) -> None:
    run = db.get(RenderRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.error_summary = f"{type(exc).__name__}: {str(exc)[:800]}"
    if commit:
        db.commit()
