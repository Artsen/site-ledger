from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

from app.browser.config import BROWSER_POLICY_VERSION


def worker_browser_capability() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright

        version = importlib.metadata.version("playwright")
        with sync_playwright() as runtime:
            executable = Path(runtime.chromium.executable_path)
            result: dict[str, Any] = {
                "engine": "chromium",
                "playwright_version": version,
                "chromium_installed": executable.is_file(),
                "browser_policy_version": BROWSER_POLICY_VERSION,
            }
            if executable.is_file():
                browser = runtime.chromium.launch(headless=True)
                result["browser_version"] = browser.version
                browser.close()
            return result
    except Exception as exc:
        return {"engine": "chromium", "chromium_installed": False, "error": type(exc).__name__}
