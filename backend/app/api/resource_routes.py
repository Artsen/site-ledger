from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.dependencies import DbSession, PageLimit, PageOffset, ResourceSortParam
from app.api.projection_routes import _projection_http_response
from app.schemas.resources import (
    ResourceDetail,
    ResourceHistoryList,
    ResourceInventoryList,
    ResourceOccurrenceList,
    ResourceSummary,
)
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

router = APIRouter(prefix="/api")


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
