from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, WebsiteProperty
from app.schemas.scans import (
    InboundLinkList,
    LinkRead,
    PageList,
    ScanCreate,
    ScanDeletePreview,
    ScanDeleteResult,
    ScanHistory,
    ScanRead,
    SnapshotRead,
)
from app.schemas.sites import (
    SiteDeleteResult,
    SiteScanCreate,
    SiteScans,
    WebsitePropertyCreate,
    WebsitePropertyList,
    WebsitePropertyRead,
    WebsitePropertyUpdate,
)
from app.services.scan_deletion import delete_scan as delete_scan_service
from app.services.scan_deletion import preview_scan_deletion
from app.services.scan_queries import (
    list_scan_history,
    list_scan_pages,
    list_snapshot_inbound_links,
)
from app.services.site_management import (
    DuplicateSiteError,
    InactiveSiteError,
    SiteHasScansError,
    create_scan_from_site,
    create_site,
    delete_site,
    update_site,
)
from app.services.site_queries import get_site_detail, list_site_scans, list_sites
from app.storage.content_store import BlobNotFoundError, LocalContentStore

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
ScanListLimit = Annotated[int, Query(ge=1, le=100)]
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/scans", response_model=ScanRead, status_code=201)
async def create_scan(payload: ScanCreate, request: Request, db: DbSession) -> Scan:
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
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    await request.app.state.scan_runner.queue(scan.id)
    return scan


@router.get("/scans", response_model=list[ScanRead])
def list_scans(db: DbSession, limit: ScanListLimit = 25) -> list[Scan]:
    return list(
        db.scalars(
            select(Scan)
            .options(joinedload(Scan.website_property))
            .order_by(Scan.created_at.desc())
            .limit(limit)
        )
    )


@router.get("/scans/history", response_model=ScanHistory)
def get_scan_history(
    db: DbSession,
    search: str | None = None,
    status: str | None = None,
    website_property_id: int | None = None,
    sort: Literal[
        "created_at", "started_at", "finished_at", "status", "starting_url"
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


@router.post("/sites", response_model=WebsitePropertyRead, status_code=201)
def post_site(payload: WebsitePropertyCreate, db: DbSession) -> WebsitePropertyRead:
    try:
        site = create_site(db, payload)
    except DuplicateSiteError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = get_site_detail(db, site.id)
    assert result is not None
    return result


@router.get("/sites", response_model=WebsitePropertyList)
def get_sites(
    db: DbSession,
    search: str | None = None,
    group_key: str | None = None,
    locale: str | None = None,
    platform_key: str | None = None,
    ownership_key: str | None = None,
    active_state: Literal["active", "inactive", "all"] = "active",
    sort: Literal["name", "base_url", "created_at", "updated_at", "latest_scan_at"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> WebsitePropertyList:
    return list_sites(
        db,
        search=search,
        group_key=group_key,
        locale=locale,
        platform_key=platform_key,
        ownership_key=ownership_key,
        active_state=active_state,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.get("/sites/{site_id}", response_model=WebsitePropertyRead)
def get_site(site_id: int, db: DbSession) -> WebsitePropertyRead:
    site = get_site_detail(db, site_id)
    if site is None:
        raise HTTPException(404, "Site not found")
    return site


@router.patch("/sites/{site_id}", response_model=WebsitePropertyRead)
def patch_site(site_id: int, payload: WebsitePropertyUpdate, db: DbSession) -> WebsitePropertyRead:
    try:
        site = update_site(db, site_id, payload)
    except DuplicateSiteError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if site is None:
        raise HTTPException(404, "Site not found")
    result = get_site_detail(db, site.id)
    assert result is not None
    return result


@router.delete("/sites/{site_id}", response_model=SiteDeleteResult)
def remove_site(site_id: int, db: DbSession) -> SiteDeleteResult:
    try:
        deleted = delete_site(db, site_id)
    except SiteHasScansError as exc:
        raise HTTPException(409, str(exc)) from exc
    if deleted is None:
        raise HTTPException(404, "Site not found")
    return SiteDeleteResult(deleted_site_id=deleted)


@router.post("/sites/{site_id}/scans", response_model=ScanRead, status_code=201)
async def post_site_scan(
    site_id: int, payload: SiteScanCreate, request: Request, db: DbSession
) -> Scan:
    try:
        scan = create_scan_from_site(db, site_id, payload.scope_config)
    except InactiveSiteError as exc:
        raise HTTPException(409, str(exc)) from exc
    if scan is None:
        raise HTTPException(404, "Site not found")
    await request.app.state.scan_runner.queue(scan.id)
    return scan


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
def get_scan(scan_id: int, db: DbSession) -> Scan:
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    return scan


@router.post("/scans/{scan_id}/cancel", response_model=ScanRead)
async def cancel_scan(scan_id: int, request: Request, db: DbSession) -> Scan:
    await request.app.state.scan_runner.cancel(scan_id)
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    db.refresh(scan)
    return scan


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
    if request.app.state.scan_runner.is_active(scan_id):
        raise HTTPException(409, "The scan must finish or be cancelled before it can be deleted.")
    store: LocalContentStore = request.app.state.content_store
    try:
        result = delete_scan_service(db, scan_id, store)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.get("/scans/{scan_id}/pages", response_model=PageList)
def list_pages(
    scan_id: int,
    db: DbSession,
    search: str | None = None,
    status: int | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    depth: int | None = None,
    min_depth: int | None = Query(default=None, ge=0),
    max_depth: int | None = Query(default=None, ge=0),
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    sort: Literal["requested_url", "status", "title", "depth", "duration"] = "requested_url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> PageList:
    return list_scan_pages(
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
    )


@router.get("/scans/{scan_id}/errors", response_model=list[SnapshotRead])
def list_errors(scan_id: int, db: DbSession) -> list[ResourceSnapshot]:
    return list(
        db.scalars(
            select(ResourceSnapshot).where(
                ResourceSnapshot.scan_id == scan_id, ResourceSnapshot.error_type.is_not(None)
            )
        )
    )


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotRead)
def get_snapshot(snapshot_id: int, db: DbSession) -> SnapshotRead:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    result = SnapshotRead.model_validate(snapshot, from_attributes=True)
    result.html_raw_byte_size = snapshot.blob.raw_byte_size if snapshot.blob else None
    result.html_stored_byte_size = snapshot.blob.stored_byte_size if snapshot.blob else None
    return result


@router.get("/snapshots/{snapshot_id}/links", response_model=list[LinkRead])
def get_snapshot_links(snapshot_id: int, db: DbSession) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id == snapshot_id)
        )
    )


@router.get("/snapshots/{snapshot_id}/inbound-links", response_model=InboundLinkList)
def get_snapshot_inbound_links(
    snapshot_id: int,
    db: DbSession,
    search: str | None = None,
    scope_decision: str | None = None,
    source_status: int | None = None,
    rel: str | None = None,
    sort: Literal["source_url", "anchor_text", "scope_decision", "source_status"] = "source_url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> InboundLinkList:
    links = list_snapshot_inbound_links(
        db,
        snapshot_id=snapshot_id,
        search=search,
        scope_decision=scope_decision,
        source_status=source_status,
        rel=rel,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if links is None:
        raise HTTPException(404, "Snapshot not found")
    return links


@router.get("/snapshots/{snapshot_id}/html")
def get_snapshot_html(snapshot_id: int, request: Request, db: DbSession) -> Response:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    if not snapshot.blob:
        raise HTTPException(404, "Snapshot has no HTML blob")
    store: LocalContentStore = request.app.state.content_store
    try:
        content = store.get(snapshot.blob)
    except BlobNotFoundError as exc:
        raise HTTPException(404, "HTML blob is missing") from exc
    return Response(
        content=content.decode(snapshot.encoding or "utf-8", errors="replace"),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/resources/{resource_id}/occurrences", response_model=list[LinkRead])
def get_resource_occurrences(resource_id: int, db: DbSession) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(ResourceOccurrence.target_resource_id == resource_id)
        )
    )
