from collections import defaultdict
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ResourceSnapshot,
    Scan,
    ScanSeed,
    SourceRefresh,
    UrlSource,
    UrlSourceEntry,
    WebsiteProperty,
)
from app.schemas.sources import (
    InventoryItem,
    InventoryList,
    ScanSeedList,
    SourceRefreshRead,
    UrlSourceEntryList,
    UrlSourceList,
    UrlSourceRead,
)
from app.services.inventory_lifecycle import (
    inventory_group_identity,
    inventory_suppression_map,
    matching_inventory_suppression,
)
from app.services.url_identity import active_url_normalization_version


def list_sources(
    db: Session,
    site_id: int,
    *,
    source_type: str | None,
    active_state: Literal["active", "inactive", "all"],
    limit: int,
    offset: int,
) -> UrlSourceList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    current_counts = (
        select(
            UrlSourceEntry.url_source_id.label("source_id"),
            func.count(UrlSourceEntry.id).label("current_count"),
        )
        .where(UrlSourceEntry.is_current.is_(True))
        .group_by(UrlSourceEntry.url_source_id)
        .subquery()
    )
    query = (
        select(UrlSource, func.coalesce(current_counts.c.current_count, 0))
        .outerjoin(current_counts, current_counts.c.source_id == UrlSource.id)
        .where(UrlSource.website_property_id == site_id)
    )
    if source_type:
        query = query.where(UrlSource.source_type == source_type)
    if active_state == "active":
        query = query.where(UrlSource.is_active.is_(True))
    elif active_state == "inactive":
        query = query.where(UrlSource.is_active.is_(False))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(UrlSource.created_at.desc()).limit(limit).offset(offset)).all()
    items = []
    for source, count in rows:
        item = UrlSourceRead.model_validate(source, from_attributes=True)
        item.current_entry_count = count
        items.append(item)
    return UrlSourceList(items=items, total=total, limit=limit, offset=offset)


def list_source_entries(
    db: Session,
    site_id: int,
    source_id: int,
    *,
    search: str | None,
    current_state: Literal["current", "not_current", "all"],
    validation_state: str | None,
    scope_decision: str | None,
    limit: int,
    offset: int,
) -> UrlSourceEntryList | None:
    source = db.scalar(
        select(UrlSource).where(UrlSource.id == source_id, UrlSource.website_property_id == site_id)
    )
    if source is None:
        return None
    query = select(UrlSourceEntry).where(UrlSourceEntry.url_source_id == source.id)
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(UrlSourceEntry.raw_url.ilike(like), UrlSourceEntry.normalized_url.ilike(like))
        )
    if current_state == "current":
        query = query.where(UrlSourceEntry.is_current.is_(True))
    elif current_state == "not_current":
        query = query.where(UrlSourceEntry.is_current.is_(False))
    if validation_state:
        query = query.where(UrlSourceEntry.validation_state == validation_state)
    if scope_decision:
        query = query.where(UrlSourceEntry.scope_decision == scope_decision)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.order_by(UrlSourceEntry.normalized_url).limit(limit).offset(offset))
    )
    return UrlSourceEntryList(items=items, total=total, limit=limit, offset=offset)


def list_refreshes(
    db: Session, site_id: int, source_id: int, *, limit: int, offset: int
) -> list[SourceRefreshRead] | None:
    source = db.scalar(
        select(UrlSource).where(UrlSource.id == source_id, UrlSource.website_property_id == site_id)
    )
    if source is None:
        return None
    refreshes = db.scalars(
        select(SourceRefresh)
        .where(SourceRefresh.url_source_id == source.id)
        .order_by(SourceRefresh.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        SourceRefreshRead.model_validate(refresh, from_attributes=True) for refresh in refreshes
    ]


def list_inventory(
    db: Session,
    site_id: int,
    *,
    search: str | None,
    source_type: str | None,
    source_id: int | None,
    scope_decision: str | None,
    validation_state: str | None,
    visibility: Literal["active", "suppressed", "all"] = "active",
    limit: int,
    offset: int,
) -> InventoryList | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    query = (
        select(UrlSourceEntry)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .where(UrlSource.website_property_id == site_id, UrlSourceEntry.is_current.is_(True))
    )
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(UrlSourceEntry.raw_url.ilike(like), UrlSourceEntry.normalized_url.ilike(like))
        )
    if source_type:
        query = query.where(UrlSource.source_type == source_type)
    if source_id:
        query = query.where(UrlSource.id == source_id)
    if scope_decision:
        query = query.where(UrlSourceEntry.scope_decision == scope_decision)
    if validation_state:
        query = query.where(UrlSourceEntry.validation_state == validation_state)
    entries = list(
        db.scalars(
            query.options(selectinload(UrlSourceEntry.url_source)).order_by(
                UrlSourceEntry.normalized_url, UrlSourceEntry.raw_url, UrlSourceEntry.id
            )
        )
    )
    active_version = active_url_normalization_version(db)
    grouped: dict[tuple[str, str], list[UrlSourceEntry]] = defaultdict(list)
    for entry in entries:
        key = inventory_group_identity(db, site, entry, active_version=active_version)
        grouped[key].append(entry)
    suppressions = inventory_suppression_map(db, site, active_version=active_version)
    suppression_by_key = {
        key: matching_inventory_suppression(
            db, site, members[0], suppressions, active_version=active_version
        )
        for key, members in grouped.items()
    }
    keys = sorted(
        key
        for key in grouped
        if visibility == "all"
        or (visibility == "suppressed" and suppression_by_key[key] is not None)
        or (visibility == "active" and suppression_by_key[key] is None)
    )
    page_keys = keys[offset : offset + limit]
    latest = _latest_scan_by_resource(
        db, [entry.resource_id for key in page_keys for entry in grouped[key]]
    )
    items: list[InventoryItem] = []
    for key in page_keys:
        members = grouped[key]
        first = members[0]
        latest_row = latest.get(first.resource_id or -1)
        source_types = sorted({member.url_source.source_type for member in members})
        classification = _inventory_classification(first, latest_row is not None)
        suppression = suppression_by_key[key]
        items.append(
            InventoryItem(
                normalized_url=first.normalized_url,
                resource_id=first.resource_id,
                source_count=len(members),
                source_types=source_types,
                sources=[
                    {
                        "id": member.url_source_id,
                        "name": member.url_source.name,
                        "type": member.url_source.source_type,
                        "entry_id": member.id,
                        "raw_url": member.raw_url,
                    }
                    for member in members
                ],
                scope_decision=first.scope_decision,
                validation_state=first.validation_state,
                sitemap_lastmod=first.sitemap_lastmod,
                latest_scan_status=latest_row[0] if latest_row else None,
                latest_fetch_date=latest_row[1] if latest_row else None,
                classification=classification,
                suppression_id=suppression.id if suppression else None,
                is_suppressed=suppression is not None,
                suppressed_at=suppression.created_at if suppression else None,
            )
        )
    return InventoryList(items=items, total=len(keys), limit=limit, offset=offset)


def list_scan_seeds(db: Session, scan_id: int, *, limit: int, offset: int) -> ScanSeedList | None:
    if db.get(Scan, scan_id) is None:
        return None
    query = (
        select(ScanSeed)
        .where(ScanSeed.scan_id == scan_id)
        .options(selectinload(ScanSeed.origins))
        .order_by(ScanSeed.created_at, ScanSeed.id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(db.scalars(query.limit(limit).offset(offset)))
    return ScanSeedList(items=items, total=total, limit=limit, offset=offset)


def _latest_scan_by_resource(
    db: Session, resource_ids: list[int | None]
) -> dict[int, tuple[str, object]]:
    ids = [resource_id for resource_id in resource_ids if resource_id is not None]
    if not ids:
        return {}
    subq = (
        select(
            ResourceSnapshot.resource_id,
            func.max(ResourceSnapshot.fetched_at).label("latest_at"),
        )
        .where(ResourceSnapshot.resource_id.in_(ids))
        .group_by(ResourceSnapshot.resource_id)
        .subquery()
    )
    rows = db.execute(
        select(ResourceSnapshot.resource_id, Scan.status, ResourceSnapshot.fetched_at)
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .join(
            subq,
            and_(
                subq.c.resource_id == ResourceSnapshot.resource_id,
                subq.c.latest_at == ResourceSnapshot.fetched_at,
            ),
        )
    )
    return {resource_id: (status, fetched_at) for resource_id, status, fetched_at in rows}


def _inventory_classification(entry: UrlSourceEntry, crawled: bool) -> str:
    if entry.validation_state != "valid":
        return "invalid"
    if entry.scope_decision != "crawlable":
        return "out_of_scope"
    return "source_and_crawl" if crawled else "source_only"
