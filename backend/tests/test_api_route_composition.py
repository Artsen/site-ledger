import hashlib
import importlib
import json
from collections.abc import Iterator

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes import _projection_http_response, router
from app.database import get_db
from app.main import app as assembled_app

EXPECTED_PATH_CONTRACT_SHA256 = "4002607a2b389c1d60f98ca4eafabf33243339c255e0498d1c33440509c72d6c"
EXPECTED_CORE_ROUTE_COUNTS = {
    "system": 1,
    "job": 4,
    "scan": 12,
    "site": 5,
    "source": 18,
    "page": 14,
    "note": 8,
    "projection": 4,
    "resource": 9,
    "legacy_render": 9,
    "graph": 3,
    "snapshot": 8,
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def test_full_openapi_path_contract_matches_pre_decomposition_baseline() -> None:
    paths = {
        path: {method: value for method, value in item.items() if method in HTTP_METHODS}
        for path, item in assembled_app.openapi()["paths"].items()
    }
    encoded = json.dumps(paths, sort_keys=True, separators=(",", ":")).encode()

    assert len(paths) == 192
    assert sum(len(item) for item in paths.values()) == 225
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_PATH_CONTRACT_SHA256
    assert "/api/health" in paths


def test_composed_application_has_no_duplicate_method_path_pairs() -> None:
    pairs = [
        (method, route.path)
        for route in _iter_api_routes(assembled_app.router)
        for method in route.methods or set()
    ]

    assert len(pairs) == 225
    assert len(pairs) == len(set(pairs))


def test_core_router_composes_expected_domain_routers_and_preserves_imports() -> None:
    assert isinstance(router, APIRouter)
    assert callable(_projection_http_response)
    for name, expected_count in EXPECTED_CORE_ROUTE_COUNTS.items():
        module = importlib.import_module(f"app.api.{name}_routes")
        assert len(module.router.routes) == expected_count


def test_literal_routes_keep_precedence_over_parameter_routes(db_session) -> None:
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        history = client.get("/api/scans/history")
        resource_summary = client.get("/api/sites/999/resources/summary")
        health = client.get("/api/health")

    assert history.status_code == 200
    assert resource_summary.status_code == 404
    assert resource_summary.json() == {"detail": "Site not found"}
    assert health.status_code == 200


def _iter_api_routes(router_value: APIRouter) -> Iterator[APIRoute]:
    for route in router_value.routes:
        included = getattr(route, "original_router", None)
        if isinstance(included, APIRouter):
            yield from _iter_api_routes(included)
        elif isinstance(route, APIRoute):
            yield route
