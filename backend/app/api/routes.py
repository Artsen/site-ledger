from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, WebResource
from app.schemas.scans import LinkRead, PageList, PageRead, ScanCreate, ScanRead, SnapshotRead
from app.storage.content_store import BlobNotFoundError, LocalContentStore

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
ScanListLimit = Annotated[int, Query(ge=1, le=100)]
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/scans", response_model=ScanRead, status_code=201)
async def create_scan(payload: ScanCreate, request: Request, db: DbSession) -> Scan:
    scan = Scan(
        starting_url=payload.starting_url,
        status="queued",
        scope_config=payload.scope_config.model_dump(),
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    await request.app.state.scan_runner.queue(scan.id)
    return scan


@router.get("/scans", response_model=list[ScanRead])
def list_scans(db: DbSession, limit: ScanListLimit = 25) -> list[Scan]:
    return list(db.scalars(select(Scan).order_by(Scan.created_at.desc()).limit(limit)))


@router.get("/scans/{scan_id}", response_model=ScanRead)
def get_scan(scan_id: int, db: DbSession) -> Scan:
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    return scan


@router.post("/scans/{scan_id}/cancel", response_model=ScanRead)
async def cancel_scan(scan_id: int, request: Request, db: DbSession) -> Scan:
    await request.app.state.scan_runner.cancel(scan_id)
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    db.refresh(scan)
    return scan


@router.get("/scans/{scan_id}/pages", response_model=PageList)
def list_pages(
    scan_id: int,
    db: DbSession,
    search: str | None = None,
    status: int | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    depth: int | None = None,
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    sort: Literal["requested_url", "status", "title", "depth", "duration"] = "requested_url",
    direction: Literal["asc", "desc"] = "asc",
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> PageList:
    base = (
        select(ResourceSnapshot, WebResource)
        .join(WebResource)
        .where(ResourceSnapshot.scan_id == scan_id)
    )
    base = _apply_page_filters(base, search, status, host, path_prefix, depth, error_state)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    sort_map = {
        "requested_url": ResourceSnapshot.requested_url,
        "status": ResourceSnapshot.http_status,
        "title": ResourceSnapshot.page_title,
        "depth": ResourceSnapshot.crawl_depth,
        "duration": ResourceSnapshot.response_time_ms,
    }
    order_col = sort_map[sort]
    base = (
        base.order_by(order_col.desc() if direction == "desc" else order_col.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(base).all()
    items: list[PageRead] = []
    for snapshot, resource in rows:
        inbound = (
            db.scalar(
                select(func.count(ResourceOccurrence.id)).where(
                    ResourceOccurrence.target_resource_id == resource.id
                )
            )
            or 0
        )
        source = db.scalar(
            select(ResourceSnapshot.final_url)
            .join(ResourceOccurrence, ResourceOccurrence.source_snapshot_id == ResourceSnapshot.id)
            .where(ResourceOccurrence.target_resource_id == resource.id)
            .limit(1)
        )
        items.append(
            PageRead(
                id=snapshot.id,
                resource_id=resource.id,
                requested_url=snapshot.requested_url,
                final_url=snapshot.final_url,
                http_status=snapshot.http_status,
                title=snapshot.page_title,
                depth=snapshot.crawl_depth,
                content_type=snapshot.content_type,
                discovery_source=source,
                inbound_occurrence_count=inbound,
                response_time_ms=snapshot.response_time_ms,
                fetch_state=snapshot.fetch_state,
                error_type=snapshot.error_type,
            )
        )
    return PageList(items=items, total=total, limit=limit, offset=offset)


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
def get_snapshot(snapshot_id: int, db: DbSession) -> ResourceSnapshot:
    snapshot = db.get(ResourceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    return snapshot


@router.get("/snapshots/{snapshot_id}/links", response_model=list[LinkRead])
def get_snapshot_links(snapshot_id: int, db: DbSession) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id == snapshot_id)
        )
    )


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


def _apply_page_filters(
    query: Select[tuple[ResourceSnapshot, WebResource]],
    search: str | None,
    status: int | None,
    host: str | None,
    path_prefix: str | None,
    depth: int | None,
    error_state: str,
) -> Select[tuple[ResourceSnapshot, WebResource]]:
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ResourceSnapshot.requested_url.ilike(pattern),
                ResourceSnapshot.final_url.ilike(pattern),
                ResourceSnapshot.page_title.ilike(pattern),
            )
        )
    if status is not None:
        query = query.where(ResourceSnapshot.http_status == status)
    if host:
        query = query.where(WebResource.host == host.lower())
    if path_prefix:
        query = query.where(WebResource.path.startswith(path_prefix))
    if depth is not None:
        query = query.where(ResourceSnapshot.crawl_depth == depth)
    if error_state == "with_errors":
        query = query.where(ResourceSnapshot.error_type.is_not(None))
    elif error_state == "without_errors":
        query = query.where(ResourceSnapshot.error_type.is_(None))
    return query
