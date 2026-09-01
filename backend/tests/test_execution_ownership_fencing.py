import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.crawler.scope import ScopeConfig
from app.database import Base
from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    BackgroundJob,
    ContentBlob,
    HtmlParseArtifact,
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    ScanProjectionBuild,
    SitePage,
    SourceRefresh,
    StaticFetchAttempt,
    UrlSource,
    UrlSourceEntry,
    WebsiteProperty,
)
from app.schemas.ai_documents import AiDocumentSourceCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.schemas.sources import UrlSourceCreate
from app.services import background_jobs, job_handlers, scan_execution
from app.services.ai_document_sources import create_ai_document_source
from app.services.job_handlers import (
    JobHandlerRegistry,
    ScanJobHandler,
    SourceRefreshJobHandler,
    run_claimed_job,
)
from app.services.job_types import JOB_TYPE_SCAN, JOB_TYPE_SOURCE_REFRESH
from app.services.site_management import create_site
from app.services.source_management import create_source
from app.services.source_refresh import create_source_refresh, execute_source_refresh
from app.storage.ai_document_store import LocalAiDocumentStore
from app.storage.content_store import LocalContentStore


class _BlockingTransport(httpx.AsyncBaseTransport):
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.content_type = content_type
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.started.set()
        await self.release.wait()
        return httpx.Response(
            200,
            headers={"content-type": self.content_type},
            content=self.content,
            request=request,
        )


class _BlockingSitemapTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            self.started.set()
            await self.release.wait()
            content = (
                b"<sitemapindex><sitemap><loc>https://source-fence.example/child.xml</loc>"
                b"</sitemap></sitemapindex>"
            )
        else:
            content = b"<urlset><url><loc>https://source-fence.example/stale</loc></url></urlset>"
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=content,
            request=request,
        )


class _TwoPageTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.second_started = asyncio.Event()
        self.release_second = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/second":
            self.second_started.set()
            await self.release_second.wait()
            body = b"<html><body>second</body></html>"
        else:
            body = b'<html><body>first<a href="/second">Second</a></body></html>'
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=body,
            request=request,
        )


class _ImmediatePageTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>ready</body></html>",
            request=request,
        )


@pytest.mark.asyncio
async def test_scan_recovery_rejects_in_flight_page_and_preserves_pre_loss_evidence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path, "scan-fence.db")
    transport = _TwoPageTransport()
    original_crawler = scan_execution.StaticPageCrawler

    def crawler_with_transport(db, store, **kwargs):
        return original_crawler(db, store, transport=transport, **kwargs)

    monkeypatch.setattr(scan_execution, "StaticPageCrawler", crawler_with_transport)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        job_handlers,
        "get_settings",
        lambda: SimpleNamespace(
            rendered_artifact_storage_root=tmp_path / "rendered",
            ai_document_storage_root=tmp_path / "ai",
        ),
    )
    with session_factory() as db:
        site = create_site(
            db,
            WebsitePropertyCreate(
                name="Scan fencing",
                base_url="https://scan-fence.example/",
                scope_config=ScopeConfigPayload(),
            ),
        )
        config = ScopeConfig(
            allowed_host_patterns=["scan-fence.example"],
            allow_private_networks=True,
            max_pages=2,
            render_mode="none",
        )
        scan = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="queued",
            scope_config=config.to_dict(),
        )
        db.add(scan)
        db.flush()
        job = background_jobs.enqueue_scan_job(db, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="scan-fence", lease_seconds=30)
        assert claimed is not None
        scan_id, job_id = scan.id, job.id

    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {
                    JOB_TYPE_SCAN: ScanJobHandler(
                        session_factory, LocalContentStore(tmp_path / "html")
                    )
                }
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    await asyncio.wait_for(transport.second_started.wait(), timeout=5)
    assert await asyncio.to_thread(_force_recovery, session_factory, job_id) == 1
    transport.release_second.set()
    await task

    with session_factory() as db:
        persisted_scan = db.get(Scan, scan_id)
        assert persisted_scan is not None and persisted_scan.status == "interrupted"
        assert persisted_scan.fetched_count == 1
        snapshots = list(
            db.scalars(select(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan_id))
        )
        assert len(snapshots) == 1 and snapshots[0].requested_url.endswith("/")
        assert db.scalar(select(func.count()).select_from(StaticFetchAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(ContentBlob)) == 1
        assert db.scalar(select(func.count()).select_from(HtmlParseArtifact)) == 1
        assert db.scalar(select(func.count()).select_from(ResourceOccurrence)) == 1
        assert db.scalar(select(func.count()).select_from(ResourceReferenceOccurrence)) == 0
        assert db.scalar(select(func.count()).select_from(SitePage)) == 1


@pytest.mark.asyncio
async def test_scan_recovery_rejects_stale_finalization_and_projection_enqueue(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path, "scan-final-fence.db")
    original_crawler = scan_execution.StaticPageCrawler
    transport = _ImmediatePageTransport()
    finalization_started = threading.Event()
    release_finalization = threading.Event()
    recovery_results: list[int] = []

    def crawler_with_transport(db, store, **kwargs):
        return original_crawler(db, store, transport=transport, **kwargs)

    def block_before_finalization(*_args, **_kwargs):
        finalization_started.set()
        assert release_finalization.wait(timeout=5)
        return []

    monkeypatch.setattr(scan_execution, "StaticPageCrawler", crawler_with_transport)
    monkeypatch.setattr(scan_execution, "select_render_candidates", block_before_finalization)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        job_handlers,
        "get_settings",
        lambda: SimpleNamespace(
            rendered_artifact_storage_root=tmp_path / "rendered-final",
            ai_document_storage_root=tmp_path / "ai-final",
        ),
    )
    with session_factory() as db:
        site = create_site(db, _site_payload("scan-final-fence.example"))
        config = ScopeConfig(
            allowed_host_patterns=["scan-final-fence.example"],
            allow_private_networks=True,
            max_pages=1,
            render_mode="none",
        )
        scan = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="queued",
            scope_config=config.to_dict(),
        )
        db.add(scan)
        db.flush()
        job = background_jobs.enqueue_scan_job(db, scan)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="scan-final-fence", lease_seconds=30)
        assert claimed is not None
        scan_id, job_id = scan.id, job.id

    def recover_then_release() -> None:
        assert finalization_started.wait(timeout=5)
        recovery_results.append(_force_recovery(session_factory, job_id))
        release_finalization.set()

    recovery_thread = threading.Thread(target=recover_then_release)
    recovery_thread.start()
    await run_claimed_job(
        session_factory=session_factory,
        registry=JobHandlerRegistry(
            {
                JOB_TYPE_SCAN: ScanJobHandler(
                    session_factory, LocalContentStore(tmp_path / "html-final")
                )
            }
        ),
        claimed_job=claimed,
        lease_seconds=30,
    )
    recovery_thread.join(timeout=5)

    assert recovery_results == [1]
    with session_factory() as db:
        persisted_scan = db.get(Scan, scan_id)
        assert persisted_scan is not None and persisted_scan.status == "interrupted"
        assert persisted_scan.fetched_count == 1
        assert db.scalar(select(func.count()).select_from(ResourceSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(ScanProjectionBuild)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.job_type == "scan_projection_build")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_source_refresh_recovery_rejects_stale_sitemap_inventory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path, "source-fence.db")
    transport = _BlockingSitemapTransport()
    await _run_blocked_source_job(
        session_factory,
        tmp_path,
        monkeypatch,
        transport,
        source_kind="sitemap",
    )
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(UrlSourceEntry)) == 0
        assert db.scalar(select(func.count()).select_from(UrlSource)) == 1
        assert db.scalar(select(func.count()).select_from(SourceRefresh)) == 1


@pytest.mark.asyncio
async def test_ai_document_recovery_rejects_stale_result_and_preserves_prior_evidence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path, "ai-fence.db")
    with session_factory() as db:
        site = create_site(db, _site_payload("ai-fence.example"))
        source = create_ai_document_source(
            db,
            site.id,
            AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
        )
        assert source is not None
        prior_refresh = create_source_refresh(db, site.id, source.id)
        assert prior_refresh is not None
        await execute_source_refresh(
            db,
            prior_refresh.id,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "text/plain"},
                    content=b"# Stable evidence",
                    request=request,
                )
            ),
            ai_document_store=LocalAiDocumentStore(tmp_path / "ai"),
        )
        prior_counts = _ai_counts(db)

    transport = _BlockingTransport(b"# Stale returned evidence", "text/plain")
    await _run_blocked_source_job(
        session_factory,
        tmp_path,
        monkeypatch,
        transport,
        source_kind="ai_document",
    )
    with session_factory() as db:
        current_counts = _ai_counts(db)
        assert current_counts[0] == prior_counts[0] + 1
        assert current_counts[1:] == prior_counts[1:]
        stale_refresh = db.scalar(select(AiDocumentRefresh).order_by(AiDocumentRefresh.id.desc()))
        assert stale_refresh is not None and stale_refresh.status == "interrupted"


async def _run_blocked_source_job(
    session_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    transport: _BlockingTransport | _BlockingSitemapTransport,
    *,
    source_kind: str,
) -> None:
    with session_factory() as db:
        site = db.scalar(select(WebsiteProperty))
        if site is None:
            site = create_site(db, _site_payload("source-fence.example"))
        if source_kind == "ai_document":
            source = db.scalar(select(UrlSource).where(UrlSource.source_type == "ai_document"))
        else:
            source = create_source(
                db,
                site.id,
                UrlSourceCreate(name="Sitemap", source_url="/sitemap.xml"),
            )
        assert source is not None
        refresh = create_source_refresh(db, site.id, source.id)
        assert refresh is not None
        job = background_jobs.enqueue_source_refresh_job(db, refresh)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="source-fence", lease_seconds=30)
        assert claimed is not None
        refresh_id, job_id = refresh.id, job.id

    original_execute = job_handlers.execute_source_refresh

    async def execute_with_transport(db, refresh_id, **kwargs):
        return await original_execute(db, refresh_id, transport=transport, **kwargs)

    monkeypatch.setattr(job_handlers, "execute_source_refresh", execute_with_transport)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        job_handlers,
        "get_settings",
        lambda: SimpleNamespace(ai_document_storage_root=tmp_path / "ai"),
    )
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_SOURCE_REFRESH: SourceRefreshJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    await asyncio.wait_for(transport.started.wait(), timeout=5)
    assert await asyncio.to_thread(_force_recovery, session_factory, job_id) == 1
    transport.release.set()
    await task
    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_refresh = db.get(SourceRefresh, refresh_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_refresh is not None and persisted_refresh.status == "interrupted"


def _session_factory(tmp_path, filename: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / filename}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _force_recovery(session_factory, job_id: int) -> int:
    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with session_factory() as db:
        return background_jobs.recover_expired_jobs(db)


def _site_payload(host: str) -> WebsitePropertyCreate:
    return WebsitePropertyCreate(
        name=host,
        base_url=f"https://{host}/",
        scope_config=ScopeConfigPayload(allowed_host_patterns=[host], allow_private_networks=True),
    )


def _ai_counts(db) -> tuple[int, int, int, int, int]:
    return tuple(
        int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in (
            AiDocumentRefresh,
            AiDocumentSnapshot,
            AiDocumentReference,
            AiDocumentBlob,
            UrlSourceEntry,
        )
    )  # type: ignore[return-value]
