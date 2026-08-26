from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.browser.capture import CapturedArtifact, CaptureResult
from app.browser.outcomes import HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticCrawlResult
from app.models import ContentBlob, RenderedObservation, ResourceSnapshot, Scan, WebResource
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


class _Renderer:
    calls: list[str] = []
    browser_version = "fixture-chromium"
    playwright_version = "fixture-playwright"

    def __init__(self, *_args: object, **_kwargs: object):
        pass

    async def __aenter__(self) -> "_Renderer":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def capture(self, url: str) -> CaptureResult:
        type(self).calls.append(url)
        if "limited.example" in url:
            return CaptureResult(
                state="failed",
                final_url=url,
                status=429,
                error_type="navigation_rate_limited",
                error_message="Main-document navigation was rate limited (HTTP 429).",
                network=[
                    {
                        "sequence": 1,
                        "request_key": "a" * 64,
                        "redacted_url": url,
                        "url_sha256": "b" * 64,
                        "method": "GET",
                        "resource_type": "document",
                        "is_main_navigation": True,
                        "is_navigation_request": True,
                        "response_status": 429,
                        "request_headers_json": {},
                        "response_headers_json": {"retry-after": "120"},
                        "blocked_by_policy": False,
                    }
                ],
            )
        return CaptureResult(
            final_url=url,
            status=200,
            artifacts=[CapturedArtifact("rendered_dom", b"<html></html>", "text/plain")],
        )


@pytest.mark.asyncio
async def test_scan_render_circuit_skips_only_throttled_host(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ScopeConfig(
        allowed_host_patterns=["limited.example", "healthy.example"],
        render_mode="all_eligible",
        max_pages=7,
        render_max_pages=7,
    )
    scan = Scan(
        starting_url="https://limited.example/0",
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
    urls = [f"https://limited.example/{index}" for index in range(6)] + [
        "https://healthy.example/ok"
    ]
    for index, url in enumerate(urls):
        host = "limited.example" if "limited" in url else "healthy.example"
        resource = WebResource(
            resource_type="page",
            normalized_url=url,
            scheme="https",
            host=host,
            path=f"/{url.rsplit('/', 1)[-1]}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add(
            ResourceSnapshot(
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
        )
    db_session.commit()

    _Renderer.calls = []
    monkeypatch.setattr("app.services.scan_execution.StaticPageCrawler", _StaticCrawler)
    monkeypatch.setattr("app.services.scan_execution.BrowserRenderer", _Renderer)
    coordinator = ScanExecutionCoordinator(
        db_session,
        LocalContentStore(tmp_path / "html"),
        LocalArtifactStore(tmp_path / "artifacts"),
        _Progress(),
    )
    summary = await coordinator.execute(scan)

    limited_calls = [url for url in _Renderer.calls if "limited.example" in url]
    assert len(limited_calls) == HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD
    assert "https://healthy.example/ok" in _Renderer.calls
    assert scan.rendered_selected_count == 7
    assert scan.rendered_attempted_count == 4
    assert scan.rendered_completed_count == 1
    assert scan.rendered_failed_count == 3
    assert scan.rendered_skipped_count == 3
    assert scan.rendered_artifact_count == 1
    assert summary.status == "completed_with_errors"

    observations = db_session.query(RenderedObservation).order_by(RenderedObservation.id).all()
    skipped = [item for item in observations if item.capture_state == "skipped"]
    assert len(skipped) == 3
    assert all(item.error_type == "host_rate_limit_circuit_open" for item in skipped)
    assert all(item.navigation_http_status is None for item in skipped)
    assert all(item.network_entries == [] for item in skipped)
    assert all(item.artifacts == [] for item in skipped)
