from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import event, select

from app.crawler.static_crawler import StaticPageCrawler
from app.models import (
    Note,
    PageCategoryAssignment,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebResourceAlias,
    WebsiteProperty,
)
from app.schemas.page_workspaces import (
    BulkPageCategories,
    BulkPageDelete,
    BulkPageMetadata,
    BulkPageWorkspaceState,
    PageCategoryCreate,
    PageCategoryUpdate,
    PageMetadataUpdate,
    PageWorkspaceStateUpdate,
)
from app.services.page_categories import (
    DuplicateCategoryError,
    create_category,
    delete_category,
    list_categories,
    preview_category_deletion,
    update_category,
)
from app.services.page_queries import get_site_page, list_page_observations, list_site_pages
from app.services.scan_deletion import delete_scan
from app.services.scan_queries import get_snapshot_detail
from app.services.site_management import delete_site
from app.services.site_pages import (
    bulk_categories,
    bulk_delete_pages,
    bulk_metadata,
    bulk_workspace_state,
    ensure_site_page,
    update_page_metadata,
    update_page_workspace_state,
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


def test_site_page_workspace_suppression_is_durable_and_preserves_metadata(db_session) -> None:
    site = _site(db_session)
    resources = [_resource(db_session, f"/lifecycle-{index}") for index in range(2)]
    scan = _scan(db_session, site.id)
    pages = [ensure_site_page(db_session, scan=scan, resource=item) for item in resources]
    assert pages[0] is not None and pages[1] is not None
    pages[0].owner_label = "Product"
    pages[0].workflow_status = "approved"
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Retained", color_key="blue")
    )
    assert category is not None
    assignment = PageCategoryAssignment(site_page_id=pages[0].id, category_id=category.id)
    note = Note(site_page_id=pages[0].id, body="Retain this note", is_pinned=True)
    db_session.add_all([assignment, note])
    db_session.commit()

    update_page_workspace_state(
        db_session, pages[0], PageWorkspaceStateUpdate(workspace_state="suppressed")
    )
    assert pages[0].suppressed_at is not None
    assert list_site_pages(db_session, site.id).total == 1  # type: ignore[union-attr]
    removed = list_site_pages(db_session, site.id, workspace_state="suppressed")
    assert removed is not None and removed.items[0].resource_id == resources[0].id
    assert get_site_page(db_session, site.id, resources[0].id).page.workspace_state == "suppressed"  # type: ignore[union-attr]

    later = ensure_site_page(db_session, scan=_scan(db_session, site.id), resource=resources[0])
    assert later is not None and later.id == pages[0].id
    assert later.workspace_state == "suppressed"
    assert (later.owner_label, later.workflow_status) == ("Product", "approved")
    assert db_session.get(PageCategoryAssignment, assignment.id) is not None
    assert db_session.get(Note, note.id) is not None

    result = bulk_workspace_state(
        db_session,
        site.id,
        BulkPageWorkspaceState(
            resource_ids=[resources[0].id, resources[0].id, resources[1].id],
            workspace_state="active",
        ),
    )
    assert (result.selected, result.changed, result.unchanged) == (2, 1, 1)
    assert pages[0].suppressed_at is None
    assert db_session.get(PageCategoryAssignment, assignment.id) is not None
    assert db_session.get(Note, note.id) is not None


def test_bulk_page_workspace_state_rejects_wrong_site_atomically(db_session) -> None:
    site = _site(db_session)
    other = _site(db_session, "Other", "https://other.example/")
    first = _resource(db_session, "/first")
    second = _resource(db_session, "/second")
    first_page = ensure_site_page(db_session, scan=_scan(db_session, site.id), resource=first)
    ensure_site_page(db_session, scan=_scan(db_session, other.id), resource=second)
    assert first_page is not None

    with pytest.raises(ValueError, match="do not belong"):
        bulk_workspace_state(
            db_session,
            site.id,
            BulkPageWorkspaceState(
                resource_ids=[first.id, second.id], workspace_state="suppressed"
            ),
        )
    assert first_page.workspace_state == "active"


def test_page_delete_removes_workspace_data_and_scan_can_recreate(db_session) -> None:
    site = _site(db_session)
    resource = _resource(db_session, "/delete-recreate")
    scan = _scan(db_session, site.id)
    page = ensure_site_page(db_session, scan=scan, resource=resource)
    assert page is not None
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Temporary", color_key="blue")
    )
    assert category is not None
    assignment = PageCategoryAssignment(site_page_id=page.id, category_id=category.id)
    note = Note(site_page_id=page.id, body="Delete with workspace", is_pinned=False)
    db_session.add_all([assignment, note])
    db_session.commit()

    result = bulk_delete_pages(
        db_session,
        site.id,
        BulkPageDelete(resource_ids=[resource.id, resource.id]),
    )

    assert (result.selected, result.changed, result.unchanged) == (1, 1, 0)
    assert db_session.query(SitePage).count() == 0
    assert db_session.get(PageCategoryAssignment, assignment.id) is None
    assert db_session.get(Note, note.id) is None
    assert db_session.get(WebResource, resource.id) is not None
    assert db_session.get(Scan, scan.id) is not None

    recreated = ensure_site_page(
        db_session,
        scan=_scan(db_session, site.id),
        resource=resource,
    )
    assert recreated is not None
    assert recreated.workspace_state == "active"
    assert recreated.owner_label is None
    assert recreated.workflow_status == "unreviewed"
    assert db_session.query(SitePage).count() == 1


def test_page_delete_rejects_wrong_site_atomically(db_session) -> None:
    site = _site(db_session)
    other = _site(db_session, "Other", "https://other.example/")
    first = _resource(db_session, "/delete-first")
    second = _resource(db_session, "/delete-second")
    first_page = ensure_site_page(db_session, scan=_scan(db_session, site.id), resource=first)
    second_page = ensure_site_page(db_session, scan=_scan(db_session, other.id), resource=second)
    assert first_page is not None and second_page is not None

    with pytest.raises(ValueError, match="do not belong"):
        bulk_delete_pages(
            db_session,
            site.id,
            BulkPageDelete(resource_ids=[first.id, second.id]),
        )

    assert db_session.get(SitePage, first_page.id) is not None
    assert db_session.get(SitePage, second_page.id) is not None


@pytest.mark.asyncio
async def test_page_delete_between_real_scans_recreates_clean_workspace(
    db_session, tmp_path
) -> None:
    site = _site(db_session)
    scan_a = _scan(db_session, site.id)
    scan_a.status = "queued"
    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(_two_page_handler),
    ).run(scan_a)
    resource = db_session.scalar(
        select(WebResource).where(WebResource.normalized_url == "https://example.com/foo")
    )
    assert resource is not None
    page_a = db_session.scalar(
        select(SitePage).where(
            SitePage.website_property_id == site.id,
            SitePage.resource_id == resource.id,
        )
    )
    snapshot_a = db_session.scalar(
        select(ResourceSnapshot).where(
            ResourceSnapshot.scan_id == scan_a.id,
            ResourceSnapshot.resource_id == resource.id,
        )
    )
    assert page_a is not None and snapshot_a is not None
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Delete lifecycle", color_key="blue")
    )
    assert category is not None
    update_page_metadata(
        db_session,
        page_a,
        PageMetadataUpdate(
            owner_label="Product",
            workflow_status="approved",
            category_ids=[category.id],
        ),
    )
    note = Note(site_page_id=page_a.id, body="Delete with Page", is_pinned=True)
    db_session.add(note)
    db_session.commit()
    snapshot_a_hash = snapshot_a.raw_html_sha256

    deleted = bulk_delete_pages(db_session, site.id, BulkPageDelete(resource_ids=[resource.id]))
    assert deleted.changed == 1
    assert db_session.get(SitePage, page_a.id) is None
    assert db_session.get(Note, note.id) is None
    assert db_session.get(WebResource, resource.id) is not None
    assert db_session.get(ResourceSnapshot, snapshot_a.id) is not None
    assert get_snapshot_detail(db_session, snapshot_a.id) is not None

    scan_b = _scan(db_session, site.id)
    scan_b.status = "queued"
    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(_two_page_handler),
    ).run(scan_b)
    pages = list(
        db_session.scalars(
            select(SitePage).where(
                SitePage.website_property_id == site.id,
                SitePage.resource_id == resource.id,
            )
        )
    )
    assert len(pages) == 1
    page_b = pages[0]
    assert page_b.workspace_state == "active"
    assert page_b.owner_label is None
    assert page_b.workflow_status == "unreviewed"
    assert db_session.query(PageCategoryAssignment).filter_by(site_page_id=page_b.id).count() == 0
    assert db_session.query(Note).filter_by(site_page_id=page_b.id).count() == 0
    snapshots = list(
        db_session.scalars(
            select(ResourceSnapshot)
            .where(ResourceSnapshot.resource_id == resource.id)
            .order_by(ResourceSnapshot.id)
        )
    )
    assert len(snapshots) == 2
    assert snapshots[0].id == snapshot_a.id
    assert snapshots[0].raw_html_sha256 == snapshot_a_hash
    assert snapshots[1].scan_id == scan_b.id
    observations = list_page_observations(db_session, site.id, resource.id)
    assert observations is not None and observations.total == 2


@pytest.mark.asyncio
async def test_page_remove_between_real_scans_stays_suppressed_with_organization(
    db_session, tmp_path
) -> None:
    site = _site(db_session)
    scan_a = _scan(db_session, site.id)
    scan_a.status = "queued"
    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(_two_page_handler),
    ).run(scan_a)
    resource = db_session.scalar(
        select(WebResource).where(WebResource.normalized_url == "https://example.com/foo")
    )
    assert resource is not None
    page = db_session.scalar(
        select(SitePage).where(
            SitePage.website_property_id == site.id,
            SitePage.resource_id == resource.id,
        )
    )
    assert page is not None
    category = create_category(
        db_session, site.id, PageCategoryCreate(name="Remove lifecycle", color_key="teal")
    )
    assert category is not None
    update_page_metadata(
        db_session,
        page,
        PageMetadataUpdate(
            owner_label="Documentation",
            workflow_status="needs_review",
            category_ids=[category.id],
        ),
    )
    note = Note(site_page_id=page.id, body="Retained Page note", is_pinned=True)
    db_session.add(note)
    db_session.commit()
    update_page_workspace_state(
        db_session, page, PageWorkspaceStateUpdate(workspace_state="suppressed")
    )

    scan_b = _scan(db_session, site.id)
    scan_b.status = "queued"
    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(_two_page_handler),
    ).run(scan_b)
    pages = list(
        db_session.scalars(
            select(SitePage).where(
                SitePage.website_property_id == site.id,
                SitePage.resource_id == resource.id,
            )
        )
    )
    assert len(pages) == 1 and pages[0].id == page.id
    assert pages[0].workspace_state == "suppressed"
    assert (pages[0].owner_label, pages[0].workflow_status) == (
        "Documentation",
        "needs_review",
    )
    assert db_session.get(Note, note.id) is not None
    assert db_session.query(PageCategoryAssignment).filter_by(site_page_id=page.id).count() == 1
    assert (
        db_session.scalar(
            select(ResourceSnapshot).where(
                ResourceSnapshot.scan_id == scan_b.id,
                ResourceSnapshot.resource_id == resource.id,
            )
        )
        is not None
    )
    assert db_session.query(ResourceSnapshot).filter_by(resource_id=resource.id).count() == 2


def test_page_workspace_state_resolves_resource_aliases_and_deduplicates(db_session) -> None:
    site = _site(db_session)
    resource = _resource(db_session, "/canonical")
    site_page = ensure_site_page(db_session, scan=_scan(db_session, site.id), resource=resource)
    assert site_page is not None
    alias_id = 999_035
    db_session.add(
        WebResourceAlias(
            legacy_resource_id=alias_id,
            target_resource_id=resource.id,
            migration_id=999_035,
            alias_reason="synthetic-test",
        )
    )
    db_session.commit()

    detail = get_site_page(db_session, site.id, alias_id)
    assert detail is not None and detail.page.resource_id == resource.id
    result = bulk_workspace_state(
        db_session,
        site.id,
        BulkPageWorkspaceState(resource_ids=[alias_id, resource.id], workspace_state="suppressed"),
    )

    assert (result.selected, result.changed, result.unchanged) == (1, 1, 0)
    assert site_page.workspace_state == "suppressed"


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


def _two_page_handler(request: httpx.Request) -> httpx.Response:
    body = (
        b'<html><head><title>Home</title></head><body><a href="/foo">Foo</a></body></html>'
        if request.url.path == "/"
        else b"<html><head><title>Foo</title></head><body>Stable Foo</body></html>"
    )
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html; charset=utf-8"},
    )
