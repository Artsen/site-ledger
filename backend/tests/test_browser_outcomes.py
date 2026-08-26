from datetime import UTC, datetime

import pytest

from app.browser.outcomes import (
    HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD,
    HostRateLimitCircuitBreaker,
    classify_main_navigation,
    host_rate_limit_skip_result,
    is_successful_page_capture,
    parse_retry_after_signal,
)


@pytest.mark.parametrize("status", [200, 201, 299])
def test_successful_main_navigation_is_artifact_eligible(status: int) -> None:
    outcome = classify_main_navigation(status)
    assert outcome.kind == "successful_page"
    assert outcome.capture_state == "completed"
    assert outcome.error_type is None
    assert outcome.artifacts_eligible
    assert is_successful_page_capture(outcome.capture_state, status)


@pytest.mark.parametrize("status", [204, 205])
def test_main_navigation_without_content_is_not_artifact_eligible(status: int) -> None:
    outcome = classify_main_navigation(status)
    assert outcome.kind == "no_content"
    assert outcome.capture_state == "failed"
    assert outcome.error_type == "navigation_no_content"
    assert str(status) in (outcome.error_message or "")
    assert not outcome.artifacts_eligible
    assert not is_successful_page_capture(outcome.capture_state, status)


@pytest.mark.parametrize(
    ("status", "kind", "error_type"),
    [
        (302, "http_redirect", "navigation_http_redirect"),
        (403, "http_client_error", "navigation_http_client_error"),
        (404, "http_client_error", "navigation_http_client_error"),
        (429, "rate_limited", "navigation_rate_limited"),
        (500, "http_server_error", "navigation_http_server_error"),
        (503, "http_server_error", "navigation_http_server_error"),
    ],
)
def test_http_non_success_is_not_artifact_eligible(status: int, kind: str, error_type: str) -> None:
    outcome = classify_main_navigation(status)
    assert outcome.kind == kind
    assert outcome.capture_state == "failed"
    assert outcome.error_type == error_type
    assert not outcome.artifacts_eligible
    assert not is_successful_page_capture(outcome.capture_state, status)


def test_rate_limit_circuit_opens_only_after_consecutive_429s_per_host() -> None:
    breaker = HostRateLimitCircuitBreaker()
    for _ in range(HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD - 1):
        assert not breaker.record(
            "https://limited.example/page",
            status=429,
            error_type="navigation_rate_limited",
        )
    assert not breaker.is_open("https://limited.example/next")
    assert breaker.record(
        "https://limited.example/page",
        status=429,
        error_type="navigation_rate_limited",
    )
    assert breaker.is_open("https://limited.example/next")
    assert not breaker.is_open("https://other.example/page")


@pytest.mark.parametrize("status", [404, 500, 503])
def test_non_rate_limit_http_failures_do_not_open_circuit(status: int) -> None:
    breaker = HostRateLimitCircuitBreaker(threshold=2)
    error_type = "navigation_http_client_error" if status < 500 else "navigation_http_server_error"
    for _ in range(5):
        assert not breaker.record("https://example.com/page", status=status, error_type=error_type)
    assert not breaker.is_open("https://example.com/next")


def test_non_rate_limit_result_resets_consecutive_count() -> None:
    breaker = HostRateLimitCircuitBreaker(threshold=2)
    breaker.record("https://example.com/a", status=429, error_type="navigation_rate_limited")
    breaker.record("https://example.com/b", status=200, error_type=None)
    assert not breaker.record(
        "https://example.com/c", status=429, error_type="navigation_rate_limited"
    )


def test_circuit_skip_is_truthful_and_contains_no_request_evidence() -> None:
    result = host_rate_limit_skip_result()
    assert result.state == "skipped"
    assert result.error_type == "host_rate_limit_circuit_open"
    assert result.status is None
    assert result.network == []
    assert result.artifacts == []


def test_retry_after_is_bounded_and_repeated_503_can_open_circuit() -> None:
    assert parse_retry_after_signal("999999") == 3_600
    assert parse_retry_after_signal("not-a-delay") is None
    assert (
        parse_retry_after_signal(
            "Wed, 26 Aug 2026 09:00:00 GMT",
            now=datetime(2026, 8, 26, 8, 59, tzinfo=UTC),
        )
        == 60
    )
    breaker = HostRateLimitCircuitBreaker(threshold=2)
    assert not breaker.record(
        "https://example.com/a",
        status=503,
        error_type="navigation_http_server_error",
        retry_after="120",
    )
    assert breaker.record(
        "https://example.com/b",
        status=503,
        error_type="navigation_http_server_error",
        retry_after="120",
    )


def test_503_without_valid_retry_after_does_not_open_circuit() -> None:
    breaker = HostRateLimitCircuitBreaker(threshold=1)
    assert not breaker.record(
        "https://example.com/a",
        status=503,
        error_type="navigation_http_server_error",
        retry_after="invalid",
    )
