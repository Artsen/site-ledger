from __future__ import annotations

import hashlib
import json
from typing import Any

from app.browser.config import BROWSER_POLICY_VERSION, CAPTURE_SCHEMA_VERSION, RENDERER_VERSION
from app.crawler.scope import ScopeConfig

RENDER_COLLECTION_PROFILE_VERSION = "render-collection-profile-v1"

_CAPTURE_FIELDS = (
    "allowed_host_patterns",
    "excluded_host_patterns",
    "included_path_prefixes",
    "excluded_path_prefixes",
    "follow_subdomains",
    "drop_query_parameters",
    "allow_private_networks",
    "max_redirects",
    "render_viewport_width",
    "render_viewport_height",
    "render_device_scale_factor",
    "render_locale",
    "render_timezone",
    "render_color_scheme",
    "render_reduced_motion",
    "render_navigation_timeout_seconds",
    "render_load_timeout_seconds",
    "render_capture_full_page",
    "render_max_full_page_height",
    "render_max_dom_bytes",
    "render_max_screenshot_bytes",
    "render_max_network_entries",
    "render_max_console_entries",
    "render_max_page_errors",
    "render_max_page_duration_seconds",
    "render_max_total_network_bytes",
    "render_max_resource_bytes",
    "url_normalization_version",
)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    return value


def render_collection_profile(configuration: dict[str, Any]) -> dict[str, Any]:
    values = ScopeConfig.from_dict(configuration).to_dict()
    if "url_normalization_version" in configuration:
        values["url_normalization_version"] = configuration["url_normalization_version"]
    capture = {name: _canonical_value(values.get(name)) for name in _CAPTURE_FIELDS}
    return {
        "profile_version": RENDER_COLLECTION_PROFILE_VERSION,
        "renderer_version": RENDERER_VERSION,
        "browser_policy_version": BROWSER_POLICY_VERSION,
        "capture_schema_version": CAPTURE_SCHEMA_VERSION,
        "capture": capture,
    }


def render_collection_profile_identity(configuration: dict[str, Any]) -> str:
    payload = json.dumps(
        render_collection_profile(configuration), sort_keys=True, separators=(",", ":")
    )
    return f"{RENDER_COLLECTION_PROFILE_VERSION}:{hashlib.sha256(payload.encode()).hexdigest()}"
