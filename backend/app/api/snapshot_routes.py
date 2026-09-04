from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.api.dependencies import DbSession, PageLimit, PageOffset
from app.models import (
    ResourceOccurrence,
    ResourceSnapshot,
    StaticFetchAttempt,
)
from app.schemas.scans import (
    InboundLinkList,
    LinkRead,
    OutgoingLinkList,
    SnapshotRead,
    StaticFetchAttemptRead,
)
from app.services.scan_queries import (
    get_snapshot_detail,
    list_snapshot_inbound_links,
    list_snapshot_outgoing_links,
)
from app.storage.content_store import BlobNotFoundError, LocalContentStore

router = APIRouter(prefix="/api")


@router.get("/scans/{scan_id}/errors", response_model=list[SnapshotRead])
def list_errors(scan_id: int, db: DbSession) -> list[ResourceSnapshot]:
    return list(
        db.scalars(
            select(ResourceSnapshot).where(
                ResourceSnapshot.scan_id == scan_id, ResourceSnapshot.error_type.is_not(None)
            )
        )
    )


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotRead)
def get_snapshot(snapshot_id: int, db: DbSession) -> SnapshotRead:
    result = get_snapshot_detail(db, snapshot_id)
    if result is None:
        raise HTTPException(404, "Snapshot not found")
    return result


@router.get(
    "/snapshots/{snapshot_id}/static-fetch-attempts",
    response_model=list[StaticFetchAttemptRead],
)
def list_static_fetch_attempts(snapshot_id: int, db: DbSession) -> list[StaticFetchAttempt]:
    if db.get(ResourceSnapshot, snapshot_id) is None:
        raise HTTPException(404, "Snapshot not found")
    return list(
        db.scalars(
            select(StaticFetchAttempt)
            .where(StaticFetchAttempt.snapshot_id == snapshot_id)
            .order_by(StaticFetchAttempt.attempt_number)
        )
    )


@router.get("/snapshots/{snapshot_id}/links", response_model=list[LinkRead])
def get_snapshot_links(snapshot_id: int, db: DbSession) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id == snapshot_id)
        )
    )


@router.get("/snapshots/{snapshot_id}/outgoing-links", response_model=OutgoingLinkList)
def get_snapshot_outgoing_links(
    snapshot_id: int,
    db: DbSession,
    search: str | None = None,
    scope_decision: str | None = None,
    link_role: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> OutgoingLinkList:
    result = list_snapshot_outgoing_links(
        db,
        snapshot_id,
        search=search,
        scope_decision=scope_decision,
        link_role=link_role,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Snapshot not found")
    return result


@router.get("/snapshots/{snapshot_id}/inbound-links", response_model=InboundLinkList)
def get_snapshot_inbound_links(
    snapshot_id: int,
    db: DbSession,
    search: str | None = None,
    scope_decision: str | None = None,
    source_status: int | None = None,
    rel: str | None = None,
    link_role: str | None = None,
    sort: Literal[
        "source_url",
        "source_status",
        "source_depth",
        "anchor_text",
        "link_role",
        "raw_href",
        "rel",
        "scope_decision",
        "discovered_at",
    ] = "source_url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> InboundLinkList:
    links = list_snapshot_inbound_links(
        db,
        snapshot_id=snapshot_id,
        search=search,
        scope_decision=scope_decision,
        source_status=source_status,
        rel=rel,
        link_role=link_role,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if links is None:
        raise HTTPException(404, "Snapshot not found")
    return links


@router.get("/snapshots/{snapshot_id}/html")
def get_snapshot_html(snapshot_id: int, request: Request, db: DbSession) -> Response:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    if not snapshot.blob:
        raise HTTPException(404, "Snapshot has no HTML blob")
    store: LocalContentStore = request.app.state.content_store
    try:
        content = store.get(snapshot.blob)
    except BlobNotFoundError as exc:
        raise HTTPException(404, "HTML blob is missing") from exc
    return Response(
        content=content.decode(snapshot.encoding or "utf-8", errors="replace"),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/resources/{resource_id}/occurrences", response_model=list[LinkRead])
def get_resource_occurrences(resource_id: int, db: DbSession) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(ResourceOccurrence.target_resource_id == resource_id)
        )
    )
