from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.dependencies import DbSession, PageLimit, PageOffset, ScanListLimit
from app.api.projection_routes import _projection_http_response
from app.models import (
    Note,
    Scan,
    WebsiteProperty,
)
from app.schemas.scans import (
    PageList,
    ScanCreate,
    ScanDeletePreview,
    ScanDeleteResult,
    ScanHistory,
    ScanRead,
)
from app.schemas.sites import (
    SiteScanCreate,
    SiteScans,
)
from app.schemas.sources import (
    ScanSeedList,
)
from app.services.background_jobs import (
    active_job_for_scan,
    enqueue_scan_job,
)
from app.services.native_cancellation import request_native_cancellation
from app.services.scan_deletion import delete_scan as delete_scan_service
from app.services.scan_deletion import preview_scan_deletion
from app.services.scan_queries import (
    list_scan_history,
)
from app.services.scan_queries import (
    list_scan_pages_routed as list_scan_pages,
)
from app.services.scan_render_authority import scan_read, scan_reads
from app.services.site_management import (
    InactiveSiteError,
    create_scan_from_site,
)
from app.services.site_queries import list_site_scans
from app.services.source_queries import (
    list_scan_seeds,
)
from app.services.url_identity import (
    active_url_normalization_version,
)
from app.storage.content_store import LocalContentStore

router = APIRouter(prefix="/api")


@router.post("/scans", response_model=ScanRead, status_code=202)
def create_scan(payload: ScanCreate, db: DbSession) -> ScanRead:
    if payload.website_property_id is not None:
        site = db.get(WebsiteProperty, payload.website_property_id)
        if site is None:
            raise HTTPException(404, "Site not found")
        if not site.is_active:
            raise HTTPException(409, "Inactive sites cannot start new scans.")
    scan = Scan(
        website_property_id=payload.website_property_id,
        starting_url=payload.starting_url,
        status="queued",
        scope_config=payload.scope_config.model_dump(),
        url_normalization_version=active_url_normalization_version(db),
    )
    db.add(scan)
    db.flush()
    enqueue_scan_job(db, scan)
    db.commit()
    db.refresh(scan)
    return scan_read(db, scan)


@router.get("/scans", response_model=list[ScanRead])
def list_scans(db: DbSession, limit: ScanListLimit = 25) -> list[ScanRead]:
    scans = list(
        db.scalars(
            select(Scan)
            .options(joinedload(Scan.website_property))
            .order_by(Scan.created_at.desc())
            .limit(limit)
        )
    )
    return scan_reads(db, scans)


@router.get("/scans/history", response_model=ScanHistory)
def get_scan_history(
    db: DbSession,
    search: str | None = None,
    status: str | None = None,
    website_property_id: int | None = None,
    sort: Literal[
        "created_at",
        "started_at",
        "finished_at",
        "status",
        "starting_url",
        "duration",
        "discovered_count",
        "stop_reason",
    ] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 50,
    offset: PageOffset = 0,
) -> ScanHistory:
    return list_scan_history(
        db,
        search=search,
        status=status,
        website_property_id=website_property_id,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/sites/{site_id}/scans", response_model=ScanRead, status_code=202)
def post_site_scan(site_id: int, payload: SiteScanCreate, db: DbSession) -> ScanRead:
    try:
        scan = create_scan_from_site(
            db,
            site_id,
            payload.scope_config,
            include_inventory=payload.include_inventory,
            source_ids=payload.source_ids,
            commit=False,
        )
    except InactiveSiteError as exc:
        raise HTTPException(409, str(exc)) from exc
    if scan is None:
        raise HTTPException(404, "Site not found")
    enqueue_scan_job(db, scan)
    db.commit()
    db.refresh(scan)
    return scan_read(db, scan)


@router.get("/scans/{scan_id}/seeds", response_model=ScanSeedList)
def get_scan_seeds(
    scan_id: int,
    db: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ScanSeedList:
    result = list_scan_seeds(db, scan_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.get("/sites/{site_id}/scans", response_model=SiteScans)
def get_site_scans(
    site_id: int,
    db: DbSession,
    status: str | None = None,
    sort: Literal[
        "created_at", "started_at", "finished_at", "status", "starting_url"
    ] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> SiteScans:
    scans = list_site_scans(
        db,
        site_id=site_id,
        status=status,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if scans is None:
        raise HTTPException(404, "Site not found")
    return scans


@router.get("/scans/{scan_id}", response_model=ScanRead)
def get_scan(scan_id: int, db: DbSession) -> ScanRead:
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    note_count = db.scalar(select(func.count(Note.id)).where(Note.scan_id == scan.id)) or 0
    return scan_read(db, scan, note_count=note_count)


@router.post("/scans/{scan_id}/cancel", response_model=ScanRead)
def cancel_scan(scan_id: int, db: DbSession) -> ScanRead:
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    job = active_job_for_scan(db, scan_id)
    if job:
        request_native_cancellation(db, job)
    db.refresh(scan)
    return scan_read(db, scan)


@router.get("/scans/{scan_id}/delete-preview", response_model=ScanDeletePreview)
def get_delete_preview(scan_id: int, db: DbSession) -> ScanDeletePreview:
    preview = preview_scan_deletion(db, scan_id)
    if preview is None:
        raise HTTPException(404, "Scan not found")
    return preview


@router.get("/scans/{scan_id}/deletion-summary", response_model=ScanDeletePreview)
def get_deletion_summary(scan_id: int, db: DbSession) -> ScanDeletePreview:
    return get_delete_preview(scan_id, db)


@router.delete("/scans/{scan_id}", response_model=ScanDeleteResult)
def delete_scan(scan_id: int, request: Request, db: DbSession) -> ScanDeleteResult:
    if active_job_for_scan(db, scan_id):
        raise HTTPException(409, "The scan must finish or be cancelled before it can be deleted.")
    store: LocalContentStore = request.app.state.content_store
    try:
        result = delete_scan_service(db, scan_id, store, request.app.state.artifact_store)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.get("/scans/{scan_id}/pages", response_model=PageList)
def list_pages(
    scan_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    search: str | None = None,
    status: int | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    depth: int | None = None,
    min_depth: int | None = Query(default=None, ge=0),
    max_depth: int | None = Query(default=None, ge=0),
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    rendered_state: Literal[
        "any",
        "not_requested",
        "captured",
        "captured_with_warnings",
        "failed",
        "skipped",
        "interrupted",
    ] = "any",
    sort: Literal[
        "requested_url",
        "status",
        "title",
        "depth",
        "content_type",
        "duration",
        "inbound",
        "rendered_state",
        "error",
    ] = "requested_url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> PageList | Response:
    result = list_scan_pages(
        db,
        scan_id,
        search,
        status,
        host,
        path_prefix,
        depth,
        min_depth,
        max_depth,
        error_state,
        sort,
        direction,
        limit,
        offset,
        rendered_state,
    )
    return _projection_http_response(request, response, result, immutable=False)
