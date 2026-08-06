from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PageCategory, PageCategoryAssignment, Scan, SitePage, WebResource
from app.schemas.page_workspaces import (
    BulkMutationResult,
    BulkPageCategories,
    BulkPageMetadata,
    PageMetadataUpdate,
)


def ensure_site_page(
    db: Session,
    *,
    scan: Scan,
    resource: WebResource,
    associated_at: datetime | None = None,
) -> SitePage | None:
    if scan.website_property_id is None:
        return None
    existing = find_site_page(db, scan.website_property_id, resource.id)
    if existing is not None:
        return existing
    try:
        with db.begin_nested():
            site_page = SitePage(
                website_property_id=scan.website_property_id,
                resource_id=resource.id,
                created_at=associated_at,
                updated_at=associated_at,
            )
            db.add(site_page)
            db.flush()
        return site_page
    except IntegrityError:
        return find_site_page(db, scan.website_property_id, resource.id)


def find_site_page(db: Session, site_id: int, resource_id: int) -> SitePage | None:
    return db.scalar(
        select(SitePage).where(
            SitePage.website_property_id == site_id,
            SitePage.resource_id == resource_id,
        )
    )


def update_page_metadata(db: Session, site_page: SitePage, payload: PageMetadataUpdate) -> SitePage:
    if "owner_label" in payload.model_fields_set:
        site_page.owner_label = payload.owner_label
    if "workflow_status" in payload.model_fields_set and payload.workflow_status is not None:
        site_page.workflow_status = payload.workflow_status
    if "category_ids" in payload.model_fields_set and payload.category_ids is not None:
        categories = _site_categories(db, site_page.website_property_id, payload.category_ids)
        if len(categories) != len(payload.category_ids):
            raise ValueError("One or more categories do not belong to this Site.")
        existing_category_ids = set(
            db.scalars(
                select(PageCategoryAssignment.category_id).where(
                    PageCategoryAssignment.site_page_id == site_page.id
                )
            )
        )
        if any(
            not category.is_active and category.id not in existing_category_ids
            for category in categories
        ):
            raise ValueError("Archived categories cannot receive new assignments.")
        db.execute(
            delete(PageCategoryAssignment).where(
                PageCategoryAssignment.site_page_id == site_page.id
            )
        )
        db.add_all(
            PageCategoryAssignment(site_page_id=site_page.id, category_id=category_id)
            for category_id in payload.category_ids
        )
    db.commit()
    db.refresh(site_page)
    return site_page


def bulk_categories(db: Session, site_id: int, payload: BulkPageCategories) -> BulkMutationResult:
    pages = _site_pages(db, site_id, payload.resource_ids)
    if len(pages) != len(payload.resource_ids):
        raise ValueError("One or more Pages do not belong to this Site.")
    category_ids = list(set(payload.add_category_ids + payload.remove_category_ids))
    categories = _site_categories(db, site_id, category_ids)
    if len(categories) != len(category_ids):
        raise ValueError("One or more categories do not belong to this Site.")
    added_ids = set(payload.add_category_ids)
    if any(not category.is_active and category.id in added_ids for category in categories):
        raise ValueError("Archived categories cannot receive new assignments.")
    page_ids = [page.id for page in pages]
    existing = set(
        db.execute(
            select(
                PageCategoryAssignment.site_page_id,
                PageCategoryAssignment.category_id,
            ).where(
                PageCategoryAssignment.site_page_id.in_(page_ids),
                PageCategoryAssignment.category_id.in_(category_ids),
            )
        ).all()
    )
    changed_pages: set[int] = set()
    for page in pages:
        for category_id in payload.add_category_ids:
            if (page.id, category_id) not in existing:
                db.add(PageCategoryAssignment(site_page_id=page.id, category_id=category_id))
                changed_pages.add(page.id)
        removals = [
            category_id
            for category_id in payload.remove_category_ids
            if (page.id, category_id) in existing
        ]
        if removals:
            db.execute(
                delete(PageCategoryAssignment).where(
                    PageCategoryAssignment.site_page_id == page.id,
                    PageCategoryAssignment.category_id.in_(removals),
                )
            )
            changed_pages.add(page.id)
    db.commit()
    return BulkMutationResult(
        selected=len(pages),
        changed=len(changed_pages),
        unchanged=len(pages) - len(changed_pages),
    )


def bulk_metadata(db: Session, site_id: int, payload: BulkPageMetadata) -> BulkMutationResult:
    pages = _site_pages(db, site_id, payload.resource_ids)
    if len(pages) != len(payload.resource_ids):
        raise ValueError("One or more Pages do not belong to this Site.")
    changed = 0
    for page in pages:
        page_changed = False
        if "owner_label" in payload.model_fields_set and page.owner_label != payload.owner_label:
            page.owner_label = payload.owner_label
            page_changed = True
        if (
            "workflow_status" in payload.model_fields_set
            and payload.workflow_status is not None
            and page.workflow_status != payload.workflow_status
        ):
            page.workflow_status = payload.workflow_status
            page_changed = True
        changed += int(page_changed)
    db.commit()
    return BulkMutationResult(selected=len(pages), changed=changed, unchanged=len(pages) - changed)


def _site_pages(db: Session, site_id: int, resource_ids: list[int]) -> list[SitePage]:
    if not resource_ids:
        return []
    return list(
        db.scalars(
            select(SitePage).where(
                SitePage.website_property_id == site_id,
                SitePage.resource_id.in_(resource_ids),
            )
        )
    )


def _site_categories(db: Session, site_id: int, category_ids: list[int]) -> list[PageCategory]:
    if not category_ids:
        return []
    return list(
        db.scalars(
            select(PageCategory).where(
                PageCategory.website_property_id == site_id,
                PageCategory.id.in_(category_ids),
            )
        )
    )
