from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, Scan, SitePage, UrlSourceEntry, WebsiteProperty
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate, WebsitePropertyUpdate
from app.services.scan_seeds import create_scan_seeds
from app.services.site_urls import normalize_site_base_url


class DuplicateSiteError(ValueError):
    pass


class SiteHasScansError(ValueError):
    pass


class InactiveSiteError(ValueError):
    pass


def create_site(db: Session, payload: WebsitePropertyCreate) -> WebsiteProperty:
    normalized = normalize_site_base_url(payload.base_url)
    _ensure_unique_base_url(db, normalized)
    site = WebsiteProperty(
        name=payload.name.strip(),
        base_url=normalized,
        normalized_base_url=normalized,
        description=payload.description,
        group_key=payload.group_key,
        locale=payload.locale,
        platform_key=payload.platform_key,
        ownership_key=payload.ownership_key,
        scope_config=payload.scope_config.model_dump(),
        is_active=payload.is_active,
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


def update_site(
    db: Session, site_id: int, payload: WebsitePropertyUpdate
) -> WebsiteProperty | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    updates = payload.model_dump(exclude_unset=True)
    if "base_url" in updates and updates["base_url"] is not None:
        normalized = normalize_site_base_url(updates.pop("base_url"))
        if normalized != site.normalized_base_url:
            _ensure_unique_base_url(db, normalized, site_id=site.id)
        site.base_url = normalized
        site.normalized_base_url = normalized
    if "scope_config" in updates and updates["scope_config"] is not None:
        scope_config = updates.pop("scope_config")
        site.scope_config = (
            scope_config.model_dump() if hasattr(scope_config, "model_dump") else scope_config
        )
    for key, value in updates.items():
        if key == "name" and isinstance(value, str):
            value = value.strip()
        setattr(site, key, value)
    db.commit()
    db.refresh(site)
    return site


def delete_site(db: Session, site_id: int) -> int | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    scan_count = db.scalar(select(func.count(Scan.id)).where(Scan.website_property_id == site.id))
    if scan_count:
        raise SiteHasScansError("Delete or detach this site's scans before deleting the site.")
    active_job_count = db.scalar(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.website_property_id == site.id,
            BackgroundJob.status.in_({"queued", "running"}),
        )
    )
    if active_job_count:
        raise SiteHasScansError("The site has active background work.")
    source_resource_ids = list(
        db.scalars(
            select(distinct(UrlSourceEntry.resource_id))
            .join(UrlSourceEntry.url_source)
            .where(
                UrlSourceEntry.resource_id.is_not(None),
                UrlSourceEntry.url_source.has(website_property_id=site.id),
            )
        )
    )
    from app.models import AiDocumentReference, AiDocumentRefresh, AiDocumentSnapshot, SourceRefresh

    ai_refresh_ids = (
        select(AiDocumentRefresh.id)
        .join(SourceRefresh)
        .where(SourceRefresh.url_source.has(website_property_id=site.id))
    )
    ai_resource_ids = list(
        db.scalars(
            select(AiDocumentSnapshot.resource_id).where(
                AiDocumentSnapshot.refresh_id.in_(ai_refresh_ids)
            )
        )
    ) + list(
        db.scalars(
            select(AiDocumentReference.target_resource_id)
            .join(
                AiDocumentSnapshot,
                AiDocumentSnapshot.id == AiDocumentReference.parent_snapshot_id,
            )
            .where(
                AiDocumentSnapshot.refresh_id.in_(ai_refresh_ids),
                AiDocumentReference.target_resource_id.is_not(None),
            )
        )
    )
    site_page_resource_ids = list(
        db.scalars(select(SitePage.resource_id).where(SitePage.website_property_id == site.id))
    )
    db.delete(site)
    db.flush()
    resource_ids = (
        set(item for item in source_resource_ids if item)
        | set(site_page_resource_ids)
        | set(item for item in ai_resource_ids if item)
    )
    _delete_unreferenced_resources_after_site_delete(db, list(resource_ids))
    db.commit()
    return site_id


def create_scan_from_site(
    db: Session,
    site_id: int,
    scope_config: ScopeConfigPayload,
    *,
    include_inventory: bool = False,
    source_ids: list[int] | None = None,
    commit: bool = True,
) -> Scan | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    if not site.is_active:
        raise InactiveSiteError("Inactive sites cannot start new scans.")
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="queued",
        scope_config=scope_config.model_dump(),
    )
    db.add(scan)
    db.flush()
    create_scan_seeds(
        db,
        scan,
        site,
        include_inventory=include_inventory,
        source_ids=source_ids or [],
    )
    if commit:
        db.commit()
        db.refresh(scan)
    return scan


def _ensure_unique_base_url(
    db: Session, normalized_base_url: str, site_id: int | None = None
) -> None:
    query = select(WebsiteProperty).where(
        WebsiteProperty.normalized_base_url == normalized_base_url
    )
    if site_id is not None:
        query = query.where(WebsiteProperty.id != site_id)
    if db.scalar(query) is not None:
        raise DuplicateSiteError("A site with this base URL already exists.")


def _reference_count(db: Session, model: type[Any], column: Any, resource_id: int) -> int:
    return db.scalar(select(func.count(model.id)).where(column == resource_id)) or 0


def _delete_unreferenced_resources_after_site_delete(db: Session, resource_ids: list[int]) -> None:
    if not resource_ids:
        return
    from app.models import (
        AiDocumentReference,
        AiDocumentSnapshot,
        ResourceOccurrence,
        ResourceSnapshot,
        ScanSeed,
        SitePage,
        UrlSourceEntry,
        WebResource,
    )

    for resource_id in set(resource_ids):
        has_reference = (
            _reference_count(db, ResourceSnapshot, ResourceSnapshot.resource_id, resource_id)
            + _reference_count(
                db, ResourceOccurrence, ResourceOccurrence.target_resource_id, resource_id
            )
            + _reference_count(db, UrlSourceEntry, UrlSourceEntry.resource_id, resource_id)
            + _reference_count(db, ScanSeed, ScanSeed.resource_id, resource_id)
            + _reference_count(db, SitePage, SitePage.resource_id, resource_id)
            + _reference_count(db, AiDocumentSnapshot, AiDocumentSnapshot.resource_id, resource_id)
            + _reference_count(
                db, AiDocumentReference, AiDocumentReference.target_resource_id, resource_id
            )
        )
        if has_reference == 0:
            resource = db.get(WebResource, resource_id)
            if resource:
                db.delete(resource)
