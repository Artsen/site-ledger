from typing import Literal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models import Note, Scan, SitePage, WebsiteProperty
from app.schemas.page_workspaces import NoteCreate, NoteList, NoteUpdate
from app.services.url_identity import resolve_resource_id


def list_notes(
    db: Session,
    *,
    website_property_id: int | None = None,
    scan_id: int | None = None,
    site_page_id: int | None = None,
    pinned: bool | None = None,
    search: str | None = None,
    sort: Literal["created_at", "updated_at"] = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    offset: int = 0,
) -> NoteList:
    target = _target_filter(website_property_id, scan_id, site_page_id)
    query = select(Note).where(target)
    if pinned is not None:
        query = query.where(Note.is_pinned.is_(pinned))
    if search:
        query = query.where(Note.body.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order_column = Note.created_at if sort == "created_at" else Note.updated_at
    order = order_column.desc() if direction == "desc" else order_column.asc()
    items = list(
        db.scalars(
            query.order_by(Note.is_pinned.desc(), order, Note.id.desc()).limit(limit).offset(offset)
        )
    )
    return NoteList(items=items, total=total, limit=limit, offset=offset)


def create_note(
    db: Session,
    payload: NoteCreate,
    *,
    website_property_id: int | None = None,
    scan_id: int | None = None,
    site_page_id: int | None = None,
) -> Note:
    _target_filter(website_property_id, scan_id, site_page_id)
    note = Note(
        website_property_id=website_property_id,
        scan_id=scan_id,
        site_page_id=site_page_id,
        body=payload.body,
        is_pinned=payload.is_pinned,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def update_note(db: Session, note_id: int, payload: NoteUpdate) -> Note | None:
    note = db.get(Note, note_id)
    if note is None:
        return None
    if "body" in payload.model_fields_set and payload.body is not None:
        note.body = payload.body
    if "is_pinned" in payload.model_fields_set and payload.is_pinned is not None:
        note.is_pinned = payload.is_pinned
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note_id: int) -> int | None:
    note = db.get(Note, note_id)
    if note is None:
        return None
    db.delete(note)
    db.commit()
    return note_id


def site_exists(db: Session, site_id: int) -> bool:
    return db.get(WebsiteProperty, site_id) is not None


def scan_exists(db: Session, scan_id: int) -> bool:
    return db.get(Scan, scan_id) is not None


def find_page_target(db: Session, site_id: int, resource_id: int) -> SitePage | None:
    resolved_id = resolve_resource_id(db, resource_id)
    if resolved_id is None:
        return None
    return db.scalar(
        select(SitePage).where(
            SitePage.website_property_id == site_id,
            SitePage.resource_id == resolved_id,
        )
    )


def _target_filter(
    website_property_id: int | None, scan_id: int | None, site_page_id: int | None
) -> ColumnElement[bool]:
    supplied = [value is not None for value in (website_property_id, scan_id, site_page_id)]
    if sum(supplied) != 1:
        raise ValueError("Exactly one note target is required.")
    if website_property_id is not None:
        return Note.website_property_id == website_property_id
    if scan_id is not None:
        return Note.scan_id == scan_id
    assert site_page_id is not None
    return Note.site_page_id == site_page_id
