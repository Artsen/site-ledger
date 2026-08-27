from starlette.requests import Request
from starlette.responses import Response

from app.api.routes import _projection_http_response
from app.schemas.projections import ProjectionMetadata
from app.schemas.scans import PageList


def _request(query: str = "", etag: str | None = None) -> Request:
    headers = [(b"if-none-match", etag.encode())] if etag else []
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/scans/1/pages",
            "raw_path": b"/api/scans/1/pages",
            "query_string": query.encode(),
            "headers": headers,
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )


def _result(source: str = "materialized", build_id: int | None = 9) -> PageList:
    return PageList(
        items=[],
        total=0,
        limit=50,
        offset=0,
        projection=ProjectionMetadata(
            projection_source=source,
            projection_version="scan-projection-v2",
            projection_build_id=build_id,
            projection_status="ready" if source == "materialized" else "not_terminal",
        ),
    )


def test_projection_response_sets_deterministic_private_etag() -> None:
    first_response = Response()
    first = _projection_http_response(_request("limit=50"), first_response, _result())
    second_response = Response()
    second = _projection_http_response(_request("limit=50"), second_response, _result())

    assert first is not None and second is not None
    assert first_response.headers["cache-control"] == "private, no-cache"
    assert first_response.headers["etag"] == second_response.headers["etag"]
    assert first_response.headers["x-projection-source"] == "materialized"


def test_matching_projection_etag_returns_304_and_query_changes_etag() -> None:
    initial_response = Response()
    _projection_http_response(_request("limit=50"), initial_response, _result())
    etag = initial_response.headers["etag"]

    matched = _projection_http_response(_request("limit=50", etag), Response(), _result())
    changed_response = Response()
    _projection_http_response(_request("limit=25"), changed_response, _result())

    assert isinstance(matched, Response) and matched.status_code == 304
    assert matched.headers["etag"] == etag
    assert changed_response.headers["etag"] != etag


def test_dynamic_response_does_not_claim_immutable_http_semantics() -> None:
    response = Response()

    result = _projection_http_response(
        _request(), response, _result(source="dynamic", build_id=None)
    )

    assert isinstance(result, PageList)
    assert "etag" not in response.headers
    assert response.headers["x-projection-source"] == "dynamic"


def test_mutable_overlay_response_keeps_projection_headers_without_etag() -> None:
    response = Response()

    result = _projection_http_response(
        _request(etag='"stale-page-validator"'),
        response,
        _result(),
        immutable=False,
    )

    assert isinstance(result, PageList)
    assert "etag" not in response.headers
    assert response.headers["x-projection-source"] == "materialized"
    assert response.headers["x-projection-build-id"] == "9"
