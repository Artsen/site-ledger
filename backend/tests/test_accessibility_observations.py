import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.accessibility.audit import AccessibilityAuditResult, audit_page
from app.accessibility.engine import (
    ACCESSIBILITY_INTEGRATION_VERSION,
    ACCESSIBILITY_NORMALIZATION_VERSION,
    AXE_BUNDLE_SHA256,
    AXE_CORE_VERSION,
    MAX_HTML_SNIPPET,
    RULESET_PROFILE,
    RULESET_SHA256,
    normalize_axe_result,
    ruleset_metadata,
    verify_detector_assets,
)
from app.browser.capture import BrowserRenderer
from app.crawler.scope import ScopeConfig
from app.database import get_db
from app.models import (
    AccessibilityObservation,
    AccessibilityPayloadBlob,
    AccessibilityRuleEvidence,
    SitePage,
    WebResource,
)
from app.schemas.accessibility import AccessibilityRunCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.accessibility_collection import (
    create_accessibility_run,
    execute_accessibility_run,
)
from app.services.accessibility_queries import (
    accessibility_pages,
    accessibility_rules,
    accessibility_summary,
    page_latest_accessibility,
)
from app.services.background_jobs import (
    claim_next_job,
    enqueue_accessibility_run_job,
    recover_expired_jobs,
)
from app.services.job_handlers import build_handler_registry, run_claimed_job
from app.services.site_management import create_site
from app.storage.accessibility_store import LocalAccessibilityPayloadStore
from app.storage.content_store import LocalContentStore


def test_pinned_detector_and_effective_ruleset_identity() -> None:
    verify_detector_assets()
    metadata = ruleset_metadata()

    assert AXE_CORE_VERSION == "4.12.1"
    assert AXE_BUNDLE_SHA256 == "66a8aaa95a8b044a7fd74a5435873bf04ff65a1ca75567c921b7509742085a14"
    assert RULESET_PROFILE == "wcag22-aa-v1"
    assert RULESET_SHA256 == "9e529b185ca8f212dc39924c0f2e6208115e44c1baf0052128a00080212705a5"
    assert len(metadata["rules"]) == 62
    assert metadata["run_only_tags"] == [
        "wcag2a",
        "wcag2aa",
        "wcag21a",
        "wcag21aa",
        "wcag22a",
        "wcag22aa",
    ]


def test_normalization_preserves_incomplete_null_impact_and_structured_targets() -> None:
    result = _axe_payload()
    long_html = "<div>" + "x" * (MAX_HTML_SNIPPET + 20) + "</div>"
    result["incomplete"][0]["impact"] = None
    result["incomplete"][0]["nodes"][0].update(
        {"impact": None, "target": [["iframe"], ["#shadow", ".field"]], "html": long_html}
    )

    first = normalize_axe_result(result)
    second = normalize_axe_result(json.loads(json.dumps(result)))
    incomplete = next(rule for rule in first.rules if rule.result_type == "incomplete")

    assert first.sha256 == second.sha256
    assert incomplete.impact is None
    assert incomplete.nodes[0].target == [["iframe"], ["#shadow", ".field"]]
    assert incomplete.nodes[0].html_truncated is True
    assert len(incomplete.nodes[0].html) == MAX_HTML_SNIPPET
    assert incomplete.nodes[0].html_original_length == len(long_html)
    assert first.violation_rule_count == 1
    assert first.incomplete_rule_count == 1
    assert first.pass_rule_count == 1
    assert first.inapplicable_rule_count == 1


def test_payload_store_deduplicates_and_round_trips_exact_bytes(
    db_session: Session, tmp_path: Path
) -> None:
    store = LocalAccessibilityPayloadStore(tmp_path / "accessibility")
    content = b'{"html":"<script>alert(1)</script>","exact":true}'
    first = store.put(db_session, content)
    second = store.put(db_session, content)
    db_session.commit()

    assert first.id == second.id
    assert store.read(first) == content
    assert first.sha256 == "dd269e86a15ee13588a05f39770835771d73f4312e94acc217e2ae2b6a3f8c50"


@pytest.mark.asyncio
async def test_run_lifecycle_is_idempotent_and_queries_latest_population(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.accessibility_collection.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.accessibility_collection.BrowserRenderer", _FakeBrowserRenderer
    )
    monkeypatch.setattr("app.services.accessibility_collection.audit_page", _fake_audit_page)
    run = create_accessibility_run(
        db_session,
        site.id,
        AccessibilityRunCreate(resource_ids=[resource.id]),
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    progress: list[tuple[int, int]] = []

    result = await execute_accessibility_run(
        factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda current, total, _counters: progress.append((current, total)),
    )
    result.status = "running"
    with factory() as db:
        db.merge(result)
        db.commit()
    reclaimed = await execute_accessibility_run(
        factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda _current, _total, _counters: None,
    )

    assert result.observation_count == 2
    assert reclaimed.status == "completed"
    assert progress[-1] == (2, 2)
    assert db_session.scalar(select(func.count()).select_from(AccessibilityObservation)) == 2
    assert db_session.scalar(select(func.count()).select_from(AccessibilityPayloadBlob)) == 1
    assert db_session.scalar(select(func.count()).select_from(AccessibilityRuleEvidence)) == 4
    summary = accessibility_summary(db_session, site.id)
    pages = accessibility_pages(
        db_session,
        site.id,
        search=None,
        outcome=None,
        impact=None,
        has_violations=None,
        needs_review=None,
        sort="audited",
        direction="desc",
        limit=10,
        offset=0,
    )
    rules = accessibility_rules(
        db_session,
        site.id,
        result_type="violation",
        impact=None,
        profile=None,
        limit=10,
        offset=0,
    )
    latest = page_latest_accessibility(db_session, site.id, resource.id)
    assert summary.pages_audited == 1
    assert summary.violation_rules == 2
    assert summary.needs_review_rules == 2
    assert pages.items[0].desktop_violations == 1
    assert pages.items[0].mobile_violations == 1
    assert rules.items[0].pages_affected == 1
    assert rules.items[0].affected_nodes == 2
    assert rules.items[0].tags == ["wcag111", "wcag2a"]
    assert latest.total == 2
    assert {item.profile for item in latest.items} == {"desktop", "mobile"}


def test_run_validates_ownership_caps_profiles_and_logical_uniqueness(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, resource = _site_page(db_session)
    monkeypatch.setattr(
        "app.services.accessibility_collection.get_settings", lambda: _settings(tmp_path)
    )
    with pytest.raises(ValueError, match="do not belong"):
        create_accessibility_run(db_session, site.id, AccessibilityRunCreate(resource_ids=[999]))
    with pytest.raises(ValueError, match="at most 10 Pages"):
        create_accessibility_run(
            db_session, site.id, AccessibilityRunCreate(resource_ids=list(range(1, 12)))
        )
    with pytest.raises(ValueError, match="duplicates"):
        AccessibilityRunCreate(resource_ids=[resource.id, resource.id])
    with pytest.raises(ValueError, match="duplicates"):
        AccessibilityRunCreate(resource_ids=[resource.id], profiles=["desktop", "desktop"])
    run = create_accessibility_run(
        db_session,
        site.id,
        AccessibilityRunCreate(resource_ids=[resource.id], profiles=["desktop"]),
    )
    db_session.flush()
    first = _observation(run.id, site.id, resource.id)
    db_session.add(first)
    db_session.flush()
    db_session.add(_observation(run.id, site.id, resource.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.asyncio
async def test_cancellation_and_expired_job_settle_accessibility_run(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, resource = _site_page(db_session)
    monkeypatch.setattr(
        "app.services.accessibility_collection.get_settings", lambda: _settings(tmp_path)
    )
    monkeypatch.setattr(
        "app.services.accessibility_collection.BrowserRenderer", _FakeBrowserRenderer
    )
    run = create_accessibility_run(
        db_session, site.id, AccessibilityRunCreate(resource_ids=[resource.id])
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    cancelled = await execute_accessibility_run(
        factory,
        run.id,
        should_cancel=lambda: True,
        progress=lambda _current, _total, _counters: None,
    )
    assert cancelled.status == "cancelled"

    second = create_accessibility_run(
        db_session, site.id, AccessibilityRunCreate(resource_ids=[resource.id])
    )
    job = enqueue_accessibility_run_job(db_session, second.id, site.id)
    db_session.commit()
    claimed = claim_next_job(db_session, worker_id="accessibility-worker", lease_seconds=1)
    assert claimed is not None and claimed.job.id == job.id
    second.status = "running"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert recover_expired_jobs(db_session) == 1
    db_session.refresh(second)
    assert second.status == "interrupted"


class _AccessibilityHandler(BaseHTTPRequestHandler):
    request_count = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).request_count += 1
        pixel = "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
        if self.path == "/violation":
            image = f'<img src="data:image/gif;base64,{pixel}">'
        elif self.path == "/clean":
            image = f'<img alt="A pixel" src="data:image/gif;base64,{pixel}">'
        else:
            self.send_error(404)
            return
        body = (
            '<!doctype html><html lang="en"><head><title>Fixture</title></head>'
            f"<body><main><h1>Fixture</h1>{image}</main></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def accessibility_server():
    _AccessibilityHandler.request_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AccessibilityHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_real_chromium_injects_local_axe_and_detects_known_violation(
    accessibility_server: str,
) -> None:
    config = _browser_config(allow_private=True)
    async with BrowserRenderer(config, accessibility_server) as renderer:
        violation = await audit_page(
            renderer,
            f"{accessibility_server}/violation",
            "desktop",
            max_payload_bytes=12 * 1024 * 1024,
        )
        clean = await audit_page(
            renderer,
            f"{accessibility_server}/clean",
            "mobile",
            max_payload_bytes=12 * 1024 * 1024,
        )

    assert violation.outcome == "ready"
    assert clean.outcome == "ready"
    violation_payload = json.loads(violation.payload or b"{}")
    clean_payload = json.loads(clean.payload or b"{}")
    assert violation_payload["testEngine"]["version"] == AXE_CORE_VERSION
    assert violation_payload["siteLedgerRuleset"]["profile"] == RULESET_PROFILE
    assert "image-alt" in {item["id"] for item in violation_payload["violations"]}
    assert "image-alt" not in {item["id"] for item in clean_payload["violations"]}
    assert violation.browser_version


@pytest.mark.asyncio
async def test_accessibility_reuses_private_network_policy(accessibility_server: str) -> None:
    config = _browser_config(allow_private=False)
    async with BrowserRenderer(config, accessibility_server) as renderer:
        result = await audit_page(
            renderer,
            f"{accessibility_server}/clean",
            "desktop",
            max_payload_bytes=12 * 1024 * 1024,
        )

    assert result.outcome == "failed"
    assert _AccessibilityHandler.request_count == 0


@pytest.mark.asyncio
async def test_full_system_api_job_chromium_and_evidence_persistence(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accessibility_server: str,
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.accessibility_collection.get_settings", lambda: settings)
    site = create_site(
        db_session,
        WebsitePropertyCreate(
            name="Accessibility System Fixture",
            base_url=f"{accessibility_server}/",
            scope_config=ScopeConfigPayload(allow_private_networks=True),
        ),
    )
    resource = WebResource(
        resource_type="page",
        normalized_url=f"{accessibility_server}/violation",
        scheme="http",
        host="127.0.0.1",
        port=int(accessibility_server.rsplit(":", 1)[1]),
        path="/violation",
        query="",
    )
    db_session.add(resource)
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    db_session.commit()

    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = FastAPI()
    from app.api.accessibility_routes import router as accessibility_router

    app.include_router(accessibility_router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.post(
            f"/api/sites/{site.id}/accessibility-runs",
            json={"resource_ids": [resource.id], "profiles": ["desktop"]},
        )
    assert response.status_code == 202
    run_id = response.json()["id"]

    with factory() as db:
        claimed = claim_next_job(db, worker_id="system-accessibility-worker", lease_seconds=30)
    assert claimed is not None
    registry = build_handler_registry(factory, LocalContentStore(tmp_path / "html"))
    await run_claimed_job(
        session_factory=factory,
        registry=registry,
        claimed_job=claimed,
        lease_seconds=30,
    )

    with TestClient(app) as client:
        response = client.get(f"/api/sites/{site.id}/accessibility-runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["ready_count"] == 1
    assert body["observations"]["items"][0]["payload_sha256"]
    with factory() as db:
        observation = db.scalar(
            select(AccessibilityObservation).where(
                AccessibilityObservation.accessibility_run_id == run_id
            )
        )
        assert observation is not None
        rules = list(
            db.scalars(
                select(AccessibilityRuleEvidence).where(
                    AccessibilityRuleEvidence.accessibility_observation_id == observation.id
                )
            )
        )
        assert "image-alt" in {rule.rule_id for rule in rules}
        assert observation.axe_core_version == AXE_CORE_VERSION
        assert observation.detector_bundle_sha256 == AXE_BUNDLE_SHA256


class _FakeBrowserRenderer:
    def __init__(self, config: ScopeConfig, starting_url: str):
        self.config = config
        self.starting_url = starting_url

    async def __aenter__(self) -> "_FakeBrowserRenderer":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


async def _fake_audit_page(
    _renderer: object, url: str, _profile: str, *, max_payload_bytes: int
) -> AccessibilityAuditResult:
    payload = json.dumps(_axe_payload(), sort_keys=True, separators=(",", ":")).encode()
    assert len(payload) < max_payload_bytes
    return AccessibilityAuditResult(
        outcome="ready",
        final_url=url,
        payload=payload,
        browser_version="test-chromium",
        playwright_version="test-playwright",
    )


def _site_page(db: Session):
    site = create_site(
        db,
        WebsitePropertyCreate(
            name="Accessibility Site",
            base_url="https://example.com/",
            scope_config=ScopeConfigPayload(),
        ),
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/page",
        scheme="https",
        host="example.com",
        path="/page",
        query="",
    )
    db.add(resource)
    db.flush()
    db.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    db.commit()
    return site, resource


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        accessibility_payload_storage_root=tmp_path / "accessibility",
        accessibility_hard_page_limit=25,
        accessibility_default_page_limit=10,
        accessibility_max_payload_bytes=12 * 1024 * 1024,
    )


def _browser_config(*, allow_private: bool) -> ScopeConfig:
    return ScopeConfig(
        allowed_host_patterns=["127.0.0.1"],
        allow_private_networks=allow_private,
        render_mode="starting_page",
        render_load_timeout_seconds=0,
        render_capture_full_page=False,
        render_max_page_duration_seconds=20,
    )


def _axe_payload() -> dict:
    return {
        "testEngine": {"name": "axe-core", "version": AXE_CORE_VERSION},
        "testRunner": {"name": "axe"},
        "testEnvironment": {"userAgent": "fixture"},
        "timestamp": "2026-08-13T00:00:00.000Z",
        "url": "https://example.com/page",
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
        "incomplete": [
            {
                "id": "color-contrast",
                "impact": "serious",
                "tags": ["wcag2aa", "wcag143"],
                "description": "Ensure contrast can be determined",
                "help": "Elements must meet minimum color contrast ratio thresholds",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/color-contrast",
                "nodes": [
                    {
                        "impact": "serious",
                        "target": ["p"],
                        "html": "<p>Text</p>",
                        "failureSummary": "Review contrast.",
                    }
                ],
            }
        ],
        "passes": [{"id": "document-title", "nodes": []}],
        "inapplicable": [{"id": "audio-caption", "nodes": []}],
    }


def _observation(run_id: int, site_id: int, resource_id: int) -> AccessibilityObservation:
    return AccessibilityObservation(
        accessibility_run_id=run_id,
        website_property_id=site_id,
        web_resource_id=resource_id,
        requested_url="https://example.com/page",
        profile="desktop",
        outcome="failed",
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_sha256=RULESET_SHA256,
        profile_json={},
    )
