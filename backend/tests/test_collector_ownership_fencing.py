import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.accessibility.audit import AccessibilityAuditResult
from app.accessibility.engine import AXE_CORE_VERSION
from app.browser.capture import CapturedArtifact, CaptureResult
from app.crawler.scope import ScopeConfig
from app.database import Base
from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityPayloadBlob,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    ArtifactBlob,
    BackgroundJob,
    JobEvent,
    PerformanceObservation,
    PerformancePayloadBlob,
    PerformanceRun,
    RenderedArtifact,
    RenderedConsoleMessage,
    RenderedNetworkEntry,
    RenderedObservation,
    RenderedPageError,
    RenderRun,
    RenderRunTarget,
    SitePage,
    WebResource,
)
from app.schemas.accessibility import AccessibilityRunCreate
from app.schemas.performance import PerformanceRunCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services import (
    accessibility_collection,
    background_jobs,
    job_handlers,
    performance_collection,
    render_runs,
)
from app.services.accessibility_collection import create_accessibility_run
from app.services.job_handlers import (
    AccessibilityRunJobHandler,
    JobExecutionContext,
    JobHandlerRegistry,
    PerformanceRunJobHandler,
    RenderRunJobHandler,
    run_claimed_job,
)
from app.services.job_types import (
    JOB_TYPE_ACCESSIBILITY_RUN,
    JOB_TYPE_PERFORMANCE_RUN,
    JOB_TYPE_RENDER_RUN,
)
from app.services.performance_collection import create_performance_run
from app.services.performance_providers import ProviderResult
from app.services.site_management import create_site


@pytest.mark.asyncio
async def test_performance_recovery_rejects_post_loss_result_and_keeps_pre_loss_evidence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    payload_root = tmp_path / "performance-payloads"
    settings = _performance_settings(payload_root)
    monkeypatch.setattr(performance_collection, "get_settings", lambda: settings)
    with session_factory() as db:
        site_id, resource_ids = _site_pages(db, "performance-race.example", 2)
        run = create_performance_run(
            db,
            site_id,
            PerformanceRunCreate(
                resource_ids=resource_ids,
                providers=["pagespeed"],
                pagespeed_strategies=["mobile"],
                crux_form_factors=[],
                include_origin_crux=False,
            ),
        )
        job = background_jobs.enqueue_performance_run_job(db, run.id, site_id)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id="performance-race", lease_seconds=30)
        assert claimed is not None
        run_id, job_id = run.id, job.id

    second_started = threading.Event()
    release_second = threading.Event()

    class BlockingClient:
        calls = 0

        def pagespeed(self, target: str, _strategy: str) -> ProviderResult:
            self.calls += 1
            if self.calls == 2:
                second_started.set()
                assert release_second.wait(timeout=5)
            return ProviderResult(
                outcome="ready",
                payload=json.dumps({"target": target}).encode(),
                metrics={"lcp": {"value": 1200 + self.calls, "unit": "ms"}},
                provider_target=target,
                provider_product_version="test-v1",
            )

        def close(self) -> None:
            pass

    client = BlockingClient()
    monkeypatch.setattr(
        performance_collection, "PerformanceProviderClient", lambda *_args, **_kwargs: client
    )
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_PERFORMANCE_RUN: PerformanceRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(second_started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_second.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_run = db.get(PerformanceRun, run_id)
        observations = list(
            db.scalars(
                select(PerformanceObservation).where(
                    PerformanceObservation.performance_run_id == run_id
                )
            )
        )
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_job.error_type == "lease_expired"
        assert persisted_run is not None and persisted_run.status == "failed"
        assert persisted_run.error_summary == "Worker lease expired during Performance collection."
        assert (persisted_run.completed_count, persisted_run.ready_count) == (1, 1)
        assert len(observations) == 1
        assert observations[0].web_resource_id == resource_ids[0]
        assert db.scalar(select(func.count()).select_from(PerformancePayloadBlob)) == 1
        assert _event_count(db, job_id, "completed") == 0
    assert _payload_files(payload_root) == 1


@pytest.mark.asyncio
async def test_accessibility_recovery_rejects_stale_audit_payload_and_normalized_evidence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    payload_root = tmp_path / "accessibility-payloads"
    settings = _accessibility_settings(payload_root)
    monkeypatch.setattr(accessibility_collection, "get_settings", lambda: settings)
    monkeypatch.setattr(accessibility_collection, "BrowserRenderer", _FakeBrowserRenderer)
    with session_factory() as db:
        site_id, resource_ids = _site_pages(db, "accessibility-race.example", 1)
        run = create_accessibility_run(
            db,
            site_id,
            AccessibilityRunCreate(resource_ids=resource_ids, profiles=["desktop"]),
        )
        job = background_jobs.enqueue_accessibility_run_job(db, run.id, site_id)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="accessibility-race", lease_seconds=30
        )
        assert claimed is not None
        run_id, job_id = run.id, job.id

    audit_started = threading.Event()
    release_audit = threading.Event()

    async def blocked_audit(
        _renderer: object, url: str, _profile: str, *, max_payload_bytes: int
    ) -> AccessibilityAuditResult:
        payload = json.dumps(_axe_payload(url), sort_keys=True, separators=(",", ":")).encode()
        assert len(payload) < max_payload_bytes
        audit_started.set()
        assert await asyncio.to_thread(release_audit.wait, 5)
        return AccessibilityAuditResult(
            outcome="ready",
            final_url=url,
            payload=payload,
            browser_version="test-chromium",
            playwright_version="test-playwright",
        )

    monkeypatch.setattr(accessibility_collection, "audit_page", blocked_audit)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_ACCESSIBILITY_RUN: AccessibilityRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(audit_started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_audit.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_run = db.get(AccessibilityRun, run_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_job.error_type == "lease_expired"
        assert persisted_run is not None and persisted_run.status == "interrupted"
        assert (
            persisted_run.error_summary == "Worker lease expired during Accessibility collection."
        )
        assert persisted_run.completed_count == 0
        assert db.scalar(select(func.count()).select_from(AccessibilityObservation)) == 0
        assert db.scalar(select(func.count()).select_from(AccessibilityPayloadBlob)) == 0
        assert db.scalar(select(func.count()).select_from(AccessibilityRuleEvidence)) == 0
        assert db.scalar(select(func.count()).select_from(AccessibilityNodeEvidence)) == 0
        assert _event_count(db, job_id, "completed") == 0
    assert _payload_files(payload_root) == 0


@pytest.mark.asyncio
async def test_recovery_before_performance_completion_preserves_evidence_and_run_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    payload_root = tmp_path / "finalization-payloads"
    settings = _performance_settings(payload_root)
    monkeypatch.setattr(performance_collection, "get_settings", lambda: settings)
    with session_factory() as db:
        site_id, resource_ids = _site_pages(db, "performance-final.example", 1)
        run = create_performance_run(
            db,
            site_id,
            PerformanceRunCreate(
                resource_ids=resource_ids,
                providers=["pagespeed"],
                pagespeed_strategies=["mobile"],
                crux_form_factors=[],
                include_origin_crux=False,
            ),
        )
        job = background_jobs.enqueue_performance_run_job(db, run.id, site_id)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="performance-final", lease_seconds=30
        )
        assert claimed is not None
        run_id, job_id = run.id, job.id

    class ReadyClient:
        def pagespeed(self, target: str, _strategy: str) -> ProviderResult:
            return ProviderResult(
                outcome="ready",
                payload=b'{"finalization":"authorized"}',
                metrics={"lcp": {"value": 1000, "unit": "ms"}},
                provider_target=target,
            )

        def close(self) -> None:
            pass

    progress_reached = threading.Event()
    release_progress = threading.Event()

    def paused_progress(self: JobExecutionContext, **_kwargs: object) -> None:
        progress_reached.set()
        assert release_progress.wait(timeout=5)

    monkeypatch.setattr(
        performance_collection,
        "PerformanceProviderClient",
        lambda *_args, **_kwargs: ReadyClient(),
    )
    monkeypatch.setattr(JobExecutionContext, "progress", paused_progress)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_PERFORMANCE_RUN: PerformanceRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(progress_reached.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_progress.set()
    await task

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_run = db.get(PerformanceRun, run_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_run is not None and persisted_run.status == "failed"
        assert (persisted_run.completed_count, persisted_run.ready_count) == (1, 1)
        assert (
            db.scalar(
                select(func.count())
                .select_from(PerformanceObservation)
                .where(PerformanceObservation.performance_run_id == run_id)
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(PerformancePayloadBlob)) == 1
        assert _event_count(db, job_id, "completed") == 0
    assert _payload_files(payload_root) == 1


@pytest.mark.asyncio
async def test_performance_cancellation_cannot_overwrite_recovery_after_ownership_loss(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    settings = _performance_settings(tmp_path / "cancellation-payloads")
    monkeypatch.setattr(performance_collection, "get_settings", lambda: settings)
    with session_factory() as db:
        site_id, resource_ids = _site_pages(db, "performance-cancel.example", 1)
        run = create_performance_run(
            db,
            site_id,
            PerformanceRunCreate(
                resource_ids=resource_ids,
                providers=["pagespeed"],
                pagespeed_strategies=["mobile"],
                crux_form_factors=[],
                include_origin_crux=False,
            ),
        )
        job = background_jobs.enqueue_performance_run_job(db, run.id, site_id)
        db.commit()
        claimed = background_jobs.claim_next_job(
            db, worker_id="performance-cancel", lease_seconds=30
        )
        assert claimed is not None
        run_id, job_id = run.id, job.id
    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        assert persisted_job is not None
        background_jobs.request_cancellation(db, persisted_job)

    class UnusedClient:
        def close(self) -> None:
            pass

    original_mark_cancelled = performance_collection._mark_cancelled

    def recovery_before_cancel(session_factory_arg, run_id_arg, fence_domain_mutation):
        assert _force_recovery(session_factory, job_id) == 1
        return original_mark_cancelled(session_factory_arg, run_id_arg, fence_domain_mutation)

    monkeypatch.setattr(
        performance_collection,
        "PerformanceProviderClient",
        lambda *_args, **_kwargs: UnusedClient(),
    )
    monkeypatch.setattr(performance_collection, "_mark_cancelled", recovery_before_cancel)
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    await run_claimed_job(
        session_factory=session_factory,
        registry=JobHandlerRegistry(
            {JOB_TYPE_PERFORMANCE_RUN: PerformanceRunJobHandler(session_factory)}
        ),
        claimed_job=claimed,
        lease_seconds=30,
    )

    with session_factory() as db:
        persisted_job = db.get(BackgroundJob, job_id)
        persisted_run = db.get(PerformanceRun, run_id)
        assert persisted_job is not None and persisted_job.status == "interrupted"
        assert persisted_run is not None and persisted_run.status == "failed"
        assert persisted_run.error_summary == "Worker lease expired during Performance collection."
        assert db.scalar(select(func.count()).select_from(PerformanceObservation)) == 0
        assert _event_count(db, job_id, "cancelled") == 0


@pytest.mark.asyncio
async def test_render_recovery_rejects_stale_capture_evidence_and_artifacts(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    artifact_root = tmp_path / "render-stale-artifacts"
    run_id, job_id, claimed = _create_render_job(
        session_factory, "render-stale.example", 1, worker_id="render-stale"
    )
    capture_started = threading.Event()
    release_capture = threading.Event()

    class BlockingRenderer(_RenderRenderer):
        async def capture(self, url: str) -> CaptureResult:
            capture_started.set()
            assert await asyncio.to_thread(release_capture.wait, 5)
            return _rich_capture(url, b"stale-render-artifact")

    _install_render_executor(monkeypatch, BlockingRenderer)
    monkeypatch.setattr(
        render_runs,
        "get_settings",
        lambda: SimpleNamespace(rendered_artifact_storage_root=artifact_root),
    )
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_RENDER_RUN: RenderRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(capture_started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_capture.set()
    await task

    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        run = db.get(RenderRun, run_id)
        observation = db.scalar(
            select(RenderedObservation).where(RenderedObservation.render_run_id == run_id)
        )
        assert job is not None and job.status == "interrupted"
        assert run is not None and run.status == "interrupted"
        assert observation is not None and observation.capture_state == "interrupted"
        assert observation.error_type == "interrupted"
        assert db.scalar(select(func.count()).select_from(RenderedNetworkEntry)) == 0
        assert db.scalar(select(func.count()).select_from(RenderedConsoleMessage)) == 0
        assert db.scalar(select(func.count()).select_from(RenderedPageError)) == 0
        assert db.scalar(select(func.count()).select_from(RenderedArtifact)) == 0
        assert db.scalar(select(func.count()).select_from(ArtifactBlob)) == 0
        assert _event_count(db, job_id, "completed") == 0
    assert _payload_files(artifact_root) == 0


@pytest.mark.asyncio
async def test_render_recovery_keeps_pre_loss_evidence_and_rejects_second_capture(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    artifact_root = tmp_path / "render-two-target-artifacts"
    run_id, job_id, claimed = _create_render_job(
        session_factory, "render-two-target.example", 2, worker_id="render-two-target"
    )
    second_started = threading.Event()
    release_second = threading.Event()

    class TwoTargetRenderer(_RenderRenderer):
        calls = 0

        async def capture(self, url: str) -> CaptureResult:
            self.calls += 1
            if self.calls == 2:
                second_started.set()
                assert await asyncio.to_thread(release_second.wait, 5)
            return _rich_capture(url, f"artifact-{self.calls}".encode())

    _install_render_executor(monkeypatch, TwoTargetRenderer)
    monkeypatch.setattr(
        render_runs,
        "get_settings",
        lambda: SimpleNamespace(rendered_artifact_storage_root=artifact_root),
    )
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_RENDER_RUN: RenderRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(second_started.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_second.set()
    await task

    with session_factory() as db:
        observations = list(
            db.scalars(
                select(RenderedObservation)
                .where(RenderedObservation.render_run_id == run_id)
                .order_by(RenderedObservation.id)
            )
        )
        assert db.get(BackgroundJob, job_id).status == "interrupted"
        assert db.get(RenderRun, run_id).status == "interrupted"
        assert [item.capture_state for item in observations] == ["completed", "interrupted"]
        assert db.scalar(select(func.count()).select_from(RenderedNetworkEntry)) == 1
        assert db.scalar(select(func.count()).select_from(RenderedConsoleMessage)) == 1
        assert db.scalar(select(func.count()).select_from(RenderedPageError)) == 1
        assert db.scalar(select(func.count()).select_from(RenderedArtifact)) == 1
        assert db.scalar(select(func.count()).select_from(ArtifactBlob)) == 1
        assert _event_count(db, job_id, "completed") == 0
    assert _payload_files(artifact_root) == 1


@pytest.mark.asyncio
async def test_render_recovery_before_finalization_keeps_interrupted_run(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    artifact_root = tmp_path / "render-finalization-artifacts"
    run_id, job_id, claimed = _create_render_job(
        session_factory, "render-finalization.example", 1, worker_id="render-finalization"
    )
    progress_reached = threading.Event()
    release_progress = threading.Event()

    class ReadyRenderer(_RenderRenderer):
        async def capture(self, url: str) -> CaptureResult:
            return _rich_capture(url, b"authorized-render-artifact")

    def paused_progress(self: JobExecutionContext, **_kwargs: object) -> None:
        progress_reached.set()
        assert release_progress.wait(timeout=5)

    _install_render_executor(monkeypatch, ReadyRenderer)
    monkeypatch.setattr(JobExecutionContext, "progress", paused_progress)
    monkeypatch.setattr(
        render_runs,
        "get_settings",
        lambda: SimpleNamespace(rendered_artifact_storage_root=artifact_root),
    )
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_RENDER_RUN: RenderRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(progress_reached.wait, 5)
    assert _force_recovery(session_factory, job_id) == 1
    release_progress.set()
    await task

    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        run = db.get(RenderRun, run_id)
        observation = db.scalar(
            select(RenderedObservation).where(RenderedObservation.render_run_id == run_id)
        )
        assert job is not None and job.status == "interrupted"
        assert run is not None and run.status == "interrupted"
        assert observation is not None and observation.capture_state == "completed"
        assert db.scalar(select(func.count()).select_from(RenderedArtifact)) == 1
        assert _event_count(db, job_id, "completed") == 0
    assert _payload_files(artifact_root) == 1


@pytest.mark.asyncio
async def test_render_cancellation_cannot_overwrite_recovery_after_ownership_loss(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = _session_factory(tmp_path)
    artifact_root = tmp_path / "render-cancellation-artifacts"
    run_id, job_id, claimed = _create_render_job(
        session_factory, "render-cancellation.example", 1, worker_id="render-cancellation"
    )
    capture_started = threading.Event()

    class CancelledRenderer(_RenderRenderer):
        async def capture(self, _url: str) -> CaptureResult:
            capture_started.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled capture unexpectedly resumed")

    original_mark_observation_cancelled = render_runs._mark_observation_cancelled

    def recovery_before_observation_cancel(
        session_factory_arg, observation_id_arg, fence_domain_mutation
    ):
        assert _force_recovery(session_factory, job_id) == 1
        return original_mark_observation_cancelled(
            session_factory_arg, observation_id_arg, fence_domain_mutation
        )

    _install_render_executor(monkeypatch, CancelledRenderer)
    monkeypatch.setattr(
        render_runs, "_mark_observation_cancelled", recovery_before_observation_cancel
    )
    monkeypatch.setattr(
        render_runs,
        "get_settings",
        lambda: SimpleNamespace(rendered_artifact_storage_root=artifact_root),
    )
    monkeypatch.setattr(background_jobs, "heartbeat_job", lambda *_args, **_kwargs: None)
    task = asyncio.create_task(
        run_claimed_job(
            session_factory=session_factory,
            registry=JobHandlerRegistry(
                {JOB_TYPE_RENDER_RUN: RenderRunJobHandler(session_factory)}
            ),
            claimed_job=claimed,
            lease_seconds=30,
        )
    )
    assert await asyncio.to_thread(capture_started.wait, 5)
    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        assert job is not None
        background_jobs.request_cancellation(db, job)
    await task

    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        run = db.get(RenderRun, run_id)
        observation = db.scalar(
            select(RenderedObservation).where(RenderedObservation.render_run_id == run_id)
        )
        assert job is not None and job.status == "interrupted"
        assert run is not None and run.status == "interrupted"
        assert observation is not None and observation.capture_state == "interrupted"
        assert _event_count(db, job_id, "cancelled") == 0
    assert _payload_files(artifact_root) == 0


class _FakeBrowserRenderer:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeBrowserRenderer":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _RenderRenderer(_FakeBrowserRenderer):
    browser_version = "fixture-chromium"
    playwright_version = "fixture-playwright"


def _install_render_executor(monkeypatch: pytest.MonkeyPatch, renderer_factory: type) -> None:
    execute = render_runs.execute_render_run

    async def execute_with_renderer(*args, **kwargs):
        return await execute(*args, **kwargs, renderer_factory=renderer_factory)

    monkeypatch.setattr(job_handlers, "execute_render_run", execute_with_renderer)


def _create_render_job(session_factory, host: str, count: int, *, worker_id: str):
    with session_factory() as db:
        site_id, resource_ids = _site_pages(db, host, count)
        run = RenderRun(
            website_property_id=site_id,
            status="queued",
            trigger="site_workspace",
            configuration_json=ScopeConfig(
                allowed_host_patterns=[host],
                max_pages=count,
                render_mode="all_eligible",
                render_max_pages=count,
            ).to_dict(),
            target_count=count,
        )
        db.add(run)
        db.flush()
        resources = list(
            db.scalars(
                select(WebResource).where(WebResource.id.in_(resource_ids)).order_by(WebResource.id)
            )
        )
        db.add_all(
            RenderRunTarget(
                render_run_id=run.id,
                web_resource_id=resource.id,
                requested_url=resource.normalized_url,
                position=position,
            )
            for position, resource in enumerate(resources, 1)
        )
        job = background_jobs.enqueue_render_run_job(db, run)
        db.commit()
        claimed = background_jobs.claim_next_job(db, worker_id=worker_id, lease_seconds=30)
        assert claimed is not None
        return run.id, job.id, claimed


def _rich_capture(url: str, artifact_content: bytes) -> CaptureResult:
    return CaptureResult(
        state="completed",
        final_url=url,
        status=200,
        title="Rendered fixture",
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
                "request_headers_json": {},
                "response_headers_json": {},
                "blocked_by_policy": False,
            }
        ],
        console=[
            {
                "sequence": 1,
                "message_type": "warning",
                "text": "fixture console evidence",
            }
        ],
        page_errors=[
            {
                "sequence": 1,
                "error_name": "FixtureError",
                "message": "fixture Page error evidence",
            }
        ],
        artifacts=[
            CapturedArtifact(
                artifact_type="viewport_screenshot",
                content=artifact_content,
                media_type="image/png",
                width=10,
                height=10,
            )
        ],
    )


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'collector-fencing.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _site_pages(db, host: str, count: int) -> tuple[int, list[int]]:
    site = create_site(
        db,
        WebsitePropertyCreate(
            name=host,
            base_url=f"https://{host}/",
            scope_config=ScopeConfigPayload(),
        ),
    )
    resources = [
        WebResource(
            resource_type="page",
            normalized_url=f"https://{host}/page-{index}",
            scheme="https",
            host=host,
            path=f"/page-{index}",
            query="",
        )
        for index in range(count)
    ]
    db.add_all(resources)
    db.flush()
    db.add_all(
        SitePage(website_property_id=site.id, resource_id=resource.id) for resource in resources
    )
    db.flush()
    return site.id, [resource.id for resource in resources]


def _force_recovery(session_factory, job_id: int) -> int:
    with session_factory() as db:
        job = db.get(BackgroundJob, job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with session_factory() as db:
        return background_jobs.recover_expired_jobs(db)


def _event_count(db, job_id: int, event_type: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.event_type == event_type)
        )
        or 0
    )


def _payload_files(root) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def _performance_settings(payload_root):
    return SimpleNamespace(
        google_api_key="test-key",
        performance_payload_storage_root=payload_root,
        performance_provider_timeout_seconds=1.0,
        performance_provider_max_response_bytes=1_000_000,
        performance_provider_max_attempts=1,
        performance_hard_page_limit=25,
        performance_default_page_limit=10,
        performance_max_provider_requests=100,
        performance_crux_queries_per_minute=120,
    )


def _accessibility_settings(payload_root):
    return SimpleNamespace(
        accessibility_payload_storage_root=payload_root,
        accessibility_hard_page_limit=25,
        accessibility_default_page_limit=10,
        accessibility_max_audit_count=50,
        accessibility_max_payload_bytes=12 * 1024 * 1024,
    )


def _axe_payload(url: str) -> dict:
    return {
        "testEngine": {"name": "axe-core", "version": AXE_CORE_VERSION},
        "testRunner": {"name": "axe"},
        "testEnvironment": {"userAgent": "fixture"},
        "timestamp": "2026-08-28T00:00:00.000Z",
        "url": url,
        "toolOptions": {},
        "violations": [
            {
                "id": "image-alt",
                "impact": "critical",
                "tags": ["wcag2a", "wcag111"],
                "description": "Ensure images have alternate text",
                "help": "Images must have alternate text",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/image-alt",
                "nodes": [
                    {
                        "impact": "critical",
                        "target": ["img"],
                        "html": '<img src="pixel.gif">',
                        "failureSummary": "Fix the missing alt attribute.",
                    }
                ],
            }
        ],
        "incomplete": [],
        "passes": [],
        "inapplicable": [],
    }
