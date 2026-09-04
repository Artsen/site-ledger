from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import DbSession, PageOffset, ScanListLimit
from app.schemas.sites import (
    SiteDeleteResult,
    WebsitePropertyCreate,
    WebsitePropertyList,
    WebsitePropertyRead,
    WebsitePropertyUpdate,
)
from app.services.site_management import (
    DuplicateSiteError,
    SiteHasScansError,
    create_site,
    delete_site,
    update_site,
)
from app.services.site_queries import get_site_detail, list_sites

router = APIRouter(prefix="/api")


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
