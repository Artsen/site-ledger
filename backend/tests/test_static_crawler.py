import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from app.crawler.safe_fetch import connect_error_type
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticPageCrawler, _retry_after_ms
from app.models import (
    ContentBlob,
    HtmlParseArtifact,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    SitePage,
    StaticFetchAttempt,
    WebsiteProperty,
)
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


def fixture_transport() -> httpx.ASGITransport:
    app = Starlette(
        routes=[
            Route("/", home),
            Route("/about", about),
            Route("/missing", missing),
            Route("/error", error),
            Route("/file.txt", text),
            Route("/relative-redirect", lambda request: RedirectResponse("/about")),
        ]
    )
    return httpx.ASGITransport(app=app)


@pytest.mark.asyncio
async def test_saved_site_failed_observation_creates_site_page(db_session, tmp_path) -> None:
    site = WebsiteProperty(
        name="Fixture",
        base_url="http://fixture.test/",
        normalized_base_url="http://fixture.test/",
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    db_session.add(site)
    db_session.flush()
    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=1,
            static_retry_initial_delay_ms=0,
            static_retry_max_delay_ms=0,
        ),
        website_property_id=site.id,
    )

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(fail),
    ).run(scan)

    snapshot = db_session.query(ResourceSnapshot).one()
    site_page = db_session.query(SitePage).one()
    assert snapshot.fetch_state == "failed"
    assert site_page.resource_id == snapshot.resource_id
    assert site_page.website_property_id == site.id


@pytest.mark.asyncio
async def test_transient_failure_is_retried_after_the_crawl(db_session, tmp_path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("temporary timeout", request=request)
        return httpx.Response(
            200,
            content=b"<html><body><a href='/next'>Next</a></body></html>",
            headers={"content-type": "text/html"},
        )

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=1,
        ),
    )
    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(handler),
    ).run(scan)

    snapshot = db_session.query(ResourceSnapshot).one()
    assert attempts == 2
    assert snapshot.fetch_state == "fetched"
    assert snapshot.error_type is None
    assert scan.failed_count == 0
    assert scan.status == "completed"
    attempts = (
        db_session.query(StaticFetchAttempt).order_by(StaticFetchAttempt.attempt_number).all()
    )
    assert [(attempt.outcome, attempt.error_type) for attempt in attempts] == [
        ("failed", "connection_timeout"),
        ("succeeded", None),
    ]
    assert attempts[0].retryable is True
    assert scan.static_request_attempt_count == 2
    assert scan.static_retry_request_count == 1
    assert scan.static_recovered_after_retry_count == 1
    assert scan.static_retry_exhausted_count == 0
    assert (
        db_session.query(ResourceOccurrence).filter_by(source_snapshot_id=snapshot.id).count() == 1
    )


@pytest.mark.asyncio
async def test_successful_retry_resumes_discovery(db_session, tmp_path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/" and requests.count("/") == 1:
            raise httpx.ConnectTimeout("temporary timeout", request=request)
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=b"<html><body><a href='/b'>B</a></body></html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(
            200,
            content=b"<html><body>B</body></html>",
            headers={"content-type": "text/html"},
        )

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=2,
            max_depth=1,
            static_retry_initial_delay_ms=0,
            static_retry_max_delay_ms=0,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    snapshots = db_session.query(ResourceSnapshot).order_by(ResourceSnapshot.crawl_depth).all()
    assert requests == ["/", "/", "/b"]
    assert [snapshot.requested_url for snapshot in snapshots] == [
        "http://fixture.test/",
        "http://fixture.test/b",
    ]
    assert scan.discovered_count == 2
    assert scan.fetched_count == 2
    assert scan.static_request_attempt_count == 3
    assert scan.static_recovered_after_retry_count == 1


@pytest.mark.asyncio
async def test_exhausted_retry_preserves_every_attempt(db_session, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("x" * 9000, request=request)

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=1,
            static_retry_initial_delay_ms=0,
            static_retry_max_delay_ms=0,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    snapshot = db_session.query(ResourceSnapshot).one()
    attempts = (
        db_session.query(StaticFetchAttempt).order_by(StaticFetchAttempt.attempt_number).all()
    )
    assert snapshot.fetch_state == "failed"
    assert snapshot.error_type == "connection_timeout"
    assert scan.failed_count == 1
    assert scan.static_retry_exhausted_count == 1
    assert len(attempts) == 2
    assert all(attempt.retryable for attempt in attempts)
    assert all(len(attempt.error_message or "") == 8000 for attempt in attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 425, 429, 502, 503, 504])
async def test_temporary_http_status_is_retried(status, db_session, tmp_path) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                status,
                headers={"content-type": "text/html", "retry-after": "0"},
                content=b"<html>temporary</html>",
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>ok</html>"
        )

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=1,
            static_retry_initial_delay_ms=0,
            static_retry_max_delay_ms=0,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    rows = db_session.query(StaticFetchAttempt).order_by(StaticFetchAttempt.attempt_number).all()
    assert attempts == 2
    assert [row.retrieval_http_status for row in rows] == [status, 200]
    assert rows[0].retry_reason == f"http_{status}"
    assert scan.static_recovered_after_retry_count == 1


@pytest.mark.asyncio
async def test_certificate_failure_is_not_retried(db_session, tmp_path) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise httpx.ConnectError("certificate verify failed", request=request)

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=1,
            static_retry_initial_delay_ms=0,
            static_retry_max_delay_ms=0,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    attempt = db_session.query(StaticFetchAttempt).one()
    assert requests == 1
    assert attempt.error_type == "certificate_validation_error"
    assert attempt.retryable is False
    assert scan.static_retry_request_count == 0


@pytest.mark.asyncio
async def test_shared_client_does_not_replay_response_cookies(db_session, tmp_path) -> None:
    observed_cookie: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_cookie
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html", "set-cookie": "session=secret"},
                content=b"<html><a href='/next'>Next</a></html>",
            )
        observed_cookie = request.headers.get("cookie")
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>next</html>"
        )

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=2,
            max_depth=1,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    assert observed_cookie is None
    first = (
        db_session.query(ResourceSnapshot)
        .filter(ResourceSnapshot.requested_url == "http://fixture.test/")
        .one()
    )
    assert "set-cookie" not in (first.response_headers or {})


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("certificate verify failed", "certificate_validation_error"),
        ("TLSV1 alert protocol version", "tls_configuration_error"),
        ("unexpected EOF while reading", "transient_tls_disconnect"),
        ("connection reset by peer", "connection_reset"),
        ("getaddrinfo failed", "dns_error"),
    ],
)
def test_transport_error_classification(message, expected) -> None:
    assert connect_error_type(httpx.ConnectError(message)) == expected


def test_retry_after_is_capped() -> None:
    assert _retry_after_ms({"Retry-After": "120"}, 5000) == 5000


@pytest.mark.asyncio
async def test_complete_fixture_crawl(db_session, tmp_path) -> None:
    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            excluded_path_prefixes=["/private/"],
            drop_query_parameters=["utm_*"],
            max_pages=10,
            max_depth=2,
            allow_private_networks=True,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=fixture_transport()
    ).run(scan)

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


@pytest.mark.asyncio
async def test_same_host_relative_redirect_succeeds_and_chain_is_saved(
    db_session, tmp_path
) -> None:
    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            max_pages=1,
            allow_private_networks=True,
        ),
        starting_url="http://fixture.test/relative-redirect",
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=fixture_transport()
    ).run(scan)

    snapshot = db_session.query(ResourceSnapshot).one()
    assert snapshot.fetch_state == "fetched"
    assert snapshot.final_url == "http://fixture.test/about"
    assert snapshot.redirect_chain == [
        {
            "requested_url": "http://fixture.test/relative-redirect",
            "status_code": 307,
            "location": "/about",
            "resolved_url": "http://fixture.test/about",
        }
    ]


@pytest.mark.asyncio
async def test_redirect_leaving_scope_is_not_requested(db_session, tmp_path) -> None:
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "fixture.test":
            return httpx.Response(302, headers={"location": "https://outside.test/"})
        return httpx.Response(200, text="should not be requested")

    scan = _scan(
        db_session,
        ScopeConfig(allowed_host_patterns=["fixture.test"], allow_private_networks=True),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    snapshot = db_session.query(ResourceSnapshot).one()
    assert requested == ["http://fixture.test/"]
    assert snapshot.error_type == "scope_excluded"
    assert snapshot.redirect_chain[0]["resolved_url"] == "https://outside.test/"


@pytest.mark.asyncio
async def test_redirect_to_loopback_is_not_requested(monkeypatch, db_session, tmp_path) -> None:
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    async def validate(url: str, allow_private_networks: bool = False) -> None:
        if "127.0.0.1" in url:
            from app.crawler.security import UnsafeDestinationError

            raise UnsafeDestinationError("Destination IP is not public: 127.0.0.1")

    monkeypatch.setattr("app.crawler.static_crawler.validate_public_destination", validate)
    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test", "127.0.0.1"],
            allow_private_networks=False,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    snapshot = db_session.query(ResourceSnapshot).one()
    assert requested == ["http://fixture.test/"]
    assert snapshot.error_type == "unsafe_destination"


@pytest.mark.asyncio
async def test_redirect_loop_and_limit_are_categorized(db_session, tmp_path) -> None:
    async def loop_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/"})

    loop_scan = _scan(
        db_session,
        ScopeConfig(allowed_host_patterns=["fixture.test"], allow_private_networks=True),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(loop_handler)
    ).run(loop_scan)
    assert db_session.query(ResourceSnapshot).filter_by(scan_id=loop_scan.id).one().error_type == (
        "redirect_loop"
    )

    async def chain_handler(request: httpx.Request) -> httpx.Response:
        next_id = int(request.url.path.strip("/") or "0") + 1
        return httpx.Response(302, headers={"location": f"/{next_id}"})

    limit_scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_redirects=1,
        ),
        starting_url="http://fixture.test/0",
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(chain_handler)
    ).run(limit_scan)
    assert db_session.query(ResourceSnapshot).filter_by(scan_id=limit_scan.id).one().error_type == (
        "too_many_redirects"
    )


@pytest.mark.asyncio
async def test_invalid_redirect_location_is_handled(db_session, tmp_path) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://%/"})

    scan = _scan(
        db_session,
        ScopeConfig(allowed_host_patterns=["fixture.test"], allow_private_networks=True),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)
    assert db_session.query(ResourceSnapshot).one().error_type == "invalid_url"


@pytest.mark.asyncio
async def test_response_size_limits_are_enforced_while_streaming(db_session, tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=(
                    b"<html><head><title>Home</title></head>"
                    b"<a href='/declared-large'>D</a><a href='/chunked-large'>C</a>"
                ),
                headers={"content-type": "text/html"},
            )
        if request.url.path == "/declared-large":
            return httpx.Response(200, headers={"content-length": "121"}, content=b"")
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>" + b"x" * 140
        )

    scan = _scan(
        db_session,
        ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_html_response_bytes=120,
            max_pages=3,
            max_depth=1,
        ),
    )
    await StaticPageCrawler(
        db_session, LocalContentStore(tmp_path), transport=httpx.MockTransport(handler)
    ).run(scan)

    oversized = (
        db_session.query(ResourceSnapshot)
        .filter(ResourceSnapshot.error_type == "response_too_large")
        .all()
    )
    assert scan.status == "completed_with_errors"
    assert len(oversized) == 2
    assert all(snapshot.html_blob_id is None for snapshot in oversized)
    assert db_session.query(ContentBlob).count() == 1


@pytest.mark.asyncio
async def test_repeat_scan_revalidates_and_reuses_parse_artifact(db_session, tmp_path) -> None:
    requests: list[httpx.Request] = []
    html = b"""
      <html><head><title>Cached</title><link rel="canonical" href="/canonical"></head>
      <body><a href="/next">Next</a></body></html>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(
                304,
                headers={
                    "etag": '"v1"',
                    "last-modified": "Wed, 05 Aug 2026 00:00:00 GMT",
                },
            )
        return httpx.Response(
            200,
            content=html,
            headers={
                "content-type": "text/html; charset=utf-8",
                "etag": '"v1"',
                "last-modified": "Wed, 05 Aug 2026 00:00:00 GMT",
            },
        )

    store = LocalContentStore(tmp_path)
    config = ScopeConfig(
        allowed_host_patterns=["fixture.test"],
        allow_private_networks=True,
        max_pages=1,
    )
    first = _scan(db_session, config)
    await StaticPageCrawler(db_session, store, transport=httpx.MockTransport(handler)).run(first)
    second = _scan(db_session, config)
    await StaticPageCrawler(db_session, store, transport=httpx.MockTransport(handler)).run(second)

    snapshots = db_session.query(ResourceSnapshot).order_by(ResourceSnapshot.id).all()
    assert len(snapshots) == 2
    assert snapshots[0].retrieval_method == "full_fetch"
    assert snapshots[0].parse_method == "parsed"
    assert snapshots[1].retrieval_method == "conditional_not_modified"
    assert snapshots[1].parse_method == "reused_not_modified"
    assert snapshots[1].retrieval_http_status == 304
    assert snapshots[1].http_status == 200
    assert snapshots[1].html_blob_id == snapshots[0].html_blob_id
    assert snapshots[1].parse_artifact_id == snapshots[0].parse_artifact_id
    assert snapshots[1].reused_from_snapshot_id == snapshots[0].id
    assert second.conditional_request_count == 1
    assert second.not_modified_count == 1
    assert second.parse_reuse_count == 1
    assert second.network_bytes_transferred == 0
    assert (
        db_session.query(ResourceOccurrence).filter_by(source_snapshot_id=snapshots[1].id).count()
        == 1
    )
    assert db_session.query(ContentBlob).count() == 1
    assert db_session.query(HtmlParseArtifact).count() == 1
    assert requests[-1].headers["if-none-match"] == '"v1"'


def _scan(
    db_session,
    config: ScopeConfig,
    starting_url: str = "http://fixture.test/",
    website_property_id: int | None = None,
) -> Scan:
    scan = Scan(
        starting_url=starting_url,
        status="queued",
        scope_config=config.to_dict(),
        website_property_id=website_property_id,
    )
    db_session.add(scan)
    db_session.commit()
    return scan
