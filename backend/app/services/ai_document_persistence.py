from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from app.crawler.url_normalizer import NormalizedUrl
from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    SourceRefresh,
    UrlSource,
    UrlSourceEntry,
    WebResource,
)
from app.storage.ai_document_store import LocalAiDocumentStore

AI_DOCUMENT_WRITE_BATCH_SIZE = 400
T = TypeVar("T")


def _chunks(items: list[T], size: int = AI_DOCUMENT_WRITE_BATCH_SIZE) -> Iterable[list[T]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


class AiDocumentResourceResolver:
    def __init__(self, db: Session):
        self.db = db
        self.cache: dict[str, WebResource] = {}
        self.peak_batch_size = 0

    def resolve(self, normalized: NormalizedUrl) -> WebResource:
        self.resolve_many([normalized])
        return self.cache[normalized.normalized_url]

    def resolve_many(self, normalized_urls: Iterable[NormalizedUrl]) -> None:
        pending = {
            item.normalized_url: item
            for item in normalized_urls
            if item.normalized_url not in self.cache
        }
        for batch in _chunks(list(pending.values())):
            self.peak_batch_size = max(self.peak_batch_size, len(batch))
            urls = [item.normalized_url for item in batch]
            existing = list(
                self.db.scalars(select(WebResource).where(WebResource.normalized_url.in_(urls)))
            )
            self.cache.update({item.normalized_url: item for item in existing})
            missing = [item for item in batch if item.normalized_url not in self.cache]
            if missing:
                statement = sqlite_insert(WebResource).values(
                    [
                        {
                            "resource_type": "page",
                            "normalized_url": item.normalized_url,
                            "scheme": item.scheme,
                            "host": item.host,
                            "port": item.port,
                            "path": item.path,
                            "query": item.query,
                        }
                        for item in missing
                    ]
                )
                self.db.execute(statement.on_conflict_do_nothing(index_elements=["normalized_url"]))
                created = list(
                    self.db.scalars(
                        select(WebResource).where(
                            WebResource.normalized_url.in_(
                                [item.normalized_url for item in missing]
                            )
                        )
                    )
                )
                self.cache.update({item.normalized_url: item for item in created})
            unresolved = [url for url in urls if url not in self.cache]
            if unresolved:
                raise RuntimeError(f"Could not resolve WebResource identities: {unresolved[:3]}")

    def touch_resolved(self) -> None:
        resource_ids = list({resource.id for resource in self.cache.values()})
        for batch in _chunks(resource_ids):
            self.peak_batch_size = max(self.peak_batch_size, len(batch))
            self.db.execute(
                update(WebResource)
                .where(WebResource.id.in_(batch))
                .values(last_seen_at=datetime.now(UTC))
            )


class AiDocumentPreviousSnapshotResolver:
    def __init__(self, db: Session, source_id: int):
        self.db = db
        self.source_id = source_id
        self.cache: dict[int, AiDocumentSnapshot | None] = {}
        self.peak_batch_size = 0

    def get(self, resource: WebResource) -> AiDocumentSnapshot | None:
        self.prime([resource])
        return self.cache[resource.id]

    def prime(self, resources: Iterable[WebResource]) -> None:
        resource_ids = list({item.id for item in resources if item.id not in self.cache})
        for batch in _chunks(resource_ids):
            self.peak_batch_size = max(self.peak_batch_size, len(batch))
            latest_ids = (
                select(func.max(AiDocumentSnapshot.id))
                .join(AiDocumentRefresh)
                .join(SourceRefresh)
                .where(
                    SourceRefresh.url_source_id == self.source_id,
                    AiDocumentSnapshot.resource_id.in_(batch),
                    AiDocumentSnapshot.retained_blob_id.is_not(None),
                )
                .group_by(AiDocumentSnapshot.resource_id)
            )
            snapshots = list(
                self.db.scalars(
                    select(AiDocumentSnapshot)
                    .options(joinedload(AiDocumentSnapshot.blob))
                    .where(AiDocumentSnapshot.id.in_(latest_ids))
                )
            )
            found = {item.resource_id: item for item in snapshots}
            self.cache.update({resource_id: found.get(resource_id) for resource_id in batch})


class AiDocumentBlobResolver:
    def __init__(self, store: LocalAiDocumentStore):
        self.store = store
        self.cache: dict[str, AiDocumentBlob] = {}

    def put(
        self,
        db: Session,
        content: bytes,
        media_type: str | None,
        encoding: str | None,
    ) -> AiDocumentBlob:
        sha256 = hashlib.sha256(content).hexdigest()
        if cached := self.cache.get(sha256):
            return cached
        blob = self.store.put(db, content, media_type, encoding)
        self.cache[sha256] = blob
        return blob


@dataclass
class AiDocumentInventoryOrigin:
    resource_id: int
    raw_url: str
    scope_decision: str
    values: dict[str, object]


@dataclass
class AiDocumentInventoryAccumulator:
    origins: dict[str, list[AiDocumentInventoryOrigin]] = field(default_factory=dict)
    peak_batch_size: int = 0

    def add(self, normalized_url: str, origin: AiDocumentInventoryOrigin) -> None:
        self.origins.setdefault(normalized_url, []).append(origin)

    def persist(
        self,
        db: Session,
        source: UrlSource,
        evidence: AiDocumentRefresh,
    ) -> set[str]:
        existing = {
            item.normalized_url: item
            for item in db.scalars(
                select(UrlSourceEntry).where(UrlSourceEntry.url_source_id == source.id)
            )
            if item.normalized_url is not None
        }
        now = datetime.now(UTC)
        inserts: list[dict[str, object]] = []
        for normalized_url, origin_rows in self.origins.items():
            latest = origin_rows[-1]
            metadata = {
                "ai_refresh_id": evidence.id,
                "ai_origins": [item.values for item in origin_rows],
            }
            entry = existing.get(normalized_url)
            if entry:
                entry.resource_id = latest.resource_id
                entry.raw_url = latest.raw_url
                entry.last_seen_at = now
                entry.last_refresh_id = evidence.source_refresh_id
                entry.is_current = True
                entry.source_metadata_json = metadata
                entry.validation_state = "valid"
                entry.validation_message = None
                entry.scope_decision = latest.scope_decision
            else:
                inserts.append(
                    {
                        "url_source_id": source.id,
                        "resource_id": latest.resource_id,
                        "normalized_url": normalized_url,
                        "raw_url": latest.raw_url,
                        "last_refresh_id": evidence.source_refresh_id,
                        "is_current": True,
                        "sitemap_lastmod": None,
                        "sitemap_changefreq": None,
                        "sitemap_priority": None,
                        "source_metadata_json": metadata,
                        "validation_state": "valid",
                        "validation_message": None,
                        "scope_decision": latest.scope_decision,
                    }
                )
        db.flush()
        for batch in _chunks(inserts):
            self.peak_batch_size = max(self.peak_batch_size, len(batch))
            db.execute(insert(UrlSourceEntry), batch)
        seen = set(self.origins)
        db.execute(
            update(UrlSourceEntry)
            .where(
                UrlSourceEntry.url_source_id == source.id,
                UrlSourceEntry.is_current.is_(True),
            )
            .values(is_current=False),
            execution_options={"synchronize_session": False},
        )
        for url_batch in _chunks(list(seen)):
            self.peak_batch_size = max(self.peak_batch_size, len(url_batch))
            db.execute(
                update(UrlSourceEntry)
                .where(
                    UrlSourceEntry.url_source_id == source.id,
                    UrlSourceEntry.normalized_url.in_(url_batch),
                )
                .values(is_current=True),
                execution_options={"synchronize_session": False},
            )
        if seen:
            parent_ids = select(AiDocumentSnapshot.id).where(
                AiDocumentSnapshot.refresh_id == evidence.id
            )
            entry_id = (
                select(UrlSourceEntry.id)
                .where(
                    UrlSourceEntry.url_source_id == source.id,
                    UrlSourceEntry.normalized_url == AiDocumentReference.normalized_target_url,
                )
                .scalar_subquery()
            )
            db.execute(
                update(AiDocumentReference)
                .where(
                    AiDocumentReference.parent_snapshot_id.in_(parent_ids),
                    AiDocumentReference.normalized_target_url.in_(seen),
                )
                .values(inventory_entry_id=entry_id),
                execution_options={"synchronize_session": False},
            )
        return seen


def link_refresh_children(db: Session, refresh_id: int) -> None:
    parent_ids = select(AiDocumentSnapshot.id).where(AiDocumentSnapshot.refresh_id == refresh_id)
    child_id = (
        select(AiDocumentSnapshot.id)
        .where(
            AiDocumentSnapshot.refresh_id == refresh_id,
            AiDocumentSnapshot.resource_id == AiDocumentReference.target_resource_id,
        )
        .limit(1)
        .scalar_subquery()
    )
    db.execute(
        update(AiDocumentReference)
        .where(
            AiDocumentReference.parent_snapshot_id.in_(parent_ids),
            AiDocumentReference.target_resource_id.is_not(None),
            child_id.is_not(None),
        )
        .values(child_snapshot_id=child_id),
        execution_options={"synchronize_session": False},
    )
