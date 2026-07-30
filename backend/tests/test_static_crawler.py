from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient, Response
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticPageCrawler
from app.models import ContentBlob, ResourceOccurrence, ResourceSnapshot, Scan
from app.storage.content_store import LocalContentStore


async def home(_request):
    return HTMLResponse(
        """
        <html><head><title>Home</title><meta name="description" content="Home desc"></head><body>
          <a href="/about?utm_source=x&a=1#fragment">About</a>
          <a href="/about?a=1">About duplicate</a>
          <a href="/missing">Missing</a>
          <a href="/error">Error</a>
          <a href="/private/hidden">Excluded</a>
          <a href="https://external.test/">External</a>
          <a href="/file.txt">File</a>
        </body></html>
        """
    )


async def about(_request):
    return HTMLResponse("<html><head><title>About</title></head><body><a href='/broken'>Broken")


async def missing(_request):
    return HTMLResponse("<html><head><title>Missing</title></head></html>", status_code=404)


async def error(_request):
    return HTMLResponse("<html><head><title>Error</title></head></html>", status_code=500)


async def text(_request):
    return PlainTextResponse("not html")


@pytest.fixture
async def fixture_client() -> AsyncIterator[AsyncClient]:
    app = Starlette(
        routes=[
            Route("/", home),
            Route("/about", about),
            Route("/missing", missing),
            Route("/error", error),
            Route("/file.txt", text),
            Route("/redirect", lambda request: RedirectResponse("/about")),
        ]
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://fixture.test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_complete_fixture_crawl(monkeypatch, db_session, tmp_path, fixture_client) -> None:
    async def fake_get(self, url, *args, **kwargs) -> Response:
        request = fixture_client.build_request("GET", url)
        return await fixture_client.send(request, follow_redirects=True)

    async def fake_validate(url: str, allow_private_networks: bool = False) -> None:
        return None

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.crawler.static_crawler.validate_public_destination", fake_validate)
    scan = Scan(
        starting_url="http://fixture.test/",
        status="queued",
        scope_config=ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            excluded_path_prefixes=["/private/"],
            drop_query_parameters=["utm_*"],
            max_pages=10,
            max_depth=2,
            allow_private_networks=True,
        ).to_dict(),
    )
    db_session.add(scan)
    db_session.commit()
    await StaticPageCrawler(db_session, LocalContentStore(tmp_path)).run(scan)

    snapshots = db_session.query(ResourceSnapshot).all()
    occurrences = db_session.query(ResourceOccurrence).all()
    assert scan.status == "completed_with_errors"
    assert {snapshot.http_status for snapshot in snapshots} >= {200, 404, 500}
    assert db_session.query(ContentBlob).count() >= 3
    assert (
        len(
            [
                occ
                for occ in occurrences
                if occ.normalized_target_url == "http://fixture.test/about?a=1"
            ]
        )
        == 2
    )
    assert any(occ.scope_decision == "excluded_path" for occ in occurrences)
    assert any(occ.scope_decision == "external" for occ in occurrences)
