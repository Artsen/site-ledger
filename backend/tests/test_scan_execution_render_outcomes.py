from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticCrawlResult
from app.models import (
    BackgroundJob,
    ContentBlob,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.scan_execution import ScanExecutionCoordinator
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore


class _Progress:
    def check_cancelled(self) -> bool:
        return False

    def progress(self, **_values: object) -> None:
        return None


class _StaticCrawler:
    def __init__(self, *_args: object, **_kwargs: object):
        pass

    async def collect(self, _scan: Scan) -> StaticCrawlResult:
        return StaticCrawlResult(False, False, "queue_exhausted")


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
