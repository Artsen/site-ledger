from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

AXE_CORE_VERSION = "4.12.1"
AXE_BUNDLE_SHA256 = "66a8aaa95a8b044a7fd74a5435873bf04ff65a1ca75567c921b7509742085a14"
ACCESSIBILITY_INTEGRATION_VERSION = "accessibility-engine-v1"
ACCESSIBILITY_NORMALIZATION_VERSION = "accessibility-normalization-v1"
RULESET_PROFILE = "wcag22-aa-v1"
RULESET_SHA256 = "9e529b185ca8f212dc39924c0f2e6208115e44c1baf0052128a00080212705a5"
WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
MAX_HTML_SNIPPET = 4096
MAX_FAILURE_SUMMARY = 16_000

VENDOR_ROOT = Path(__file__).parent / "vendor"
AXE_BUNDLE_PATH = VENDOR_ROOT / "axe.min.js"
RULESET_PATH = VENDOR_ROOT / "wcag22-aa-v1.json"

PROFILES: dict[str, dict[str, Any]] = {
    "desktop": {
        "label": "Desktop",
        "viewport_width": 1440,
        "viewport_height": 900,
        "device_scale_factor": 1.0,
        "locale": "en-US",
        "timezone": "UTC",
        "color_scheme": "light",
        "reduced_motion": "reduce",
    },
    "mobile": {
        "label": "Mobile",
        "viewport_width": 390,
        "viewport_height": 844,
        "device_scale_factor": 1.0,
        "locale": "en-US",
        "timezone": "UTC",
        "color_scheme": "light",
        "reduced_motion": "reduce",
    },
}


@dataclass(frozen=True)
class NormalizedNode:
    position: int
    impact: str | None
    target: list[Any]
    html: str
    html_original_length: int
    html_truncated: bool
    failure_summary: str
    sha256: str


@dataclass(frozen=True)
class NormalizedRule:
    position: int
    rule_id: str
    result_type: str
    impact: str | None
    description: str
    help: str
    help_url: str | None
    tags: list[str]
    nodes: list[NormalizedNode]
    sha256: str


@dataclass(frozen=True)
class NormalizedAccessibility:
    rules: list[NormalizedRule]
    violation_rule_count: int
    violation_node_count: int
    incomplete_rule_count: int
    incomplete_node_count: int
    pass_rule_count: int
    inapplicable_rule_count: int
    sha256: str


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_detector_assets() -> None:
    if hashlib.sha256(AXE_BUNDLE_PATH.read_bytes()).hexdigest() != AXE_BUNDLE_SHA256:
        raise RuntimeError("Pinned axe-core detector checksum mismatch.")
    if hashlib.sha256(RULESET_PATH.read_bytes()).hexdigest() != RULESET_SHA256:
        raise RuntimeError("Pinned Accessibility ruleset checksum mismatch.")
    ruleset = json.loads(RULESET_PATH.read_bytes())
    if ruleset["axe_core_version"] != AXE_CORE_VERSION or ruleset["profile"] != RULESET_PROFILE:
        raise RuntimeError("Pinned Accessibility ruleset identity mismatch.")


def ruleset_metadata() -> dict[str, Any]:
    verify_detector_assets()
    return cast(dict[str, Any], json.loads(RULESET_PATH.read_bytes()))


def detector_source() -> str:
    verify_detector_assets()
    return AXE_BUNDLE_PATH.read_text(encoding="utf-8")


def normalize_axe_result(result: dict[str, Any]) -> NormalizedAccessibility:
    rules: list[NormalizedRule] = []
    normalized_for_hash: list[dict[str, Any]] = []
    for result_type, source_key in (("violation", "violations"), ("incomplete", "incomplete")):
        source_rules = sorted(result.get(source_key, []), key=lambda item: str(item.get("id", "")))
        for position, source in enumerate(source_rules, start=1):
            nodes: list[NormalizedNode] = []
            node_hash_values: list[dict[str, Any]] = []
            for node_position, node in enumerate(source.get("nodes", []), start=1):
                raw_html = str(node.get("html") or "")
                html = raw_html[:MAX_HTML_SNIPPET]
                failure = str(node.get("failureSummary") or "")[:MAX_FAILURE_SUMMARY]
                node_value = {
                    "position": node_position,
                    "impact": _impact(node.get("impact")),
                    "target": node.get("target") if isinstance(node.get("target"), list) else [],
                    "html": html,
                    "html_original_length": len(raw_html),
                    "html_truncated": len(raw_html) > MAX_HTML_SNIPPET,
                    "failure_summary": failure,
                }
                node_sha = hashlib.sha256(canonical_json(node_value)).hexdigest()
                nodes.append(NormalizedNode(**node_value, sha256=node_sha))
                node_hash_values.append({**node_value, "sha256": node_sha})
            rule_id = str(source.get("id") or "")[:128]
            impact = _impact(source.get("impact"))
            description = str(source.get("description") or "")
            help_text = str(source.get("help") or "")
            help_url = _safe_help_url(source.get("helpUrl"))
            tags = sorted(str(tag) for tag in source.get("tags", []))
            rule_value: dict[str, Any] = {
                "position": position,
                "rule_id": rule_id,
                "result_type": result_type,
                "impact": impact,
                "description": description,
                "help": help_text,
                "help_url": help_url,
                "tags": tags,
                "nodes": node_hash_values,
            }
            rule_sha = hashlib.sha256(canonical_json(rule_value)).hexdigest()
            rules.append(
                NormalizedRule(
                    position=position,
                    rule_id=rule_id,
                    result_type=result_type,
                    impact=impact,
                    description=description,
                    help=help_text,
                    help_url=help_url,
                    tags=tags,
                    nodes=nodes,
                    sha256=rule_sha,
                )
            )
            normalized_for_hash.append({**rule_value, "sha256": rule_sha})
    counts = {
        "violation_rule_count": len(result.get("violations", [])),
        "violation_node_count": sum(
            len(item.get("nodes", [])) for item in result.get("violations", [])
        ),
        "incomplete_rule_count": len(result.get("incomplete", [])),
        "incomplete_node_count": sum(
            len(item.get("nodes", [])) for item in result.get("incomplete", [])
        ),
        "pass_rule_count": len(result.get("passes", [])),
        "inapplicable_rule_count": len(result.get("inapplicable", [])),
    }
    identity = {
        "integration_version": ACCESSIBILITY_INTEGRATION_VERSION,
        "normalization_version": ACCESSIBILITY_NORMALIZATION_VERSION,
        "ruleset_profile": RULESET_PROFILE,
        "ruleset_sha256": RULESET_SHA256,
        "rules": normalized_for_hash,
        **counts,
    }
    return NormalizedAccessibility(
        rules=rules, sha256=hashlib.sha256(canonical_json(identity)).hexdigest(), **counts
    )


def _impact(value: Any) -> str | None:
    return str(value)[:32] if value is not None else None


def _safe_help_url(value: Any) -> str | None:
    text = str(value or "")
    return text if text.startswith("https://") else None
