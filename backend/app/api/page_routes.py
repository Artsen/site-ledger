from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import DbSession, PageLimit, PageOffset
from app.schemas.page_workspaces import (
    BulkMutationResult,
    BulkPageCategories,
    BulkPageDelete,
    BulkPageMetadata,
    BulkPageWorkspaceState,
    PageCategoryCreate,
    PageCategoryDeletionPreview,
    PageCategoryList,
    PageCategoryRead,
    PageCategoryUpdate,
    PageMetadataUpdate,
    PageWorkspaceStateUpdate,
)
from app.schemas.scans import (
    PageObservationList,
    PersistentPageDetail,
    PersistentPageList,
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
from app.services.site_pages import (
    bulk_categories,
    bulk_delete_pages,
    bulk_metadata,
    bulk_workspace_state,
    find_site_page,
    update_page_metadata,
    update_page_workspace_state,
)

router = APIRouter(prefix="/api")


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
