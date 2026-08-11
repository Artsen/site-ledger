from starlette.requests import Request
from starlette.responses import Response

from app.api.comparison_routes import _immutable_response


def _request(query: str = "", etag: str | None = None) -> Request:
    headers = [(b"if-none-match", etag.encode())] if etag else []
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/sites/1/comparisons/2/pages",
            "raw_path": b"/api/sites/1/comparisons/2/pages",
            "query_string": query.encode(),
            "headers": headers,
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )


def test_ready_comparison_response_has_build_specific_private_etag() -> None:
    first_response = Response()
    result = _immutable_response(_request("limit=50"), first_response, {"items": []}, 9)
    second_response = Response()
    _immutable_response(_request("limit=50"), second_response, {"items": []}, 9)

    assert result == {"items": []}
    assert first_response.headers["cache-control"] == "private, no-cache"
    assert first_response.headers["etag"] == second_response.headers["etag"]
    assert first_response.headers["x-comparison-version"] == "scan-comparison-v2"
    assert first_response.headers["x-comparison-build-id"] == "9"


def test_comparison_etag_supports_304_and_changes_by_query_and_build() -> None:
    initial_response = Response()
    _immutable_response(_request("limit=50"), initial_response, {}, 9)
    etag = initial_response.headers["etag"]

    matched = _immutable_response(_request("limit=50", etag), Response(), {}, 9)
    changed_query = Response()
    _immutable_response(_request("limit=25"), changed_query, {}, 9)
    changed_build = Response()
    _immutable_response(_request("limit=50"), changed_build, {}, 10)

    assert isinstance(matched, Response) and matched.status_code == 304
    assert matched.headers["etag"] == etag
    assert changed_query.headers["etag"] != etag
    assert changed_build.headers["etag"] != etag
