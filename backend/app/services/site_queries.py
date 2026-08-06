from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Note, PageCategory, Scan, WebsiteProperty
from app.schemas.sites import (
    ScanSummary,
    SiteScans,
    WebsitePropertyList,
    WebsitePropertyListItem,
    WebsitePropertyRead,
)


def list_sites(
    db: Session,
    search: str | None,
    group_key: str | None,
    locale: str | None,
    platform_key: str | None,
    ownership_key: str | None,
    active_state: Literal["active", "inactive", "all"],
    sort: Literal["name", "base_url", "created_at", "updated_at", "latest_scan_at"],
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> WebsitePropertyList:
    latest_id = select(func.max(Scan.id)).group_by(Scan.website_property_id)
    stats = (
        select(
            Scan.website_property_id.label("site_id"),
            func.count(Scan.id).label("scan_count"),
            func.max(Scan.id).label("latest_scan_id"),
        )
        .where(Scan.website_property_id.is_not(None))
        .group_by(Scan.website_property_id)
        .subquery()
    )
    latest = (
        select(
            Scan.id.label("scan_id"),
            Scan.website_property_id.label("site_id"),
            Scan.status,
            Scan.created_at,
            Scan.discovered_count,
            Scan.failed_count,
        )
        .where(Scan.id.in_(latest_id))
        .subquery()
    )
    query = (
        select(WebsiteProperty, stats.c.scan_count, latest)
        .outerjoin(stats, stats.c.site_id == WebsiteProperty.id)
        .outerjoin(latest, latest.c.site_id == WebsiteProperty.id)
    )
    query = _apply_site_filters(query, search, group_key, locale, platform_key, ownership_key)
    if active_state == "active":
        query = query.where(WebsiteProperty.is_active.is_(True))
    elif active_state == "inactive":
        query = query.where(WebsiteProperty.is_active.is_(False))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "name": WebsiteProperty.name,
        "base_url": WebsiteProperty.base_url,
        "created_at": WebsiteProperty.created_at,
        "updated_at": WebsiteProperty.updated_at,
        "latest_scan_at": latest.c.created_at,
    }
    order_col = sort_map[sort]
    order = order_col.desc() if direction == "desc" else order_col.asc()
    id_order = WebsiteProperty.id.desc() if direction == "desc" else WebsiteProperty.id.asc()
    rows = db.execute(
        query.order_by(order, id_order)
        .limit(limit)
        .offset(offset)
    ).all()
    return WebsitePropertyList(
        items=[
            WebsitePropertyListItem(
                id=site.id,
                name=site.name,
                base_url=site.base_url,
                normalized_base_url=site.normalized_base_url,
                description=site.description,
                group_key=site.group_key,
                locale=site.locale,
                platform_key=site.platform_key,
                ownership_key=site.ownership_key,
                scope_config=site.scope_config,
                is_active=site.is_active,
                created_at=site.created_at,
                updated_at=site.updated_at,
                total_scan_count=scan_count or 0,
                latest_scan_id=scan_id,
                latest_scan_status=status,
                latest_scan_date=created_at,
                latest_scan_discovered_count=discovered_count,
                latest_scan_failed_count=failed_count,
            )
            for (
                site,
                scan_count,
                scan_id,
                _site_id,
                status,
                created_at,
                discovered_count,
                failed_count,
            ) in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_site_detail(db: Session, site_id: int) -> WebsitePropertyRead | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    total = db.scalar(select(func.count(Scan.id)).where(Scan.website_property_id == site.id)) or 0
    recent = list(
        db.scalars(
            select(Scan)
            .options(joinedload(Scan.website_property))
            .where(Scan.website_property_id == site.id)
            .order_by(Scan.created_at.desc(), Scan.id.desc())
            .limit(5)
        )
    )
    latest = recent[0] if recent else None
    return WebsitePropertyRead(
        id=site.id,
        name=site.name,
        base_url=site.base_url,
        normalized_base_url=site.normalized_base_url,
        description=site.description,
        group_key=site.group_key,
        locale=site.locale,
        platform_key=site.platform_key,
        ownership_key=site.ownership_key,
        scope_config=site.scope_config,
        is_active=site.is_active,
        created_at=site.created_at,
        updated_at=site.updated_at,
        total_scan_count=total,
        latest_scan=_scan_summary(latest) if latest else None,
        recent_scans=[_scan_summary(scan) for scan in recent],
        note_count=db.scalar(select(func.count(Note.id)).where(Note.website_property_id == site.id))
        or 0,
        category_count=db.scalar(
            select(func.count(PageCategory.id)).where(PageCategory.website_property_id == site.id)
        )
        or 0,
    )


def list_site_scans(
    db: Session,
    site_id: int,
    status: str | None,
    sort: Literal["created_at", "started_at", "finished_at", "status", "starting_url"],
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> SiteScans | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    query = (
        select(Scan)
        .options(joinedload(Scan.website_property))
        .where(Scan.website_property_id == site_id)
    )
    if status:
        query = query.where(Scan.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "created_at": Scan.created_at,
        "started_at": Scan.started_at,
        "finished_at": Scan.finished_at,
        "status": Scan.status,
        "starting_url": Scan.starting_url,
    }
    order_col = sort_map[sort]
    scans = list(
        db.scalars(
            query.order_by(order_col.desc() if direction == "desc" else order_col.asc())
            .order_by(Scan.id.desc() if direction == "desc" else Scan.id.asc())
            .limit(limit)
            .offset(offset)
        )
    )
    return SiteScans(
        items=[_scan_summary(scan) for scan in scans],
        total=total,
        limit=limit,
        offset=offset,
    )


def _apply_site_filters(
    query: Any,
    search: str | None,
    group_key: str | None,
    locale: str | None,
    platform_key: str | None,
    ownership_key: str | None,
) -> Any:
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                WebsiteProperty.name.ilike(pattern),
                WebsiteProperty.base_url.ilike(pattern),
                WebsiteProperty.description.ilike(pattern),
            )
        )
    if group_key:
        query = query.where(WebsiteProperty.group_key == group_key)
    if locale:
        query = query.where(WebsiteProperty.locale == locale)
    if platform_key:
        query = query.where(WebsiteProperty.platform_key == platform_key)
    if ownership_key:
        query = query.where(WebsiteProperty.ownership_key == ownership_key)
    return query


def _scan_summary(scan: Scan) -> ScanSummary:
    return ScanSummary(
        id=scan.id,
        website_property_id=scan.website_property_id,
        website_property_name=scan.website_property_name,
        website_property_base_url=scan.website_property_base_url,
        starting_url=scan.starting_url,
        status=scan.status,
        scope_config=scan.scope_config,
        created_at=scan.created_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        discovered_count=scan.discovered_count,
        fetched_count=scan.fetched_count,
        failed_count=scan.failed_count,
        skipped_count=scan.skipped_count,
        queued_count=scan.queued_count,
        stop_reason=scan.stop_reason,
        fatal_error_message=scan.fatal_error_message,
    )
