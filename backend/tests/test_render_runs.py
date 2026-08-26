from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.browser.capture import CaptureResult
from app.browser.outcomes import HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD
from app.crawler.scope import ScopeConfig
from app.models import (
    ArtifactBlob,
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
from app.services.render_runs import create_render_run, execute_render_run
from app.services.scan_deletion import delete_scan
from app.services.site_management import delete_site
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore


def _site_page(db_session, suffix: str = "page") -> tuple[WebsiteProperty, WebResource]:
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={"allowed_host_patterns": ["example.com"]},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://example.com/{suffix}",
        scheme="https",
        host="example.com",
        path=f"/{suffix}",
        query="",
    )
    db_session.add_all([site, resource])
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    db_session.commit()
    return site, resource


def _run_target(db_session, site: WebsiteProperty, resource: WebResource) -> RenderRunTarget:
    run = RenderRun(
        website_property_id=site.id,
        status="queued",
        trigger="site_workspace",
        configuration_json={"render_mode": "all_eligible", "render_max_pages": 1},
        target_count=1,
    )
    db_session.add(run)
    db_session.flush()
    target = RenderRunTarget(
        render_run_id=run.id,
        web_resource_id=resource.id,
        requested_url=resource.normalized_url,
        position=1,
    )
    db_session.add(target)
    db_session.commit()
    return target


def _observation(target: RenderRunTarget) -> RenderedObservation:
    return RenderedObservation(
        render_run_id=target.render_run_id,
        render_run_target_id=target.id,
        web_resource_id=target.web_resource_id,
        snapshot_id=None,
        capture_state="capturing",
        started_at=datetime.now(UTC),
        requested_url=target.requested_url,
        browser_engine="chromium",
        renderer_version="2",
        browser_policy_version="2",
        capture_schema_version="2",
        viewport_width=1440,
        viewport_height=900,
        device_scale_factor=1.0,
        locale="en-US",
        timezone_id="UTC",
        color_scheme="light",
        reduced_motion="reduce",
        configuration_fingerprint="a" * 64,
    )


def test_same_web_resource_can_have_immutable_observations_in_repeated_runs(db_session) -> None:
    site, resource = _site_page(db_session)
    first_target = _run_target(db_session, site, resource)
    second_target = _run_target(db_session, site, resource)
    first = _observation(first_target)
    first.capture_state = "failed"
    first.navigation_http_status = 429
    first.error_type = "navigation_rate_limited"
    second = _observation(second_target)
    second.capture_state = "completed"
    second.navigation_http_status = 200
    db_session.add_all([first, second])
    db_session.commit()

    assert first.snapshot_id is None and second.snapshot_id is None
    assert first.web_resource_id == second.web_resource_id == resource.id
    assert first.render_run_id != second.render_run_id
    assert (first.navigation_http_status, second.navigation_http_status) == (429, 200)


def test_render_target_accepts_only_one_observation(db_session) -> None:
    site, resource = _site_page(db_session)
    target = _run_target(db_session, site, resource)
    db_session.add(_observation(target))
    db_session.commit()
    db_session.add(_observation(target))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_historical_scan_bound_observation_remains_readable_without_run(db_session) -> None:
    _site, resource = _site_page(db_session)
    scan = Scan(starting_url=resource.normalized_url, status="completed", scope_config={})
    db_session.add(scan)
    db_session.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.flush()
    legacy = _observation(
        RenderRunTarget(
            id=0,
            render_run_id=0,
            web_resource_id=resource.id,
            requested_url=resource.normalized_url,
            position=1,
        )
    )
    legacy.render_run_id = None
    legacy.render_run_target_id = None
    legacy.web_resource_id = None
    legacy.snapshot_id = snapshot.id
    db_session.add(legacy)
    db_session.commit()

    saved = db_session.get(RenderedObservation, legacy.id)
    assert saved is not None
    assert saved.snapshot_id == snapshot.id
    assert saved.render_run_id is None


def test_scan_deletion_preserves_run_evidence_and_detaches_optional_provenance(
    db_session, tmp_path
) -> None:
    site, resource = _site_page(db_session, "scan-source")
    scan = Scan(
        website_property_id=site.id,
        starting_url=resource.normalized_url,
        status="completed",
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=200,
        content_type="text/html",
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.flush()
    run = RenderRun(
        website_property_id=site.id,
        source_scan_id=scan.id,
        status="completed",
        trigger="scan",
        configuration_json={},
        target_count=1,
    )
    db_session.add(run)
    db_session.flush()
    target = RenderRunTarget(
        render_run_id=run.id,
        web_resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        requested_url=resource.normalized_url,
        position=1,
    )
    db_session.add(target)
    db_session.flush()
    observation = _observation(target)
    observation.snapshot_id = snapshot.id
    observation.capture_state = "completed"
    observation.navigation_http_status = 200
    db_session.add(observation)
    db_session.commit()
    scan_id, run_id, target_id, observation_id = scan.id, run.id, target.id, observation.id

    result = delete_scan(db_session, scan_id, LocalContentStore(tmp_path / "content"))

    assert result is not None
    assert result.rendered_observations_deleted == 0
    assert db_session.get(Scan, scan_id) is None
    preserved_run = db_session.get(RenderRun, run_id)
    preserved_target = db_session.get(RenderRunTarget, target_id)
    preserved_observation = db_session.get(RenderedObservation, observation_id)
    assert preserved_run is not None and preserved_run.source_scan_id is None
    assert preserved_target is not None and preserved_target.source_snapshot_id is None
    assert preserved_observation is not None and preserved_observation.snapshot_id is None


def test_ad_hoc_scan_deletion_removes_site_less_run_and_only_exclusive_artifacts(
    db_session, tmp_path
) -> None:
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/ad-hoc",
        scheme="https",
        host="example.com",
        path="/ad-hoc",
        query="",
    )
    scan = Scan(
        website_property_id=None,
        starting_url=resource.normalized_url,
        status="completed",
        scope_config={},
    )
    db_session.add_all([resource, scan])
    db_session.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=200,
        content_type="text/html",
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.flush()
    run = RenderRun(
        website_property_id=None,
        source_scan_id=scan.id,
        status="completed",
        trigger="scan",
        configuration_json={},
        target_count=1,
    )
    db_session.add(run)
    db_session.flush()
    target = RenderRunTarget(
        render_run_id=run.id,
        web_resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        requested_url=resource.normalized_url,
        position=1,
    )
    db_session.add(target)
    db_session.flush()
    observation = _observation(target)
    observation.snapshot_id = snapshot.id
    observation.capture_state = "completed"
    observation.navigation_http_status = 200
    db_session.add(observation)

    site, saved_resource = _site_page(db_session, "shared-artifact")
    saved_target = _run_target(db_session, site, saved_resource)
    saved_observation = _observation(saved_target)
    saved_observation.capture_state = "completed"
    saved_observation.navigation_http_status = 200
    db_session.add(saved_observation)
    db_session.commit()

    store = LocalArtifactStore(tmp_path / "artifacts")
    shared_blob = store.put(db_session, b"shared", "image/png")
    exclusive_blob = store.put(db_session, b"exclusive", "text/html")
    db_session.add_all(
        [
            RenderedArtifact(
                rendered_observation_id=observation.id,
                artifact_blob_id=shared_blob.id,
                artifact_type="viewport_screenshot",
                metadata_json={},
            ),
            RenderedArtifact(
                rendered_observation_id=observation.id,
                artifact_blob_id=exclusive_blob.id,
                artifact_type="rendered_dom",
                metadata_json={},
            ),
            RenderedArtifact(
                rendered_observation_id=saved_observation.id,
                artifact_blob_id=shared_blob.id,
                artifact_type="viewport_screenshot",
                metadata_json={},
            ),
        ]
    )
    db_session.commit()
    scan_id = scan.id
    run_id = run.id
    target_id = target.id
    observation_id = observation.id
    shared_blob_id = shared_blob.id
    exclusive_blob_id = exclusive_blob.id
    shared_path = store.path_for(shared_blob)
    exclusive_path = store.path_for(exclusive_blob)

    result = delete_scan(
        db_session,
        scan_id,
        LocalContentStore(tmp_path / "content"),
        store,
    )
    db_session.expire_all()

    assert result is not None
    assert result.rendered_observations_deleted == 1
    assert result.rendered_artifacts_deleted == 2
    assert db_session.get(Scan, scan_id) is None
    assert db_session.get(RenderRun, run_id) is None
    assert db_session.get(RenderRunTarget, target_id) is None
    assert db_session.get(RenderedObservation, observation_id) is None
    assert db_session.get(ArtifactBlob, exclusive_blob_id) is None
    assert not exclusive_path.exists()
    assert db_session.get(ArtifactBlob, shared_blob_id) is not None
    assert shared_path.exists()
    assert (
        db_session.query(RenderRun)
        .filter(RenderRun.website_property_id.is_(None), RenderRun.source_scan_id.is_(None))
        .count()
        == 0
    )


def test_site_deletion_cleans_render_runs_and_exclusive_artifact(db_session, tmp_path) -> None:
    site, resource = _site_page(db_session, "site-delete")
    target = _run_target(db_session, site, resource)
    observation = _observation(target)
    observation.capture_state = "completed"
    observation.navigation_http_status = 200
    db_session.add(observation)
    db_session.commit()
    store = LocalArtifactStore(tmp_path / "artifacts")
    blob = store.put(db_session, b"rendered", "text/plain")
    artifact_path = store.path_for(blob)
    artifact = RenderedArtifact(
        rendered_observation_id=observation.id,
        artifact_blob_id=blob.id,
        artifact_type="rendered_dom",
        metadata_json={},
    )
    db_session.add(artifact)
    db_session.commit()
    run_id, observation_id, blob_id = target.render_run_id, observation.id, blob.id

    assert delete_site(db_session, site.id, artifact_store=store) == site.id
    assert db_session.get(RenderRun, run_id) is None
    assert db_session.get(RenderedObservation, observation_id) is None
    assert db_session.get(ArtifactBlob, blob_id) is None
    assert not artifact_path.exists()


class _RateLimitedRenderer:
    calls: list[str] = []
    browser_version = "fixture-chromium"
    playwright_version = "fixture-playwright"

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def capture(self, url: str) -> CaptureResult:
        self.calls.append(url)
        if "limited.example" in url:
            return CaptureResult(
                state="failed",
                final_url=url,
                status=429,
                error_type="navigation_rate_limited",
                error_message="Main-document navigation was rate limited (HTTP 429).",
            )
        return CaptureResult(state="completed", final_url=url, status=200)


@pytest.mark.asyncio
async def test_standalone_run_uses_run_local_rate_limit_circuit(db_session) -> None:
    site = WebsiteProperty(
        name="Rate limit",
        base_url="https://limited.example/",
        normalized_base_url="https://limited.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={"allowed_host_patterns": ["limited.example", "healthy.example"]},
    )
    db_session.add(site)
    db_session.flush()
    run = RenderRun(
        website_property_id=site.id,
        status="queued",
        trigger="site_workspace",
        configuration_json=ScopeConfig(
            allowed_host_patterns=["limited.example", "healthy.example"],
            render_mode="all_eligible",
            max_pages=7,
            render_max_pages=7,
        ).to_dict(),
        target_count=7,
    )
    db_session.add(run)
    db_session.flush()
    urls = [f"https://limited.example/{index}" for index in range(6)] + [
        "https://healthy.example/ok"
    ]
    for position, url in enumerate(urls, 1):
        resource = WebResource(
            resource_type="page",
            normalized_url=url,
            scheme="https",
            host="limited.example" if "limited" in url else "healthy.example",
            path=f"/{url.rsplit('/', 1)[-1]}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add(
            RenderRunTarget(
                render_run_id=run.id,
                web_resource_id=resource.id,
                requested_url=url,
                position=position,
            )
        )
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    _RateLimitedRenderer.calls = []

    result = await execute_render_run(
        factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda *_args: None,
        renderer_factory=_RateLimitedRenderer,
    )

    limited_calls = [url for url in _RateLimitedRenderer.calls if "limited.example" in url]
    assert len(limited_calls) == HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD
    assert "https://healthy.example/ok" in _RateLimitedRenderer.calls
    assert result.status == "completed_with_errors"
    assert result.attempted_count == 4
    assert result.completed_count == 1
    assert result.failed_count == 3
    assert result.skipped_count == 3

    later_resource = WebResource(
        resource_type="page",
        normalized_url="https://limited.example/later",
        scheme="https",
        host="limited.example",
        path="/later",
        query="",
    )
    db_session.add(later_resource)
    db_session.flush()
    later_run = RenderRun(
        website_property_id=site.id,
        status="queued",
        trigger="rerender",
        configuration_json=ScopeConfig(
            allowed_host_patterns=["limited.example"],
            render_mode="all_eligible",
            max_pages=1,
            render_max_pages=1,
        ).to_dict(),
        target_count=1,
    )
    db_session.add(later_run)
    db_session.flush()
    db_session.add(
        RenderRunTarget(
            render_run_id=later_run.id,
            web_resource_id=later_resource.id,
            requested_url=later_resource.normalized_url,
            position=1,
        )
    )
    db_session.commit()

    later = await execute_render_run(
        factory,
        later_run.id,
        should_cancel=lambda: False,
        progress=lambda *_args: None,
        renderer_factory=_RateLimitedRenderer,
    )

    assert _RateLimitedRenderer.calls[-1] == later_resource.normalized_url
    assert later.attempted_count == 1
    assert later.failed_count == 1
    assert result.failed_count == 3


class _SuccessfulRenderer:
    calls: list[str] = []
    browser_version = "fixture-chromium"
    playwright_version = "fixture-playwright"

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def capture(self, url: str) -> CaptureResult:
        self.calls.append(url)
        return CaptureResult(state="completed", final_url=url, status=200)


@pytest.mark.asyncio
async def test_frozen_target_executes_after_page_is_suppressed(db_session) -> None:
    site, resource = _site_page(db_session, "freeze")
    run = create_render_run(
        db_session,
        site.id,
        RenderRunCreate(resource_ids=[resource.id]),
    )
    db_session.commit()
    page = db_session.query(SitePage).filter_by(resource_id=resource.id).one()
    page.workspace_state = "suppressed"
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    _SuccessfulRenderer.calls = []

    result = await execute_render_run(
        factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda *_args: None,
        renderer_factory=_SuccessfulRenderer,
    )

    assert result.status == "completed"
    assert _SuccessfulRenderer.calls == [resource.normalized_url]
    assert db_session.query(RenderedObservation).filter_by(render_run_id=run.id).count() == 1


@pytest.mark.asyncio
async def test_cancellation_preserves_completed_evidence_and_unattempted_targets(
    db_session,
) -> None:
    site, first = _site_page(db_session, "cancel-1")
    second = WebResource(
        resource_type="page",
        normalized_url="https://example.com/cancel-2",
        scheme="https",
        host="example.com",
        path="/cancel-2",
        query="",
    )
    db_session.add(second)
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=second.id))
    db_session.commit()
    run = create_render_run(
        db_session,
        site.id,
        RenderRunCreate(resource_ids=[first.id, second.id]),
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    checks = 0

    def cancel_before_second_target() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    result = await execute_render_run(
        factory,
        run.id,
        should_cancel=cancel_before_second_target,
        progress=lambda *_args: None,
        renderer_factory=_SuccessfulRenderer,
    )

    observations = db_session.query(RenderedObservation).filter_by(render_run_id=run.id).all()
    assert result.status == "cancelled"
    assert len(run.targets) == 2
    assert len(observations) == 1
    assert observations[0].capture_state == "completed"
