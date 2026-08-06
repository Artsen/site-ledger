from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.browser.capture import BrowserRenderer, CaptureResult, configuration_fingerprint
from app.browser.config import BROWSER_POLICY_VERSION, CAPTURE_SCHEMA_VERSION, RENDERER_VERSION
from app.crawler.scope import ScopeConfig, ScopeEngine
from app.models import (
    RenderedArtifact,
    RenderedConsoleMessage,
    RenderedNetworkEntry,
    RenderedObservation,
    RenderedPageError,
    ResourceSnapshot,
    Scan,
)
from app.storage.artifact_store import LocalArtifactStore


def select_render_candidates(
    db: Session, scan: Scan, config: ScopeConfig
) -> list[ResourceSnapshot]:
    if config.render_mode == "none":
        return []
    snapshots = list(
        db.scalars(
            select(ResourceSnapshot)
            .where(
                ResourceSnapshot.scan_id == scan.id,
                ResourceSnapshot.html_blob_id.is_not(None),
                ResourceSnapshot.final_url.is_not(None),
                ResourceSnapshot.fetch_state != "failed",
            )
            .order_by(
                case((ResourceSnapshot.requested_url == scan.starting_url, 0), else_=1),
                ResourceSnapshot.crawl_depth,
                ResourceSnapshot.fetched_at,
                ResourceSnapshot.id,
            )
        )
    )
    scope = ScopeEngine(config, scan.starting_url)
    eligible = [
        item for item in snapshots if scope.evaluate(item.final_url or item.requested_url).in_scope
    ]
    if config.render_mode == "starting_page":
        eligible = (
            eligible[:1]
            if eligible
            and (eligible[0].requested_url == scan.starting_url or eligible[0].crawl_depth == 0)
            else []
        )
    return eligible[: config.render_max_pages]


def create_observation(
    db: Session, snapshot: ResourceSnapshot, config: ScopeConfig
) -> RenderedObservation:
    observation = RenderedObservation(
        snapshot_id=snapshot.id,
        capture_state="capturing",
        started_at=datetime.now(UTC),
        requested_url=snapshot.final_url or snapshot.requested_url,
        browser_engine="chromium",
        renderer_version=RENDERER_VERSION,
        browser_policy_version=BROWSER_POLICY_VERSION,
        capture_schema_version=CAPTURE_SCHEMA_VERSION,
        viewport_width=config.render_viewport_width,
        viewport_height=config.render_viewport_height,
        device_scale_factor=config.render_device_scale_factor,
        locale=config.render_locale,
        timezone_id=config.render_timezone,
        color_scheme=config.render_color_scheme,
        reduced_motion=config.render_reduced_motion,
        configuration_fingerprint=configuration_fingerprint(config),
        warnings_json=[],
    )
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return observation


def persist_capture(
    db: Session,
    observation_id: int,
    result: CaptureResult,
    renderer: BrowserRenderer,
    store: LocalArtifactStore,
) -> RenderedObservation:
    observation = db.get(RenderedObservation, observation_id)
    if observation is None:
        raise ValueError("Rendered observation disappeared during capture")
    observation.capture_state = result.state
    observation.finished_at = datetime.now(UTC)
    observation.final_url = result.final_url
    observation.navigation_http_status = result.status
    observation.document_title = result.title
    observation.browser_version = renderer.browser_version
    observation.playwright_version = renderer.playwright_version
    observation.user_agent = result.user_agent
    observation.readiness_state = result.readiness_state
    observation.load_event_reached = result.load_event_reached
    observation.fonts_ready_reached = result.fonts_ready_reached
    observation.duration_ms = result.duration_ms
    observation.network_entry_count = len(result.network)
    observation.blocked_request_count = result.blocked_requests
    observation.console_message_count = len(result.console)
    observation.page_error_count = len(result.page_errors)
    observation.warning_count = len(result.warnings)
    observation.network_truncated = result.network_truncated
    observation.console_truncated = result.console_truncated
    observation.page_errors_truncated = result.page_errors_truncated
    observation.total_encoded_network_bytes = result.total_network_bytes
    observation.error_type = result.error_type
    observation.error_message = result.error_message
    observation.warnings_json = result.warnings[:50]
    for row in result.network:
        db.add(RenderedNetworkEntry(rendered_observation_id=observation.id, **row))
    for row in result.console:
        db.add(RenderedConsoleMessage(rendered_observation_id=observation.id, **row))
    for row in result.page_errors:
        db.add(RenderedPageError(rendered_observation_id=observation.id, **row))
    for artifact in result.artifacts:
        blob = store.put(
            db, artifact.content, artifact.media_type, gzip_content=artifact.gzip_content
        )
        db.add(
            RenderedArtifact(
                rendered_observation_id=observation.id,
                artifact_blob_id=blob.id,
                artifact_type=artifact.artifact_type,
                width=artifact.width,
                height=artifact.height,
                metadata_json={},
            )
        )
    db.commit()
    db.refresh(observation)
    return observation


def mark_capturing_interrupted(
    db: Session, scan_id: int, reason: str = "worker_interrupted"
) -> int:
    observations = list(
        db.scalars(
            select(RenderedObservation)
            .join(ResourceSnapshot)
            .where(
                ResourceSnapshot.scan_id == scan_id,
                RenderedObservation.capture_state == "capturing",
            )
        )
    )
    for item in observations:
        item.capture_state = "interrupted"
        item.error_type = "interrupted"
        item.error_message = reason[:1000]
        item.finished_at = datetime.now(UTC)
    db.commit()
    return len(observations)
