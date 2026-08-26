from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    PageCategory,
    PageCategoryAssignment,
    PageCategoryAssignmentSupport,
    Scan,
    SitePage,
    WebResource,
)
from app.schemas.page_workspaces import (
    BulkMutationResult,
    BulkPageCategories,
    BulkPageDelete,
    BulkPageMetadata,
    BulkPageWorkspaceState,
    PageMetadataUpdate,
    PageWorkspaceStateUpdate,
)
from app.services.url_identity import resolve_resource_id


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
    resolved_id = resolve_resource_id(db, resource_id)
    if resolved_id is None:
        return None
    return db.scalar(
        select(SitePage).where(
            SitePage.website_property_id == site_id,
            SitePage.resource_id == resolved_id,
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
        assignments = list(
            db.scalars(
                select(PageCategoryAssignment).where(
                    PageCategoryAssignment.site_page_id == site_page.id
                )
            )
        )
        assignment_by_category = {assignment.category_id: assignment for assignment in assignments}
        existing_category_ids = set(assignment_by_category)
        if any(
            not category.is_active and category.id not in existing_category_ids
            for category in categories
        ):
            raise ValueError("Archived categories cannot receive new assignments.")
        desired_manual = set(payload.category_ids)
        manual_supports = (
            {
                support.page_category_assignment_id: support
                for support in db.scalars(
                    select(PageCategoryAssignmentSupport).where(
                        PageCategoryAssignmentSupport.page_category_assignment_id.in_(
                            [assignment.id for assignment in assignments]
                        ),
                        PageCategoryAssignmentSupport.support_type == "manual",
                    )
                )
            }
            if assignments
            else {}
        )
        for category_id in desired_manual:
            assignment = assignment_by_category.get(category_id)
            if assignment is None:
                assignment = PageCategoryAssignment(
                    site_page_id=site_page.id, category_id=category_id
                )
                db.add(assignment)
                db.flush()
                assignment_by_category[category_id] = assignment
            if assignment.id not in manual_supports:
                db.add(
                    PageCategoryAssignmentSupport(
                        page_category_assignment_id=assignment.id,
                        support_type="manual",
                        support_key="manual",
                    )
                )
        db.flush()
        removed_support_ids = [
            manual_supports[assignment.id].id
            for category_id, assignment in assignment_by_category.items()
            if category_id not in desired_manual and assignment.id in manual_supports
        ]
        if removed_support_ids:
            db.execute(
                delete(PageCategoryAssignmentSupport).where(
                    PageCategoryAssignmentSupport.id.in_(removed_support_ids)
                )
            )
            db.flush()
        _delete_unsupported_assignments(
            db, [assignment.id for assignment in assignment_by_category.values()]
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
    assignments = list(
        db.scalars(
            select(PageCategoryAssignment).where(
                PageCategoryAssignment.site_page_id.in_(page_ids),
                PageCategoryAssignment.category_id.in_(category_ids),
            )
        )
    )
    assignment_map = {(item.site_page_id, item.category_id): item for item in assignments}
    manual_supports = (
        {
            support.page_category_assignment_id: support
            for support in db.scalars(
                select(PageCategoryAssignmentSupport).where(
                    PageCategoryAssignmentSupport.page_category_assignment_id.in_(
                        [assignment.id for assignment in assignments]
                    ),
                    PageCategoryAssignmentSupport.support_type == "manual",
                )
            )
        }
        if assignments
        else {}
    )
    changed_pages: set[int] = set()
    for page in pages:
        for category_id in payload.add_category_ids:
            assignment = assignment_map.get((page.id, category_id))
            if assignment is None:
                assignment = PageCategoryAssignment(site_page_id=page.id, category_id=category_id)
                db.add(assignment)
                db.flush()
                assignment_map[(page.id, category_id)] = assignment
            if assignment.id not in manual_supports:
                db.add(
                    PageCategoryAssignmentSupport(
                        page_category_assignment_id=assignment.id,
                        support_type="manual",
                        support_key="manual",
                    )
                )
                changed_pages.add(page.id)
        db.flush()
        removals = [
            assignment_map[(page.id, category_id)]
            for category_id in payload.remove_category_ids
            if (page.id, category_id) in assignment_map
            and assignment_map[(page.id, category_id)].id in manual_supports
        ]
        if removals:
            db.execute(
                delete(PageCategoryAssignmentSupport).where(
                    PageCategoryAssignmentSupport.id.in_(
                        [manual_supports[item.id].id for item in removals]
                    ),
                )
            )
            db.flush()
            _delete_unsupported_assignments(db, [item.id for item in removals])
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


def update_page_workspace_state(
    db: Session, site_page: SitePage, payload: PageWorkspaceStateUpdate
) -> SitePage:
    if site_page.workspace_state != payload.workspace_state:
        site_page.workspace_state = payload.workspace_state
        site_page.suppressed_at = (
            datetime.now(UTC) if payload.workspace_state == "suppressed" else None
        )
        db.commit()
        db.refresh(site_page)
    return site_page


def bulk_workspace_state(
    db: Session, site_id: int, payload: BulkPageWorkspaceState
) -> BulkMutationResult:
    resolved_values = [resolve_resource_id(db, resource_id) for resource_id in payload.resource_ids]
    if any(resource_id is None for resource_id in resolved_values):
        raise ValueError("One or more Pages do not belong to this Site.")
    resolved_ids = {resource_id for resource_id in resolved_values if resource_id is not None}
    pages = _site_pages(db, site_id, list(resolved_ids))
    if len(pages) != len(resolved_ids):
        raise ValueError("One or more Pages do not belong to this Site.")
    changed = 0
    now = datetime.now(UTC)
    for page in pages:
        if page.workspace_state == payload.workspace_state:
            continue
        page.workspace_state = payload.workspace_state
        page.suppressed_at = now if payload.workspace_state == "suppressed" else None
        changed += 1
    db.commit()
    return BulkMutationResult(selected=len(pages), changed=changed, unchanged=len(pages) - changed)


def bulk_delete_pages(db: Session, site_id: int, payload: BulkPageDelete) -> BulkMutationResult:
    resolved_values = [resolve_resource_id(db, resource_id) for resource_id in payload.resource_ids]
    if any(resource_id is None for resource_id in resolved_values):
        raise ValueError("One or more Pages do not belong to this Site.")
    resolved_ids = {resource_id for resource_id in resolved_values if resource_id is not None}
    pages = _site_pages(db, site_id, list(resolved_ids))
    if len(pages) != len(resolved_ids):
        raise ValueError("One or more Pages do not belong to this Site.")
    for page in pages:
        db.delete(page)
    db.commit()
    return BulkMutationResult(selected=len(pages), changed=len(pages), unchanged=0)


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


def _delete_unsupported_assignments(db: Session, assignment_ids: list[int]) -> None:
    if not assignment_ids:
        return
    unsupported = list(
        db.scalars(
            select(PageCategoryAssignment.id).where(
                PageCategoryAssignment.id.in_(assignment_ids),
                ~select(PageCategoryAssignmentSupport.id)
                .where(
                    PageCategoryAssignmentSupport.page_category_assignment_id
                    == PageCategoryAssignment.id
                )
                .exists(),
            )
        )
    )
    if unsupported:
        db.execute(delete(PageCategoryAssignment).where(PageCategoryAssignment.id.in_(unsupported)))
