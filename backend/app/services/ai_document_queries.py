from typing import Literal

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    AiDocumentValidation,
    SourceRefresh,
)
from app.schemas.ai_documents import (
    AiDocumentRefreshRead,
    AiDocumentSnapshotRead,
    AiDocumentTree,
    AiDocumentTreeNode,
    AiValidationRead,
    PaginatedAiDocuments,
    PaginatedAiReferences,
    PaginatedAiRefreshes,
)


def list_ai_refreshes(db: Session, source_id: int, limit: int, offset: int) -> PaginatedAiRefreshes:
    query = (
        select(AiDocumentRefresh)
        .join(SourceRefresh)
        .where(SourceRefresh.url_source_id == source_id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.order_by(AiDocumentRefresh.id.desc()).limit(limit).offset(offset))
    )
    return PaginatedAiRefreshes(
        items=[AiDocumentRefreshRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def list_ai_documents(
    db: Session,
    refresh_id: int,
    *,
    search: str | None,
    kind: str | None,
    role: str | None,
    fetch_state: str | None,
    parse_state: str | None,
    changed: str | None,
    depth: int | None,
    sort: Literal["url", "depth", "fetched", "size"],
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> PaginatedAiDocuments:
    parent_counts = (
        select(
            AiDocumentReference.child_snapshot_id.label("snapshot_id"),
            func.count(AiDocumentReference.id).label("parent_count"),
        )
        .where(AiDocumentReference.child_snapshot_id.is_not(None))
        .group_by(AiDocumentReference.child_snapshot_id)
        .subquery()
    )
    query = (
        select(AiDocumentSnapshot, func.coalesce(parent_counts.c.parent_count, 0))
        .outerjoin(parent_counts, parent_counts.c.snapshot_id == AiDocumentSnapshot.id)
        .options(joinedload(AiDocumentSnapshot.blob))
        .where(AiDocumentSnapshot.refresh_id == refresh_id)
    )
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                AiDocumentSnapshot.requested_url.ilike(like),
                AiDocumentSnapshot.final_url.ilike(like),
                AiDocumentSnapshot.parsed_title.ilike(like),
            )
        )
    if kind:
        query = query.where(AiDocumentSnapshot.document_kind == kind)
    if role:
        query = query.where(AiDocumentSnapshot.document_role == role)
    if fetch_state:
        query = query.where(AiDocumentSnapshot.fetch_state == fetch_state)
    if parse_state:
        query = query.where(AiDocumentSnapshot.parse_state == parse_state)
    if changed:
        query = query.where(AiDocumentSnapshot.change_state == changed)
    if depth is not None:
        query = query.where(AiDocumentSnapshot.parent_depth_min == depth)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_column = {
        "url": AiDocumentSnapshot.requested_url,
        "depth": AiDocumentSnapshot.parent_depth_min,
        "fetched": AiDocumentSnapshot.fetched_at,
        "size": AiDocumentSnapshot.network_bytes_transferred,
    }[sort]
    order = desc if direction == "desc" else asc
    rows = db.execute(
        query.order_by(order(sort_column), order(AiDocumentSnapshot.id)).limit(limit).offset(offset)
    ).all()
    items = []
    for snapshot, parent_count in rows:
        item = AiDocumentSnapshotRead.model_validate(snapshot)
        item.raw_byte_size = snapshot.blob.raw_byte_size if snapshot.blob else None
        item.stored_byte_size = snapshot.blob.stored_byte_size if snapshot.blob else None
        item.parent_count = parent_count
        items.append(item)
    return PaginatedAiDocuments(items=items, total=total, limit=limit, offset=offset)


def list_ai_references(
    db: Session,
    refresh_id: int,
    *,
    search: str | None,
    in_scope: bool | None,
    optional: bool | None,
    fetched: bool | None,
    limit: int,
    offset: int,
) -> PaginatedAiReferences:
    query = (
        select(AiDocumentReference)
        .join(AiDocumentSnapshot, AiDocumentSnapshot.id == AiDocumentReference.parent_snapshot_id)
        .where(AiDocumentSnapshot.refresh_id == refresh_id)
    )
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                AiDocumentReference.raw_url.ilike(like),
                AiDocumentReference.resolved_url.ilike(like),
                AiDocumentReference.label.ilike(like),
            )
        )
    if in_scope is not None:
        query = query.where(AiDocumentReference.in_scope.is_(in_scope))
    if optional is not None:
        query = query.where(AiDocumentReference.optional.is_(optional))
    if fetched is not None:
        query = query.where(
            AiDocumentReference.child_snapshot_id.is_not(None)
            if fetched
            else AiDocumentReference.child_snapshot_id.is_(None)
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.order_by(
                AiDocumentReference.parent_snapshot_id,
                AiDocumentReference.position,
                AiDocumentReference.id,
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return PaginatedAiReferences(items=items, total=total, limit=limit, offset=offset)


def get_ai_tree(db: Session, refresh_id: int) -> AiDocumentTree:
    documents = list_ai_documents(
        db,
        refresh_id,
        search=None,
        kind=None,
        role=None,
        fetch_state=None,
        parse_state=None,
        changed=None,
        depth=None,
        sort="depth",
        direction="asc",
        limit=5000,
        offset=0,
    )
    return AiDocumentTree(
        items=[
            AiDocumentTreeNode(
                snapshot=item,
                parent_count=item.parent_count,
                cycle=bool(
                    db.scalar(
                        select(func.count(AiDocumentReference.id)).where(
                            AiDocumentReference.child_snapshot_id == item.id,
                            AiDocumentReference.forms_cycle.is_(True),
                        )
                    )
                ),
            )
            for item in documents.items
        ]
    )


def list_ai_validations(db: Session, refresh_id: int) -> list[AiValidationRead]:
    return [
        AiValidationRead.model_validate(item)
        for item in db.scalars(
            select(AiDocumentValidation)
            .where(AiDocumentValidation.refresh_id == refresh_id)
            .order_by(AiDocumentValidation.severity.desc(), AiDocumentValidation.id)
        )
    ]


def get_ai_snapshot(db: Session, snapshot_id: int) -> AiDocumentSnapshotRead | None:
    snapshot = db.scalar(
        select(AiDocumentSnapshot)
        .options(joinedload(AiDocumentSnapshot.blob))
        .where(AiDocumentSnapshot.id == snapshot_id)
    )
    if snapshot is None:
        return None
    item = AiDocumentSnapshotRead.model_validate(snapshot)
    item.raw_byte_size = snapshot.blob.raw_byte_size if snapshot.blob else None
    item.stored_byte_size = snapshot.blob.stored_byte_size if snapshot.blob else None
    item.parent_count = (
        db.scalar(
            select(func.count(AiDocumentReference.id)).where(
                AiDocumentReference.child_snapshot_id == snapshot.id
            )
        )
        or 0
    )
    return item
