from __future__ import annotations

import json
from typing import Any

from app.schemas.performance import (
    PageSpeedAuditPresentation,
    PerformanceMetricPresentation,
)

PAGESPEED_OPPORTUNITY_LIMIT = 10
PAGESPEED_DIAGNOSTIC_LIMIT = 10

METRIC_LABELS = {
    "performance_score": "Performance score",
    "fcp": "First Contentful Paint",
    "lcp": "Largest Contentful Paint",
    "cls": "Cumulative Layout Shift",
    "tbt": "Total Blocking Time",
    "speed_index": "Speed Index",
    "server_response_time": "Server response time",
    "inp": "Interaction to Next Paint",
    "ttfb": "Time to First Byte",
}
METRIC_ORDER = tuple(METRIC_LABELS)
CRUX_THRESHOLDS = {
    "lcp": (2500.0, 4000.0),
    "inp": (200.0, 500.0),
    "cls": (0.1, 0.25),
}


def metric_presentations(
    provider: str, metrics: dict[str, Any]
) -> list[PerformanceMetricPresentation]:
    result: list[PerformanceMetricPresentation] = []
    for key in METRIC_ORDER:
        item = metrics.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("value"), (int, float)):
            continue
        value = float(item["value"])
        unit = str(item.get("unit") or "")
        assessment = _assessment(provider, key, value)
        histogram = item.get("histogram")
        result.append(
            PerformanceMetricPresentation(
                key=key,
                label=METRIC_LABELS[key],
                value=value,
                unit=unit,
                formatted_value=_format_value(key, value, unit),
                assessment=assessment,
                histogram=histogram if isinstance(histogram, list) else [],
            )
        )
    return result


def parse_pagespeed_presentation(
    payload: bytes,
) -> tuple[list[PageSpeedAuditPresentation], list[PageSpeedAuditPresentation], str | None]:
    try:
        document = json.loads(payload)
        audits = document["lighthouseResult"]["audits"]
        if not isinstance(audits, dict):
            raise TypeError
    except (json.JSONDecodeError, KeyError, TypeError):
        return [], [], "The retained PageSpeed payload could not be presented as structured audits."

    opportunities: list[PageSpeedAuditPresentation] = []
    diagnostics: list[PageSpeedAuditPresentation] = []
    metric_audits = {
        "first-contentful-paint",
        "largest-contentful-paint",
        "cumulative-layout-shift",
        "total-blocking-time",
        "speed-index",
        "server-response-time",
    }
    for audit_id, value in audits.items():
        if not isinstance(audit_id, str) or not isinstance(value, dict):
            continue
        raw_details = value.get("details")
        details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
        savings_ms = _number(details.get("overallSavingsMs"))
        savings_bytes = _number(details.get("overallSavingsBytes"))
        item = PageSpeedAuditPresentation(
            audit_id=audit_id,
            title=_plain(value.get("title"), audit_id),
            description=_plain(value.get("description")),
            display_value=_plain(value.get("displayValue")),
            score=_number(value.get("score")),
            savings_ms=savings_ms,
            savings_bytes=savings_bytes,
        )
        is_opportunity = (
            details.get("type") == "opportunity"
            or savings_ms is not None
            or savings_bytes is not None
        )
        if is_opportunity:
            opportunities.append(item)
        elif audit_id not in metric_audits and value.get("scoreDisplayMode") in {
            "informative",
            "numeric",
            "binary",
        }:
            diagnostics.append(item)

    opportunities.sort(
        key=lambda item: (
            -(item.savings_ms or 0),
            -(item.savings_bytes or 0),
            item.audit_id,
        )
    )
    diagnostics.sort(key=lambda item: (item.score is None, item.score or 0, item.audit_id))
    return (
        opportunities[:PAGESPEED_OPPORTUNITY_LIMIT],
        diagnostics[:PAGESPEED_DIAGNOSTIC_LIMIT],
        None,
    )


def _assessment(provider: str, key: str, value: float) -> str | None:
    if key == "performance_score":
        if value >= 0.9:
            return "good"
        if value >= 0.5:
            return "needs_improvement"
        return "poor"
    if provider != "crux" or key not in CRUX_THRESHOLDS:
        return None
    good, poor = CRUX_THRESHOLDS[key]
    if value <= good:
        return "good"
    if value <= poor:
        return "needs_improvement"
    return "poor"


def _format_value(key: str, value: float, unit: str) -> str:
    if key == "performance_score":
        return str(round(value * 100))
    if unit == "ms" and value >= 1000:
        return f"{value / 1000:.2f} s"
    if unit == "ms":
        return f"{round(value)} ms"
    if unit == "score":
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:g} {unit}".strip()


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _plain(value: Any, fallback: str | None = None) -> str | None:
    if not isinstance(value, str):
        return fallback
    # Provider descriptions can contain Markdown/HTML-like text. Presentation keeps literal text.
    return value[:4000]
