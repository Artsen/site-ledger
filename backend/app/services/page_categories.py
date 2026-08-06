from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PageCategory, PageCategoryAssignment, SitePage, WebResource, WebsiteProperty
from app.schemas.page_workspaces import (
    CategoryDeletionPage,
    PageCategoryCreate,
    PageCategoryDeletionPreview,
    PageCategoryList,
    PageCategoryRead,
    PageCategoryUpdate,
)


class DuplicateCategoryError(ValueError):
    pass


def normalize_category_name(name: str) -> str:
    return " ".join(name.casefold().split())


def list_categories(
    db: Session,
    site_id: int,
    *,
    search: str | None = None,
    active_state: Literal["active", "archived", "all"] = "all",
    sort: Literal["name", "sort_order", "created_at"] = "sort_order",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> PageCategoryList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    counts = (
        select(
            PageCategoryAssignment.category_id,
            func.count(PageCategoryAssignment.id).label("assignment_count"),
        )
        .group_by(PageCategoryAssignment.category_id)
        .subquery()
    )
    query = (
        select(PageCategory, func.coalesce(counts.c.assignment_count, 0))
        .outerjoin(counts, counts.c.category_id == PageCategory.id)
        .where(PageCategory.website_property_id == site_id)
    )
    if search:
        query = query.where(PageCategory.name.ilike(f"%{search}%"))
    if active_state != "all":
        query = query.where(PageCategory.is_active.is_(active_state == "active"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "name": PageCategory.normalized_name,
        "sort_order": PageCategory.sort_order,
        "created_at": PageCategory.created_at,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.execute(query.order_by(order, PageCategory.id).limit(limit).offset(offset)).all()
    return PageCategoryList(
        items=[_read(category, count) for category, count in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def create_category(db: Session, site_id: int, payload: PageCategoryCreate) -> PageCategory | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    category = PageCategory(
        website_property_id=site_id,
        name=payload.name,
        normalized_name=normalize_category_name(payload.name),
        description=payload.description,
        color_key=payload.color_key,
        sort_order=payload.sort_order,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCategoryError(
            "A category with that name already exists in this Site."
        ) from exc
    db.refresh(category)
    return category


def update_category(
    db: Session, site_id: int, category_id: int, payload: PageCategoryUpdate
) -> PageCategory | None:
    category = db.scalar(
        select(PageCategory).where(
            PageCategory.id == category_id,
            PageCategory.website_property_id == site_id,
        )
    )
    if category is None:
        return None
    for field in ("description", "color_key", "sort_order", "is_active"):
        if field in payload.model_fields_set:
            setattr(category, field, getattr(payload, field))
    if "name" in payload.model_fields_set and payload.name is not None:
        category.name = payload.name
        category.normalized_name = normalize_category_name(payload.name)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateCategoryError(
            "A category with that name already exists in this Site."
        ) from exc
    db.refresh(category)
    return category


def preview_category_deletion(
    db: Session, site_id: int, category_id: int
) -> PageCategoryDeletionPreview | None:
    category = db.scalar(
        select(PageCategory).where(
            PageCategory.id == category_id,
            PageCategory.website_property_id == site_id,
        )
    )
    if category is None:
        return None
    assignment_count = (
        db.scalar(
            select(func.count(PageCategoryAssignment.id)).where(
                PageCategoryAssignment.category_id == category_id
            )
        )
        or 0
    )
    samples = db.execute(
        select(SitePage.resource_id, WebResource.normalized_url)
        .join(PageCategoryAssignment, PageCategoryAssignment.site_page_id == SitePage.id)
        .join(WebResource, WebResource.id == SitePage.resource_id)
        .where(PageCategoryAssignment.category_id == category_id)
        .order_by(WebResource.normalized_url)
        .limit(5)
    ).all()
    return PageCategoryDeletionPreview(
        category=_read(category, assignment_count),
        assignment_count=assignment_count,
        sample_pages=[
            CategoryDeletionPage(resource_id=resource_id, normalized_url=url)
            for resource_id, url in samples
        ],
    )


def delete_category(db: Session, site_id: int, category_id: int) -> int | None:
    category = db.scalar(
        select(PageCategory).where(
            PageCategory.id == category_id,
            PageCategory.website_property_id == site_id,
        )
    )
    if category is None:
        return None
    db.execute(
        delete(PageCategoryAssignment).where(PageCategoryAssignment.category_id == category.id)
    )
    db.execute(delete(PageCategory).where(PageCategory.id == category.id))
    db.commit()
    return category_id


def _read(category: PageCategory, assignment_count: int) -> PageCategoryRead:
    result = PageCategoryRead.model_validate(category)
    result.assignment_count = assignment_count
    return result
