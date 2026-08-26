from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.browser.capture import CaptureResult
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticCrawlResult
from app.models import (
    BackgroundJob,
    ContentBlob,
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.render_runs import execute_render_run
from app.services.scan_execution import ScanExecutionCoordinator
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore


class _Progress:
    def check_cancelled(self) -> bool:
        return False

    def progress(self, **_values: object) -> None:
        return None


class _StaticCrawler:
    calls = 0

    def __init__(self, *_args: object, **_kwargs: object):
        pass

    async def collect(self, _scan: Scan) -> StaticCrawlResult:
        _StaticCrawler.calls += 1
        return StaticCrawlResult(False, False, "queue_exhausted")


class _SuccessfulRenderer:
    calls: list[str] = []
    browser_version = "fixture-chromium"
    playwright_version = "fixture-playwright"

    def __init__(self, *_args: object, **_kwargs: object):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object):
        return None

    async def capture(self, url: str) -> CaptureResult:
        self.calls.append(url)
        return CaptureResult(state="completed", final_url=url, status=200)


@pytest.mark.asyncio
async def test_saved_site_scan_queues_frozen_render_run_without_inline_browser(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ScopeConfig(
        allowed_host_patterns=["example.com"],
        render_mode="all_eligible",
        max_pages=2,
        render_max_pages=2,
    )
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config=config.to_dict(),
    )
    scan = Scan(
        website_property=site,
        starting_url="https://example.com/0",
        status="queued",
        scope_config=config.to_dict(),
    )
    blob = ContentBlob(
        sha256="c" * 64,
        storage_key="cc/content",
        compression_type="gzip",
        content_type="text/html",
        encoding="utf-8",
        raw_byte_size=10,
        stored_byte_size=8,
    )
    db_session.add_all([scan, blob])
    db_session.flush()
    started = datetime.now(UTC)
    snapshots: list[ResourceSnapshot] = []
    for index in range(2):
        url = f"https://example.com/{index}"
        resource = WebResource(
            resource_type="page",
            normalized_url=url,
            scheme="https",
            host="example.com",
            path=f"/{index}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        snapshot = ResourceSnapshot(
            scan_id=scan.id,
            resource_id=resource.id,
            requested_url=url,
            final_url=url,
            http_status=200,
            content_type="text/html",
            crawl_depth=0,
            fetched_at=started + timedelta(milliseconds=index),
            html_blob_id=blob.id,
            fetch_state="fetched",
        )
        db_session.add(snapshot)
        snapshots.append(snapshot)
    db_session.commit()

    monkeypatch.setattr("app.services.scan_execution.StaticPageCrawler", _StaticCrawler)
    coordinator = ScanExecutionCoordinator(
        db_session,
        LocalContentStore(tmp_path / "html"),
        LocalArtifactStore(tmp_path / "artifacts"),
        _Progress(),
    )
    summary = await coordinator.execute(scan)

    run = db_session.query(RenderRun).one()
    targets = db_session.query(RenderRunTarget).order_by(RenderRunTarget.position).all()
    job = db_session.query(BackgroundJob).filter_by(render_run_id=run.id).one()
    assert summary.status == scan.status == "completed"
    assert run.source_scan_id == scan.id
    assert run.status == "queued"
    assert [target.source_snapshot_id for target in targets] == [item.id for item in snapshots]
    assert [target.requested_url for target in targets] == [item.final_url for item in snapshots]
    assert job.job_type == "render_run"
    assert job.status == "queued"
    assert scan.rendered_selected_count == 2
    assert scan.rendered_attempted_count == 0
    assert run.observations == []


@pytest.mark.asyncio
async def test_ad_hoc_scan_queues_and_executes_site_less_render_run(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ScopeConfig(
        allowed_host_patterns=["example.com"],
        render_mode="all_eligible",
        max_pages=2,
        render_max_pages=2,
    )
    scan = Scan(
        website_property_id=None,
        starting_url="https://example.com/0",
        status="queued",
        scope_config=config.to_dict(),
    )
    blob = ContentBlob(
        sha256="d" * 64,
        storage_key="dd/content",
        compression_type="gzip",
        content_type="text/html",
        encoding="utf-8",
        raw_byte_size=10,
        stored_byte_size=8,
    )
    db_session.add_all([scan, blob])
    db_session.flush()
    snapshots: list[ResourceSnapshot] = []
    for index in range(2):
        url = f"https://example.com/{index}"
        resource = WebResource(
            resource_type="page",
            normalized_url=url,
            scheme="https",
            host="example.com",
            path=f"/{index}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        snapshot = ResourceSnapshot(
            scan_id=scan.id,
            resource_id=resource.id,
            requested_url=url,
            final_url=url,
            http_status=200,
            content_type="text/html",
            crawl_depth=0,
            fetched_at=datetime.now(UTC) + timedelta(milliseconds=index),
            html_blob_id=blob.id,
            fetch_state="fetched",
        )
        db_session.add(snapshot)
        snapshots.append(snapshot)
    db_session.commit()

    _StaticCrawler.calls = 0
    monkeypatch.setattr("app.services.scan_execution.StaticPageCrawler", _StaticCrawler)
    coordinator = ScanExecutionCoordinator(
        db_session,
        LocalContentStore(tmp_path / "html"),
        LocalArtifactStore(tmp_path / "artifacts"),
        _Progress(),
    )
    summary = await coordinator.execute(scan)

    run = db_session.query(RenderRun).one()
    targets = db_session.query(RenderRunTarget).order_by(RenderRunTarget.position).all()
    job = db_session.query(BackgroundJob).filter_by(render_run_id=run.id).one()
    assert summary.status == scan.status == "completed"
    assert scan.stop_reason != "render_run_requires_saved_site"
    assert scan.rendered_selected_count == 2
    assert scan.rendered_skipped_count == 0
    assert run.website_property_id is None
    assert run.source_scan_id == scan.id
    assert [target.source_snapshot_id for target in targets] == [item.id for item in snapshots]
    assert job.job_type == "render_run"
    assert job.website_property_id is None
    assert _StaticCrawler.calls == 1

    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    _SuccessfulRenderer.calls = []
    completed = await execute_render_run(
        factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda *_args: None,
        renderer_factory=_SuccessfulRenderer,
    )

    observations = db_session.query(RenderedObservation).filter_by(render_run_id=run.id).all()
    assert completed.status == "completed"
    assert _SuccessfulRenderer.calls == [item.requested_url for item in targets]
    assert _StaticCrawler.calls == 1
    assert len(observations) == 2
    assert all(item.navigation_http_status == 200 for item in observations)
    assert all(item.renderer_version == "2" for item in observations)
    assert all(item.snapshot_id is not None for item in observations)
