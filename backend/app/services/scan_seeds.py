from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.scope import ScopeConfig, ScopeEngine
from app.models import Scan, ScanSeed, ScanSeedOrigin, UrlSource, UrlSourceEntry, WebsiteProperty
from app.services.inventory_lifecycle import (
    inventory_suppression_map,
    matching_inventory_suppression,
)
from app.services.repositories import get_or_create_resource


def create_scan_seeds(
    db: Session,
    scan: Scan,
    site: WebsiteProperty,
    *,
    include_inventory: bool,
    source_ids: list[int] | None = None,
) -> None:
    config = ScopeConfig.from_dict(scan.scope_config)
    scope = ScopeEngine(config, scan.starting_url, scan.url_normalization_version)
    seeds_by_url: dict[str, ScanSeed] = {}

    _add_seed(
        db,
        scan,
        scope,
        scan.starting_url,
        origin_type="starting_url",
        raw_url=scan.starting_url,
        metadata={},
        seeds_by_url=seeds_by_url,
    )
    if not include_inventory:
        db.flush()
        return

    query = (
        select(UrlSourceEntry)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .where(
            UrlSource.website_property_id == site.id,
            UrlSource.is_active.is_(True),
            UrlSourceEntry.is_current.is_(True),
        )
        .order_by(UrlSourceEntry.normalized_url, UrlSourceEntry.id)
    )
    if source_ids:
        query = query.where(UrlSource.id.in_(source_ids))
    max_pages = config.max_pages
    suppressions = inventory_suppression_map(db, site)
    for entry in db.scalars(query):
        if matching_inventory_suppression(db, site, entry, suppressions) is not None:
            continue
        seed = _add_seed(
            db,
            scan,
            scope,
            entry.normalized_url or entry.raw_url,
            origin_type=entry.url_source.source_type,
            raw_url=entry.raw_url,
            metadata={
                "source_name": entry.url_source.name,
                "validation_state": entry.validation_state,
                "sitemap_lastmod": entry.sitemap_lastmod,
            },
            seeds_by_url=seeds_by_url,
            entry=entry,
            max_queued=max_pages,
        )
        if (
            seed
            and seed.queue_state == "queued"
            and len([item for item in seeds_by_url.values() if item.queue_state == "queued"])
            > max_pages
        ):
            seed.queue_state = "not_queued_page_limit"
    db.flush()


def _add_seed(
    db: Session,
    scan: Scan,
    scope: ScopeEngine,
    requested_url: str,
    *,
    origin_type: str,
    raw_url: str,
    metadata: dict[str, Any],
    seeds_by_url: dict[str, ScanSeed],
    entry: UrlSourceEntry | None = None,
    max_queued: int | None = None,
) -> ScanSeed | None:
    result = scope.evaluate(requested_url)
    normalized_url = result.normalized.normalized_url if result.normalized else None
    key = result.site_policy_key or normalized_url or f"invalid:{entry.id if entry else raw_url}"
    seed = seeds_by_url.get(key)
    if seed is None:
        resource = (
            get_or_create_resource(
                db,
                result.normalized,
                normalization_version=scan.url_normalization_version,
            )
            if result.normalized
            else None
        )
        queued_count = len([item for item in seeds_by_url.values() if item.queue_state == "queued"])
        queue_state = "queued" if result.in_scope else "rejected"
        if max_queued is not None and queue_state == "queued" and queued_count >= max_queued:
            queue_state = "not_queued_page_limit"
        seed = ScanSeed(
            scan_id=scan.id,
            resource_id=resource.id if resource else None,
            normalized_url=normalized_url,
            requested_url=normalized_url or requested_url,
            depth=0,
            queue_state=queue_state,
            scope_decision=result.decision,
            exclusion_reason=result.exclusion_reason,
        )
        db.add(seed)
        db.flush()
        seeds_by_url[key] = seed
    origin = ScanSeedOrigin(
        scan_seed_id=seed.id,
        origin_type=origin_type,
        url_source_id=entry.url_source_id if entry else None,
        url_source_entry_id=entry.id if entry else None,
        source_refresh_id=entry.last_refresh_id if entry else None,
        raw_url=raw_url,
        metadata_json=metadata,
    )
    db.add(origin)
    return seed
