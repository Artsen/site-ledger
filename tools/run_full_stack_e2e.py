from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


class Child:
    def __init__(
        self, name: str, command: list[str], cwd: Path, env: dict[str, str], log: Path
    ) -> None:
        self.name = name
        self.log = log
        self.output: IO[str] = log.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=self.output,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.output.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Site Ledger's disposable full-stack Golden Path."
    )
    parser.add_argument("--artifacts-dir", type=Path, default=ROOT / "golden-path-artifacts")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--expected-target-copy", default="Version two product copy.")
    args = parser.parse_args()
    workspace = Path(tempfile.mkdtemp(prefix="site-ledger-golden-path-"))
    logs = workspace / "logs"
    logs.mkdir()
    manifest_path = workspace / "manifest.json"
    result_path = workspace / "browser-result.json"
    request_log = workspace / "fixture-requests.jsonl"
    state_path = workspace / "fixture-state.txt"
    children: list[Child] = []
    started = time.monotonic()
    workspace_id = str(uuid.uuid4())
    fixture_port, backend_port, frontend_port = _free_ports(3)
    fixture_url = f"http://127.0.0.1:{fixture_port}"
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    manifest: dict[str, Any] = {
        "workspace_id": workspace_id,
        "workspace": str(workspace),
        "ports": {"fixture": fixture_port, "backend": backend_port, "frontend": frontend_port},
        "urls": {"fixture": fixture_url, "backend": backend_url, "frontend": frontend_url},
        "status": "starting",
    }
    python_env = os.environ.copy()
    python_env.update(
        {
            "SCANNER_DATABASE_URL": f"sqlite:///{(workspace / 'site-ledger.db').as_posix()}",
            "SCANNER_HTML_STORAGE_ROOT": str(workspace / "html"),
            "SCANNER_AI_DOCUMENT_STORAGE_ROOT": str(workspace / "ai-documents"),
            "SCANNER_RENDERED_ARTIFACT_STORAGE_ROOT": str(workspace / "rendered"),
            "SCANNER_CORS_ORIGINS": json.dumps([frontend_url]),
            "SCANNER_WORKER_POLL_INTERVAL_SECONDS": "0.1",
            "SCANNER_WORKER_HEARTBEAT_INTERVAL_SECONDS": "0.5",
            "SCANNER_WORKER_OFFLINE_AFTER_SECONDS": "5",
        }
    )
    try:
        _run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=python_env,
            log=logs / "migration.log",
        )
        children.append(
            Child(
                "fixture",
                [
                    sys.executable,
                    str(ROOT / "tools" / "full_stack" / "fixture_server.py"),
                    "--port",
                    str(fixture_port),
                    "--state",
                    str(state_path),
                    "--request-log",
                    str(request_log),
                ],
                ROOT,
                python_env,
                logs / "fixture.log",
            )
        )
        children.append(
            Child(
                "backend",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(backend_port),
                ],
                BACKEND,
                python_env,
                logs / "backend.log",
            )
        )
        children.append(
            Child(
                "worker",
                [
                    sys.executable,
                    "-m",
                    "app.worker",
                    "--worker-id",
                    "golden-path-worker",
                    "--concurrency",
                    "1",
                ],
                BACKEND,
                python_env,
                logs / "worker.log",
            )
        )
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is not available on PATH")
        frontend_env = os.environ.copy()
        frontend_env["VITE_API_BASE_URL"] = backend_url
        children.append(
            Child(
                "frontend",
                [
                    node,
                    str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(frontend_port),
                    "--strictPort",
                ],
                FRONTEND,
                frontend_env,
                logs / "frontend.log",
            )
        )
        _wait_json(f"{fixture_url}/__fixture__/health", children)
        _wait_json(f"{backend_url}/api/health", children)
        _wait_url(frontend_url, children)
        _wait_worker(f"{backend_url}/api/jobs/worker-health", children)
        test_env = os.environ.copy()
        test_env.update(
            {
                "GOLDEN_PATH_API_URL": backend_url,
                "GOLDEN_PATH_APP_URL": frontend_url,
                "GOLDEN_PATH_FIXTURE_URL": fixture_url,
                "GOLDEN_PATH_RESULT_PATH": str(result_path),
                "GOLDEN_PATH_WORKSPACE_ID": workspace_id,
                "GOLDEN_PATH_EXPECTED_TARGET_COPY": args.expected_target_copy,
                "GOLDEN_PATH_OUTPUT_DIR": str(workspace / "test-results"),
                "GOLDEN_PATH_REPORT_DIR": str(workspace / "playwright-report"),
            }
        )
        _run(
            [
                node,
                str(FRONTEND / "node_modules" / "@playwright" / "test" / "cli.js"),
                "test",
                "--config",
                "playwright.full-stack.config.ts",
            ],
            cwd=FRONTEND,
            env=test_env,
            log=logs / "playwright.log",
        )
        _run(
            [
                sys.executable,
                str(ROOT / "tools" / "full_stack" / "verify_run.py"),
                "--result",
                str(result_path),
                "--request-log",
                str(request_log),
                "--manifest",
                str(manifest_path),
            ],
            cwd=BACKEND,
            env=python_env,
            log=logs / "verification.log",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {"status": "passed", "duration_seconds": round(time.monotonic() - started, 3)}
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
    except BaseException as exc:
        manifest.update(
            {
                "status": "failed",
                "duration_seconds": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _copy_diagnostics(workspace, args.artifacts_dir)
        raise
    finally:
        for child in reversed(children):
            child.stop()
        if not args.keep_workspace:
            shutil.rmtree(workspace)
        else:
            print(f"Golden Path workspace: {workspace}", file=sys.stderr)


def _free_ports(count: int) -> list[int]:
    reservations = [socket.socket() for _ in range(count)]
    try:
        for reservation in reservations:
            reservation.bind(("127.0.0.1", 0))
        return [int(reservation.getsockname()[1]) for reservation in reservations]
    finally:
        for reservation in reservations:
            reservation.close()


def _run(command: list[str], *, cwd: Path, env: dict[str, str], log: Path) -> None:
    with log.open("w", encoding="utf-8") as output:
        completed = subprocess.run(
            command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, text=True
        )
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{_tail(log)}"
        )


def _wait_url(url: str, children: list[Child], timeout: float = 45) -> bytes:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        for child in children:
            if child.process.poll() is not None:
                raise RuntimeError(
                    f"{child.name} exited early ({child.process.returncode})\n{_tail(child.log)}"
                )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read()
        except Exception as exc:  # Readiness retries intentionally include transient HTTP errors.
            last_error = exc
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def _wait_json(url: str, children: list[Child]) -> dict[str, Any]:
    return json.loads(_wait_url(url, children))


def _wait_worker(url: str, children: list[Child]) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = _wait_json(url, children)
        if int(value.get("online_workers", 0)) > 0:
            return
        time.sleep(0.25)
    raise TimeoutError("Worker did not register before the readiness deadline")


def _tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _copy_diagnostics(workspace: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / workspace.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(workspace, target)


if __name__ == "__main__":
    main()
