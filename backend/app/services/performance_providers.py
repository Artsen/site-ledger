from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

PAGESPEED_ADAPTER_VERSION = "pagespeed-provider-v1"
CRUX_ADAPTER_VERSION = "crux-provider-v1"
PERFORMANCE_NORMALIZATION_VERSION = "performance-normalization-v1"
PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CRUX_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
CRUX_METRICS = [
    "largest_contentful_paint",
    "interaction_to_next_paint",
    "cumulative_layout_shift",
    "first_contentful_paint",
    "experimental_time_to_first_byte",
]


@dataclass(frozen=True)
class ProviderResult:
    outcome: str
    payload: bytes | None
    metrics: dict[str, Any]
    provider_target: str | None = None
    provider_analysis_at: datetime | None = None
    provider_period: dict[str, Any] | None = None
    provider_product_version: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def normalized_sha256(self) -> str | None:
        if self.outcome != "ready":
            return None
        return hashlib.sha256(canonical_json(self.metrics)).hexdigest()


class ProviderResponseTooLarge(RuntimeError):
    pass


class PerformanceProviderClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 90.0,
        max_response_bytes: int = 12 * 1024 * 1024,
        max_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.max_response_bytes = max_response_bytes
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def pagespeed(self, target: str, strategy: str) -> ProviderResult:
        response, payload, error = self._request(
            "GET",
            PAGESPEED_ENDPOINT,
            params={
                "url": target,
                "strategy": strategy,
                "category": "performance",
                "key": self.api_key,
            },
        )
        if error:
            return error
        assert response is not None and payload is not None
        if response.status_code != 200:
            return _http_failure("pagespeed", response.status_code, payload)
        try:
            document = json.loads(payload)
            metrics, metadata = normalize_pagespeed(document)
            return ProviderResult(
                outcome="ready",
                payload=payload,
                metrics=metrics,
                provider_target=metadata["provider_target"],
                provider_analysis_at=metadata["analysis_at"],
                provider_product_version=metadata["product_version"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return ProviderResult(
                outcome="failed",
                payload=payload,
                metrics={},
                error_type="invalid_provider_payload",
                error_message="PageSpeed returned an unusable response.",
            )

    def crux(self, target: str, target_kind: str, form_factor: str) -> ProviderResult:
        body: dict[str, Any] = {
            target_kind: target,
            "formFactor": form_factor,
            "metrics": CRUX_METRICS,
        }
        response, payload, error = self._request(
            "POST",
            CRUX_ENDPOINT,
            params={"key": self.api_key},
            json_body=body,
        )
        if error:
            return error
        assert response is not None and payload is not None
        if response.status_code == 404:
            return ProviderResult(
                outcome="unavailable",
                payload=payload,
                metrics={},
                error_type="no_field_data",
                error_message=(
                    "CrUX has no qualifying field dataset for this target and form factor."
                ),
            )
        if response.status_code != 200:
            return _http_failure("crux", response.status_code, payload)
        try:
            document = json.loads(payload)
            metrics, metadata = normalize_crux(document)
            return ProviderResult(
                outcome="ready",
                payload=payload,
                metrics=metrics,
                provider_target=metadata["provider_target"],
                provider_period=metadata["period"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return ProviderResult(
                outcome="failed",
                payload=payload,
                metrics={},
                error_type="invalid_provider_payload",
                error_message="CrUX returned an unusable response.",
            )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> tuple[httpx.Response | None, bytes | None, ProviderResult | None]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self.client.stream(
                    method, endpoint, params=params, json=json_body
                ) as response:
                    payload = _bounded_body(response, self.max_response_bytes)
                if (
                    response.status_code == 429 or 500 <= response.status_code <= 599
                ) and attempt < self.max_attempts:
                    self.sleep(_retry_delay(response, attempt))
                    continue
                return response, payload, None
            except ProviderResponseTooLarge:
                return (
                    None,
                    None,
                    ProviderResult(
                        outcome="failed",
                        payload=None,
                        metrics={},
                        error_type="response_too_large",
                        error_message="Provider response exceeded the configured evidence limit.",
                    ),
                )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
                if attempt < self.max_attempts:
                    self.sleep(min(float(attempt), 3.0))
                    continue
                return (
                    None,
                    None,
                    ProviderResult(
                        outcome="failed",
                        payload=None,
                        metrics={},
                        error_type="provider_network_error",
                        error_message="Provider request failed after bounded retries.",
                    ),
                )
        raise AssertionError("unreachable")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def normalize_pagespeed(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    lighthouse = document["lighthouseResult"]
    audits = lighthouse["audits"]
    performance = lighthouse["categories"]["performance"].get("score")
    metrics: dict[str, Any] = {}
    if isinstance(performance, (int, float)):
        metrics["performance_score"] = {"value": performance, "unit": "ratio"}
    audit_map = {
        "fcp": ("first-contentful-paint", "ms"),
        "lcp": ("largest-contentful-paint", "ms"),
        "cls": ("cumulative-layout-shift", "score"),
        "tbt": ("total-blocking-time", "ms"),
        "speed_index": ("speed-index", "ms"),
        "server_response_time": ("server-response-time", "ms"),
    }
    for key, (audit_key, unit) in audit_map.items():
        value = audits.get(audit_key, {}).get("numericValue")
        if isinstance(value, (int, float)):
            metrics[key] = {"value": value, "unit": unit}
    return metrics, {
        "provider_target": lighthouse.get("finalUrl") or document.get("id"),
        "analysis_at": _parse_datetime(
            document.get("analysisUTCTimestamp") or lighthouse.get("fetchTime")
        ),
        "product_version": lighthouse.get("lighthouseVersion"),
    }


def normalize_crux(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    record = document["record"]
    source = record["metrics"]
    metric_map = {
        "lcp": ("largest_contentful_paint", "ms"),
        "inp": ("interaction_to_next_paint", "ms"),
        "cls": ("cumulative_layout_shift", "score"),
        "fcp": ("first_contentful_paint", "ms"),
        "ttfb": ("experimental_time_to_first_byte", "ms"),
    }
    metrics: dict[str, Any] = {}
    for key, (provider_key, unit) in metric_map.items():
        item = source.get(provider_key)
        if not isinstance(item, dict):
            continue
        value = item.get("percentiles", {}).get("p75")
        if isinstance(value, (int, float, str)):
            try:
                numeric = float(value)
            except ValueError:
                continue
            metrics[key] = {
                "value": numeric,
                "unit": unit,
                "histogram": item.get("histogram", []),
            }
    if not metrics:
        raise ValueError("No requested CrUX metrics")
    key = record.get("key", {})
    return metrics, {
        "provider_target": key.get("url") or key.get("origin"),
        "period": record.get("collectionPeriod"),
    }


def _bounded_body(response: httpx.Response, limit: int) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise ProviderResponseTooLarge
    return bytes(body)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return min(max(float(value), 0.0), 5.0)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                return min(max((retry_at - datetime.now(UTC)).total_seconds(), 0.0), 5.0)
            except (TypeError, ValueError):
                pass
    return min(float(attempt), 3.0)


def _http_failure(provider: str, status: int, payload: bytes) -> ProviderResult:
    error_type = "provider_auth_error" if status in {401, 403} else "provider_http_error"
    if status == 429:
        error_type = "provider_rate_limited"
    return ProviderResult(
        outcome="failed",
        payload=payload,
        metrics={},
        error_type=error_type,
        error_message=f"{provider.title()} request failed with HTTP {status}.",
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
