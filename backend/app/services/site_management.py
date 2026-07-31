from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Scan, WebsiteProperty
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate, WebsitePropertyUpdate
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
    db.delete(site)
    db.commit()
    return site_id


def create_scan_from_site(
    db: Session,
    site_id: int,
    scope_config: ScopeConfigPayload,
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
