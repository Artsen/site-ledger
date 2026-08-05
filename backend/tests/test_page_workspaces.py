from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from app.models import (
    PageCategoryAssignment,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.page_workspaces import (
    BulkPageCategories,
    BulkPageMetadata,
    PageCategoryCreate,
    PageCategoryUpdate,
    PageMetadataUpdate,
)
from app.services.page_categories import (
    DuplicateCategoryError,
    create_category,
    delete_category,
    list_categories,
    preview_category_deletion,
    update_category,
)
from app.services.page_queries import get_site_page, list_site_pages
from app.services.scan_deletion import delete_scan
from app.services.site_management import delete_site
from app.services.site_pages import (
    bulk_categories,
    bulk_metadata,
    ensure_site_page,
    update_page_metadata,
)
from app.storage.content_store import LocalContentStore


def test_site_page_identity_is_site_scoped_and_ad_hoc_scans_do_not_create(db_session) -> None:
    first_site = _site(db_session, "First", "https://example.com/")
    second_site = _site(db_session, "Second", "https://example.com/docs/")
    resource = _resource(db_session)
    first_scan = _scan(db_session, first_site.id)
    second_scan = _scan(db_session, second_site.id)
    ad_hoc_scan = _scan(db_session, None)

    first = ensure_site_page(db_session, scan=first_scan, resource=resource)
    repeated = ensure_site_page(db_session, scan=first_scan, resource=resource)
    second = ensure_site_page(db_session, scan=second_scan, resource=resource)
    ad_hoc = ensure_site_page(db_session, scan=ad_hoc_scan, resource=resource)

    assert first is not None and repeated is not None and second is not None
    assert first.id == repeated.id
    assert first.id != second.id
    assert ad_hoc is None
    assert db_session.query(SitePage).count() == 2


def test_site_page_catalog_preserves_manual_metadata_without_observations(db_session) -> None:
    site = _site(db_session)
    resource = _resource(db_session)
    scan = _scan(db_session, site.id)
    site_page = ensure_site_page(db_session, scan=scan, resource=resource)
    assert site_page is not None
    update_page_metadata(
        db_session,
        site_page,
        PageMetadataUpdate(owner_label="  Documentation  ", workflow_status="needs_review"),
    )

    pages = list_site_pages(db_session, site.id)
    detail = get_site_page(db_session, site.id, resource.id)

    assert pages is not None and pages.total == 1
    assert pages.items[0].observation_count == 0
    assert pages.items[0].latest_snapshot_id is None
    assert pages.items[0].owner_label == "Documentation"
    assert detail is not None
    assert "retry" not in detail.model_dump_json().casefold()


def test_categories_are_site_scoped_editable_archivable_and_assignable(db_session) -> None:
    site = _site(db_session)
    other = _site(db_session, "Other", "https://other.example/")
    resource = _resource(db_session)
    site_page = ensure_site_page(db_session, scan=_scan(db_session, site.id), resource=resource)
    assert site_page is not None
    category = create_category(
        db_session,
        site.id,
        PageCategoryCreate(name="  Product Docs  ", color_key="blue"),
    )
    assert category is not None and category.name == "Product Docs"
    with pytest.raises(DuplicateCategoryError):
        create_category(
            db_session,
            site.id,
            PageCategoryCreate(name="product docs", color_key="teal"),
        )
    assert (
        create_category(
            db_session,
            other.id,
            PageCategoryCreate(name="product docs", color_key="teal"),
        )
        is not None
    )

    update_page_metadata(
        db_session,
        site_page,
        PageMetadataUpdate(category_ids=[category.id]),
    )
    update_category(
        db_session,
        site.id,
        category.id,
        PageCategoryUpdate(name="Documentation", is_active=False, color_key="indigo"),
    )
    listed = list_categories(db_session, site.id, active_state="archived")
    preview = preview_category_deletion(db_session, site.id, category.id)

    assert listed is not None and listed.items[0].assignment_count == 1
    assert preview is not None and preview.assignment_count == 1
    assert preview.sample_pages[0].resource_id == resource.id
    assert delete_category(db_session, site.id, category.id) == category.id
    assert db_session.get(SitePage, site_page.id) is not None
    assert db_session.query(PageCategoryAssignment).count() == 0


def test_bulk_categories_owner_and_workflow_are_idempotent(db_session) -> None:
    site = _site(db_session)
    resources = [_resource(db_session, f"/page-{index}") for index in range(2)]
    scan = _scan(db_session, site.id)
    pages = [ensure_site_page(db_session, scan=scan, resource=item) for item in resources]
    assert all(page is not None for page in pages)
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Review", color_key="amber")
    )
    assert category is not None
    request = BulkPageCategories(
        resource_ids=[resource.id for resource in resources], add_category_ids=[category.id]
    )
    first = bulk_categories(db_session, site.id, request)
    repeated = bulk_categories(db_session, site.id, request)
    metadata = bulk_metadata(
        db_session,
        site.id,
        BulkPageMetadata(
            resource_ids=[resource.id for resource in resources],
            owner_label="Marketing",
            workflow_status="approved",
        ),
    )

    assert (first.changed, repeated.changed) == (2, 0)
    assert metadata.changed == 2
    assert db_session.query(PageCategoryAssignment).count() == 2
    assert {page.owner_label for page in db_session.scalars(select(SitePage))} == {"Marketing"}


def test_archived_categories_preserve_existing_assignments_but_reject_new_ones(
    db_session,
) -> None:
    site = _site(db_session)
    resources = [_resource(db_session, f"/archive-{index}") for index in range(2)]
    scan = _scan(db_session, site.id)
    pages = [ensure_site_page(db_session, scan=scan, resource=item) for item in resources]
    assert pages[0] is not None and pages[1] is not None
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Legacy", color_key="stone")
    )
    assert category is not None
    update_page_metadata(db_session, pages[0], PageMetadataUpdate(category_ids=[category.id]))
    update_category(
        db_session,
        site.id,
        category.id,
        PageCategoryUpdate(is_active=False),
    )

    update_page_metadata(db_session, pages[0], PageMetadataUpdate(category_ids=[category.id]))
    with pytest.raises(ValueError, match="Archived categories"):
        update_page_metadata(db_session, pages[1], PageMetadataUpdate(category_ids=[category.id]))
    with pytest.raises(ValueError, match="Archived categories"):
        bulk_categories(
            db_session,
            site.id,
            BulkPageCategories(resource_ids=[resources[1].id], add_category_ids=[category.id]),
        )

    removed = bulk_categories(
        db_session,
        site.id,
        BulkPageCategories(resource_ids=[resources[0].id], remove_category_ids=[category.id]),
    )
    assert removed.changed == 1


def test_page_filters_are_set_based(db_session) -> None:
    site = _site(db_session)
    resources = [_resource(db_session, f"/filter-{index}") for index in range(2)]
    scan = _scan(db_session, site.id)
    pages = [ensure_site_page(db_session, scan=scan, resource=item) for item in resources]
    assert pages[0] is not None and pages[1] is not None
    pages[0].owner_label = "Product"
    pages[0].workflow_status = "updating"
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Product", color_key="green")
    )
    assert category is not None
    db_session.add(PageCategoryAssignment(site_page_id=pages[0].id, category_id=category.id))
    db_session.commit()

    categorized = list_site_pages(db_session, site.id, category_id=category.id)
    uncategorized = list_site_pages(db_session, site.id, uncategorized=True)
    updating = list_site_pages(db_session, site.id, workflow_status="updating", owner="prod")

    assert categorized is not None and categorized.total == 1
    assert uncategorized is not None and uncategorized.total == 1
    assert updating is not None and updating.total == 1


def test_site_page_catalog_query_count_is_bounded(db_session) -> None:
    site = _site(db_session)
    scan = _scan(db_session, site.id)
    for index in range(20):
        resource = _resource(db_session, f"/bounded-{index}")
        assert ensure_site_page(db_session, scan=scan, resource=resource) is not None
    db_session.commit()
    queries: list[str] = []

    def before_cursor_execute(*args) -> None:
        queries.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        result = list_site_pages(db_session, site.id, limit=20)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_cursor_execute)

    assert result is not None and len(result.items) == 20
    assert len(queries) <= 5


def test_scan_deletion_preserves_site_page_metadata_and_site_deletion_releases_resource(
    db_session, tmp_path
) -> None:
    site = _site(db_session)
    resource = _resource(db_session)
    scan = _scan(db_session, site.id)
    site_page = ensure_site_page(db_session, scan=scan, resource=resource)
    assert site_page is not None
    site_page.owner_label = "Product"
    site_page.workflow_status = "approved"
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=None,
        http_status=None,
        content_type=None,
        encoding=None,
        crawl_depth=0,
        fetched_at=datetime(2026, 8, 5, tzinfo=UTC),
        response_time_ms=None,
        response_headers=None,
        redirect_chain=[],
        fetch_state="failed",
        error_type="connection_error",
        error_message="offline",
    )
    db_session.add(snapshot)
    db_session.commit()

    assert delete_scan(db_session, scan.id, LocalContentStore(tmp_path)) is not None
    retained = db_session.get(SitePage, site_page.id)
    assert retained is not None
    assert (retained.owner_label, retained.workflow_status) == ("Product", "approved")
    assert db_session.get(WebResource, resource.id) is not None

    assert delete_site(db_session, site.id) == site.id
    assert db_session.get(SitePage, site_page.id) is None
    assert db_session.get(WebResource, resource.id) is None


def _site(
    db_session, name: str = "Example", base_url: str = "https://example.com/"
) -> WebsiteProperty:
    site = WebsiteProperty(
        name=name,
        base_url=base_url,
        normalized_base_url=base_url,
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    db_session.add(site)
    db_session.flush()
    return site


def _resource(db_session, path: str = "/page") -> WebResource:
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://example.com{path}",
        scheme="https",
        host="example.com",
        port=None,
        path=path,
        query="",
    )
    db_session.add(resource)
    db_session.flush()
    return resource


def _scan(db_session, site_id: int | None) -> Scan:
    scan = Scan(
        website_property_id=site_id,
        starting_url="https://example.com/",
        status="completed",
        scope_config={},
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    db_session.add(scan)
    db_session.flush()
    return scan
