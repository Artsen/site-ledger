from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from app.browser.config import DEFAULTS
from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
    NormalizedUrl,
    UrlNormalizationError,
    normalize_url_for_version,
    site_url_policy_key,
)

ScopeDecision = str


@dataclass
class ScopeConfig:
    allowed_host_patterns: list[str] = field(default_factory=list)
    excluded_host_patterns: list[str] = field(default_factory=list)
    included_path_prefixes: list[str] = field(default_factory=lambda: ["/"])
    excluded_path_prefixes: list[str] = field(default_factory=list)
    follow_subdomains: bool = False
    max_pages: int = 100
    max_depth: int = 3
    respect_robots_txt: bool = False
    request_timeout_seconds: float = 10
    static_max_attempts: int = 2
    static_retry_initial_delay_ms: int = 500
    static_retry_max_delay_ms: int = 5000
    max_html_response_bytes: int = 2_000_000
    concurrent_requests_per_host: int = 2
    delay_between_requests_ms: int = 0
    user_agent: str = "WebsiteScanner/0.1"
    drop_query_parameters: list[str] = field(default_factory=list)
    allow_private_networks: bool = False
    max_redirects: int = 10
    enable_http_revalidation: bool = True
    enable_parse_reuse: bool = True
    render_mode: str = DEFAULTS.render_mode
    render_max_pages: int = DEFAULTS.render_max_pages
    render_viewport_width: int = DEFAULTS.render_viewport_width
    render_viewport_height: int = DEFAULTS.render_viewport_height
    render_device_scale_factor: float = DEFAULTS.render_device_scale_factor
    render_locale: str = DEFAULTS.render_locale
    render_timezone: str = DEFAULTS.render_timezone
    render_color_scheme: str = DEFAULTS.render_color_scheme
    render_reduced_motion: str = DEFAULTS.render_reduced_motion
    render_navigation_timeout_seconds: float = DEFAULTS.render_navigation_timeout_seconds
    render_load_timeout_seconds: float = DEFAULTS.render_load_timeout_seconds
    render_capture_full_page: bool = DEFAULTS.render_capture_full_page
    render_max_full_page_height: int = DEFAULTS.render_max_full_page_height
    render_max_dom_bytes: int = DEFAULTS.render_max_dom_bytes
    render_max_screenshot_bytes: int = DEFAULTS.render_max_screenshot_bytes
    render_max_network_entries: int = DEFAULTS.render_max_network_entries
    render_max_console_entries: int = DEFAULTS.render_max_console_entries
    render_max_page_errors: int = DEFAULTS.render_max_page_errors
    render_max_page_duration_seconds: float = DEFAULTS.render_max_page_duration_seconds
    render_max_total_network_bytes: int = DEFAULTS.render_max_total_network_bytes
    render_max_resource_bytes: int = DEFAULTS.render_max_resource_bytes

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScopeConfig":
        config = cls()
        for key, value in data.items():
            if key in cls.__dataclass_fields__:
                setattr(config, key, value)
        return config

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "allowed_host_patterns": self.allowed_host_patterns,
            "excluded_host_patterns": self.excluded_host_patterns,
            "included_path_prefixes": self.included_path_prefixes,
            "excluded_path_prefixes": self.excluded_path_prefixes,
            "follow_subdomains": self.follow_subdomains,
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "respect_robots_txt": self.respect_robots_txt,
            "request_timeout_seconds": self.request_timeout_seconds,
            "static_max_attempts": self.static_max_attempts,
            "static_retry_initial_delay_ms": self.static_retry_initial_delay_ms,
            "static_retry_max_delay_ms": self.static_retry_max_delay_ms,
            "max_html_response_bytes": self.max_html_response_bytes,
            "concurrent_requests_per_host": self.concurrent_requests_per_host,
            "delay_between_requests_ms": self.delay_between_requests_ms,
            "user_agent": self.user_agent,
            "drop_query_parameters": self.drop_query_parameters,
            "allow_private_networks": self.allow_private_networks,
            "max_redirects": self.max_redirects,
            "enable_http_revalidation": self.enable_http_revalidation,
            "enable_parse_reuse": self.enable_parse_reuse,
        }
        for name in self.__dataclass_fields__:
            if name.startswith("render_"):
                result[name] = getattr(self, name)
        return result


@dataclass(frozen=True)
class ScopeResult:
    decision: ScopeDecision
    in_scope: bool
    normalized: NormalizedUrl | None = None
    exclusion_reason: str | None = None
    site_policy_key: str | None = None


class ScopeEngine:
    def __init__(
        self,
        config: ScopeConfig,
        starting_url: str,
        normalization_version: str = URL_NORMALIZATION_V1_VERSION,
    ):
        self.config = config
        self.normalization_version = normalization_version
        self.starting_url = self._normalize(starting_url)
        if not self.config.allowed_host_patterns:
            self.config.allowed_host_patterns = [self.starting_url.host]

    def evaluate(
        self, raw_url: str, base_url: str | None = None, seen: set[str] | None = None
    ) -> ScopeResult:
        try:
            normalized = self._normalize(raw_url, base_url)
        except (UrlNormalizationError, ValueError) as exc:
            message = str(exc)
            decision = "unsupported_scheme" if "unsupported scheme" in message else "invalid_url"
            return ScopeResult(decision, False, None, message)

        policy_key = self.policy_key(normalized)
        if normalized.scheme not in {"http", "https"}:
            return ScopeResult(
                "unsupported_scheme",
                False,
                normalized,
                "Only HTTP and HTTPS are supported",
                policy_key,
            )
        if not _host_matches_any(
            normalized.host, self.config.allowed_host_patterns, self.config.follow_subdomains
        ):
            return ScopeResult(
                "external",
                False,
                normalized,
                "Host is outside allowed host patterns",
                policy_key,
            )
        if _host_matches_any(normalized.host, self.config.excluded_host_patterns, True):
            return ScopeResult(
                "excluded_host",
                False,
                normalized,
                "Host matched excluded host patterns",
                policy_key,
            )
        if self.config.included_path_prefixes and not any(
            normalized.path.startswith(prefix) for prefix in self.config.included_path_prefixes
        ):
            return ScopeResult(
                "excluded_path",
                False,
                normalized,
                "Path did not match included prefixes",
                policy_key,
            )
        if any(normalized.path.startswith(prefix) for prefix in self.config.excluded_path_prefixes):
            return ScopeResult(
                "excluded_path",
                False,
                normalized,
                "Path matched excluded prefixes",
                policy_key,
            )
        if seen is not None and policy_key in seen:
            return ScopeResult(
                "already_seen",
                False,
                normalized,
                "URL was already queued or fetched",
                policy_key,
            )
        return ScopeResult("crawlable", True, normalized, site_policy_key=policy_key)

    def _normalize(self, raw_url: str, base_url: str | None = None) -> NormalizedUrl:
        return normalize_url_for_version(
            raw_url,
            normalization_version=self.normalization_version,
            base_url=base_url,
            drop_query_params=(
                self.config.drop_query_parameters
                if self.normalization_version == URL_NORMALIZATION_V1_VERSION
                else ()
            ),
        )

    def policy_key(self, normalized: NormalizedUrl) -> str:
        if self.normalization_version == URL_NORMALIZATION_V2_VERSION:
            return site_url_policy_key(normalized, self.config.drop_query_parameters)
        return normalized.normalized_url


def _host_matches_any(host: str, patterns: list[str], follow_subdomains: bool) -> bool:
    for pattern in patterns:
        normalized_pattern = pattern.lower()
        if fnmatchcase(host, normalized_pattern):
            return True
        if (
            follow_subdomains
            and "*" not in normalized_pattern
            and host.endswith(f".{normalized_pattern}")
        ):
            return True
    return False
