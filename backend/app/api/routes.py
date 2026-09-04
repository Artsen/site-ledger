"""Compatibility composition surface for Site Ledger core API routes."""

from fastapi import APIRouter

from app.api.graph_routes import router as graph_router
from app.api.job_routes import router as job_router
from app.api.legacy_render_routes import router as legacy_render_router
from app.api.note_routes import router as note_router
from app.api.page_routes import router as page_router
from app.api.projection_routes import (
    _projection_http_response,
)
from app.api.projection_routes import (
    router as projection_router,
)
from app.api.resource_routes import router as resource_router
from app.api.scan_routes import router as scan_router
from app.api.site_routes import router as site_router
from app.api.snapshot_routes import router as snapshot_router
from app.api.source_routes import router as source_router
from app.api.system_routes import router as system_router

router = APIRouter()
router.include_router(system_router)
router.include_router(job_router)
router.include_router(scan_router)
router.include_router(site_router)
router.include_router(source_router)
router.include_router(page_router)
router.include_router(note_router)
router.include_router(projection_router)
router.include_router(resource_router)
router.include_router(legacy_render_router)
router.include_router(graph_router)
router.include_router(snapshot_router)

__all__ = ["_projection_http_response", "router"]
