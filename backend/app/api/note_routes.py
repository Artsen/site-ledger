from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.dependencies import DbSession, PageOffset, ScanListLimit
from app.schemas.page_workspaces import (
    NoteCreate,
    NoteList,
    NoteRead,
    NoteSort,
    NoteUpdate,
)
from app.services.notes import (
    create_note,
    delete_note,
    find_page_target,
    list_notes,
    scan_exists,
    site_exists,
    update_note,
)

router = APIRouter(prefix="/api")


@router.get("/sites/{site_id}/notes", response_model=NoteList)
def get_site_notes(
    site_id: int,
    db: DbSession,
    pinned: bool | None = None,
    search: str | None = None,
    sort: NoteSort = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> NoteList:
    if not site_exists(db, site_id):
        raise HTTPException(404, "Site not found")
    return list_notes(
        db,
        website_property_id=site_id,
        pinned=pinned,
        search=search,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/sites/{site_id}/notes", response_model=NoteRead, status_code=201)
def post_site_note(site_id: int, payload: NoteCreate, db: DbSession) -> NoteRead:
    if not site_exists(db, site_id):
        raise HTTPException(404, "Site not found")
    return NoteRead.model_validate(create_note(db, payload, website_property_id=site_id))


@router.get("/scans/{scan_id}/notes", response_model=NoteList)
def get_scan_notes(
    scan_id: int,
    db: DbSession,
    pinned: bool | None = None,
    search: str | None = None,
    sort: NoteSort = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> NoteList:
    if not scan_exists(db, scan_id):
        raise HTTPException(404, "Scan not found")
    return list_notes(
        db,
        scan_id=scan_id,
        pinned=pinned,
        search=search,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/scans/{scan_id}/notes", response_model=NoteRead, status_code=201)
def post_scan_note(scan_id: int, payload: NoteCreate, db: DbSession) -> NoteRead:
    if not scan_exists(db, scan_id):
        raise HTTPException(404, "Scan not found")
    return NoteRead.model_validate(create_note(db, payload, scan_id=scan_id))


@router.get("/sites/{site_id}/pages/{resource_id}/notes", response_model=NoteList)
def get_page_notes(
    site_id: int,
    resource_id: int,
    db: DbSession,
    pinned: bool | None = None,
    search: str | None = None,
    sort: NoteSort = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: ScanListLimit = 25,
    offset: PageOffset = 0,
) -> NoteList:
    site_page = find_page_target(db, site_id, resource_id)
    if site_page is None:
        raise HTTPException(404, "Page not found")
    return list_notes(
        db,
        site_page_id=site_page.id,
        pinned=pinned,
        search=search,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.post("/sites/{site_id}/pages/{resource_id}/notes", response_model=NoteRead, status_code=201)
def post_page_note(site_id: int, resource_id: int, payload: NoteCreate, db: DbSession) -> NoteRead:
    site_page = find_page_target(db, site_id, resource_id)
    if site_page is None:
        raise HTTPException(404, "Page not found")
    return NoteRead.model_validate(create_note(db, payload, site_page_id=site_page.id))


@router.patch("/notes/{note_id}", response_model=NoteRead)
def patch_note(note_id: int, payload: NoteUpdate, db: DbSession) -> NoteRead:
    note = update_note(db, note_id, payload)
    if note is None:
        raise HTTPException(404, "Note not found")
    return NoteRead.model_validate(note)


@router.delete("/notes/{note_id}")
def remove_note(note_id: int, db: DbSession) -> dict[str, int]:
    deleted = delete_note(db, note_id)
    if deleted is None:
        raise HTTPException(404, "Note not found")
    return {"deleted_note_id": deleted}
