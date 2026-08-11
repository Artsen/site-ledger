from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ResourceSnapshot, Scan, SitePage, WebsiteProperty
from app.schemas.structured_content import StructuredContentRead
from app.services.background_jobs import enqueue_structured_content_job
from app.services.structured_content import get_or_create_structured_artifact
from app.services.structured_content_queries import (
    latest_page_content_snapshot,
    structured_content_for_snapshot,
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
    _ensure_page_exists(db, site_id, resource_id)
    snapshot = latest_page_content_snapshot(db, site_id, resource_id)
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
    _ensure_page_exists(db, site_id, resource_id)
    snapshot = latest_page_content_snapshot(db, site_id, resource_id)
    if snapshot is None or snapshot.blob is None:
        raise HTTPException(409, "No successful retained HTML observation is available")
    store: LocalContentStore = request.app.state.content_store
    try:
        get_or_create_structured_artifact(db, snapshot.blob, store=store)
    except BlobNotFoundError as exc:
        raise HTTPException(404, "Retained HTML blob is missing from storage") from exc
    db.commit()
    return structured_content_for_snapshot(db, snapshot, limit=limit, offset=offset)


def _ensure_page_exists(db: Session, site_id: int, resource_id: int) -> None:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    if (
        db.scalar(
            select(SitePage.id).where(
                SitePage.website_property_id == site_id,
                SitePage.resource_id == resource_id,
            )
        )
        is None
    ):
        raise HTTPException(404, "Page not found")
