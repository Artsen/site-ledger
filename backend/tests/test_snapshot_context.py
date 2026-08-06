from sqlalchemy import func, select

from app.models import ResourceSnapshot, Scan, SitePage, WebResource, WebsiteProperty
from app.services.scan_queries import get_snapshot_detail


def test_snapshot_context_uses_the_scan_site_when_resources_overlap(db_session) -> None:
    first_site = _site(db_session, "First", "https://first.example/")
    second_site = _site(db_session, "Second", "https://second.example/")
    resource = _resource(db_session)
    scan = _scan(db_session, first_site.id)
    snapshot = _snapshot(db_session, scan.id, resource.id, "text/html", "html_page")
    first_page = SitePage(website_property_id=first_site.id, resource_id=resource.id)
    db_session.add_all(
        [first_page, SitePage(website_property_id=second_site.id, resource_id=resource.id)]
    )
    db_session.commit()

    result = get_snapshot_detail(db_session, snapshot.id)

    assert result is not None
    assert result.website_property_id == first_site.id
    assert result.website_property_name == "First"
    assert result.site_page_id == first_page.id
    assert result.has_persistent_page is True
    assert result.is_html_page is True


def test_snapshot_context_does_not_create_a_missing_legacy_site_page(db_session) -> None:
    site = _site(db_session, "Legacy", "https://legacy.example/")
    resource = _resource(db_session)
    scan = _scan(db_session, site.id)
    snapshot = _snapshot(db_session, scan.id, resource.id, "text/html", None)
    db_session.commit()

    result = get_snapshot_detail(db_session, snapshot.id)

    assert result is not None
    assert result.website_property_id == site.id
    assert result.site_page_id is None
    assert result.has_persistent_page is False
    assert db_session.scalar(select(func.count()).select_from(SitePage)) == 0


def test_snapshot_context_excludes_ad_hoc_and_non_html_observations(db_session) -> None:
    site = _site(db_session, "Resources", "https://resources.example/")
    resource = _resource(db_session)
    ad_hoc_scan = _scan(db_session, None)
    ad_hoc = _snapshot(db_session, ad_hoc_scan.id, resource.id, "text/html", "html_page")
    resource_scan = _scan(db_session, site.id)
    document = _snapshot(
        db_session, resource_scan.id, resource.id, "application/pdf", "document"
    )
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    db_session.commit()

    ad_hoc_result = get_snapshot_detail(db_session, ad_hoc.id)
    document_result = get_snapshot_detail(db_session, document.id)

    assert ad_hoc_result is not None and ad_hoc_result.website_property_id is None
    assert ad_hoc_result.has_persistent_page is False
    assert document_result is not None and document_result.site_page_id is not None
    assert document_result.is_html_page is False
    assert document_result.has_persistent_page is False


def _site(db_session, name: str, base_url: str) -> WebsiteProperty:
    site = WebsiteProperty(
        name=name,
        base_url=base_url,
        normalized_base_url=base_url,
        description=None,
        group_key="group",
        locale=None,
        platform_key="platform",
        ownership_key="owner",
        scope_config={},
        is_active=True,
    )
    db_session.add(site)
    db_session.flush()
    return site


def _resource(db_session) -> WebResource:
    resource = WebResource(
        resource_type="page",
        normalized_url="https://shared.example/page",
        scheme="https",
        host="shared.example",
        port=None,
        path="/page",
        query="",
    )
    db_session.add(resource)
    db_session.flush()
    return resource


def _scan(db_session, site_id: int | None) -> Scan:
    scan = Scan(
        website_property_id=site_id,
        starting_url="https://shared.example/",
        status="completed",
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    return scan


def _snapshot(
    db_session,
    scan_id: int,
    resource_id: int,
    content_type: str,
    representation_kind: str | None,
) -> ResourceSnapshot:
    snapshot = ResourceSnapshot(
        scan_id=scan_id,
        resource_id=resource_id,
        requested_url="https://shared.example/page",
        final_url="https://shared.example/page",
        http_status=200,
        content_type=content_type,
        encoding="utf-8",
        crawl_depth=0,
        response_time_ms=10,
        response_headers={},
        redirect_chain=[],
        raw_html_sha256=None,
        head_sha256=None,
        page_title="Shared Page",
        html_language="en",
        meta_description=None,
        meta_robots=None,
        canonical_url=None,
        parsed_head_json={},
        fetch_state="fetched",
        error_type=None,
        error_message=None,
        representation_kind=representation_kind,
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot
