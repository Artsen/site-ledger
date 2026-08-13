from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from app.accessibility.engine import (
    AXE_CORE_VERSION,
    PROFILES,
    RULESET_PROFILE,
    WCAG_TAGS,
    canonical_json,
    detector_source,
    ruleset_metadata,
)
from app.browser.capture import BrowserRenderer


@dataclass(frozen=True)
class AccessibilityAuditResult:
    outcome: str
    final_url: str | None
    payload: bytes | None
    browser_version: str | None
    playwright_version: str
    error_type: str | None = None
    error_message: str | None = None


async def audit_page(
    renderer: BrowserRenderer,
    url: str,
    profile: str,
    *,
    max_payload_bytes: int,
) -> AccessibilityAuditResult:
    profile_config = PROFILES[profile]
    renderer.config.render_viewport_width = profile_config["viewport_width"]
    renderer.config.render_viewport_height = profile_config["viewport_height"]
    renderer.config.render_device_scale_factor = profile_config["device_scale_factor"]
    renderer.config.render_locale = profile_config["locale"]
    renderer.config.render_timezone = profile_config["timezone"]
    renderer.config.render_color_scheme = profile_config["color_scheme"]
    renderer.config.render_reduced_motion = profile_config["reduced_motion"]
    try:
        capture = await asyncio.wait_for(
            renderer.capture(url, after_ready=_execute_axe, capture_artifacts=False),
            timeout=renderer.config.render_max_page_duration_seconds,
        )
    except TimeoutError:
        return _failure(
            renderer, "audit_timeout", "Accessibility audit exceeded its duration limit."
        )
    if capture.state == "failed" or not isinstance(capture.callback_result, dict):
        return _failure(
            renderer,
            capture.error_type or "browser_audit_failed",
            capture.error_message or "Chromium did not produce Accessibility evidence.",
            capture.final_url,
        )
    payload = canonical_json(capture.callback_result)
    if len(payload) > max_payload_bytes:
        return _failure(
            renderer,
            "payload_too_large",
            "The axe-core result exceeded the configured evidence limit.",
            capture.final_url,
        )
    return AccessibilityAuditResult(
        outcome="ready",
        final_url=capture.final_url,
        payload=payload,
        browser_version=renderer.browser_version,
        playwright_version=renderer.playwright_version,
    )


async def _execute_axe(page: Any) -> dict[str, Any]:
    await page.add_script_tag(content=detector_source())
    expected = ruleset_metadata()
    result = await page.evaluate(
        """
        async ({ expectedVersion, tags }) => {
          const detector = window.axe;
          if (!detector || detector.version !== expectedVersion) {
            throw new Error("Pinned axe-core version mismatch");
          }
          const rules = detector.getRules(tags)
            .filter((rule) => rule.enabled)
            .map((rule) => ({
              rule_id: rule.ruleId,
              tags: rule.tags.filter((tag) => tag.startsWith("wcag")).sort(),
            }))
            .sort((a, b) => a.rule_id.localeCompare(b.rule_id));
          const evidence = await detector.run(document, {
            runOnly: { type: "tag", values: tags },
            resultTypes: ["violations", "incomplete", "passes", "inapplicable"],
          });
          if (detector.version !== expectedVersion) {
            throw new Error("axe-core identity changed during execution");
          }
          return { ...evidence, siteLedgerRuleset: { profile: "wcag22-aa-v1", rules } };
        }
        """,
        {"expectedVersion": AXE_CORE_VERSION, "tags": WCAG_TAGS},
    )
    actual = result.get("siteLedgerRuleset", {})
    if actual.get("profile") != RULESET_PROFILE or actual.get("rules") != expected["rules"]:
        raise RuntimeError("Runtime axe-core ruleset does not match pinned evidence identity.")
    if result.get("testEngine", {}).get("version") != AXE_CORE_VERSION:
        raise RuntimeError("axe-core result reported an unexpected detector version.")
    return cast(dict[str, Any], result)


def _failure(
    renderer: BrowserRenderer,
    error_type: str,
    error_message: str,
    final_url: str | None = None,
) -> AccessibilityAuditResult:
    return AccessibilityAuditResult(
        outcome="failed",
        final_url=final_url,
        payload=None,
        browser_version=renderer.browser_version,
        playwright_version=renderer.playwright_version,
        error_type=error_type[:64],
        error_message=error_message[:8000],
    )
