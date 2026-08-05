from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from app.crawler.url_normalizer import NormalizedUrl, UrlNormalizationError, normalize_url

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
    max_html_response_bytes: int = 2_000_000
    concurrent_requests_per_host: int = 2
    delay_between_requests_ms: int = 0
    user_agent: str = "WebsiteScanner/0.1"
    drop_query_parameters: list[str] = field(default_factory=list)
    allow_private_networks: bool = False
    max_redirects: int = 10
    enable_http_revalidation: bool = True
    enable_parse_reuse: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScopeConfig":
        config = cls()
        for key, value in data.items():
            if key in cls.__dataclass_fields__:
                setattr(config, key, value)
        return config

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_host_patterns": self.allowed_host_patterns,
            "excluded_host_patterns": self.excluded_host_patterns,
            "included_path_prefixes": self.included_path_prefixes,
            "excluded_path_prefixes": self.excluded_path_prefixes,
            "follow_subdomains": self.follow_subdomains,
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "respect_robots_txt": self.respect_robots_txt,
            "request_timeout_seconds": self.request_timeout_seconds,
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


@dataclass(frozen=True)
class ScopeResult:
    decision: ScopeDecision
    in_scope: bool
    normalized: NormalizedUrl | None = None
    exclusion_reason: str | None = None


class ScopeEngine:
    def __init__(self, config: ScopeConfig, starting_url: str):
        self.config = config
        self.starting_url = normalize_url(
            starting_url, drop_query_params=config.drop_query_parameters
        )
        if not self.config.allowed_host_patterns:
            self.config.allowed_host_patterns = [self.starting_url.host]

    def evaluate(
        self, raw_url: str, base_url: str | None = None, seen: set[str] | None = None
    ) -> ScopeResult:
        try:
            normalized = normalize_url(raw_url, base_url, self.config.drop_query_parameters)
        except (UrlNormalizationError, ValueError) as exc:
            message = str(exc)
            decision = "unsupported_scheme" if "unsupported scheme" in message else "invalid_url"
            return ScopeResult(decision, False, None, message)

        if normalized.scheme not in {"http", "https"}:
            return ScopeResult(
                "unsupported_scheme", False, normalized, "Only HTTP and HTTPS are supported"
            )
        if not _host_matches_any(
            normalized.host, self.config.allowed_host_patterns, self.config.follow_subdomains
        ):
            return ScopeResult(
                "external", False, normalized, "Host is outside allowed host patterns"
            )
        if _host_matches_any(normalized.host, self.config.excluded_host_patterns, True):
            return ScopeResult(
                "excluded_host", False, normalized, "Host matched excluded host patterns"
            )
        if self.config.included_path_prefixes and not any(
            normalized.path.startswith(prefix) for prefix in self.config.included_path_prefixes
        ):
            return ScopeResult(
                "excluded_path", False, normalized, "Path did not match included prefixes"
            )
        if any(normalized.path.startswith(prefix) for prefix in self.config.excluded_path_prefixes):
            return ScopeResult("excluded_path", False, normalized, "Path matched excluded prefixes")
        if seen is not None and normalized.normalized_url in seen:
            return ScopeResult(
                "already_seen", False, normalized, "URL was already queued or fetched"
            )
        return ScopeResult("crawlable", True, normalized)


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
