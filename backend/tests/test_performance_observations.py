import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    PerformanceObservation,
    PerformancePayloadBlob,
    SitePage,
    WebResource,
)
from app.schemas.performance import PerformanceRunCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.background_jobs import (
    claim_next_job,
    enqueue_performance_run_job,
    recover_expired_jobs,
)
from app.services.performance_collection import create_performance_run, execute_performance_run
from app.services.performance_providers import (
    PERFORMANCE_NORMALIZATION_VERSION,
    PerformanceProviderClient,
    ProviderResult,
    normalize_crux,
    normalize_pagespeed,
)
from app.services.performance_queries import (
    latest_site_performance,
    page_latest_performance,
    page_performance_history,
)
from app.services.site_management import create_site
from app.storage.performance_store import LocalPerformancePayloadStore


def test_pagespeed_normalization_uses_stable_metric_keys() -> None:
    metrics, metadata = normalize_pagespeed(_pagespeed_document())

    assert metrics["performance_score"] == {"value": 0.91, "unit": "ratio"}
    assert metrics["lcp"] == {"value": 2450, "unit": "ms"}
    assert metrics["cls"] == {"value": 0.08, "unit": "score"}
    assert metrics["server_response_time"]["value"] == 310
    assert metadata["provider_target"] == "https://example.com/final"
    assert metadata["product_version"] == "12.4.0"


def test_crux_normalization_preserves_p75_histogram_and_provider_key() -> None:
    metrics, metadata = normalize_crux(_crux_document())

    assert metrics["lcp"]["value"] == 2200
    assert metrics["lcp"]["histogram"][0]["density"] == 0.8
    assert metrics["inp"]["value"] == 180
    assert metadata["provider_target"] == "https://example.com/page"
    assert metadata["period"]["lastDate"]["day"] == 28


def test_provider_retries_429_and_uses_fixed_pagespeed_contract() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429, json={"error": {"message": "quota"}}, headers={"Retry-After": "0"}
            )
        return httpx.Response(200, json=_pagespeed_document())

    client = PerformanceProviderClient(
        "secret-key", transport=httpx.MockTransport(respond), sleep=lambda _delay: None
    )
    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "ready"
    assert len(requests) == 2
    assert requests[0].url.host == "www.googleapis.com"
    assert requests[0].url.path == "/pagespeedonline/v5/runPagespeed"
    assert requests[0].url.params["category"] == "performance"
    assert requests[0].url.params["strategy"] == "mobile"


def test_crux_404_is_unavailable_and_payload_is_retained() -> None:
    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        ),
        sleep=lambda _delay: None,
    )
    result = client.crux("https://example.com/page", "url", "PHONE")
    client.close()

    assert result.outcome == "unavailable"
    assert result.error_type == "no_field_data"
    assert result.payload is not None and b"NOT_FOUND" in result.payload


def test_provider_bounds_response_and_sanitizes_auth_failure() -> None:
    oversized = PerformanceProviderClient(
        "secret-key",
        max_response_bytes=8,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 9)),
    )
    too_large = oversized.pagespeed("https://example.com/", "mobile")
    oversized.close()
    auth = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(403, json={"error": {"message": "bad key"}})
        ),
    )
    denied = auth.crux("https://example.com/", "url", "PHONE")
    auth.close()

    assert too_large.error_type == "response_too_large"
    assert too_large.payload is None
    assert denied.error_type == "provider_auth_error"
    assert "secret-key" not in (denied.error_message or "")
    assert denied.payload is not None


def test_payload_store_deduplicates_exact_gzip_bytes(db_session: Session, tmp_path: Path) -> None:
    store = LocalPerformancePayloadStore(tmp_path / "performance")
    first = store.put(db_session, b'{"exact":true}')
    second = store.put(db_session, b'{"exact":true}')
    db_session.commit()

    assert first.id == second.id
    assert store.read(first) == b'{"exact":true}'
    assert first.stored_byte_size < first.raw_byte_size + 30


def test_run_is_bounded_idempotent_and_preserves_unavailable(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    run = create_performance_run(
        db_session,
        site.id,
        PerformanceRunCreate(resource_ids=[resource.id]),
    )
    db_session.commit()
    session_factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    fake = FakeProviderClient()

    result = execute_performance_run(
        session_factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda _current, _total, _counters: None,
        client_factory=lambda: fake,
    )
    again = execute_performance_run(
        session_factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda _current, _total, _counters: None,
        client_factory=lambda: FakeProviderClient(),
    )

    assert run.request_count == 6
    assert result.status == "completed"
    assert result.ready_count == 4
    assert result.unavailable_count == 2
    assert result.failed_count == 0
    assert again.id == result.id
    assert db_session.scalar(select(func.count()).select_from(PerformanceObservation)) == 6
    assert db_session.scalar(select(func.count()).select_from(PerformancePayloadBlob)) == 3
    observations = list(db_session.scalars(select(PerformanceObservation)))
    assert all(
        item.normalization_version == PERFORMANCE_NORMALIZATION_VERSION for item in observations
    )
    assert all(
        "key" not in json.dumps(item.request_descriptor_json).lower() for item in observations
    )

    latest = latest_site_performance(db_session, site.id, provider=None, limit=20, offset=0)
    history = page_performance_history(db_session, site.id, resource.id, limit=20, offset=0)
    page_latest = page_latest_performance(db_session, site.id, resource.id)
    assert latest.total == 6
    assert history.total == 4
    assert page_latest.total == 4


def test_run_validates_configuration_membership_and_key(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    settings.google_api_key = None
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    with pytest.raises(ValueError, match="not configured"):
        create_performance_run(
            db_session, site.id, PerformanceRunCreate(resource_ids=[resource.id])
        )
    settings.google_api_key = "test-key"
    with pytest.raises(ValueError, match="do not belong"):
        create_performance_run(db_session, site.id, PerformanceRunCreate(resource_ids=[999]))
    with pytest.raises(ValueError, match="at most 10 Pages"):
        create_performance_run(
            db_session, site.id, PerformanceRunCreate(resource_ids=list(range(1, 12)))
        )
    with pytest.raises(ValueError, match="duplicates"):
        PerformanceRunCreate(resource_ids=[resource.id, resource.id])


def test_run_cancellation_retains_terminal_state_without_observations(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    run = create_performance_run(
        db_session, site.id, PerformanceRunCreate(resource_ids=[resource.id])
    )
    db_session.commit()
    session_factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)

    result = execute_performance_run(
        session_factory,
        run.id,
        should_cancel=lambda: True,
        progress=lambda _current, _total, _counters: None,
        client_factory=lambda: FakeProviderClient(),
    )

    assert result.status == "cancelled"
    assert result.finished_at is not None
    assert db_session.scalar(select(func.count()).select_from(PerformanceObservation)) == 0


def test_expired_performance_job_settles_run(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    run = create_performance_run(
        db_session, site.id, PerformanceRunCreate(resource_ids=[resource.id])
    )
    job = enqueue_performance_run_job(db_session, run.id, site.id)
    db_session.commit()
    claimed = claim_next_job(db_session, worker_id="performance-worker", lease_seconds=1)
    assert claimed is not None and claimed.job.id == job.id
    run.status = "running"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert recover_expired_jobs(db_session) == 1
    db_session.refresh(run)
    db_session.refresh(job)
    assert job.status == "interrupted"
    assert run.status == "failed"
    assert run.error_summary == "Worker lease expired during Performance collection."


def test_expired_performance_job_reconciles_terminal_run(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    run = create_performance_run(
        db_session, site.id, PerformanceRunCreate(resource_ids=[resource.id])
    )
    job = enqueue_performance_run_job(db_session, run.id, site.id)
    db_session.commit()
    claimed = claim_next_job(db_session, worker_id="performance-worker", lease_seconds=1)
    assert claimed is not None and claimed.job.id == job.id
    run.status = "completed_with_errors"
    run.finished_at = datetime.now(UTC)
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert recover_expired_jobs(db_session) == 1
    db_session.refresh(job)
    assert job.status == "completed_with_errors"


class FakeProviderClient:
    def pagespeed(self, target: str, strategy: str) -> ProviderResult:
        return ProviderResult(
            outcome="ready",
            payload=b'{"shared":"pagespeed"}',
            metrics={"lcp": {"value": 2000, "unit": "ms"}},
            provider_target=target,
            provider_product_version="12.4.0",
        )

    def crux(self, target: str, target_kind: str, form_factor: str) -> ProviderResult:
        if form_factor == "DESKTOP":
            return ProviderResult(
                outcome="unavailable",
                payload=b'{"shared":"unavailable"}',
                metrics={},
                error_type="no_field_data",
                error_message="No data.",
            )
        return ProviderResult(
            outcome="ready",
            payload=b'{"shared":"crux"}',
            metrics={"lcp": {"value": 2100, "unit": "ms", "histogram": []}},
            provider_target=target,
        )

    def close(self) -> None:
        pass


def _site_page(db: Session):
    site = create_site(
        db,
        WebsitePropertyCreate(
            name="Performance Site",
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


def _settings(tmp_path: Path):
    return SimpleNamespace(
        google_api_key="test-key",
        performance_payload_storage_root=tmp_path / "performance",
        performance_provider_timeout_seconds=1.0,
        performance_provider_max_response_bytes=1_000_000,
        performance_provider_max_attempts=3,
        performance_hard_page_limit=25,
        performance_default_page_limit=10,
    )


def _pagespeed_document() -> dict:
    return {
        "id": "https://example.com/final",
        "analysisUTCTimestamp": "2026-08-12T12:00:00Z",
        "lighthouseResult": {
            "finalUrl": "https://example.com/final",
            "lighthouseVersion": "12.4.0",
            "categories": {"performance": {"score": 0.91}},
            "audits": {
                "first-contentful-paint": {"numericValue": 900},
                "largest-contentful-paint": {"numericValue": 2450},
                "cumulative-layout-shift": {"numericValue": 0.08},
                "total-blocking-time": {"numericValue": 120},
                "speed-index": {"numericValue": 1300},
                "server-response-time": {"numericValue": 310},
            },
        },
    }


def _crux_document() -> dict:
    return {
        "record": {
            "key": {"url": "https://example.com/page", "formFactor": "PHONE"},
            "metrics": {
                "largest_contentful_paint": {
                    "histogram": [{"start": 0, "end": 2500, "density": 0.8}],
                    "percentiles": {"p75": 2200},
                },
                "interaction_to_next_paint": {
                    "histogram": [],
                    "percentiles": {"p75": 180},
                },
            },
            "collectionPeriod": {
                "firstDate": {"year": 2026, "month": 8, "day": 1},
                "lastDate": {"year": 2026, "month": 8, "day": 28},
            },
        }
    }
