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
from app.services.observability_payload_gc import collect_performance_payload_gc
from app.services.performance_collection import (
    CruxRateLimiter,
    PerformanceCollectionCancelled,
    create_performance_run,
    execute_performance_run,
)
from app.services.performance_deletion import (
    delete_performance_observation,
    preview_performance_observation_deletion,
)
from app.services.performance_presentation import (
    metric_presentations,
    parse_pagespeed_presentation,
)
from app.services.performance_providers import (
    CRUX_ADAPTER_VERSION,
    PAGESPEED_ADAPTER_VERSION,
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
    performance_observation_read,
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


def test_performance_provider_versions_define_pagespeed_v2_boundary() -> None:
    assert PAGESPEED_ADAPTER_VERSION == "pagespeed-provider-v2"
    assert CRUX_ADAPTER_VERSION == "crux-provider-v1"
    assert PERFORMANCE_NORMALIZATION_VERSION == "performance-normalization-v1"


@pytest.mark.parametrize(
    ("score", "audits", "expected_metrics"),
    [
        (0.91, {}, {"performance_score"}),
        (None, {"largest-contentful-paint": {"numericValue": 2450}}, {"lcp"}),
        (
            None,
            {
                "first-contentful-paint": {"numericValue": 900},
                "cumulative-layout-shift": {"numericValue": 0.08},
            },
            {"fcp", "cls"},
        ),
        (0, {}, {"performance_score"}),
        (None, {"total-blocking-time": {"numericValue": 0}}, {"tbt"}),
    ],
    ids=["score-only", "one-audit", "audits-without-score", "zero-score", "zero-audit"],
)
def test_pagespeed_ready_requires_at_least_one_recognized_metric(
    score: float | None,
    audits: dict[str, dict[str, float]],
    expected_metrics: set[str],
) -> None:
    document = _pagespeed_document()
    document["lighthouseResult"]["categories"]["performance"]["score"] = score
    document["lighthouseResult"]["audits"] = audits
    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=document)),
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "ready"
    assert set(result.metrics) == expected_metrics
    assert result.normalized_sha256 is not None


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


def test_pagespeed_rejects_lighthouse_response_without_usable_metrics() -> None:
    document = _pagespeed_document()
    document["lighthouseResult"]["categories"]["performance"]["score"] = None
    document["lighthouseResult"]["audits"] = {}
    payload = json.dumps(document).encode()
    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=payload)),
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "failed"
    assert result.error_type == "no_usable_performance_metrics"
    assert result.error_message == "PageSpeed returned no usable Performance metrics."
    assert result.metrics == {}
    assert result.normalized_sha256 is None
    assert result.payload == payload
    assert result.provider_target == "https://example.com/final"
    assert result.provider_analysis_at == datetime(2026, 8, 12, 12, tzinfo=UTC)
    assert result.provider_product_version == "12.4.0"


@pytest.mark.parametrize(
    ("score", "audits"),
    [
        ("not-numeric", {}),
        (None, {"unused-audit": {"numericValue": 123}}),
        (None, {}),
    ],
    ids=["empty-audits", "unrelated-audits", "null-score"],
)
def test_pagespeed_metric_empty_variants_fail(
    score: object, audits: dict[str, dict[str, float]]
) -> None:
    document = _pagespeed_document()
    document["lighthouseResult"]["categories"]["performance"]["score"] = score
    document["lighthouseResult"]["audits"] = audits
    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=document)),
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "failed"
    assert result.error_type == "no_usable_performance_metrics"
    assert result.payload is not None


@pytest.mark.parametrize(
    "payload",
    [
        b"{not-json",
        b'{"id":"https://example.com/"}',
        b'{"lighthouseResult":{"categories":{"performance":{"score":0.9}}}}',
    ],
    ids=["malformed-json", "missing-lighthouse", "missing-audits"],
)
def test_pagespeed_invalid_structures_remain_invalid_provider_payload(payload: bytes) -> None:
    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=payload)),
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "failed"
    assert result.error_type == "invalid_provider_payload"
    assert result.payload == payload


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(400, "provider_http_error"), (401, "provider_auth_error"), (403, "provider_auth_error")],
)
def test_pagespeed_http_failures_remain_distinct(status: int, error_type: str) -> None:
    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, json={"error": {}})),
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "failed"
    assert result.error_type == error_type


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(429, "provider_rate_limited"), (500, "provider_http_error")],
)
def test_pagespeed_retryable_http_failures_settle_after_bounded_retries(
    status: int, error_type: str
) -> None:
    attempts = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, json={"error": {}})

    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert attempts == 3
    assert result.outcome == "failed"
    assert result.error_type == error_type


def test_pagespeed_network_failure_remains_provider_network_error() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic failure", request=request)

    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(fail),
        sleep=lambda _delay: None,
    )

    result = client.pagespeed("https://example.com/page", "mobile")
    client.close()

    assert result.outcome == "failed"
    assert result.error_type == "provider_network_error"


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


def test_crux_throttle_hook_runs_before_every_attempt_only_for_crux() -> None:
    requests: list[httpx.Request] = []
    throttle_calls: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "chromeuxreport.googleapis.com" and len(requests) == 1:
            return httpx.Response(429, json={"error": {}}, headers={"Retry-After": "0"})
        if request.url.host == "chromeuxreport.googleapis.com":
            return httpx.Response(200, json=_crux_document())
        return httpx.Response(200, json=_pagespeed_document())

    client = PerformanceProviderClient(
        "secret-key",
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
        before_crux_attempt=lambda: throttle_calls.append(len(requests)),
    )
    assert client.crux("https://example.com/page", "url", "PHONE").outcome == "ready"
    assert throttle_calls == [0, 1]
    assert client.pagespeed("https://example.com/page", "mobile").outcome == "ready"
    assert throttle_calls == [0, 1]
    client.close()


def test_pagespeed_presentation_is_bounded_ordered_and_literal() -> None:
    document = _pagespeed_document()
    audits = document["lighthouseResult"]["audits"]
    for index in range(12):
        audits[f"opportunity-{index:02d}"] = {
            "title": f"<b>Opportunity {index}</b>",
            "description": "Provider **markup** remains literal.",
            "details": {"type": "opportunity", "overallSavingsMs": index * 10},
        }
    audits["diagnostic"] = {
        "title": "Diagnostic",
        "score": 0,
        "scoreDisplayMode": "informative",
    }

    opportunities, diagnostics, error = parse_pagespeed_presentation(json.dumps(document).encode())

    assert error is None
    assert len(opportunities) == 10
    assert opportunities[0].audit_id == "opportunity-11"
    assert opportunities[0].title == "<b>Opportunity 11</b>"
    assert diagnostics[0].audit_id == "diagnostic"
    assert parse_pagespeed_presentation(b"not-json")[2] is not None


def test_metric_assessments_use_provider_specific_thresholds() -> None:
    metrics = metric_presentations(
        "crux",
        {
            "lcp": {"value": 2500, "unit": "ms"},
            "inp": {"value": 300, "unit": "ms"},
            "cls": {"value": 0.3, "unit": "score"},
            "fcp": {"value": 1000, "unit": "ms"},
        },
    )

    assessments = {item.key: item.assessment for item in metrics}
    assert assessments == {
        "fcp": None,
        "lcp": "good",
        "cls": "poor",
        "inp": "needs_improvement",
    }


def test_crux_rate_limiter_spaces_attempts_and_checks_cancellation() -> None:
    now = [0.0]
    cancelled = [False]

    def sleep(delay: float) -> None:
        now[0] += delay
        cancelled[0] = True

    limiter = CruxRateLimiter(
        120,
        should_cancel=lambda: cancelled[0],
        clock=lambda: now[0],
        sleep=sleep,
    )
    limiter.wait()
    with pytest.raises(PerformanceCollectionCancelled):
        limiter.wait()


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
    assert latest.field_available_phone_page_count == 1
    assert latest.field_available_desktop_page_count == 0
    assert history.total == 4
    assert page_latest.total == 4

    newer = create_performance_run(
        db_session,
        site.id,
        PerformanceRunCreate(
            resource_ids=[resource.id],
            providers=["crux"],
            pagespeed_strategies=[],
            crux_form_factors=["PHONE"],
            include_origin_crux=False,
        ),
    )
    db_session.commit()
    execute_performance_run(
        session_factory,
        newer.id,
        should_cancel=lambda: False,
        progress=lambda _current, _total, _counters: None,
        client_factory=lambda: UnavailableProviderClient(),
    )
    current = latest_site_performance(db_session, site.id, provider=None, limit=20, offset=0)
    assert current.field_available_phone_page_count == 0
    assert current.field_available_page_count == 0


def test_empty_pagespeed_metrics_persist_as_failed_evidence(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    document = _pagespeed_document()
    document["lighthouseResult"]["categories"]["performance"]["score"] = None
    document["lighthouseResult"]["audits"] = {}
    payload = json.dumps(document, separators=(",", ":")).encode()
    run = create_performance_run(
        db_session,
        site.id,
        PerformanceRunCreate(
            resource_ids=[resource.id],
            providers=["pagespeed"],
            pagespeed_strategies=["mobile"],
            crux_form_factors=[],
            include_origin_crux=False,
        ),
    )
    db_session.commit()
    session_factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)

    result = execute_performance_run(
        session_factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda _current, _total, _counters: None,
        client_factory=lambda: PerformanceProviderClient(
            "secret-key",
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=payload)),
        ),
    )

    db_session.expire_all()
    observation = db_session.scalar(
        select(PerformanceObservation).where(PerformanceObservation.performance_run_id == run.id)
    )
    assert observation is not None
    assert result.status == "completed_with_errors"
    assert (
        result.completed_count,
        result.ready_count,
        result.unavailable_count,
        result.failed_count,
    ) == (
        1,
        0,
        0,
        1,
    )
    assert observation.provider == "pagespeed"
    assert observation.provider_adapter_version == "pagespeed-provider-v2"
    assert observation.normalization_version == "performance-normalization-v1"
    assert observation.outcome == "failed"
    assert observation.metrics_json == {}
    assert observation.normalized_sha256 is None
    assert observation.payload_blob_id is not None
    assert observation.error_type == "no_usable_performance_metrics"
    assert observation.provider_target == "https://example.com/final"
    assert observation.provider_analysis_at == datetime(2026, 8, 12, 12, tzinfo=UTC)
    assert observation.provider_product_version == "12.4.0"
    blob = db_session.get(PerformancePayloadBlob, observation.payload_blob_id)
    assert blob is not None
    store = LocalPerformancePayloadStore(settings.performance_payload_storage_root)
    assert store.read(blob) == payload

    latest = latest_site_performance(db_session, site.id, provider="pagespeed", limit=10, offset=0)
    page_latest = page_latest_performance(db_session, site.id, resource.id)
    assert latest.total == 1 and latest.items[0].outcome == "failed"
    assert page_latest.total == 1 and page_latest.items[0].outcome == "failed"
    assert page_latest.items[0].metrics_json == {}

    gc_report = collect_performance_payload_gc(db_session, store)
    assert gc_report.referenced_blob_records == 1
    assert gc_report.unreferenced_blob_records == 0
    preview = preview_performance_observation_deletion(db_session, site.id, observation.id)
    assert preview is not None and preview.can_delete and preview.payload_present
    deletion = delete_performance_observation(db_session, site.id, observation.id, store)
    assert deletion is not None
    assert deletion.observations_deleted == 1
    assert deletion.payload_blob_records_deleted == 1
    assert db_session.get(PerformancePayloadBlob, blob.id) is None


def test_mixed_pagespeed_run_retains_ready_and_failed_payloads(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    ready_payload = json.dumps(_pagespeed_document(), separators=(",", ":")).encode()
    empty_document = _pagespeed_document()
    empty_document["lighthouseResult"]["categories"]["performance"]["score"] = None
    empty_document["lighthouseResult"]["audits"] = {}
    failed_payload = json.dumps(empty_document, separators=(",", ":")).encode()

    def respond(request: httpx.Request) -> httpx.Response:
        payload = ready_payload if request.url.params["strategy"] == "mobile" else failed_payload
        return httpx.Response(200, content=payload)

    run = create_performance_run(
        db_session,
        site.id,
        PerformanceRunCreate(
            resource_ids=[resource.id],
            providers=["pagespeed"],
            pagespeed_strategies=["mobile", "desktop"],
            crux_form_factors=[],
            include_origin_crux=False,
        ),
    )
    db_session.commit()
    session_factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)

    result = execute_performance_run(
        session_factory,
        run.id,
        should_cancel=lambda: False,
        progress=lambda _current, _total, _counters: None,
        client_factory=lambda: PerformanceProviderClient(
            "secret-key", transport=httpx.MockTransport(respond)
        ),
    )

    assert result.status == "completed_with_errors"
    assert (
        result.completed_count,
        result.ready_count,
        result.unavailable_count,
        result.failed_count,
    ) == (
        2,
        1,
        0,
        1,
    )
    db_session.expire_all()
    observations = list(
        db_session.scalars(
            select(PerformanceObservation)
            .where(PerformanceObservation.performance_run_id == run.id)
            .order_by(PerformanceObservation.dimension)
        )
    )
    assert {item.outcome for item in observations} == {"ready", "failed"}
    store = LocalPerformancePayloadStore(settings.performance_payload_storage_root)
    retained: set[bytes] = set()
    for observation in observations:
        assert observation.payload_blob_id is not None
        blob = db_session.get(PerformancePayloadBlob, observation.payload_blob_id)
        assert blob is not None
        retained.add(store.read(blob))
    assert retained == {ready_payload, failed_payload}


def test_historical_pagespeed_v1_empty_ready_observation_remains_readable(
    db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    site, resource = _site_page(db_session)
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.services.performance_collection.get_settings", lambda: settings)
    run = create_performance_run(
        db_session,
        site.id,
        PerformanceRunCreate(
            resource_ids=[resource.id],
            providers=["pagespeed"],
            pagespeed_strategies=["mobile"],
            crux_form_factors=[],
            include_origin_crux=False,
        ),
    )
    run.status = "completed"
    run.completed_count = 1
    run.ready_count = 1
    run.finished_at = datetime.now(UTC)
    blob = LocalPerformancePayloadStore(settings.performance_payload_storage_root).put(
        db_session, b'{"historical":"v1"}'
    )
    observation = PerformanceObservation(
        performance_run_id=run.id,
        website_property_id=site.id,
        web_resource_id=resource.id,
        payload_blob_id=blob.id,
        provider="pagespeed",
        provider_adapter_version="pagespeed-provider-v1",
        normalization_version="performance-normalization-v1",
        target_kind="url",
        target_key="historical-v1-page",
        requested_target=resource.normalized_url,
        provider_target=resource.normalized_url,
        dimension="mobile",
        outcome="ready",
        request_descriptor_json={"provider": "pagespeed"},
        metrics_json={},
        normalized_sha256=None,
        observed_at=datetime.now(UTC),
    )
    db_session.add(observation)
    db_session.commit()

    history = page_performance_history(db_session, site.id, resource.id, limit=10, offset=0)
    latest = page_latest_performance(db_session, site.id, resource.id)
    read = performance_observation_read(observation)

    assert history.items[0].provider_adapter_version == "pagespeed-provider-v1"
    assert history.items[0].outcome == "ready" and history.items[0].metrics_json == {}
    assert latest.items[0].id == observation.id and latest.items[0].outcome == "ready"
    assert read.provider_adapter_version == "pagespeed-provider-v1"
    assert read.payload_sha256 == blob.sha256


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
    settings.performance_hard_page_limit = 10
    with pytest.raises(ValueError, match="at most 10 Pages"):
        create_performance_run(
            db_session, site.id, PerformanceRunCreate(resource_ids=list(range(1, 12)))
        )
    settings.performance_max_provider_requests = 5
    with pytest.raises(ValueError, match="6 provider requests"):
        create_performance_run(
            db_session, site.id, PerformanceRunCreate(resource_ids=[resource.id])
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


class UnavailableProviderClient(FakeProviderClient):
    def crux(self, target: str, target_kind: str, form_factor: str) -> ProviderResult:
        return ProviderResult(
            outcome="unavailable",
            payload=b'{"newer":"unavailable"}',
            metrics={},
            error_type="no_field_data",
            error_message="No URL-level field data.",
        )


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
        performance_max_provider_requests=102,
        performance_crux_queries_per_minute=120,
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
