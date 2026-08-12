from __future__ import annotations

import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class FixtureState:
    def __init__(self, state_path: Path, request_log_path: Path) -> None:
        self.state_path = state_path
        self.request_log_path = request_log_path
        self.lock = threading.Lock()

    def version(self) -> int:
        return int(self.state_path.read_text(encoding="ascii").strip())

    def set_version(self, version: int) -> None:
        with self.lock:
            self.state_path.write_text(f"{version}\n", encoding="ascii")

    def log_request(self, method: str, path: str, user_agent: str) -> None:
        entry = {
            "method": method,
            "path": path,
            "user_agent": user_agent,
            "version": self.version(),
        }
        with self.lock, self.request_log_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(entry, sort_keys=True) + "\n")


class FixtureHandler(BaseHTTPRequestHandler):
    server: FixtureServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        self.server.state.log_request("GET", path, self.headers.get("User-Agent", ""))
        if path == "/__fixture__/health":
            self._json({"status": "ok", "version": self.server.state.version()})
            return
        if path == "/__fixture__/status":
            self._json({"version": self.server.state.version()})
            return
        if path == "/assets/runtime.js":
            self._send(
                HTTPStatus.OK,
                b'window.fixtureRuntime = "stable";\n',
                "application/javascript; charset=utf-8",
            )
            return
        html = fixture_page(path, self.server.state.version())
        if html is None:
            self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")
            return
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        self.server.state.log_request("POST", path, self.headers.get("User-Agent", ""))
        if path not in {"/__fixture__/version/1", "/__fixture__/version/2"}:
            self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")
            return
        version = int(path.rsplit("/", 1)[1])
        self.server.state.set_version(version)
        self._json({"version": version})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} {format % args}", flush=True)

    def _json(self, value: dict[str, object]) -> None:
        self._send(
            HTTPStatus.OK,
            json.dumps(value, sort_keys=True).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class FixtureServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: FixtureState) -> None:
        super().__init__(address, FixtureHandler)
        self.state = state


def fixture_page(path: str, version: int) -> str | None:
    if path == "/":
        copy = "Version one product copy." if version == 1 else "Version two product copy."
        new_link = '\n      <li><a href="/new/">New</a></li>' if version == 2 else ""
        return _document(
            "Golden Path Home",
            f"""<main>
    <h1>Fixture Product</h1>
    <h2>Overview</h2>
    <p>{copy}</p>
    <nav aria-label="Fixture pages"><ul>
      <li><a href="/pricing/">Pricing</a></li>
      <li><a href="/technical/">Technical</a></li>
      <li><a href="/unchanged/">Unchanged</a></li>{new_link}
    </ul></nav>
  </main>""",
        )
    if path == "/pricing/":
        title = "Pricing" if version == 1 else "Pricing &amp; Plans"
        return _document(title, "<main><h1>Pricing</h1><p>Plans start at ten dollars.</p></main>")
    if path == "/technical/":
        return _document(
            "Technical Fixture",
            "<main><h1>Technical Fixture</h1><p>Stable technical page.</p></main>",
            head=f'<script src="/assets/runtime.js?build={version}"></script>',
        )
    if path == "/unchanged/":
        return _document(
            "Stable Page",
            "<main><h1>Stable Page</h1><p>This page does not change.</p></main>",
        )
    if path == "/new/" and version == 2:
        return _document(
            "New Fixture Page",
            "<main><h1>New Fixture Page</h1><p>Introduced in version two.</p></main>",
        )
    return None


def _document(title: str, body: str, *, head: str = "") -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        f'<head><meta charset="utf-8"><title>{title}</title>{head}</head>\n'
        f"<body>{body}</body>\n"
        "</html>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the deterministic Golden Path website.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--request-log", type=Path, required=True)
    args = parser.parse_args()
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.request_log.parent.mkdir(parents=True, exist_ok=True)
    if not args.state.exists():
        args.state.write_text("1\n", encoding="ascii")
    server = FixtureServer(("127.0.0.1", args.port), FixtureState(args.state, args.request_log))
    print(f"fixture ready on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
