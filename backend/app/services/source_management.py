from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.url_normalizer import UrlNormalizationError
from app.models import (
    BackgroundJob,
    SourceRefresh,
    UrlSource,
    UrlSourceEntry,
    WebResource,
    WebsiteProperty,
)
from app.schemas.sources import UrlSourceCreate, UrlSourceUpdate
from app.services.repositories import get_or_create_resource
from app.services.url_identity import active_url_normalization_version


class DuplicateSourceError(ValueError):
    pass


class SourceNotFoundError(ValueError):
    pass


class SourceHasActiveJobError(ValueError):
    pass


def create_source(db: Session, site_id: int, payload: UrlSourceCreate) -> UrlSource | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    normalized_source_url = (
        _normalize_source_url(db, payload.source_url, site) if payload.source_url else None
    )
    if normalized_source_url:
        _ensure_unique_source(db, site.id, payload.source_type, normalized_source_url)
    source = UrlSource(
        website_property_id=site.id,
        source_type=payload.source_type,
        name=payload.name.strip(),
        source_url=normalized_source_url,
        normalized_source_url=normalized_source_url,
        is_active=payload.is_active,
        discovery_mode=payload.discovery_mode,
        settings_json=payload.settings_json,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def update_source(
    db: Session, site_id: int, source_id: int, payload: UrlSourceUpdate
) -> UrlSource | None:
    source = _get_site_source(db, site_id, source_id)
    if source is None:
        return None
    site = source.website_property
    updates = payload.model_dump(exclude_unset=True)
    if "source_url" in updates:
        raw_url = updates.pop("source_url")
        normalized = _normalize_source_url(db, raw_url, site) if raw_url else None
        if normalized != source.normalized_source_url and normalized:
            _ensure_unique_source(db, site.id, source.source_type, normalized, source.id)
        source.source_url = normalized
        source.normalized_source_url = normalized
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    for key, value in updates.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    return source


def delete_source(db: Session, site_id: int, source_id: int) -> int | None:
    source = _get_site_source(db, site_id, source_id)
    if source is None:
        return None
    active_job = db.scalar(
        select(BackgroundJob.id)
        .join(SourceRefresh, BackgroundJob.source_refresh_id == SourceRefresh.id)
        .where(
            SourceRefresh.url_source_id == source.id,
            BackgroundJob.status.in_({"queued", "running"}),
        )
        .limit(1)
    )
    if active_job is not None:
        raise SourceHasActiveJobError("The source has an active refresh job.")
    resource_ids = [
        resource_id
        for resource_id in db.scalars(
            select(UrlSourceEntry.resource_id).where(
                UrlSourceEntry.url_source_id == source.id,
                UrlSourceEntry.resource_id.is_not(None),
            )
        )
        if resource_id is not None
    ]
    db.delete(source)
    _delete_unreferenced_source_resources(db, resource_ids)
    db.commit()
    return source_id


def get_or_create_manual_source(db: Session, site: WebsiteProperty) -> UrlSource:
    source = db.scalar(
        select(UrlSource).where(
            UrlSource.website_property_id == site.id,
            UrlSource.source_type == "manual",
            UrlSource.discovery_mode == "system_manual_collection",
        )
    )
    if source:
        return source
    source = UrlSource(
        website_property_id=site.id,
        source_type="manual",
        name="Manual URLs",
        source_url=None,
        normalized_source_url=None,
        is_active=True,
        discovery_mode="system_manual_collection",
        settings_json={},
    )
    db.add(source)
    db.flush()
    return source


def add_manual_urls(
    db: Session, site_id: int, urls_text: str
) -> tuple[UrlSource | None, list[UrlSourceEntry], int, int, int]:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None, [], 0, 0, 0
    source = get_or_create_manual_source(db, site)
    rows = [row.strip() for row in urls_text.splitlines() if row.strip()]
    entries: list[UrlSourceEntry] = []
    policy_index = _source_policy_index(db, source, site)
    accepted = rejected = duplicates = 0
    for row in rows:
        entry, state = upsert_source_entry(
            db,
            source,
            row,
            site=site,
            source_type="manual",
            policy_index=policy_index,
        )
        entries.append(entry)
        if state == "duplicate":
            duplicates += 1
        elif entry.validation_state == "valid":
            accepted += 1
        else:
            rejected += 1
    db.commit()
    db.refresh(source)
    return source, entries, accepted, rejected, duplicates


def upsert_source_entry(
    db: Session,
    source: UrlSource,
    raw_url: str,
    *,
    site: WebsiteProperty,
    source_type: str,
    refresh_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    sitemap_lastmod: str | None = None,
    sitemap_changefreq: str | None = None,
    sitemap_priority: str | None = None,
    policy_index: dict[str, UrlSourceEntry] | None = None,
) -> tuple[UrlSourceEntry, str]:
    config = ScopeConfig.from_dict(site.scope_config)
    normalization_version = active_url_normalization_version(db)
    try:
        scope_result = ScopeEngine(config, site.base_url, normalization_version).evaluate(
            raw_url, site.base_url
        )
        normalized = scope_result.normalized
        if normalized is None:
            raise UrlNormalizationError(scope_result.exclusion_reason or "URL is invalid")
        resource = (
            get_or_create_resource(
                db,
                normalized,
                normalization_version=normalization_version,
            )
            if scope_result.in_scope
            else None
        )
        normalized_url = normalized.normalized_url
        validation_state = "valid" if scope_result.in_scope else "rejected"
        validation_message = None if scope_result.in_scope else scope_result.exclusion_reason
        scope_decision = scope_result.decision
        resource_id = resource.id if resource else None
    except (UrlNormalizationError, ValueError) as exc:
        normalized_url = None
        resource_id = None
        validation_state = "invalid"
        validation_message = str(exc)
        scope_decision = "unsupported_scheme" if "unsupported scheme" in str(exc) else "invalid_url"

    policy_key = scope_result.site_policy_key if normalized_url else None
    existing = policy_index.get(policy_key) if policy_index is not None and policy_key else None
    existing = existing or (
        db.scalar(
            select(UrlSourceEntry).where(
                UrlSourceEntry.url_source_id == source.id,
                UrlSourceEntry.normalized_url == normalized_url,
                UrlSourceEntry.normalized_url.is_not(None),
            )
        )
        if normalized_url
        else None
    )
    now = datetime.now(UTC)
    if existing:
        existing.raw_url = raw_url
        existing.last_seen_at = now
        existing.last_refresh_id = refresh_id
        existing.is_current = True
        existing.sitemap_lastmod = sitemap_lastmod
        existing.sitemap_changefreq = sitemap_changefreq
        existing.sitemap_priority = sitemap_priority
        existing.source_metadata_json = metadata or {}
        existing.validation_state = validation_state
        existing.validation_message = validation_message
        existing.scope_decision = scope_decision
        existing.resource_id = resource_id
        db.flush()
        if policy_index is not None and policy_key:
            policy_index[policy_key] = existing
        return existing, "duplicate" if source_type == "manual" else "updated"
    entry = UrlSourceEntry(
        url_source_id=source.id,
        resource_id=resource_id,
        normalized_url=normalized_url,
        raw_url=raw_url,
        last_refresh_id=refresh_id,
        is_current=True,
        sitemap_lastmod=sitemap_lastmod,
        sitemap_changefreq=sitemap_changefreq,
        sitemap_priority=sitemap_priority,
        source_metadata_json=metadata or {},
        validation_state=validation_state,
        validation_message=validation_message,
        scope_decision=scope_decision,
    )
    db.add(entry)
    db.flush()
    if policy_index is not None and policy_key:
        policy_index[policy_key] = entry
    return entry, "added"


def _get_site_source(db: Session, site_id: int, source_id: int) -> UrlSource | None:
    return db.scalar(
        select(UrlSource).where(
            UrlSource.id == source_id,
            UrlSource.website_property_id == site_id,
        )
    )


def _normalize_source_url(db: Session, value: str | None, site: WebsiteProperty) -> str:
    if not value:
        raise ValueError("Source URL is required.")
    config = ScopeConfig.from_dict(site.scope_config)
    result = ScopeEngine(config, site.base_url, active_url_normalization_version(db)).evaluate(
        value, site.base_url
    )
    normalized = result.normalized
    if normalized is None:
        raise ValueError(result.exclusion_reason or "Source URL is invalid.")
    if not result.in_scope:
        raise ValueError(result.exclusion_reason or "Source URL is outside site scope.")
    return normalized.normalized_url


def _source_policy_index(
    db: Session,
    source: UrlSource,
    site: WebsiteProperty,
) -> dict[str, UrlSourceEntry]:
    config = ScopeConfig.from_dict(site.scope_config)
    engine = ScopeEngine(config, site.base_url, active_url_normalization_version(db))
    index: dict[str, UrlSourceEntry] = {}
    for entry in db.scalars(
        select(UrlSourceEntry)
        .where(UrlSourceEntry.url_source_id == source.id)
        .order_by(UrlSourceEntry.id)
    ):
        result = engine.evaluate(entry.raw_url, site.base_url)
        if result.site_policy_key:
            index.setdefault(result.site_policy_key, entry)
    return index


def _ensure_unique_source(
    db: Session, site_id: int, source_type: str, normalized_url: str, source_id: int | None = None
) -> None:
    query = select(UrlSource).where(
        UrlSource.website_property_id == site_id,
        UrlSource.source_type == source_type,
        UrlSource.normalized_source_url == normalized_url,
    )
    if source_id is not None:
        query = query.where(UrlSource.id != source_id)
    if db.scalar(query) is not None:
        raise DuplicateSourceError("A source with this URL already exists for the site.")


def _delete_unreferenced_source_resources(db: Session, resource_ids: list[int]) -> None:
    if not resource_ids:
        return
    from app.models import (
        AiDocumentReference,
        AiDocumentSnapshot,
        ResourceOccurrence,
        ResourceSnapshot,
        ScanSeed,
    )

    referenced = set(
        db.scalars(
            select(WebResource.id).where(
                WebResource.id.in_(resource_ids),
                (
                    select(func.count(ResourceSnapshot.id))
                    .where(ResourceSnapshot.resource_id == WebResource.id)
                    .scalar_subquery()
                    > 0
                )
                | (
                    select(func.count(ResourceOccurrence.id))
                    .where(ResourceOccurrence.target_resource_id == WebResource.id)
                    .scalar_subquery()
                    > 0
                )
                | (
                    select(func.count(UrlSourceEntry.id))
                    .where(UrlSourceEntry.resource_id == WebResource.id)
                    .scalar_subquery()
                    > 0
                )
                | (
                    select(func.count(ScanSeed.id))
                    .where(ScanSeed.resource_id == WebResource.id)
                    .scalar_subquery()
                    > 0
                )
                | (
                    select(func.count(AiDocumentSnapshot.id))
                    .where(AiDocumentSnapshot.resource_id == WebResource.id)
                    .scalar_subquery()
                    > 0
                )
                | (
                    select(func.count(AiDocumentReference.id))
                    .where(AiDocumentReference.target_resource_id == WebResource.id)
                    .scalar_subquery()
                    > 0
                ),
            )
        )
    )
    deletable = sorted(set(resource_ids) - referenced)
    for resource_id in deletable:
        resource = db.get(WebResource, resource_id)
        if resource:
            db.delete(resource)
