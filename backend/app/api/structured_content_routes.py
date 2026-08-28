from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.canonical_document import render_markdown
from app.database import get_db
from app.models import ResourceSnapshot, Scan, SitePage, WebsiteProperty
from app.schemas.structured_content import StructuredContentDocumentRead, StructuredContentRead
from app.services.background_jobs import enqueue_structured_content_job
from app.services.structured_content import (
    compatible_structured_artifact,
    get_or_create_structured_artifact,
)
from app.services.structured_content_queries import (
    latest_page_content_snapshot,
    structured_content_for_snapshot,
    structured_document_for_snapshot,
)
from app.storage.content_store import BlobNotFoundError, LocalContentStore

router = APIRouter(prefix="/api", tags=["structured-content"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/sites/{site_id}/structured-content/prepare")
def prepare_site_structured_content(
    site_id: int,
    db: DbSession,
    scan_id: int | None = None,
    limit: int | None = Query(default=None, ge=1, le=100_000),
) -> dict[str, int | str]:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    if (
        scan_id is not None
        and db.scalar(
            select(Scan.id).where(Scan.id == scan_id, Scan.website_property_id == site_id)
        )
        is None
    ):
        raise HTTPException(404, "Scan not found for this Site")
    job = enqueue_structured_content_job(db, site_id, scan_id=scan_id, limit=limit)
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/snapshots/{snapshot_id}/structured-content", response_model=StructuredContentRead)
def get_snapshot_structured_content(
    snapshot_id: int,
    db: DbSession,
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> StructuredContentRead:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, "Snapshot not found")
    return structured_content_for_snapshot(db, snapshot, limit=limit, offset=offset)


@router.get(
    "/snapshots/{snapshot_id}/structured-content/document",
    response_model=StructuredContentDocumentRead,
)
def get_snapshot_structured_document(
    snapshot_id: int,
    db: DbSession,
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> StructuredContentDocumentRead:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, "Snapshot not found")
    return structured_document_for_snapshot(db, snapshot, limit=limit, offset=offset)


@router.get("/snapshots/{snapshot_id}/structured-content/markdown")
def get_snapshot_structured_markdown(
    snapshot_id: int,
    db: DbSession,
    max_characters: int = Query(default=1_000_000, ge=1, le=2_000_000),
) -> Response:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, "Snapshot not found")
    return _markdown_response(db, snapshot, max_characters)


@router.post(
    "/snapshots/{snapshot_id}/structured-content/prepare", response_model=StructuredContentRead
)
def prepare_snapshot_structured_content(
    snapshot_id: int,
    request: Request,
    db: DbSession,
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> StructuredContentRead:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, "Snapshot not found")
    if snapshot.blob is None:
        raise HTTPException(409, "Snapshot has no retained HTML ContentBlob")
    store: LocalContentStore = request.app.state.content_store
    try:
        get_or_create_structured_artifact(db, snapshot.blob, store=store)
    except BlobNotFoundError as exc:
        raise HTTPException(404, "Retained HTML blob is missing from storage") from exc
    db.commit()
    return structured_content_for_snapshot(db, snapshot, limit=limit, offset=offset)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/structured-content",
    response_model=StructuredContentRead,
)
def get_page_structured_content(
    site_id: int,
    resource_id: int,
    db: DbSession,
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> StructuredContentRead:
    resolved_id = _ensure_page_exists(db, site_id, resource_id)
    snapshot = latest_page_content_snapshot(db, site_id, resolved_id)
    if snapshot is None:
        return StructuredContentRead(
            status="not_applicable",
            reason="No successful retained HTML observation is available for this Page.",
            items=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    return structured_content_for_snapshot(db, snapshot, limit=limit, offset=offset)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/structured-content/document",
    response_model=StructuredContentDocumentRead,
)
def get_page_structured_document(
    site_id: int,
    resource_id: int,
    db: DbSession,
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> StructuredContentDocumentRead:
    resolved_id = _ensure_page_exists(db, site_id, resource_id)
    snapshot = latest_page_content_snapshot(db, site_id, resolved_id)
    if snapshot is None:
        return StructuredContentDocumentRead(
            status="not_applicable",
            reason="No successful retained HTML observation is available for this Page.",
            items=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    return structured_document_for_snapshot(db, snapshot, limit=limit, offset=offset)


@router.get("/sites/{site_id}/pages/{resource_id}/structured-content/markdown")
def get_page_structured_markdown(
    site_id: int,
    resource_id: int,
    db: DbSession,
    max_characters: int = Query(default=1_000_000, ge=1, le=2_000_000),
) -> Response:
    resolved_id = _ensure_page_exists(db, site_id, resource_id)
    snapshot = latest_page_content_snapshot(db, site_id, resolved_id)
    if snapshot is None:
        raise HTTPException(409, "No successful retained HTML observation is available")
    return _markdown_response(db, snapshot, max_characters)


@router.post(
    "/sites/{site_id}/pages/{resource_id}/structured-content/prepare",
    response_model=StructuredContentRead,
)
def prepare_page_structured_content(
    site_id: int,
    resource_id: int,
    request: Request,
    db: DbSession,
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> StructuredContentRead:
    resolved_id = _ensure_page_exists(db, site_id, resource_id)
    snapshot = latest_page_content_snapshot(db, site_id, resolved_id)
    if snapshot is None or snapshot.blob is None:
        raise HTTPException(409, "No successful retained HTML observation is available")
    store: LocalContentStore = request.app.state.content_store
    try:
        get_or_create_structured_artifact(db, snapshot.blob, store=store)
    except BlobNotFoundError as exc:
        raise HTTPException(404, "Retained HTML blob is missing from storage") from exc
    db.commit()
    return structured_content_for_snapshot(db, snapshot, limit=limit, offset=offset)


def _ensure_page_exists(db: Session, site_id: int, resource_id: int) -> int:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    from app.services.url_identity import resolve_resource_id

    resolved_id = resolve_resource_id(db, resource_id)
    if (
        resolved_id is None
        or db.scalar(
            select(SitePage.id).where(
                SitePage.website_property_id == site_id,
                SitePage.resource_id == resolved_id,
            )
        )
        is None
    ):
        raise HTTPException(404, "Page not found")
    return resolved_id


def _markdown_response(db: Session, snapshot: ResourceSnapshot, max_characters: int) -> Response:
    if snapshot.html_blob_id is None:
        raise HTTPException(409, "Observation has no retained HTML ContentBlob")
    artifact = compatible_structured_artifact(db, snapshot.html_blob_id)
    if artifact is None:
        raise HTTPException(409, "Structured Content V2 has not been prepared")
    markdown = render_markdown(artifact.nodes)
    partial = len(markdown) > max_characters
    body = markdown[:max_characters]
    return Response(
        content=body,
        media_type="text/markdown",
        headers={
            "X-Structured-Content-Extractor": artifact.extractor_version,
            "X-Structured-Content-Config": artifact.extractor_config_version,
            "X-Structured-Markdown-Renderer": artifact.markdown_renderer_version or "",
            "X-Structured-Markdown-SHA256": artifact.markdown_sha256 or "",
            "X-Structured-Markdown-Partial": str(partial).lower(),
            "X-Structured-Markdown-Total-Characters": str(len(markdown)),
        },
    )
