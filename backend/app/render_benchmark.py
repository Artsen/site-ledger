"""Run a small, local, bounded rendered-capture benchmark."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.browser.capture import BrowserRenderer
from app.crawler.scope import ScopeConfig


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if self.path.startswith("/asset-"):
            body = b"fixture asset" * 100
            self._send(body, "application/octet-stream")
            return
        assets = "".join(f'<img src="/asset-{index}">' for index in range(20))
        body = (
            "<html><head><title>Rendered benchmark</title></head><body>"
            f"{assets}<div id='delayed'></div><script>"
            "console.log('benchmark-ready'); console.error('fixture-console-error');"
            "setTimeout(() => document.querySelector('#delayed').textContent='ready', 100);"
            "</script></body></html>"
        ).encode()
        self._send(body, "text/html; charset=utf-8")

    def _send(self, body: bytes, media_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


async def run() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    config = ScopeConfig(
        allowed_host_patterns=["127.0.0.1"],
        allow_private_networks=True,
        max_redirects=3,
        render_mode="starting_page",
        render_max_page_duration_seconds=15,
    )
    try:
        async with BrowserRenderer(config, url) as renderer:
            result = await renderer.capture(url)
        print(
            json.dumps(
                {
                    "capture_state": result.state,
                    "duration_ms": result.duration_ms,
                    "network_entries": len(result.network),
                    "observed_network_bytes": result.total_network_bytes,
                    "console_messages": len(result.console),
                    "page_errors": len(result.page_errors),
                    "artifact_count": len(result.artifacts),
                    "artifact_bytes": sum(len(item.content) for item in result.artifacts),
                },
                indent=2,
            )
        )
    finally:
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
