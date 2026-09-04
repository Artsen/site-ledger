from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.dependencies import DbSession, PageLimit, PageOffset, ScanListLimit
from app.models import (
    SourceRefresh,
)
from app.schemas.page_workspaces import (
    BulkMutationResult,
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
    SourceRefreshRead,
    UrlSourceCreate,
    UrlSourceEntryList,
    UrlSourceEntryRead,
    UrlSourceList,
    UrlSourceRead,
    UrlSourceUpdate,
)
from app.services.background_jobs import (
    active_job_for_source_refresh,
    enqueue_source_refresh_job,
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
from app.services.native_cancellation import request_native_cancellation
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
    list_source_entries,
    list_sources,
)
from app.services.source_refresh import (
    create_robots_discovery_refresh,
    create_source_refresh,
    enqueue_bulk_source_refreshes,
)

router = APIRouter(prefix="/api")


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
        request_native_cancellation(db, job)
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
