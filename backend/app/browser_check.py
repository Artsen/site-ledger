import asyncio


async def check() -> int:
    try:
        import importlib.metadata

        from playwright.async_api import async_playwright

        print(f"Playwright package: {importlib.metadata.version('playwright')}")
    except Exception as exc:
        print(f"Playwright unavailable: {exc}\nInstall the project dependencies first.")
        return 1
    try:
        async with async_playwright() as runtime:
            browser = await runtime.chromium.launch(headless=True)
            print(f"Chromium launch: OK\nBrowser version: {browser.version}")
            await browser.close()
        return 0
    except Exception as exc:
        print(f"Chromium unavailable: {exc}\nRemediation: python -m playwright install chromium")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
