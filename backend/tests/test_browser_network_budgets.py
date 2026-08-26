import asyncio
import contextlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from app.browser.capture import BrowserRenderer, ObservedByteBudget
from app.browser.config import BROWSER_POLICY_VERSION, CAPTURE_SCHEMA_VERSION, RENDERER_VERSION
from app.crawler.scope import ScopeConfig


def test_observed_budget_reconciles_stream_events_with_loading_finished() -> None:
    budget = ObservedByteBudget(resource_limit=100, total_limit=175)
    assert budget.observe("a", 60) == set()
    assert budget.observe("a", 50) == {"resource_byte_budget_exceeded"}
    assert budget.finish("a", 125) == {"resource_byte_budget_exceeded"}
    assert budget.observe("b", 51) == {"total_network_budget_exceeded"}
    assert budget.total == 176
    assert budget.resources == {"a": 125, "b": 51}


def test_observed_bytes_override_any_declared_length() -> None:
    declared_content_length = 1
    budget = ObservedByteBudget(resource_limit=100, total_limit=1_000)
    assert declared_content_length < budget.resource_limit
    assert budget.observe("lying", 101) == {"resource_byte_budget_exceeded"}


def test_browser_budget_provenance_versions() -> None:
    assert BROWSER_POLICY_VERSION == "2"
    assert CAPTURE_SCHEMA_VERSION == "2"
    assert RENDERER_VERSION == "2"


class _BudgetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    bytes_written: dict[str, int] = {}
    part_requests = 0

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/under":
            self._body(b"<html><body><h1>Under budget</h1></body></html>", "text/html")
            return
        if path == "/rate-limited":
            self.send_response(429)
            self.send_header("Content-Type", "text/html")
            self.send_header("Retry-After", "120")
            body = b"<html><body><h1>Too many requests</h1></body></html>"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/no-content", "/reset-content"}:
            self.send_response(204 if path == "/no-content" else 205)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in {"/forbidden", "/missing", "/server-error", "/unavailable"}:
            status = {
                "/forbidden": 403,
                "/missing": 404,
                "/server-error": 500,
                "/unavailable": 503,
            }[path]
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            if status == 503:
                self.send_header("Retry-After", "60")
            body = f"<html><body><h1>HTTP {status}</h1></body></html>".encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/disconnect":
            self.close_connection = True
            self.connection.shutdown(2)
            self.connection.close()
            return
        if path in {"/chunked-page", "/honest-page", "/lying-page"}:
            resource = {
                "/chunked-page": "/chunked-stream",
                "/honest-page": "/honest-stream",
                "/lying-page": "/lying-stream",
            }[path]
            body = (
                "<html><body><script>"
                f"fetch('{resource}').then(response => response.arrayBuffer()).catch(() => null);"
                "</script></body></html>"
            )
            self._body(body.encode(), "text/html")
            return
        if path == "/aggregate":
            script = """
                <script>
                (async () => {
                  for (let i = 0; i < 20; i++) {
                    try { await fetch('/part?i=' + i); } catch (_) {}
                  }
                  document.body.dataset.aggregateDone = 'true';
                })();
                </script>
            """
            self._body(f"<html><body>{script}</body></html>".encode(), "text/html")
            return
        if path == "/part":
            type(self).part_requests += 1
            self._body(b"p" * 80_000, "application/octet-stream")
            return
        if path == "/honest-stream":
            self._stream(path, content_length=2_000_000)
            return
        if path == "/chunked-stream":
            self._stream(path, content_length=None)
            return
        if path == "/lying-stream":
            self._stream(path, content_length=1, chunked=True)
            return
        self.send_error(404)

    def _body(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, key: str, content_length: int | None, *, chunked: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        if content_length is None or chunked:
            self.send_header("Transfer-Encoding", "chunked")
        if content_length is not None:
            self.send_header("Content-Length", str(content_length))
        self.end_headers()
        chunk = b"x" * 8192
        type(self).bytes_written[key] = 0
        with contextlib.suppress(BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            while type(self).bytes_written[key] < 2_000_000:
                payload = (
                    f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n"
                    if content_length is None or chunked
                    else chunk
                )
                self.wfile.write(payload)
                self.wfile.flush()
                type(self).bytes_written[key] += len(chunk)
                time.sleep(0.002)
            if content_length is None or chunked:
                self.wfile.write(b"0\r\n\r\n")

    def log_message(self, *_args: object) -> None:
        return None


def _config(resource_limit: int = 100_000, total_limit: int = 1_000_000) -> ScopeConfig:
    return ScopeConfig(
        allowed_host_patterns=["127.0.0.1"],
        allow_private_networks=True,
        render_mode="starting_page",
        render_max_resource_bytes=resource_limit,
        render_max_total_network_bytes=total_limit,
        render_load_timeout_seconds=0,
        render_capture_full_page=False,
    )


@pytest.fixture
def budget_server():
    _BudgetHandler.bytes_written = {}
    _BudgetHandler.part_requests = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BudgetHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_chromium_under_budget_capture_retains_artifacts(budget_server: str) -> None:
    url = f"{budget_server}/under"
    async with BrowserRenderer(_config(), url) as renderer:
        result = await renderer.capture(url)
    assert result.state == "completed"
    assert result.total_network_bytes < 100_000
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "rendered_dom",
        "viewport_screenshot",
    }


@pytest.mark.asyncio
async def test_chromium_rate_limit_retains_evidence_without_page_artifacts(
    budget_server: str,
) -> None:
    url = f"{budget_server}/rate-limited"
    async with BrowserRenderer(_config(), url) as renderer:
        result = await renderer.capture(url)

    assert result.status == 429
    assert result.state == "failed"
    assert result.error_type == "navigation_rate_limited"
    assert result.artifacts == []
    navigation = next(row for row in result.network if row["is_main_navigation"])
    assert navigation["response_status"] == 429
    assert navigation["response_headers_json"]["retry-after"] == "120"


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "status"), [("/no-content", 204), ("/reset-content", 205)])
async def test_chromium_no_content_retains_status_without_page_artifacts(
    budget_server: str, path: str, status: int
) -> None:
    url = budget_server + path
    async with BrowserRenderer(_config(), url) as renderer:
        result = await renderer.capture(url)

    assert result.status == status
    assert result.state == "failed"
    assert result.error_type == "navigation_no_content"
    assert result.artifacts == []
    navigation = next(row for row in result.network if row["is_main_navigation"])
    assert navigation["response_status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "status", "error_type"),
    [
        ("/forbidden", 403, "navigation_http_client_error"),
        ("/missing", 404, "navigation_http_client_error"),
        ("/server-error", 500, "navigation_http_server_error"),
        ("/unavailable", 503, "navigation_http_server_error"),
    ],
)
async def test_chromium_http_errors_retain_status_without_page_artifacts(
    budget_server: str, path: str, status: int, error_type: str
) -> None:
    url = budget_server + path
    async with BrowserRenderer(_config(), url) as renderer:
        result = await renderer.capture(url)

    assert result.status == status
    assert result.state == "failed"
    assert result.error_type == error_type
    assert result.artifacts == []
    navigation = next(row for row in result.network if row["is_main_navigation"])
    assert navigation["response_status"] == status
    if status == 503:
        assert navigation["response_headers_json"]["retry-after"] == "60"


@pytest.mark.asyncio
async def test_chromium_navigation_exception_does_not_capture_partial_page_artifacts(
    budget_server: str,
) -> None:
    url = f"{budget_server}/disconnect"
    async with BrowserRenderer(_config(), url) as renderer:
        result = await renderer.capture(url)

    assert result.state == "failed"
    assert result.status is None
    assert result.error_type
    assert result.artifacts == []


@pytest.mark.asyncio
async def test_chromium_cancels_capture_with_route_callback_in_flight(
    budget_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    route_entered = asyncio.Event()

    async def stalled_destination_validation(*_args: object) -> None:
        route_entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "app.browser.capture.validate_public_destination",
        stalled_destination_validation,
    )
    url = f"{budget_server}/under"
    async with BrowserRenderer(_config(), url) as renderer:
        capture = asyncio.create_task(renderer.capture(url))
        await asyncio.wait_for(route_entered.wait(), timeout=5)
        capture.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(capture, timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page", "stream"),
    [
        ("/honest-page", "/honest-stream"),
        ("/chunked-page", "/chunked-stream"),
        ("/lying-page", "/lying-stream"),
    ],
)
async def test_chromium_stops_oversized_streams(budget_server: str, page: str, stream: str) -> None:
    url = budget_server + page
    async with BrowserRenderer(_config(), url) as renderer:
        result = await renderer.capture(url)
    warning_types = {item["type"] for item in result.warnings}
    assert "resource_byte_budget_exceeded" in warning_types
    assert result.total_network_bytes > 100_000
    assert result.state == "completed_with_warnings"
    assert _BudgetHandler.bytes_written[stream] < 2_000_000
    stream_rows = [row for row in result.network if row["redacted_url"].endswith(stream)]
    assert stream_rows[0]["encoded_data_length"] > 100_000


@pytest.mark.asyncio
async def test_chromium_total_budget_blocks_later_requests(budget_server: str) -> None:
    url = f"{budget_server}/aggregate"
    config = _config(resource_limit=100_000, total_limit=1_000_000)

    async def wait_for_aggregate(page: object) -> None:
        await page.wait_for_function("document.body.dataset.aggregateDone === 'true'")

    async with BrowserRenderer(config, url) as renderer:
        result = await renderer.capture(url, after_ready=wait_for_aggregate)
    warning_types = {item["type"] for item in result.warnings}
    assert "total_network_budget_exceeded" in warning_types
    assert result.total_network_bytes > 1_000_000
    assert _BudgetHandler.part_requests < 20
    assert result.state == "completed_with_warnings"
