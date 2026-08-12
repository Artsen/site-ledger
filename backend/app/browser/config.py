from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

RENDER_MODES = ("none", "starting_page", "all_eligible")
ARTIFACT_TYPES = ("rendered_dom", "viewport_screenshot", "full_page_screenshot")
BROWSER_ENGINE = "chromium"
RENDERER_VERSION = "1"
BROWSER_POLICY_VERSION = "2"
CAPTURE_SCHEMA_VERSION = "2"


@dataclass(frozen=True)
class RenderDefaults:
    render_mode: str = "none"
    render_max_pages: int = 10
    render_viewport_width: int = 1440
    render_viewport_height: int = 900
    render_device_scale_factor: float = 1.0
    render_locale: str = "en-US"
    render_timezone: str = "UTC"
    render_color_scheme: str = "light"
    render_reduced_motion: str = "reduce"
    render_navigation_timeout_seconds: float = 30
    render_load_timeout_seconds: float = 10
    render_capture_full_page: bool = True
    render_max_full_page_height: int = 20_000
    render_max_dom_bytes: int = 5_000_000
    render_max_screenshot_bytes: int = 15_000_000
    render_max_network_entries: int = 1_000
    render_max_console_entries: int = 200
    render_max_page_errors: int = 50
    render_max_page_duration_seconds: float = 60
    render_max_total_network_bytes: int = 50_000_000
    render_max_resource_bytes: int = 10_000_000


DEFAULTS = RenderDefaults()

LIMITS: dict[str, tuple[float, float]] = {
    "render_max_pages": (1, 1_000),
    "render_viewport_width": (320, 3_840),
    "render_viewport_height": (240, 2_160),
    "render_device_scale_factor": (0.5, 3),
    "render_navigation_timeout_seconds": (1, 120),
    "render_load_timeout_seconds": (0, 60),
    "render_max_full_page_height": (1_000, 50_000),
    "render_max_dom_bytes": (100_000, 20_000_000),
    "render_max_screenshot_bytes": (100_000, 50_000_000),
    "render_max_network_entries": (10, 5_000),
    "render_max_console_entries": (0, 2_000),
    "render_max_page_errors": (0, 500),
    "render_max_page_duration_seconds": (5, 180),
    "render_max_total_network_bytes": (1_000_000, 250_000_000),
    "render_max_resource_bytes": (100_000, 50_000_000),
}


def capabilities() -> dict[str, Any]:
    return {
        "defaults": asdict(DEFAULTS),
        "limits": {
            key: {"minimum": value[0], "maximum": value[1]} for key, value in LIMITS.items()
        },
        "supported_modes": list(RENDER_MODES),
        "browser_engine": BROWSER_ENGINE,
        "artifact_types": list(ARTIFACT_TYPES),
        "allowed_request_methods": ["GET", "HEAD", "OPTIONS"],
        "service_workers": "blocked",
    }


def validate_render_config(values: dict[str, Any]) -> None:
    mode = values.get("render_mode", DEFAULTS.render_mode)
    if mode not in RENDER_MODES:
        raise ValueError(f"render_mode must be one of: {', '.join(RENDER_MODES)}")
    for name, (minimum, maximum) in LIMITS.items():
        value = values.get(name, getattr(DEFAULTS, name))
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    if mode != "none" and values.get("render_max_pages", DEFAULTS.render_max_pages) > values.get(
        "max_pages", 100
    ):
        raise ValueError("render_max_pages cannot exceed max_pages")
    if values.get("render_color_scheme", DEFAULTS.render_color_scheme) not in {
        "light",
        "dark",
        "no-preference",
    }:
        raise ValueError("render_color_scheme is unsupported")
    if values.get("render_reduced_motion", DEFAULTS.render_reduced_motion) not in {
        "reduce",
        "no-preference",
    }:
        raise ValueError("render_reduced_motion is unsupported")
