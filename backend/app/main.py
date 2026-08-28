from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api.accessibility_routes import router as accessibility_router
from app.api.ai_document_routes import router as ai_document_router
from app.api.category_rule_routes import router as category_rule_router
from app.api.comparison_routes import router as comparison_router
from app.api.performance_routes import router as performance_router
from app.api.render_routes import router as render_router
from app.api.routes import router
from app.api.site_intelligence_routes import router as site_intelligence_router
from app.api.structured_content_routes import router as structured_content_router
from app.config import get_settings
from app.database import SessionLocal
from app.product import API_TITLE, API_VERSION, PRODUCT_DESCRIPTION
from app.services.url_identity import inspect_url_identity_state
from app.storage.accessibility_store import LocalAccessibilityPayloadStore
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore
from app.storage.performance_store import LocalPerformancePayloadStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    store = LocalContentStore(settings.html_storage_root)
    app.state.content_store = store
    app.state.artifact_store = LocalArtifactStore(settings.rendered_artifact_storage_root)
    app.state.accessibility_payload_store = LocalAccessibilityPayloadStore(
        settings.accessibility_payload_storage_root
    )
    app.state.performance_payload_store = LocalPerformancePayloadStore(
        settings.performance_payload_storage_root
    )
    yield


class UrlIdentityMaintenanceMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        *,
        session_factory: Callable[[], Session],
    ) -> None:
        super().__init__(app)
        self.session_factory = session_factory

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path.rstrip("/")
        if not path.startswith("/api") or path == "/api/health":
            return await call_next(request)
        with self.session_factory() as db:
            status = inspect_url_identity_state(db)
        if not status.maintenance_required:
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "url_identity_maintenance_required",
                    "message": (
                        "URL identity migration recovery is required before normal API "
                        "operation can resume."
                    ),
                    "migration_id": status.active_migration_id,
                    "migration_status": status.migration_status,
                }
            },
        )


def create_app(*, session_factory: Callable[[], Session] = SessionLocal) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=API_TITLE,
        description=PRODUCT_DESCRIPTION,
        version=API_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        UrlIdentityMaintenanceMiddleware,
        session_factory=session_factory,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(accessibility_router)
    app.include_router(ai_document_router)
    app.include_router(category_rule_router)
    app.include_router(comparison_router)
    app.include_router(structured_content_router)
    app.include_router(performance_router)
    app.include_router(render_router)
    app.include_router(site_intelligence_router)
    return app


app = create_app()
