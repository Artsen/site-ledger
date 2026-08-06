from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.models import AiDocumentRefresh, AiDocumentSnapshot, SourceRefresh
from app.schemas.ai_documents import (
    AiDocumentDiscoveryResult,
    AiDocumentRefreshRead,
    AiDocumentSnapshotRead,
    AiDocumentSourceCreate,
    AiDocumentSourceRead,
    AiDocumentTree,
    AiSourceDeletePreview,
    AiValidationRead,
    PaginatedAiDocuments,
    PaginatedAiReferences,
    PaginatedAiRefreshes,
)
from app.services.ai_document_queries import (
    get_ai_snapshot,
    get_ai_tree,
    list_ai_documents,
    list_ai_references,
    list_ai_refreshes,
    list_ai_validations,
)
from app.services.ai_document_sources import (
    create_ai_document_source,
    delete_ai_source,
    discover_ai_document_sources,
    get_ai_source,
    preview_ai_source_deletion,
)
from app.services.background_jobs import active_job_for_source_refresh
from app.services.source_management import DuplicateSourceError
from app.storage.ai_document_store import AiDocumentBlobNotFoundError, LocalAiDocumentStore

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/sites/{site_id}/ai-document-sources/discover", response_model=AiDocumentDiscoveryResult
)
async def discover(site_id: int, db: DbSession) -> AiDocumentDiscoveryResult:
    result = await discover_ai_document_sources(db, site_id)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post(
    "/sites/{site_id}/ai-document-sources", response_model=AiDocumentSourceRead, status_code=201
)
def create(site_id: int, payload: AiDocumentSourceCreate, db: DbSession) -> AiDocumentSourceRead:
    try:
        source = create_ai_document_source(db, site_id, payload)
    except (DuplicateSourceError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if source is None:
        raise HTTPException(404, "Site not found")
    result = get_ai_source(db, source.id)
    assert result is not None
    return result


@router.get("/ai-document-sources/{source_id}", response_model=AiDocumentSourceRead)
def detail(source_id: int, db: DbSession) -> AiDocumentSourceRead:
    result = get_ai_source(db, source_id)
    if result is None:
        raise HTTPException(404, "AI Document Source not found")
    return result


@router.get("/ai-document-sources/{source_id}/refreshes", response_model=PaginatedAiRefreshes)
def refreshes(
    source_id: int,
    db: DbSession,
    limit: int = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> PaginatedAiRefreshes:
    return list_ai_refreshes(db, source_id, limit, offset)


@router.get(
    "/ai-document-sources/{source_id}/refreshes/{refresh_id}", response_model=AiDocumentRefreshRead
)
def refresh_detail(source_id: int, refresh_id: int, db: DbSession) -> AiDocumentRefreshRead:
    item = db.scalar(
        select(AiDocumentRefresh)
        .join(SourceRefresh)
        .where(AiDocumentRefresh.id == refresh_id, SourceRefresh.url_source_id == source_id)
    )
    if item is None:
        raise HTTPException(404, "AI document refresh not found")
    return AiDocumentRefreshRead.model_validate(item)


@router.get(
    "/ai-document-sources/{source_id}/refreshes/{refresh_id}/documents",
    response_model=PaginatedAiDocuments,
)
def documents(
    source_id: int,
    refresh_id: int,
    db: DbSession,
    search: str | None = None,
    kind: str | None = None,
    role: str | None = None,
    fetch_state: str | None = None,
    parse_state: str | None = None,
    changed: str | None = None,
    depth: int | None = Query(None, ge=0),
    sort: Literal["url", "depth", "fetched", "size"] = "depth",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> PaginatedAiDocuments:
    _require_refresh(db, source_id, refresh_id)
    return list_ai_documents(
        db,
        refresh_id,
        search=search,
        kind=kind,
        role=role,
        fetch_state=fetch_state,
        parse_state=parse_state,
        changed=changed,
        depth=depth,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/ai-document-sources/{source_id}/refreshes/{refresh_id}/references",
    response_model=PaginatedAiReferences,
)
def references(
    source_id: int,
    refresh_id: int,
    db: DbSession,
    search: str | None = None,
    in_scope: bool | None = None,
    optional: bool | None = None,
    fetched: bool | None = None,
    limit: int = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> PaginatedAiReferences:
    _require_refresh(db, source_id, refresh_id)
    return list_ai_references(
        db,
        refresh_id,
        search=search,
        in_scope=in_scope,
        optional=optional,
        fetched=fetched,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/ai-document-sources/{source_id}/refreshes/{refresh_id}/tree", response_model=AiDocumentTree
)
def tree(source_id: int, refresh_id: int, db: DbSession) -> AiDocumentTree:
    _require_refresh(db, source_id, refresh_id)
    return get_ai_tree(db, refresh_id)


@router.get(
    "/ai-document-sources/{source_id}/refreshes/{refresh_id}/validation",
    response_model=list[AiValidationRead],
)
def validation(source_id: int, refresh_id: int, db: DbSession) -> list[AiValidationRead]:
    _require_refresh(db, source_id, refresh_id)
    return list_ai_validations(db, refresh_id)


@router.get("/ai-document-snapshots/{snapshot_id}", response_model=AiDocumentSnapshotRead)
def snapshot(snapshot_id: int, db: DbSession) -> AiDocumentSnapshotRead:
    result = get_ai_snapshot(db, snapshot_id)
    if result is None:
        raise HTTPException(404, "Saved AI document not found")
    return result


@router.get("/ai-document-snapshots/{snapshot_id}/content")
def content(snapshot_id: int, db: DbSession) -> Response:
    payload, _name = _saved_content(db, snapshot_id)
    return Response(payload, media_type="text/plain", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/ai-document-snapshots/{snapshot_id}/download")
def download(snapshot_id: int, db: DbSession) -> Response:
    payload, name = _saved_content(db, snapshot_id)
    return Response(
        payload,
        media_type="application/octet-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{name}"',
        },
    )


@router.get(
    "/ai-document-sources/{source_id}/deletion-preview", response_model=AiSourceDeletePreview
)
def deletion_preview(source_id: int, db: DbSession) -> AiSourceDeletePreview:
    result = preview_ai_source_deletion(db, source_id)
    if result is None:
        raise HTTPException(404, "AI Document Source not found")
    return result


@router.delete("/ai-document-sources/{source_id}")
def remove(source_id: int, db: DbSession) -> dict[str, int]:
    source_refresh_ids = list(
        db.scalars(select(SourceRefresh.id).where(SourceRefresh.url_source_id == source_id))
    )
    if any(active_job_for_source_refresh(db, refresh_id) for refresh_id in source_refresh_ids):
        raise HTTPException(409, "The source has an active refresh job.")
    deleted = delete_ai_source(
        db, source_id, LocalAiDocumentStore(get_settings().ai_document_storage_root)
    )
    if deleted is None:
        raise HTTPException(404, "AI Document Source not found")
    return {"deleted_source_id": deleted}


def _require_refresh(db: Session, source_id: int, refresh_id: int) -> None:
    if (
        db.scalar(
            select(AiDocumentRefresh.id)
            .join(SourceRefresh)
            .where(AiDocumentRefresh.id == refresh_id, SourceRefresh.url_source_id == source_id)
        )
        is None
    ):
        raise HTTPException(404, "AI document refresh not found")


def _saved_content(db: Session, snapshot_id: int) -> tuple[bytes, str]:
    item = db.scalar(
        select(AiDocumentSnapshot)
        .options(joinedload(AiDocumentSnapshot.blob))
        .where(AiDocumentSnapshot.id == snapshot_id)
    )
    if item is None or item.blob is None:
        raise HTTPException(404, "Retained file evidence is unavailable")
    try:
        payload = LocalAiDocumentStore(get_settings().ai_document_storage_root).get(item.blob)
    except AiDocumentBlobNotFoundError as exc:
        raise HTTPException(410, "Retained file evidence is missing from local storage") from exc
    name = (
        urlsplit(item.final_url or item.requested_url).path.rsplit("/", 1)[-1] or "ai-document.txt"
    )
    safe_name = (
        "".join(char for char in name if char.isalnum() or char in "._-")[:120] or "ai-document.txt"
    )
    return payload, safe_name
