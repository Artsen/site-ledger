from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app.browser.capture import CaptureResult

HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD = 3
MAX_RETRY_AFTER_SIGNAL_SECONDS = 3_600
SUCCESSFUL_CAPTURE_STATES = frozenset({"completed", "completed_with_warnings"})


@dataclass(frozen=True)
class MainNavigationOutcome:
    kind: str
    capture_state: str
    error_type: str | None
    error_message: str | None
    artifacts_eligible: bool


def classify_main_navigation(status: int | None) -> MainNavigationOutcome:
    if status is None:
        return MainNavigationOutcome(
            "navigation_failure",
            "failed",
            "navigation_no_response",
            "Browser navigation did not return a main-document HTTP response.",
            False,
        )
    if status in {204, 205}:
        return MainNavigationOutcome(
            "no_content",
            "failed",
            "navigation_no_content",
            f"Main-document navigation returned HTTP {status} with no Page content.",
            False,
        )
    if 200 <= status < 300:
        return MainNavigationOutcome("successful_page", "completed", None, None, True)
    if status == 429:
        return MainNavigationOutcome(
            "rate_limited",
            "failed",
            "navigation_rate_limited",
            "Main-document navigation was rate limited (HTTP 429).",
            False,
        )
    if 400 <= status < 500:
        return MainNavigationOutcome(
            "http_client_error",
            "failed",
            "navigation_http_client_error",
            f"Main-document navigation returned HTTP {status}.",
            False,
        )
    if 500 <= status < 600:
        return MainNavigationOutcome(
            "http_server_error",
            "failed",
            "navigation_http_server_error",
            f"Main-document navigation returned HTTP {status}.",
            False,
        )
    if 300 <= status < 400:
        return MainNavigationOutcome(
            "http_redirect",
            "failed",
            "navigation_http_redirect",
            f"Main-document navigation ended at an unfollowed HTTP {status} response.",
            False,
        )
    return MainNavigationOutcome(
        "unexpected_http_status",
        "failed",
        "navigation_unexpected_http_status",
        f"Main-document navigation returned unexpected HTTP status {status}.",
        False,
    )


def is_successful_page_capture(capture_state: str, status: int | None) -> bool:
    return (
        capture_state in SUCCESSFUL_CAPTURE_STATES
        and status is not None
        and 200 <= status < 300
        and status not in {204, 205}
    )


class HostRateLimitCircuitBreaker:
    def __init__(self, threshold: int = HOST_RATE_LIMIT_CONSECUTIVE_THRESHOLD):
        if threshold < 1:
            raise ValueError("Rate-limit circuit threshold must be positive")
        self.threshold = threshold
        self._consecutive: dict[str, int] = {}
        self._open_hosts: set[str] = set()

    def is_open(self, url: str) -> bool:
        return self._host(url) in self._open_hosts

    def record(
        self,
        url: str,
        *,
        status: int | None,
        error_type: str | None,
        retry_after: str | None = None,
    ) -> bool:
        host = self._host(url)
        explicit_throttling = status == 429 and error_type == "navigation_rate_limited"
        if status == 503 and parse_retry_after_signal(retry_after) is not None:
            explicit_throttling = True
        if explicit_throttling:
            count = self._consecutive.get(host, 0) + 1
            self._consecutive[host] = count
            if count >= self.threshold:
                self._open_hosts.add(host)
        else:
            self._consecutive[host] = 0
        return host in self._open_hosts

    @staticmethod
    def _host(url: str) -> str:
        return (urlsplit(url).hostname or "").lower()


def parse_retry_after_signal(value: str | None, *, now: datetime | None = None) -> int | None:
    if not value or len(value) > 128:
        return None
    candidate = value.strip()
    if candidate.isdigit():
        return min(int(candidate), MAX_RETRY_AFTER_SIGNAL_SECONDS)
    try:
        retry_at = parsedate_to_datetime(candidate)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        return min(
            max(0, int((retry_at - current).total_seconds())), MAX_RETRY_AFTER_SIGNAL_SECONDS
        )
    except (TypeError, ValueError, OverflowError):
        return None


def main_navigation_retry_after(network: list[dict[str, object]]) -> str | None:
    for row in network:
        if not row.get("is_main_navigation"):
            continue
        headers = row.get("response_headers_json")
        if isinstance(headers, dict):
            value = headers.get("retry-after")
            return value if isinstance(value, str) else None
    return None


def host_rate_limit_skip_result() -> CaptureResult:
    from app.browser.capture import CaptureResult

    return CaptureResult(
        state="skipped",
        error_type="host_rate_limit_circuit_open",
        error_message=(
            "Browser capture was not attempted because repeated rate-limit responses opened "
            "the host render circuit."
        ),
    )
