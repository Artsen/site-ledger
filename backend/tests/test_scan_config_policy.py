from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route

from app.api.routes import router
from app.browser.config import STRING_LIMITS as BROWSER_STRING_LIMITS
from app.config import Settings
from app.crawler.config import (
    COLLECTION_LIMITS,
    CRAWL_LIMITS,
    STARTING_URL_MAX_LENGTH,
    STRING_LIMITS,
    CollectionLimit,
    ScopeConfigValidationError,
)
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticPageCrawler
from app.database import get_db
from app.models import (
    BackgroundJob,
    RenderedObservation,
    ResourceSnapshot,
    Scan,
    StaticFetchAttempt,
    WebsiteProperty,
)
from app.schemas.scans import ScanCreate, ScopeConfigPayload
from app.schemas.sites import WebsitePropertyUpdate
from app.services.background_jobs import claim_next_job, enqueue_scan_job
from app.services.job_handlers import build_handler_registry, run_claimed_job
from app.services.site_management import update_site
from app.storage.content_store import LocalContentStore

NUMERIC_BOUNDARIES = [(name, limit.minimum, limit.maximum) for name, limit in CRAWL_LIMITS.items()]


def test_direct_scan_api_rejects_unsafe_unbounded_resource_value(
    db_session: Session,
) -> None:
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.post(
            "/api/scans",
            json={
                "starting_url": "https://example.com/",
                "scope_config": {"max_pages": 50_001},
            },
        )
        long_url_response = client.post(
            "/api/scans",
            json={
                "starting_url": "x" * (STARTING_URL_MAX_LENGTH + 1),
                "scope_config": {},
            },
        )

    assert response.status_code == 422
    assert long_url_response.status_code == 422
    assert db_session.scalar(select(func.count(Scan.id))) == 0


def test_all_direct_scan_and_site_api_paths_reject_unsafe_scope_config(
    db_session: Session,
) -> None:
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = _api_app(factory)
    with TestClient(app) as client:
        site_create = client.post(
            "/api/sites",
            json={
                "name": "Rejected Site",
                "base_url": "https://rejected.example/",
                "scope_config": {"max_depth": 101},
            },
        )
        valid_site = client.post(
            "/api/sites",
            json={
                "name": "Valid Site",
                "base_url": "https://valid.example/",
                "scope_config": {},
            },
        )
        assert valid_site.status_code == 201
        site_id = valid_site.json()["id"]
        site_update = client.patch(
            f"/api/sites/{site_id}",
            json={"scope_config": {"max_html_response_bytes": 20_000_001}},
        )
        site_scan = client.post(
            f"/api/sites/{site_id}/scans",
            json={"scope_config": {"max_redirects": 21}},
        )

    assert site_create.status_code == 422
    assert site_update.status_code == 422
    assert site_scan.status_code == 422
    db_session.expire_all()
    assert db_session.scalar(select(func.count(WebsiteProperty.id))) == 1
    assert db_session.scalar(select(func.count(Scan.id))) == 0
    site = db_session.get(WebsiteProperty, site_id)
    assert site is not None
    assert site.scope_config["max_html_response_bytes"] == 2_000_000


@pytest.mark.parametrize(("name", "minimum", "maximum"), NUMERIC_BOUNDARIES)
def test_numeric_policy_accepts_exact_boundaries(
    name: str, minimum: int | float, maximum: int | float
) -> None:
    ScopeConfigPayload(**_numeric_value(name, minimum))
    ScopeConfigPayload(**_numeric_value(name, maximum))
    ScopeConfig.from_dict(_numeric_value(name, minimum))
    ScopeConfig.from_dict(_numeric_value(name, maximum))


@pytest.mark.parametrize(("name", "minimum", "maximum"), NUMERIC_BOUNDARIES)
def test_numeric_policy_rejects_values_outside_boundaries(
    name: str, minimum: int | float, maximum: int | float
) -> None:
    delta = 0.01 if isinstance(minimum, float) else 1
    for value in (minimum - delta, maximum + delta):
        with pytest.raises(ValidationError):
            ScopeConfigPayload(**_numeric_value(name, value))
        with pytest.raises(ValueError):
            ScopeConfig.from_dict(_numeric_value(name, value))


@pytest.mark.parametrize(("name", "limit"), COLLECTION_LIMITS.items())
def test_collection_policy_enforces_count_and_item_boundaries(
    name: str, limit: CollectionLimit
) -> None:
    ScopeConfigPayload(**{name: ["x"] * limit.max_items})
    ScopeConfigPayload(**{name: ["x" * limit.max_item_length]})
    ScopeConfig.from_dict({name: ["x"] * limit.max_items})
    ScopeConfig.from_dict({name: ["x" * limit.max_item_length]})
    with pytest.raises(ValidationError):
        ScopeConfigPayload(**{name: ["x"] * (limit.max_items + 1)})
    with pytest.raises(ValidationError):
        ScopeConfigPayload(**{name: ["x" * (limit.max_item_length + 1)]})
    with pytest.raises(ValueError):
        ScopeConfig.from_dict({name: ["x"] * (limit.max_items + 1)})
    with pytest.raises(ValueError):
        ScopeConfig.from_dict({name: ["x" * (limit.max_item_length + 1)]})


def test_string_policy_enforces_user_agent_starting_url_and_render_string_bounds() -> None:
    ScopeConfigPayload(user_agent="x" * STRING_LIMITS["user_agent"])
    ScopeConfigPayload(render_locale="x" * BROWSER_STRING_LIMITS["render_locale"])
    ScopeConfigPayload(render_timezone="x" * BROWSER_STRING_LIMITS["render_timezone"])
    ScanCreate(starting_url="x" * STARTING_URL_MAX_LENGTH, scope_config=ScopeConfigPayload())
    with pytest.raises(ValidationError):
        ScopeConfigPayload(user_agent="x" * (STRING_LIMITS["user_agent"] + 1))
    with pytest.raises(ValidationError):
        ScopeConfigPayload(render_locale="x" * (BROWSER_STRING_LIMITS["render_locale"] + 1))
    with pytest.raises(ValidationError):
        ScopeConfigPayload(render_timezone="x" * (BROWSER_STRING_LIMITS["render_timezone"] + 1))
    with pytest.raises(ValidationError):
        ScanCreate(
            starting_url="x" * (STARTING_URL_MAX_LENGTH + 1),
            scope_config=ScopeConfigPayload(),
        )


@pytest.mark.parametrize(
    "scope_config",
    [
        {"max_pages": "100"},
        {"max_pages": True},
        {"request_timeout_seconds": float("nan")},
        {"request_timeout_seconds": float("inf")},
        {"allowed_host_patterns": "example.com"},
        {"allowed_host_patterns": [1, 2, 3]},
    ],
)
def test_runtime_policy_rejects_malformed_types(scope_config: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ScopeConfig.from_dict(scope_config)


@pytest.mark.parametrize(
    "scope_config",
    [
        {"max_pages": 999_999_999},
        {"max_pages": True},
        {"allowed_host_patterns": "example.com"},
    ],
)
def test_persisted_scope_config_is_revalidated_without_pydantic(
    scope_config: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ScopeConfig.from_dict(scope_config)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_scope",
    [
        {"max_pages": 999_999_999},
        {"allowed_host_patterns": "example.com"},
        {"render_locale": "x" * (BROWSER_STRING_LIMITS["render_locale"] + 1)},
    ],
)
async def test_unsafe_persisted_scan_fails_normally_before_execution(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_scope: dict[str, object],
) -> None:
    scan = Scan(
        starting_url="https://example.com/",
        status="queued",
        scope_config=unsafe_scope,
    )
    db_session.add(scan)
    db_session.flush()
    job = enqueue_scan_job(db_session, scan)
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    starts: list[str] = []

    def forbidden_crawler(*_args, **_kwargs):
        starts.append("network")
        raise AssertionError("Static crawler must not start")

    def forbidden_browser(*_args, **_kwargs):
        starts.append("browser")
        raise AssertionError("Browser must not start")

    monkeypatch.setattr("app.services.scan_execution.StaticPageCrawler", forbidden_crawler)
    monkeypatch.setattr("app.services.render_runs.BrowserRenderer", forbidden_browser)
    monkeypatch.setattr(
        "app.services.job_handlers.get_settings",
        lambda: Settings(rendered_artifact_storage_root=tmp_path / "rendered"),
    )
    with factory() as db:
        claimed = claim_next_job(db, worker_id="scope-policy-worker", lease_seconds=30)
    assert claimed is not None

    await run_claimed_job(
        session_factory=factory,
        registry=build_handler_registry(factory, LocalContentStore(tmp_path / "html")),
        claimed_job=claimed,
        lease_seconds=30,
    )

    db_session.expire_all()
    saved_scan = db_session.get(Scan, scan.id)
    saved_job = db_session.get(BackgroundJob, job.id)
    assert saved_scan is not None and saved_job is not None
    assert saved_scan.status == "failed"
    assert saved_scan.stop_reason == "invalid_scope_config"
    assert saved_scan.fatal_error_message.startswith("Invalid Scan configuration:")
    assert saved_scan.finished_at is not None
    assert saved_scan.started_at is None
    assert saved_job.status == "failed"
    assert saved_job.error_type == "invalid_scope_config"
    assert starts == []
    assert db_session.scalar(select(func.count(ResourceSnapshot.id))) == 0
    assert db_session.scalar(select(func.count(StaticFetchAttempt.id))) == 0
    assert db_session.scalar(select(func.count(RenderedObservation.id))) == 0


def test_historical_unsafe_scan_remains_readable_and_site_patch_does_not_revalidate(
    db_session: Session,
) -> None:
    unsafe = {"max_pages": 999_999_999}
    site = WebsiteProperty(
        name="Historical Site",
        base_url="https://historical.example/",
        normalized_base_url="https://historical.example/",
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        display_timezone=None,
        scope_config=unsafe,
        is_active=True,
    )
    scan = Scan(
        website_property=site,
        starting_url=site.base_url,
        status="completed",
        scope_config=unsafe,
    )
    db_session.add_all([site, scan])
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)

    with TestClient(_api_app(factory)) as client:
        response = client.get(f"/api/scans/{scan.id}")
    updated = update_site(
        db_session,
        site.id,
        WebsitePropertyUpdate(description="Still readable"),
    )

    assert response.status_code == 200
    assert response.json()["scope_config"] == unsafe
    assert updated is not None
    assert updated.description == "Still readable"
    assert updated.scope_config == unsafe


def test_new_scope_config_rejects_unimplemented_robots_enforcement() -> None:
    values = ScopeConfig().to_dict()
    values["respect_robots_txt"] = True

    with pytest.raises(
        ScopeConfigValidationError,
        match="robots.txt enforcement is not implemented",
    ):
        ScopeConfig.from_dict(values)
    with pytest.raises(ValidationError, match="robots.txt enforcement is not implemented"):
        ScopeConfigPayload(**values)


def test_historical_robots_enabled_scan_remains_api_readable(db_session: Session) -> None:
    historical = ScopeConfig().to_dict()
    historical["respect_robots_txt"] = True
    scan = Scan(
        starting_url="https://historical.example/",
        status="completed",
        scope_config=historical,
    )
    db_session.add(scan)
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)

    with TestClient(_api_app(factory)) as client:
        response = client.get(f"/api/scans/{scan.id}")

    assert response.status_code == 200
    assert response.json()["scope_config"]["respect_robots_txt"] is True


@pytest.mark.asyncio
async def test_valid_api_config_persists_and_executes_unchanged(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    requested = {
        "allowed_host_patterns": ["fixture.test"],
        "max_pages": 1,
        "max_depth": 0,
        "request_timeout_seconds": 7.5,
        "static_retry_initial_delay_ms": 0,
        "static_retry_max_delay_ms": 0,
        "concurrent_requests_per_host": 1,
        "allow_private_networks": True,
    }
    with TestClient(_api_app(factory)) as client:
        response = client.post(
            "/api/scans",
            json={"starting_url": "http://fixture.test/", "scope_config": requested},
        )
    assert response.status_code == 202
    scan_id = response.json()["id"]

    fixture_app = Starlette(
        routes=[Route("/", lambda _request: HTMLResponse("<html><body>Ready</body></html>"))]
    )

    class FixtureCrawler(StaticPageCrawler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, transport=httpx.ASGITransport(app=fixture_app), **kwargs)

    monkeypatch.setattr("app.services.scan_execution.StaticPageCrawler", FixtureCrawler)
    monkeypatch.setattr(
        "app.services.job_handlers.get_settings",
        lambda: Settings(rendered_artifact_storage_root=tmp_path / "rendered"),
    )
    with factory() as db:
        claimed = claim_next_job(db, worker_id="valid-scope-worker", lease_seconds=30)
    assert claimed is not None
    await run_claimed_job(
        session_factory=factory,
        registry=build_handler_registry(factory, LocalContentStore(tmp_path / "html")),
        claimed_job=claimed,
        lease_seconds=30,
    )

    db_session.expire_all()
    saved_scan = db_session.get(Scan, scan_id)
    assert saved_scan is not None
    assert saved_scan.status == "completed"
    assert {key: saved_scan.scope_config[key] for key in requested} == requested
    hydrated = ScopeConfig.from_dict(saved_scan.scope_config)
    assert {key: hydrated.to_dict()[key] for key in requested} == requested
    assert db_session.scalar(select(func.count(ResourceSnapshot.id))) == 1
    assert db_session.scalar(select(func.count(StaticFetchAttempt.id))) == 1


def _api_app(factory) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return app


def _numeric_value(name: str, value: int | float) -> dict[str, int | float]:
    values: dict[str, int | float] = {name: value}
    if name == "static_retry_initial_delay_ms":
        values["static_retry_max_delay_ms"] = value if value > 5_000 else 5_000
    elif name == "static_retry_max_delay_ms":
        values["static_retry_initial_delay_ms"] = value if value < 500 else 500
    return values
