from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.static_crawler import CrawlItem, StaticPageCrawler
from app.crawler.url_normalizer import NormalizedUrl
from app.database import Base
from app.models import ResourceSnapshot, Scan, WebResource
from app.services.repositories import get_or_create_resource
from app.storage.content_store import LocalContentStore

PAGE_COUNT = 60
DUPLICATE_LINKS_PER_PAGE = 40
TRANSIENT_PAGE = 10


class LegacyStaticPageCrawler(StaticPageCrawler):
    async def _fetch_one(
        self,
        scan: Scan,
        item: CrawlItem,
        config: ScopeConfig,
        scope: ScopeEngine,
        client: httpx.AsyncClient | None,
    ) -> tuple[ResourceSnapshot, list[Any], list[Any]]:
        return await super()._fetch_one(scan, item, config, scope, None)

    def _resource(self, normalized: NormalizedUrl) -> WebResource:
        return get_or_create_resource(self.db, normalized)


async def _run_case(root: Path, *, legacy: bool) -> dict[str, Any]:
    attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        attempts[path] = attempts.get(path, 0) + 1
        index = int(path.rsplit("/", 1)[-1])
        if index == TRANSIENT_PAGE and attempts[path] == 1:
            raise httpx.ConnectTimeout("synthetic transient timeout", request=request)
        next_index = index + 1
        links = ""
        if next_index < PAGE_COUNT:
            links = "".join(
                f'<a href="/page/{next_index}">Next</a>' for _ in range(DUPLICATE_LINKS_PER_PAGE)
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=f"<html><body>{links}</body></html>".encode(),
        )

    engine = create_engine(
        f"sqlite:///{root / ('legacy.db' if legacy else 'optimized.db')}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as db:
        scan = Scan(
            starting_url="http://fixture.test/page/0",
            status="queued",
            scope_config=ScopeConfig(
                allowed_host_patterns=["fixture.test"],
                allow_private_networks=True,
                max_pages=PAGE_COUNT,
                max_depth=PAGE_COUNT,
                static_max_attempts=2,
                static_retry_initial_delay_ms=0,
                static_retry_max_delay_ms=0,
            ).to_dict(),
        )
        db.add(scan)
        db.commit()
        crawler_type = LegacyStaticPageCrawler if legacy else StaticPageCrawler
        started = time.perf_counter()
        await crawler_type(
            db,
            LocalContentStore(root / ("legacy-html" if legacy else "optimized-html")),
            transport=httpx.MockTransport(handler),
        ).run(scan)
        elapsed_ms = (time.perf_counter() - started) * 1000
        crawled_urls = set(
            db.scalars(
                select(ResourceSnapshot.requested_url).where(ResourceSnapshot.scan_id == scan.id)
            )
        )
        result = {
            "mode": "legacy_new_client_uncached_resources" if legacy else "pooled_cached",
            "elapsed_ms": round(elapsed_ms, 2),
            "pages": scan.fetched_count,
            "attempts": scan.static_request_attempt_count,
            "retry_requests": scan.static_retry_request_count,
            "recovered": scan.static_recovered_after_retry_count,
            "exhausted": scan.static_retry_exhausted_count,
            "retry_discovered_page_crawled": (
                f"http://fixture.test/page/{TRANSIENT_PAGE + 1}" in crawled_urls
            ),
        }
    engine.dispose()
    return result


async def _main() -> None:
    with tempfile.TemporaryDirectory(prefix="site-ledger-static-benchmark-") as directory:
        root = Path(directory)
        before = await _run_case(root, legacy=True)
        after = await _run_case(root, legacy=False)
        before_ms = float(before["elapsed_ms"])
        after_ms = float(after["elapsed_ms"])
        speedup = round(before_ms / after_ms, 2) if after_ms else None
        print(json.dumps({"before": before, "after": after, "speedup": speedup}, indent=2))


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
