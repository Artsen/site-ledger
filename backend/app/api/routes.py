import hashlib
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.browser.config import capabilities as render_capabilities_data
from app.database import get_db
from app.models import (
    BackgroundJob,
    JobEvent,
    Note,
    RenderedArtifact,
    RenderedConsoleMessage,
    RenderedNetworkEntry,
    RenderedObservation,
    RenderedPageError,
    RenderRun,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    SourceRefresh,
    StaticFetchAttempt,
    WebsiteProperty,
)
from app.schemas.graph import GraphCapabilitiesRead, GraphEdgeOccurrenceList, GraphResponse
from app.schemas.jobs import JobEventList, JobEventRead, JobList, JobRead, WorkerHealth
from app.schemas.page_workspaces import (
    BulkMutationResult,
    BulkPageCategories,
    BulkPageDelete,
    BulkPageMetadata,
    BulkPageWorkspaceState,
    NoteCreate,
    NoteList,
    NoteRead,
    NoteSort,
    NoteUpdate,
    PageCategoryCreate,
    PageCategoryDeletionPreview,
    PageCategoryList,
    PageCategoryRead,
    PageCategoryUpdate,
    PageMetadataUpdate,
    PageWorkspaceStateUpdate,
)
from app.schemas.projections import ScanProjectionBuildRead, ScanProjectionStatusRead
from app.schemas.rendered import (
    RenderCapabilitiesRead,
    RenderedArtifactRead,
    RenderedConsoleMessageRead,
    RenderedEventList,
    RenderedNetworkEntryRead,
    RenderedObservationIndexList,
    RenderedObservationRead,
    RenderedPageErrorRead,
)
from app.schemas.resources import (
    ResourceDetail,
    ResourceHistoryList,
    ResourceInventoryList,
    ResourceOccurrenceList,
    ResourceSummary,
)
from app.schemas.scans import (
    InboundLinkList,
    LinkRead,
    OutgoingLinkList,
    PageList,
    PageObservationList,
    PersistentPageDetail,
    PersistentPageList,
    ScanCreate,
    ScanDeletePreview,
    ScanDeleteResult,
    ScanHistory,
    ScanRead,
    SnapshotRead,
    StaticFetchAttemptRead,
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
    BulkInventoryEntryDelete,
    BulkInventorySuppressionCreate,
    BulkInventorySuppressionRestore,
    BulkSourceRefreshCreate,
    InventoryList,
    InventorySuppressionCreate,
    InventorySuppressionRead,
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
from app.services.background_jobs import (
    active_job_for_scan,
    active_job_for_source_refresh,
    enqueue_scan_job,
    enqueue_scan_projection_job,
    enqueue_source_refresh_job,
    presentation_status,
    request_cancellation,
    worker_health,
)
from app.services.graph_config import GRAPH_CONFIG
from app.services.graph_filters import GraphFilters
from app.services.graph_queries import (
    get_graph_capabilities,
    get_scan_graph,
    list_graph_edge_occurrences,
)
from app.services.inventory_lifecycle import (
    ManagedSourceEntryError,
    bulk_create_inventory_suppressions,
    bulk_delete_inventory_entries,
    bulk_restore_inventory_suppressions,
    create_inventory_suppression,
    delete_inventory_suppression,
    remove_manual_source_entry,
)
from app.services.notes import (
    create_note,
    delete_note,
    find_page_target,
    list_notes,
    scan_exists,
    site_exists,
    update_note,
)
from app.services.page_categories import (
    DuplicateCategoryError,
    create_category,
    delete_category,
    list_categories,
    preview_category_deletion,
    update_category,
)
from app.services.page_queries import get_site_page, list_page_observations, list_site_pages
from app.services.rendered_queries import list_scan_rendered_observations
from app.services.resource_queries import (
    get_scan_resource,
    get_site_resource,
    list_resource_occurrences,
    list_scan_resources,
    list_site_resource_history,
    list_site_resources,
    scan_resource_summary,
    site_resource_summary,
)
from app.services.scan_deletion import delete_scan as delete_scan_service
from app.services.scan_deletion import preview_scan_deletion
from app.services.scan_projections import (
    create_projection_build,
    projection_status,
    verify_projection_build,
)
from app.services.scan_queries import (
    get_snapshot_detail,
    list_scan_history,
    list_snapshot_inbound_links,
    list_snapshot_outgoing_links,
)
from app.services.scan_queries import (
    list_scan_pages_routed as list_scan_pages,
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
from app.services.site_pages import (
    bulk_categories,
    bulk_delete_pages,
    bulk_metadata,
    bulk_workspace_state,
    find_site_page,
    update_page_metadata,
    update_page_workspace_state,
)
from app.services.site_queries import get_site_detail, list_site_scans, list_sites
from app.services.source_management import (
    DuplicateSourceError,
    SourceHasActiveJobError,
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
from app.services.source_refresh import (
    create_robots_discovery_refresh,
    create_source_refresh,
    enqueue_bulk_source_refreshes,
)
from app.services.url_identity import (
    active_url_normalization_version,
    inspect_url_identity_state,
)
from app.storage.artifact_store import ArtifactNotFoundError, LocalArtifactStore
from app.storage.content_store import BlobNotFoundError, LocalContentStore

router = APIRouter(prefix="/api")
ProjectionResponseT = TypeVar(
    "ProjectionResponseT", PageList, ResourceInventoryList, ResourceSummary, GraphResponse
)
DbSession = Annotated[Session, Depends(get_db)]
ScanListLimit = Annotated[int, Query(ge=1, le=250)]
PageLimit = Annotated[int, Query(ge=1, le=250)]
PageOffset = Annotated[int, Query(ge=0)]
ResourceSortParam = Literal[
    "url",
    "kind",
    "mime_type",
    "http_status",
    "declared_size",
    "occurrence_count",
    "source_page_count",
    "observed",
    "in_scope_count",
    "first_discovered",
    "latest_discovered",
]


@router.get("/health")
def health(db: DbSession) -> dict[str, object]:
    identity = inspect_url_identity_state(db)
    return {
        "status": "maintenance_required" if identity.maintenance_required else "ok",
        "url_identity": {
            "active_version": identity.active_normalization_version,
            "maintenance_required": identity.maintenance_required,
            "migration_id": identity.active_migration_id,
            "migration_status": identity.migration_status,
        },
    }


@router.get("/jobs/worker-health", response_model=WorkerHealth)
def get_worker_health(db: DbSession) -> WorkerHealth:
    from app.config import get_settings

    return worker_health(db, get_settings().job_worker_offline_seconds)


@router.get("/jobs", response_model=JobList)
def list_jobs(
    db: DbSession,
    job_type: str | None = None,
    status: str | None = None,
    scan_id: int | None = None,
    source_refresh_id: int | None = None,
    website_property_id: int | None = None,
    limit: ScanListLimit = 50,
    offset: PageOffset = 0,
) -> JobList:
    query = select(BackgroundJob)
    count_query = select(func.count(BackgroundJob.id))
    if job_type:
        query = query.where(BackgroundJob.job_type == job_type)
        count_query = count_query.where(BackgroundJob.job_type == job_type)
    if status:
        query = query.where(BackgroundJob.status == status)
        count_query = count_query.where(BackgroundJob.status == status)
    if scan_id is not None:
        query = query.where(BackgroundJob.scan_id == scan_id)
        count_query = count_query.where(BackgroundJob.scan_id == scan_id)
    if source_refresh_id is not None:
        query = query.where(BackgroundJob.source_refresh_id == source_refresh_id)
        count_query = count_query.where(BackgroundJob.source_refresh_id == source_refresh_id)
    if website_property_id is not None:
        query = query.where(BackgroundJob.website_property_id == website_property_id)
        count_query = count_query.where(BackgroundJob.website_property_id == website_property_id)
    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    health = get_worker_health(db)
    return JobList(
        items=[_job_read(job, health) for job in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: DbSession) -> JobRead:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _job_read(job, get_worker_health(db))


@router.get("/jobs/{job_id}/events", response_model=JobEventList)
def get_job_events(
    job_id: int,
    db: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> JobEventList:
    if db.get(BackgroundJob, job_id) is None:
        raise HTTPException(404, "Job not found")
    total = db.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id == job_id)) or 0
    events = list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
    )
    return JobEventList(
        items=[JobEventRead.model_validate(event, from_attributes=True) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/scans", response_model=ScanRead, status_code=202)
def create_scan(payload: ScanCreate, db: DbSession) -> Scan:
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
    sort: Literal[
        "name",
        "base_url",
        "classification",
        "state",
        "created_at",
        "updated_at",
        "latest_scan_at",
        "scan_count",
    ] = "name",
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
def remove_site(site_id: int, request: Request, db: DbSession) -> SiteDeleteResult:
    warnings: list[str] = []
    try:
        deleted = delete_site(
            db,
            site_id,
            request.app.state.performance_payload_store,
            request.app.state.accessibility_payload_store,
            warnings,
            request.app.state.artifact_store,
        )
    except SiteHasScansError as exc:
        raise HTTPException(409, str(exc)) from exc
    if deleted is None:
        raise HTTPException(404, "Site not found")
    return SiteDeleteResult(deleted_site_id=deleted, warnings=warnings)


@router.post("/sites/{site_id}/scans", response_model=ScanRead, status_code=202)
def post_site_scan(site_id: int, payload: SiteScanCreate, db: DbSession) -> Scan:
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
    try:
        deleted = delete_source(db, site_id, source_id)
    except SourceHasActiveJobError as exc:
        raise HTTPException(409, str(exc)) from exc
    if deleted is None:
        raise HTTPException(404, "Source not found")
    return {"deleted_source_id": deleted}


@router.post(
    "/sites/{site_id}/sources/{source_id}/refresh",
    response_model=SourceRefreshRead,
    status_code=202,
)
def post_source_refresh(site_id: int, source_id: int, db: DbSession) -> SourceRefreshRead:
    refresh = create_source_refresh(db, site_id, source_id, commit=False)
    if refresh is None:
        raise HTTPException(404, "Source not found")
    enqueue_source_refresh_job(db, refresh)
    db.commit()
    db.refresh(refresh)
    return SourceRefreshRead.model_validate(refresh, from_attributes=True)


@router.post(
    "/sites/{site_id}/sources/bulk-refresh",
    response_model=list[SourceRefreshRead],
    status_code=202,
)
def post_bulk_source_refresh(
    site_id: int, payload: BulkSourceRefreshCreate, db: DbSession
) -> list[SourceRefreshRead]:
    try:
        refreshes = enqueue_bulk_source_refreshes(db, site_id, payload.source_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if refreshes is None:
        raise HTTPException(404, "Site not found")
    return [
        SourceRefreshRead.model_validate(refresh, from_attributes=True) for refresh in refreshes
    ]


@router.post(
    "/sites/{site_id}/sources/discover-robots",
    response_model=SourceRefreshRead,
    status_code=202,
)
def post_robots_discovery(site_id: int, db: DbSession) -> SourceRefreshRead:
    refresh = create_robots_discovery_refresh(db, site_id, commit=False)
    if refresh is None:
        raise HTTPException(404, "Site not found")
    enqueue_source_refresh_job(db, refresh)
    db.commit()
    db.refresh(refresh)
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


@router.delete(
    "/sites/{site_id}/sources/{source_id}/entries/{entry_id}",
    response_model=UrlSourceEntryRead,
)
def delete_manual_source_entry(
    site_id: int, source_id: int, entry_id: int, db: DbSession
) -> UrlSourceEntryRead:
    try:
        entry = remove_manual_source_entry(db, site_id, source_id, entry_id)
    except ManagedSourceEntryError as exc:
        raise HTTPException(409, str(exc)) from exc
    if entry is None:
        raise HTTPException(404, "Source entry not found")
    return UrlSourceEntryRead.model_validate(entry, from_attributes=True)


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


@router.post("/source-refreshes/{refresh_id}/cancel", response_model=SourceRefreshRead)
def cancel_source_refresh(refresh_id: int, db: DbSession) -> SourceRefreshRead:
    refresh = db.get(SourceRefresh, refresh_id)
    if refresh is None:
        raise HTTPException(404, "Source refresh not found")
    job = active_job_for_source_refresh(db, refresh_id)
    if job:
        request_cancellation(db, job)
        if job.status == "cancelled":
            refresh.status = "cancelled"
            refresh.error_type = "cancelled"
            refresh.error_message = "Refresh cancelled by user."
            db.commit()
    db.refresh(refresh)
    return SourceRefreshRead.model_validate(refresh, from_attributes=True)


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
    visibility: Literal["active", "suppressed", "all"] = "active",
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
        visibility=visibility,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post(
    "/sites/{site_id}/inventory/suppressions",
    response_model=InventorySuppressionRead,
    status_code=201,
)
def post_inventory_suppression(
    site_id: int, payload: InventorySuppressionCreate, db: DbSession
) -> InventorySuppressionRead:
    suppression = create_inventory_suppression(db, site_id, payload.entry_id)
    if suppression is None:
        raise HTTPException(404, "Inventory entry not found")
    return InventorySuppressionRead.model_validate(suppression, from_attributes=True)


@router.delete("/sites/{site_id}/inventory/suppressions/{suppression_id}")
def remove_inventory_suppression(
    site_id: int, suppression_id: int, db: DbSession
) -> dict[str, int]:
    deleted = delete_inventory_suppression(db, site_id, suppression_id)
    if deleted is None:
        raise HTTPException(404, "Inventory suppression not found")
    return {"deleted_suppression_id": deleted}


@router.post(
    "/sites/{site_id}/inventory/suppressions/bulk",
    response_model=BulkMutationResult,
)
def post_bulk_inventory_suppressions(
    site_id: int, payload: BulkInventorySuppressionCreate, db: DbSession
) -> BulkMutationResult:
    try:
        result = bulk_create_inventory_suppressions(db, site_id, payload.entry_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post(
    "/sites/{site_id}/inventory/suppressions/bulk-restore",
    response_model=BulkMutationResult,
)
def post_bulk_inventory_suppression_restore(
    site_id: int, payload: BulkInventorySuppressionRestore, db: DbSession
) -> BulkMutationResult:
    try:
        result = bulk_restore_inventory_suppressions(db, site_id, payload.suppression_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post(
    "/sites/{site_id}/inventory/bulk-delete",
    response_model=BulkMutationResult,
)
def post_bulk_inventory_delete(
    site_id: int, payload: BulkInventoryEntryDelete, db: DbSession
) -> BulkMutationResult:
    try:
        result = bulk_delete_inventory_entries(db, site_id, payload.entry_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get("/sites/{site_id}/page-categories", response_model=PageCategoryList)
def get_page_categories(
    site_id: int,
    db: DbSession,
    search: str | None = None,
    active_state: Literal["active", "archived", "all"] = "all",
    sort: Literal["name", "sort_order", "created_at"] = "sort_order",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> PageCategoryList:
    result = list_categories(
        db,
        site_id,
        search=search,
        active_state=active_state,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post("/sites/{site_id}/page-categories", response_model=PageCategoryRead, status_code=201)
def post_page_category(
    site_id: int, payload: PageCategoryCreate, db: DbSession
) -> PageCategoryRead:
    try:
        category = create_category(db, site_id, payload)
    except DuplicateCategoryError as exc:
        raise HTTPException(409, str(exc)) from exc
    if category is None:
        raise HTTPException(404, "Site not found")
    return PageCategoryRead.model_validate(category)


@router.patch("/sites/{site_id}/page-categories/{category_id}", response_model=PageCategoryRead)
def patch_page_category(
    site_id: int, category_id: int, payload: PageCategoryUpdate, db: DbSession
) -> PageCategoryRead:
    try:
        category = update_category(db, site_id, category_id, payload)
    except DuplicateCategoryError as exc:
        raise HTTPException(409, str(exc)) from exc
    if category is None:
        raise HTTPException(404, "Category not found")
    return PageCategoryRead.model_validate(category)


@router.get(
    "/sites/{site_id}/page-categories/{category_id}/deletion-preview",
    response_model=PageCategoryDeletionPreview,
)
def get_page_category_deletion_preview(
    site_id: int, category_id: int, db: DbSession
) -> PageCategoryDeletionPreview:
    result = preview_category_deletion(db, site_id, category_id)
    if result is None:
        raise HTTPException(404, "Category not found")
    return result


@router.delete("/sites/{site_id}/page-categories/{category_id}")
def delete_page_category(site_id: int, category_id: int, db: DbSession) -> dict[str, int]:
    deleted = delete_category(db, site_id, category_id)
    if deleted is None:
        raise HTTPException(404, "Category not found")
    return {"deleted_category_id": deleted}


@router.post("/sites/{site_id}/pages/bulk-categories", response_model=BulkMutationResult)
def post_bulk_page_categories(
    site_id: int, payload: BulkPageCategories, db: DbSession
) -> BulkMutationResult:
    try:
        return bulk_categories(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sites/{site_id}/pages/bulk-metadata", response_model=BulkMutationResult)
def post_bulk_page_metadata(
    site_id: int, payload: BulkPageMetadata, db: DbSession
) -> BulkMutationResult:
    try:
        return bulk_metadata(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sites/{site_id}/pages/bulk-workspace-state", response_model=BulkMutationResult)
def post_bulk_page_workspace_state(
    site_id: int, payload: BulkPageWorkspaceState, db: DbSession
) -> BulkMutationResult:
    try:
        return bulk_workspace_state(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sites/{site_id}/pages/bulk-delete", response_model=BulkMutationResult)
def post_bulk_page_delete(
    site_id: int, payload: BulkPageDelete, db: DbSession
) -> BulkMutationResult:
    try:
        return bulk_delete_pages(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/sites/{site_id}/pages", response_model=PersistentPageList)
def get_site_pages(
    site_id: int,
    db: DbSession,
    search: str | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    workflow_status: str | None = None,
    owner: str | None = None,
    unassigned_owner: bool = False,
    has_notes: bool | None = None,
    min_observations: int | None = Query(default=None, ge=0),
    workspace_state: Literal["active", "suppressed", "all"] = "active",
    sort: Literal[
        "url",
        "observations",
        "first_observed",
        "latest_observed",
        "owner",
        "workflow",
        "categories",
        "notes",
    ] = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> PersistentPageList:
    result = list_site_pages(
        db,
        site_id,
        search=search,
        host=host,
        path_prefix=path_prefix,
        category_id=category_id,
        uncategorized=uncategorized,
        workflow_status=workflow_status,
        owner=owner,
        unassigned_owner=unassigned_owner,
        has_notes=has_notes,
        min_observations=min_observations,
        workspace_state=workspace_state,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get("/sites/{site_id}/pages/{resource_id}", response_model=PersistentPageDetail)
def get_site_page_detail(site_id: int, resource_id: int, db: DbSession) -> PersistentPageDetail:
    result = get_site_page(db, site_id, resource_id)
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


@router.patch("/sites/{site_id}/pages/{resource_id}/metadata", response_model=PersistentPageDetail)
def patch_site_page_metadata(
    site_id: int, resource_id: int, payload: PageMetadataUpdate, db: DbSession
) -> PersistentPageDetail:
    site_page = find_site_page(db, site_id, resource_id)
    if site_page is None:
        raise HTTPException(404, "Page not found")
    try:
        update_page_metadata(db, site_page, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = get_site_page(db, site_id, resource_id)
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


@router.patch(
    "/sites/{site_id}/pages/{resource_id}/workspace-state",
    response_model=PersistentPageDetail,
)
def patch_site_page_workspace_state(
    site_id: int, resource_id: int, payload: PageWorkspaceStateUpdate, db: DbSession
) -> PersistentPageDetail:
    site_page = find_site_page(db, site_id, resource_id)
    if site_page is None:
        raise HTTPException(404, "Page not found")
    update_page_workspace_state(db, site_page, payload)
    result = get_site_page(db, site_id, resource_id)
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


@router.get(
    "/sites/{site_id}/pages/{resource_id}/observations",
    response_model=PageObservationList,
)
def get_site_page_observations(
    site_id: int,
    resource_id: int,
    db: DbSession,
    scope: Literal["site", "all"] = "site",
    scan_status: str | None = None,
    http_status: int | None = None,
    fetch_state: str | None = None,
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    retrieval_method: str | None = None,
    parse_method: str | None = None,
    direction: Literal["asc", "desc"] = "desc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> PageObservationList:
    result = list_page_observations(
        db,
        site_id,
        resource_id,
        scope=scope,
        scan_status=scan_status,
        http_status=http_status,
        fetch_state=fetch_state,
        error_state=error_state,
        retrieval_method=retrieval_method,
        parse_method=parse_method,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


@router.get("/sites/{site_id}/notes", response_model=NoteList)
def get_site_notes(
    site_id: int,
    db: DbSession,
    pinned: bool | None = None,
    search: str | None = None,
    sort: NoteSort = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> NoteList:
    if not site_exists(db, site_id):
        raise HTTPException(404, "Site not found")
    return list_notes(
        db,
        website_property_id=site_id,
        pinned=pinned,
        search=search,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/sites/{site_id}/notes", response_model=NoteRead, status_code=201)
def post_site_note(site_id: int, payload: NoteCreate, db: DbSession) -> NoteRead:
    if not site_exists(db, site_id):
        raise HTTPException(404, "Site not found")
    return NoteRead.model_validate(create_note(db, payload, website_property_id=site_id))


@router.get("/scans/{scan_id}/notes", response_model=NoteList)
def get_scan_notes(
    scan_id: int,
    db: DbSession,
    pinned: bool | None = None,
    search: str | None = None,
    sort: NoteSort = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> NoteList:
    if not scan_exists(db, scan_id):
        raise HTTPException(404, "Scan not found")
    return list_notes(
        db,
        scan_id=scan_id,
        pinned=pinned,
        search=search,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/scans/{scan_id}/notes", response_model=NoteRead, status_code=201)
def post_scan_note(scan_id: int, payload: NoteCreate, db: DbSession) -> NoteRead:
    if not scan_exists(db, scan_id):
        raise HTTPException(404, "Scan not found")
    return NoteRead.model_validate(create_note(db, payload, scan_id=scan_id))


@router.get("/sites/{site_id}/pages/{resource_id}/notes", response_model=NoteList)
def get_page_notes(
    site_id: int,
    resource_id: int,
    db: DbSession,
    pinned: bool | None = None,
    search: str | None = None,
    sort: NoteSort = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> NoteList:
    site_page = find_page_target(db, site_id, resource_id)
    if site_page is None:
        raise HTTPException(404, "Page not found")
    return list_notes(
        db,
        site_page_id=site_page.id,
        pinned=pinned,
        search=search,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/sites/{site_id}/pages/{resource_id}/notes", response_model=NoteRead, status_code=201)
def post_page_note(site_id: int, resource_id: int, payload: NoteCreate, db: DbSession) -> NoteRead:
    site_page = find_page_target(db, site_id, resource_id)
    if site_page is None:
        raise HTTPException(404, "Page not found")
    return NoteRead.model_validate(create_note(db, payload, site_page_id=site_page.id))


@router.patch("/notes/{note_id}", response_model=NoteRead)
def patch_note(note_id: int, payload: NoteUpdate, db: DbSession) -> NoteRead:
    note = update_note(db, note_id, payload)
    if note is None:
        raise HTTPException(404, "Note not found")
    return NoteRead.model_validate(note)


@router.delete("/notes/{note_id}")
def remove_note(note_id: int, db: DbSession) -> dict[str, int]:
    deleted = delete_note(db, note_id)
    if deleted is None:
        raise HTTPException(404, "Note not found")
    return {"deleted_note_id": deleted}


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
    result = ScanRead.model_validate(scan, from_attributes=True)
    result.note_count = db.scalar(select(func.count(Note.id)).where(Note.scan_id == scan.id)) or 0
    render_run = db.scalar(
        select(RenderRun).where(RenderRun.source_scan_id == scan.id).order_by(RenderRun.id.desc())
    )
    if render_run:
        result.render_run_id = render_run.id
        result.render_run_status = render_run.status
    return result


@router.post("/scans/{scan_id}/cancel", response_model=ScanRead)
def cancel_scan(scan_id: int, db: DbSession) -> Scan:
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    job = active_job_for_scan(db, scan_id)
    if job:
        request_cancellation(db, job)
        if job.status == "cancelled":
            scan.status = "cancelled"
            scan.stop_reason = "cancelled_by_user"
            db.commit()
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


@router.get("/scans/{scan_id}/projection", response_model=ScanProjectionStatusRead)
def get_scan_projection_status(scan_id: int, db: DbSession) -> ScanProjectionStatusRead:
    result = projection_status(db, scan_id)
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.post(
    "/scans/{scan_id}/projection/build",
    response_model=ScanProjectionBuildRead,
    status_code=202,
)
def build_scan_projection(scan_id: int, db: DbSession) -> ScanProjectionBuildRead:
    return _queue_scan_projection(db, scan_id, force=False)


@router.post(
    "/scans/{scan_id}/projection/rebuild",
    response_model=ScanProjectionBuildRead,
    status_code=202,
)
def rebuild_scan_projection(scan_id: int, db: DbSession) -> ScanProjectionBuildRead:
    return _queue_scan_projection(db, scan_id, force=True)


@router.post("/scans/{scan_id}/projection/verify")
def verify_scan_projection(scan_id: int, db: DbSession) -> dict[str, object]:
    try:
        return verify_projection_build(db, scan_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


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


@router.get("/scans/{scan_id}/resources", response_model=ResourceInventoryList)
def get_scan_resources(
    scan_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    search: str | None = None,
    resource_kind: str | None = None,
    mime_type: str | None = None,
    extension: str | None = None,
    host: str | None = None,
    status: int | None = None,
    evidence_state: Literal["any", "observed", "discovered_only"] = "any",
    scope_state: Literal["any", "in_scope", "out_of_scope"] = "any",
    location_state: Literal["any", "internal", "external"] = "any",
    min_size: int | None = Query(default=None, ge=0),
    max_size: int | None = Query(default=None, ge=0),
    has_multiple_source_pages: bool = False,
    sort: ResourceSortParam = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ResourceInventoryList | Response:
    result = list_scan_resources(
        db,
        scan_id,
        search=search,
        resource_kind=resource_kind,
        mime_type=mime_type,
        extension=extension,
        host=host,
        status=status,
        evidence_state=evidence_state,
        scope_state=scope_state,
        location_state=location_state,
        min_size=min_size,
        max_size=max_size,
        has_multiple_source_pages=has_multiple_source_pages,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Scan not found")
    return _projection_http_response(request, response, result)


@router.get("/sites/{site_id}/resources", response_model=ResourceInventoryList)
def get_site_resources(
    site_id: int,
    db: DbSession,
    search: str | None = None,
    resource_kind: str | None = None,
    mime_type: str | None = None,
    extension: str | None = None,
    host: str | None = None,
    status: int | None = None,
    evidence_state: Literal["any", "observed", "discovered_only"] = "any",
    scope_state: Literal["any", "in_scope", "out_of_scope"] = "any",
    location_state: Literal["any", "internal", "external"] = "any",
    min_size: int | None = Query(default=None, ge=0),
    max_size: int | None = Query(default=None, ge=0),
    has_multiple_source_pages: bool = False,
    sort: ResourceSortParam = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ResourceInventoryList:
    result = list_site_resources(
        db,
        site_id,
        search=search,
        resource_kind=resource_kind,
        mime_type=mime_type,
        extension=extension,
        host=host,
        status=status,
        evidence_state=evidence_state,
        scope_state=scope_state,
        location_state=location_state,
        min_size=min_size,
        max_size=max_size,
        has_multiple_source_pages=has_multiple_source_pages,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get("/sites/{site_id}/resources/summary", response_model=ResourceSummary)
def get_site_resource_summary(site_id: int, db: DbSession) -> ResourceSummary:
    result = site_resource_summary(db, site_id)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get("/sites/{site_id}/resources/{resource_id}", response_model=ResourceDetail)
def get_site_resource_detail(site_id: int, resource_id: int, db: DbSession) -> ResourceDetail:
    result = get_site_resource(db, site_id, resource_id)
    if result is None:
        raise HTTPException(404, "Resource not found")
    return result


@router.get(
    "/sites/{site_id}/resources/{resource_id}/history",
    response_model=ResourceHistoryList,
)
def get_site_resource_history(
    site_id: int,
    resource_id: int,
    db: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ResourceHistoryList:
    result = list_site_resource_history(db, site_id, resource_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(404, "Resource not found")
    return result


@router.get(
    "/sites/{site_id}/resources/{resource_id}/occurrences",
    response_model=ResourceOccurrenceList,
)
def get_site_resource_occurrences(
    site_id: int,
    resource_id: int,
    db: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ResourceOccurrenceList:
    if get_site_resource(db, site_id, resource_id) is None:
        raise HTTPException(404, "Resource not found")
    return list_resource_occurrences(db, resource_id, site_id=site_id, limit=limit, offset=offset)


@router.get("/scans/{scan_id}/resources/summary", response_model=ResourceSummary)
def get_scan_resource_summary(
    scan_id: int, request: Request, response: Response, db: DbSession
) -> ResourceSummary | Response:
    result = scan_resource_summary(db, scan_id)
    if result is None:
        raise HTTPException(404, "Scan not found")
    return _projection_http_response(request, response, result)


@router.get("/scans/{scan_id}/resources/{resource_id}", response_model=ResourceDetail)
def get_scan_resource_detail(scan_id: int, resource_id: int, db: DbSession) -> ResourceDetail:
    result = get_scan_resource(db, scan_id, resource_id)
    if result is None:
        raise HTTPException(404, "Resource not found")
    return result


@router.get(
    "/scans/{scan_id}/resources/{resource_id}/occurrences",
    response_model=ResourceOccurrenceList,
)
def get_scan_resource_occurrences(
    scan_id: int,
    resource_id: int,
    db: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ResourceOccurrenceList:
    if get_scan_resource(db, scan_id, resource_id) is None:
        raise HTTPException(404, "Resource not found")
    return list_resource_occurrences(db, resource_id, scan_id=scan_id, limit=limit, offset=offset)


@router.get(
    "/scans/{scan_id}/rendered-observations",
    response_model=RenderedObservationIndexList,
)
def get_scan_rendered_observations(
    scan_id: int,
    db: DbSession,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_console_messages: bool | None = None,
    has_blocked_requests: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    has_full_page_screenshot: bool | None = None,
    has_rendered_dom: bool | None = None,
    sort: Literal[
        "page_url",
        "capture_state",
        "duration",
        "navigation_status",
        "warning_count",
        "page_error_count",
        "browser_evidence",
        "capture_time",
    ] = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedObservationIndexList:
    if db.get(Scan, scan_id) is None:
        raise HTTPException(404, "Scan not found")
    return list_scan_rendered_observations(
        db,
        scan_id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_console_messages=has_console_messages,
        has_blocked_requests=has_blocked_requests,
        has_viewport_screenshot=has_viewport_screenshot,
        has_full_page_screenshot=has_full_page_screenshot,
        has_rendered_dom=has_rendered_dom,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.get("/scans/{scan_id}/graph", response_model=GraphResponse)
def get_graph(
    scan_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    max_nodes: int = Query(
        GRAPH_CONFIG.default_node_limit,
        ge=1,
        le=GRAPH_CONFIG.maximum_node_limit,
    ),
    max_edges: int = Query(
        GRAPH_CONFIG.default_edge_limit,
        ge=0,
        le=GRAPH_CONFIG.maximum_edge_limit,
    ),
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
    focus_hops: int = Query(
        GRAPH_CONFIG.default_focus_hops,
        ge=1,
        le=GRAPH_CONFIG.maximum_focus_hops,
    ),
) -> GraphResponse | Response:
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
    return _projection_http_response(request, response, graph)


@router.get("/graph/capabilities", response_model=GraphCapabilitiesRead)
def graph_capabilities() -> GraphCapabilitiesRead:
    return get_graph_capabilities()


@router.get("/rendering/capabilities", response_model=RenderCapabilitiesRead)
def rendering_capabilities() -> dict[str, object]:
    return render_capabilities_data()


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
    result = get_snapshot_detail(db, snapshot_id)
    if result is None:
        raise HTTPException(404, "Snapshot not found")
    return result


@router.get(
    "/snapshots/{snapshot_id}/static-fetch-attempts",
    response_model=list[StaticFetchAttemptRead],
)
def list_static_fetch_attempts(snapshot_id: int, db: DbSession) -> list[StaticFetchAttempt]:
    if db.get(ResourceSnapshot, snapshot_id) is None:
        raise HTTPException(404, "Snapshot not found")
    return list(
        db.scalars(
            select(StaticFetchAttempt)
            .where(StaticFetchAttempt.snapshot_id == snapshot_id)
            .order_by(StaticFetchAttempt.attempt_number)
        )
    )


def _rendered_read(observation: RenderedObservation) -> RenderedObservationRead:
    data = {
        column.name: getattr(observation, column.name)
        for column in RenderedObservation.__table__.columns
    }
    data["artifacts"] = [
        RenderedArtifactRead(
            id=item.id,
            artifact_type=item.artifact_type,
            width=item.width,
            height=item.height,
            media_type=item.blob.media_type,
            raw_byte_size=item.blob.raw_byte_size,
            stored_byte_size=item.blob.stored_byte_size,
            sha256=item.blob.sha256,
            metadata_json=item.metadata_json,
        )
        for item in observation.artifacts
    ]
    return RenderedObservationRead(**data)


@router.get("/snapshots/{snapshot_id}/rendered", response_model=RenderedObservationRead)
def get_snapshot_rendered(snapshot_id: int, db: DbSession) -> RenderedObservationRead:
    observation = db.scalar(
        select(RenderedObservation).where(RenderedObservation.snapshot_id == snapshot_id)
    )
    if observation is None:
        raise HTTPException(404, "Snapshot has no rendered observation")
    return _rendered_read(observation)


@router.get("/rendered-observations/{rendered_id}", response_model=RenderedObservationRead)
def get_rendered_observation(rendered_id: int, db: DbSession) -> RenderedObservationRead:
    observation = db.get(RenderedObservation, rendered_id)
    if observation is None:
        raise HTTPException(404, "Rendered observation not found")
    return _rendered_read(observation)


@router.get(
    "/rendered-observations/{rendered_id}/artifacts", response_model=list[RenderedArtifactRead]
)
def list_rendered_artifacts(rendered_id: int, db: DbSession) -> list[RenderedArtifactRead]:
    return get_rendered_observation(rendered_id, db).artifacts


@router.get("/rendered-observations/{rendered_id}/network", response_model=RenderedEventList)
def list_rendered_network(
    rendered_id: int,
    db: DbSession,
    search: str | None = None,
    resource_type: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedEventList:
    query = select(RenderedNetworkEntry).where(
        RenderedNetworkEntry.rendered_observation_id == rendered_id
    )
    if search:
        query = query.where(RenderedNetworkEntry.redacted_url.ilike(f"%{search}%"))
    if resource_type:
        query = query.where(RenderedNetworkEntry.resource_type == resource_type)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.order_by(RenderedNetworkEntry.sequence).limit(limit).offset(offset))
    )
    return RenderedEventList(
        items=[RenderedNetworkEntryRead.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rendered-observations/{rendered_id}/console", response_model=RenderedEventList)
def list_rendered_console(
    rendered_id: int,
    db: DbSession,
    search: str | None = None,
    message_type: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedEventList:
    query = select(RenderedConsoleMessage).where(
        RenderedConsoleMessage.rendered_observation_id == rendered_id
    )
    if search:
        query = query.where(RenderedConsoleMessage.text.ilike(f"%{search}%"))
    if message_type:
        query = query.where(RenderedConsoleMessage.message_type == message_type)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.order_by(RenderedConsoleMessage.sequence).limit(limit).offset(offset))
    )
    return RenderedEventList(
        items=[RenderedConsoleMessageRead.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rendered-observations/{rendered_id}/errors", response_model=RenderedEventList)
def list_rendered_errors(
    rendered_id: int,
    db: DbSession,
    search: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedEventList:
    query = select(RenderedPageError).where(
        RenderedPageError.rendered_observation_id == rendered_id
    )
    if search:
        query = query.where(RenderedPageError.message.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(db.scalars(query.order_by(RenderedPageError.sequence).limit(limit).offset(offset)))
    return RenderedEventList(
        items=[RenderedPageErrorRead.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rendered-artifacts/{artifact_id}/content")
def get_rendered_artifact_content(artifact_id: int, request: Request, db: DbSession) -> Response:
    artifact = db.get(RenderedArtifact, artifact_id)
    if artifact is None or artifact.artifact_type not in {
        "rendered_dom",
        "viewport_screenshot",
        "full_page_screenshot",
    }:
        raise HTTPException(404, "Rendered artifact not found")
    store: LocalArtifactStore = request.app.state.artifact_store
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"}
    try:
        if artifact.artifact_type == "rendered_dom":
            return Response(
                store.read(artifact.blob), media_type="text/plain; charset=utf-8", headers=headers
            )
        return FileResponse(store.path_for(artifact.blob), media_type="image/png", headers=headers)
    except ArtifactNotFoundError as exc:
        raise HTTPException(404, "Rendered artifact file is missing") from exc


@router.get("/snapshots/{snapshot_id}/links", response_model=list[LinkRead])
def get_snapshot_links(snapshot_id: int, db: DbSession) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id == snapshot_id)
        )
    )


@router.get("/snapshots/{snapshot_id}/outgoing-links", response_model=OutgoingLinkList)
def get_snapshot_outgoing_links(
    snapshot_id: int,
    db: DbSession,
    search: str | None = None,
    scope_decision: str | None = None,
    link_role: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> OutgoingLinkList:
    result = list_snapshot_outgoing_links(
        db,
        snapshot_id,
        search=search,
        scope_decision=scope_decision,
        link_role=link_role,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Snapshot not found")
    return result


@router.get("/snapshots/{snapshot_id}/inbound-links", response_model=InboundLinkList)
def get_snapshot_inbound_links(
    snapshot_id: int,
    db: DbSession,
    search: str | None = None,
    scope_decision: str | None = None,
    source_status: int | None = None,
    rel: str | None = None,
    link_role: str | None = None,
    sort: Literal[
        "source_url",
        "source_status",
        "source_depth",
        "anchor_text",
        "link_role",
        "raw_href",
        "rel",
        "scope_decision",
        "discovered_at",
    ] = "source_url",
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
        link_role=link_role,
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


def _queue_scan_projection(db: Session, scan_id: int, *, force: bool) -> ScanProjectionBuildRead:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found")
    try:
        build = create_projection_build(db, scan_id, force=force)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if build.status == "queued":
        enqueue_scan_projection_job(db, build.id, scan)
    db.commit()
    db.refresh(build)
    return ScanProjectionBuildRead.model_validate(build)


def _projection_http_response(
    request: Request,
    response: Response,
    result: ProjectionResponseT,
    *,
    immutable: bool = True,
) -> ProjectionResponseT | Response:
    metadata = result.projection
    if metadata is None:
        return result
    response.headers["X-Projection-Source"] = metadata.projection_source
    response.headers["X-Projection-Version"] = metadata.projection_version
    response.headers["X-Projection-Status"] = metadata.projection_status
    if metadata.projection_source != "materialized" or metadata.projection_build_id is None:
        return result
    response.headers["X-Projection-Build-Id"] = str(metadata.projection_build_id)
    if not immutable:
        response.headers["Cache-Control"] = "private, no-cache"
        return result
    identity = (
        f"{request.url.path}?{request.url.query}|{metadata.projection_version}|"
        f"{metadata.projection_build_id}"
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    etag = f'"scan-{metadata.projection_build_id}-{digest[:24]}"'
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "X-Projection-Source": metadata.projection_source,
        "X-Projection-Version": metadata.projection_version,
        "X-Projection-Status": metadata.projection_status,
        "X-Projection-Build-Id": str(metadata.projection_build_id),
    }
    response.headers.update(headers)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return result


def _job_read(job: BackgroundJob, health: WorkerHealth) -> JobRead:
    return JobRead(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        presentation_status=presentation_status(job, health),
        priority=job.priority,
        scan_id=job.scan_id,
        source_refresh_id=job.source_refresh_id,
        scan_comparison_id=job.scan_comparison_id,
        performance_run_id=job.performance_run_id,
        accessibility_run_id=job.accessibility_run_id,
        website_property_id=job.website_property_id,
        dedupe_key=job.dedupe_key,
        payload_json=job.payload_json,
        progress_version=job.progress_version,
        progress_json=job.progress_json,
        current_operation=job.current_operation,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        progress_unit=job.progress_unit,
        result_json=job.result_json,
        created_at=job.created_at,
        available_at=job.available_at,
        claimed_at=job.claimed_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        lease_expires_at=job.lease_expires_at,
        finished_at=job.finished_at,
        worker_id=job.worker_id,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        cancellation_requested_at=job.cancellation_requested_at,
        cancelled_at=job.cancelled_at,
        error_type=job.error_type,
        error_message=job.error_message,
        last_error_at=job.last_error_at,
    )
