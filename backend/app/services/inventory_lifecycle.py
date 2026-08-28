from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.url_normalizer import (
    SUPPORTED_URL_NORMALIZATION_VERSIONS,
    UrlNormalizationError,
    normalize_url_for_version,
)
from app.models import SiteInventorySuppression, UrlSource, UrlSourceEntry, WebsiteProperty
from app.schemas.page_workspaces import BulkMutationResult
from app.services.url_identity import active_url_normalization_version


class ManagedSourceEntryError(ValueError):
    pass


@dataclass(frozen=True)
class InventorySummary:
    active_count: int
    suppressed_count: int


def create_inventory_suppression(
    db: Session, site_id: int, entry_id: int
) -> SiteInventorySuppression | None:
    row = db.execute(
        select(UrlSourceEntry, UrlSource, WebsiteProperty)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .join(WebsiteProperty, WebsiteProperty.id == UrlSource.website_property_id)
        .where(UrlSourceEntry.id == entry_id, UrlSource.website_property_id == site_id)
    ).one_or_none()
    if row is None:
        return None
    entry, _source, site = row
    kind, value, version = inventory_suppression_identity(db, site, entry)
    suppressions = inventory_suppression_map(db, site)
    existing = matching_inventory_suppression(db, site, entry, suppressions)
    if existing is not None:
        return existing
    suppression = SiteInventorySuppression(
        website_property_id=site_id,
        target_kind=kind,
        target_value=value,
        normalization_version=version,
    )
    try:
        with db.begin_nested():
            db.add(suppression)
            db.flush()
    except IntegrityError:
        recovered = db.scalar(
            select(SiteInventorySuppression).where(
                SiteInventorySuppression.website_property_id == site_id,
                SiteInventorySuppression.target_kind == kind,
                SiteInventorySuppression.target_value == value,
            )
        )
        if recovered is None:
            raise
        suppression = recovered
    db.commit()
    db.refresh(suppression)
    return suppression


def delete_inventory_suppression(db: Session, site_id: int, suppression_id: int) -> int | None:
    suppression = db.scalar(
        select(SiteInventorySuppression).where(
            SiteInventorySuppression.id == suppression_id,
            SiteInventorySuppression.website_property_id == site_id,
        )
    )
    if suppression is None:
        return None
    db.delete(suppression)
    db.commit()
    return suppression_id


def bulk_create_inventory_suppressions(
    db: Session, site_id: int, entry_ids: list[int]
) -> BulkMutationResult | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    requested_ids = set(entry_ids)
    entries = list(
        db.scalars(
            select(UrlSourceEntry)
            .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
            .where(
                UrlSource.website_property_id == site_id,
                UrlSourceEntry.id.in_(requested_ids),
            )
        )
    )
    if len(entries) != len(requested_ids):
        raise ValueError("One or more Inventory entries do not belong to this Site.")

    identities: dict[tuple[str, str], tuple[str | None, UrlSourceEntry]] = {}
    for entry in entries:
        kind, value, version = inventory_suppression_identity(db, site, entry)
        identities.setdefault((kind, value), (version, entry))

    suppressions = inventory_suppression_map(db, site)
    changed = 0
    for (kind, value), (version, entry) in identities.items():
        if matching_inventory_suppression(db, site, entry, suppressions) is not None:
            continue
        suppression = SiteInventorySuppression(
            website_property_id=site_id,
            target_kind=kind,
            target_value=value,
            normalization_version=version,
        )
        db.add(suppression)
        suppressions[(kind, value)] = suppression
        changed += 1
    db.commit()
    return BulkMutationResult(
        selected=len(identities),
        changed=changed,
        unchanged=len(identities) - changed,
    )


def bulk_restore_inventory_suppressions(
    db: Session, site_id: int, suppression_ids: list[int]
) -> BulkMutationResult | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    requested_ids = set(suppression_ids)
    suppressions = list(
        db.scalars(
            select(SiteInventorySuppression).where(
                SiteInventorySuppression.website_property_id == site_id,
                SiteInventorySuppression.id.in_(requested_ids),
            )
        )
    )
    if len(suppressions) != len(requested_ids):
        raise ValueError("One or more Inventory suppressions do not belong to this Site.")
    for suppression in suppressions:
        db.delete(suppression)
    db.commit()
    return BulkMutationResult(selected=len(suppressions), changed=len(suppressions), unchanged=0)


def bulk_delete_inventory_entries(
    db: Session, site_id: int, entry_ids: list[int]
) -> BulkMutationResult | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    requested_ids = set(entry_ids)
    representatives = list(
        db.scalars(
            select(UrlSourceEntry)
            .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
            .where(
                UrlSource.website_property_id == site_id,
                UrlSourceEntry.id.in_(requested_ids),
            )
        )
    )
    if len(representatives) != len(requested_ids):
        raise ValueError("One or more Inventory entries do not belong to this Site.")

    identities = {inventory_group_identity(db, site, entry): entry for entry in representatives}
    contributors: dict[tuple[str, str], list[UrlSourceEntry]] = {
        identity: [] for identity in identities
    }
    for entry in db.scalars(
        select(UrlSourceEntry)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .where(UrlSource.website_property_id == site_id)
    ):
        identity = inventory_group_identity(db, site, entry)
        if identity in contributors:
            contributors[identity].append(entry)

    suppressions = inventory_suppression_map(db, site)
    matching_suppressions = {
        suppression.id: suppression
        for entry in representatives
        if (suppression := matching_inventory_suppression(db, site, entry, suppressions))
        is not None
    }
    for suppression in matching_suppressions.values():
        db.delete(suppression)
    changed = 0
    for entries in contributors.values():
        current_entries = [entry for entry in entries if entry.is_current]
        if current_entries:
            changed += 1
        for entry in current_entries:
            entry.is_current = False
    db.commit()
    return BulkMutationResult(
        selected=len(identities),
        changed=changed,
        unchanged=len(identities) - changed,
    )


def remove_manual_source_entry(
    db: Session, site_id: int, source_id: int, entry_id: int
) -> UrlSourceEntry | None:
    row = db.execute(
        select(UrlSourceEntry, UrlSource)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .where(
            UrlSource.website_property_id == site_id,
            UrlSource.id == source_id,
            UrlSourceEntry.id == entry_id,
        )
    ).one_or_none()
    if row is None:
        return None
    entry = cast(UrlSourceEntry, row[0])
    source = cast(UrlSource, row[1])
    if source.source_type != "manual":
        raise ManagedSourceEntryError(
            "This URL is managed by its Source. Remove it from active Inventory instead."
        )
    entry.is_current = False
    db.commit()
    db.refresh(entry)
    return entry


def inventory_suppression_map(
    db: Session,
    site: WebsiteProperty,
    *,
    active_version: str | None = None,
) -> dict[tuple[str, str], SiteInventorySuppression]:
    active_version = active_version or active_url_normalization_version(db)
    result: dict[tuple[str, str], SiteInventorySuppression] = {}
    for suppression in db.scalars(
        select(SiteInventorySuppression).where(
            SiteInventorySuppression.website_property_id == site.id
        )
    ):
        result[(suppression.target_kind, suppression.target_value)] = suppression
        if suppression.target_kind == "normalized_url":
            if suppression.normalization_version is not None:
                result[
                    (
                        f"normalized_url@{suppression.normalization_version}",
                        suppression.target_value,
                    )
                ] = suppression
            try:
                current_value = normalize_url_for_version(
                    suppression.target_value,
                    normalization_version=active_version,
                ).normalized_url
            except UrlNormalizationError:
                continue
            result[("normalized_url", current_value)] = suppression
    return result


def matching_inventory_suppression(
    db: Session,
    site: WebsiteProperty,
    entry: UrlSourceEntry,
    suppressions: dict[tuple[str, str], SiteInventorySuppression] | None = None,
    *,
    active_version: str | None = None,
) -> SiteInventorySuppression | None:
    suppression_map = (
        suppressions
        if suppressions is not None
        else inventory_suppression_map(db, site, active_version=active_version)
    )
    if entry.normalized_url is None:
        return suppression_map.get(("raw_url", entry.raw_url))
    active_version = active_version or active_url_normalization_version(db)
    try:
        current_value = normalize_url_for_version(
            entry.raw_url,
            normalization_version=active_version,
            base_url=site.base_url,
        ).normalized_url
    except UrlNormalizationError:
        current_value = entry.normalized_url
    direct = suppression_map.get(("normalized_url", current_value))
    if direct is not None:
        return direct
    for version in SUPPORTED_URL_NORMALIZATION_VERSIONS:
        try:
            versioned_value = normalize_url_for_version(
                entry.raw_url,
                normalization_version=version,
                base_url=site.base_url,
            ).normalized_url
        except UrlNormalizationError:
            continue
        match = suppression_map.get((f"normalized_url@{version}", versioned_value))
        if match is not None:
            return match
    return None


def inventory_suppression_identity(
    db: Session,
    site: WebsiteProperty,
    entry: UrlSourceEntry,
    *,
    active_version: str | None = None,
) -> tuple[str, str, str | None]:
    if entry.normalized_url is None:
        return "raw_url", entry.raw_url, None
    version = active_version or active_url_normalization_version(db)
    normalized = normalize_url_for_version(
        entry.raw_url,
        normalization_version=version,
        base_url=site.base_url,
    )
    return "normalized_url", normalized.normalized_url, version


def inventory_group_identity(
    db: Session,
    site: WebsiteProperty,
    entry: UrlSourceEntry,
    *,
    active_version: str | None = None,
) -> tuple[str, str]:
    kind, value, _version = inventory_suppression_identity(
        db, site, entry, active_version=active_version
    )
    return kind, value


def summarize_current_inventory(
    db: Session, site: WebsiteProperty, *, batch_size: int = 500
) -> InventorySummary:
    """Summarize current Inventory with the workspace's version-aware identity contract."""
    identities: dict[tuple[str, str], bool] = {}
    active_version: str | None = None
    suppressions: dict[tuple[str, str], SiteInventorySuppression] | None = None
    entries = db.scalars(
        select(UrlSourceEntry)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .where(
            UrlSource.website_property_id == site.id,
            UrlSourceEntry.is_current.is_(True),
        )
        .execution_options(yield_per=batch_size)
    )
    for entry in entries:
        if active_version is None:
            active_version = active_url_normalization_version(db)
            suppressions = inventory_suppression_map(db, site, active_version=active_version)
        assert suppressions is not None
        identity = inventory_group_identity(db, site, entry, active_version=active_version)
        is_suppressed = (
            matching_inventory_suppression(
                db,
                site,
                entry,
                suppressions,
                active_version=active_version,
            )
            is not None
        )
        identities[identity] = identities.get(identity, False) or is_suppressed
    suppressed_count = sum(identities.values())
    return InventorySummary(
        active_count=len(identities) - suppressed_count,
        suppressed_count=suppressed_count,
    )
