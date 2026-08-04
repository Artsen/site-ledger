from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, WebsiteProperty
from app.schemas.graph import GraphEdgeOccurrenceList, GraphResponse
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
from app.schemas.sources import (
    InventoryList,
    ManualUrlBatchCreate,
    ManualUrlBatchResult,
    ScanSeedList,
    SourceRefreshRead,
    UrlSourceCreate,
    UrlSourceEntryList,
    UrlSourceEntryRead,
    UrlSourceList,
    UrlSourceRead,
    UrlSourceUpdate,
)
from app.services.graph_queries import (
    DEFAULT_GRAPH_EDGE_LIMIT,
    DEFAULT_GRAPH_NODE_LIMIT,
    MAX_GRAPH_EDGE_LIMIT,
    MAX_GRAPH_NODE_LIMIT,
    GraphFilters,
    get_scan_graph,
    list_graph_edge_occurrences,
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
from app.services.source_management import (
    DuplicateSourceError,
    add_manual_urls,
    create_source,
    delete_source,
    update_source,
)
from app.services.source_queries import (
    list_inventory,
    list_refreshes,
    list_scan_seeds,
    list_source_entries,
    list_sources,
)
from app.services.source_refresh import discover_from_robots, refresh_source
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
        scan = create_scan_from_site(
            db,
            site_id,
            payload.scope_config,
            include_inventory=payload.include_inventory,
            source_ids=payload.source_ids,
        )
    except InactiveSiteError as exc:
        raise HTTPException(409, str(exc)) from exc
    if scan is None:
        raise HTTPException(404, "Site not found")
    await request.app.state.scan_runner.queue(scan.id)
    return scan


@router.post("/sites/{site_id}/sources", response_model=UrlSourceRead, status_code=201)
def post_site_source(site_id: int, payload: UrlSourceCreate, db: DbSession) -> UrlSourceRead:
    try:
        source = create_source(db, site_id, payload)
    except DuplicateSourceError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if source is None:
        raise HTTPException(404, "Site not found")
    return UrlSourceRead.model_validate(source, from_attributes=True)


@router.get("/sites/{site_id}/sources", response_model=UrlSourceList)
def get_site_sources(
    site_id: int,
    db: DbSession,
    source_type: str | None = None,
    active_state: Literal["active", "inactive", "all"] = "all",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> UrlSourceList:
    result = list_sources(
        db, site_id, source_type=source_type, active_state=active_state, limit=limit, offset=offset
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.patch("/sites/{site_id}/sources/{source_id}", response_model=UrlSourceRead)
def patch_site_source(
    site_id: int, source_id: int, payload: UrlSourceUpdate, db: DbSession
) -> UrlSourceRead:
    try:
        source = update_source(db, site_id, source_id, payload)
    except DuplicateSourceError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if source is None:
        raise HTTPException(404, "Source not found")
    return UrlSourceRead.model_validate(source, from_attributes=True)


@router.delete("/sites/{site_id}/sources/{source_id}")
def delete_site_source(site_id: int, source_id: int, db: DbSession) -> dict[str, int]:
    deleted = delete_source(db, site_id, source_id)
    if deleted is None:
        raise HTTPException(404, "Source not found")
    return {"deleted_source_id": deleted}


@router.post(
    "/sites/{site_id}/sources/{source_id}/refresh",
    response_model=SourceRefreshRead,
    status_code=201,
)
async def post_source_refresh(site_id: int, source_id: int, db: DbSession) -> SourceRefreshRead:
    refresh = await refresh_source(db, site_id, source_id)
    if refresh is None:
        raise HTTPException(404, "Source not found")
    return SourceRefreshRead.model_validate(refresh, from_attributes=True)


@router.post(
    "/sites/{site_id}/sources/discover-robots",
    response_model=SourceRefreshRead,
    status_code=201,
)
async def post_robots_discovery(site_id: int, db: DbSession) -> SourceRefreshRead:
    refresh = await discover_from_robots(db, site_id)
    if refresh is None:
        raise HTTPException(404, "Site not found")
    return SourceRefreshRead.model_validate(refresh, from_attributes=True)


@router.get("/sites/{site_id}/sources/{source_id}/entries", response_model=UrlSourceEntryList)
def get_source_entries(
    site_id: int,
    source_id: int,
    db: DbSession,
    search: str | None = None,
    current_state: Literal["current", "not_current", "all"] = "current",
    validation_state: str | None = None,
    scope_decision: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> UrlSourceEntryList:
    result = list_source_entries(
        db,
        site_id,
        source_id,
        search=search,
        current_state=current_state,
        validation_state=validation_state,
        scope_decision=scope_decision,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.get(
    "/sites/{site_id}/sources/{source_id}/refreshes",
    response_model=list[SourceRefreshRead],
)
def get_source_refreshes(
    site_id: int,
    source_id: int,
    db: DbSession,
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> list[SourceRefreshRead]:
    result = list_refreshes(db, site_id, source_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.post("/sites/{site_id}/manual-urls", response_model=ManualUrlBatchResult, status_code=201)
def post_manual_urls(
    site_id: int, payload: ManualUrlBatchCreate, db: DbSession
) -> ManualUrlBatchResult:
    source, entries, accepted, rejected, duplicates = add_manual_urls(
        db, site_id, payload.urls_text
    )
    if source is None:
        raise HTTPException(404, "Site not found")
    source_read = UrlSourceRead.model_validate(source, from_attributes=True)
    source_read.current_entry_count = len([entry for entry in source.entries if entry.is_current])
    return ManualUrlBatchResult(
        source=source_read,
        items=[UrlSourceEntryRead.model_validate(entry, from_attributes=True) for entry in entries],
        accepted_count=accepted,
        rejected_count=rejected,
        duplicate_count=duplicates,
    )


@router.get("/sites/{site_id}/inventory", response_model=InventoryList)
def get_site_inventory(
    site_id: int,
    db: DbSession,
    search: str | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    scope_decision: str | None = None,
    validation_state: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> InventoryList:
    result = list_inventory(
        db,
        site_id,
        search=search,
        source_type=source_type,
        source_id=source_id,
        scope_decision=scope_decision,
        validation_state=validation_state,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


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


@router.get("/scans/{scan_id}/graph", response_model=GraphResponse)
def get_graph(
    scan_id: int,
    db: DbSession,
    max_nodes: int = Query(DEFAULT_GRAPH_NODE_LIMIT, ge=1, le=MAX_GRAPH_NODE_LIMIT),
    max_edges: int = Query(DEFAULT_GRAPH_EDGE_LIMIT, ge=0, le=MAX_GRAPH_EDGE_LIMIT),
    min_depth: int | None = Query(default=None, ge=0),
    max_depth: int | None = Query(default=None, ge=0),
    host: str | None = None,
    path_prefix: str | None = None,
    status: Literal["any", "2xx", "3xx", "4xx", "5xx", "none"] = "any",
    fetch_state: str | None = None,
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    min_inbound: int | None = Query(default=None, ge=0),
    min_outbound: int | None = Query(default=None, ge=0),
    include_self_links: bool = True,
    include_unfetched: bool = False,
    focus_snapshot_id: int | None = Query(default=None, ge=1),
    focus_hops: int = Query(1, ge=1, le=3),
) -> GraphResponse:
    if min_depth is not None and max_depth is not None and min_depth > max_depth:
        raise HTTPException(422, "min_depth cannot be greater than max_depth")
    try:
        graph = get_scan_graph(
            db,
            scan_id,
            GraphFilters(
                max_nodes=max_nodes,
                max_edges=max_edges,
                min_depth=min_depth,
                max_depth=max_depth,
                host=host,
                path_prefix=path_prefix,
                status=status,
                fetch_state=fetch_state,
                error_state=error_state,
                min_inbound=min_inbound,
                min_outbound=min_outbound,
                include_self_links=include_self_links,
                include_unfetched=include_unfetched,
                focus_snapshot_id=focus_snapshot_id,
                focus_hops=focus_hops,
            ),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if graph is None:
        raise HTTPException(404, "Scan not found")
    return graph


@router.get(
    "/scans/{scan_id}/graph/edges/{edge_id}/occurrences",
    response_model=GraphEdgeOccurrenceList,
)
def get_graph_edge_occurrences(
    scan_id: int,
    edge_id: str,
    db: DbSession,
    search: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> GraphEdgeOccurrenceList:
    result = list_graph_edge_occurrences(
        db,
        scan_id=scan_id,
        edge_id=edge_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Graph edge not found")
    return result


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
