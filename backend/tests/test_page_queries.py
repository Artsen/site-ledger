from datetime import UTC, datetime, timedelta

from app.models import ResourceSnapshot, Scan, WebResource, WebsiteProperty
from app.services.page_queries import list_page_observations, list_site_pages


def test_site_pages_collapses_observations_by_resource(db_session) -> None:
    site = _site(db_session)
    resource = _resource(db_session)
    first_scan = _scan(db_session, site.id, datetime(2026, 8, 1, tzinfo=UTC))
    second_scan = _scan(db_session, site.id, datetime(2026, 8, 2, tzinfo=UTC))
    _snapshot(db_session, first_scan.id, resource.id, datetime(2026, 8, 1, 1, tzinfo=UTC), "First")
    latest = _snapshot(
        db_session, second_scan.id, resource.id, datetime(2026, 8, 2, 1, tzinfo=UTC), "Latest"
    )
    db_session.commit()

    pages = list_site_pages(db_session, site.id)

    assert pages is not None
    assert pages.total == 1
    assert pages.items[0].resource_id == resource.id
    assert pages.items[0].observation_count == 2
    assert pages.items[0].latest_snapshot_id == latest.id
    assert pages.items[0].latest_title == "Latest"


def test_page_observation_history_is_paginated_newest_first(db_session) -> None:
    site = _site(db_session)
    resource = _resource(db_session)
    base = datetime(2026, 8, 1, tzinfo=UTC)
    scans = [_scan(db_session, site.id, base + timedelta(days=index)) for index in range(3)]
    for index, scan in enumerate(scans):
        _snapshot(db_session, scan.id, resource.id, base + timedelta(days=index), f"Page {index}")
    db_session.commit()

    history = list_page_observations(db_session, site.id, resource.id, limit=2, offset=0)

    assert history is not None
    assert history.total == 3
    assert [item.page_title for item in history.items] == ["Page 2", "Page 1"]


def _site(db_session) -> WebsiteProperty:
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        description=None,
        group_key="marketing",
        locale=None,
        platform_key="custom",
        ownership_key="owned",
        scope_config={},
        is_active=True,
    )
    db_session.add(site)
    db_session.flush()
    return site


def _resource(db_session) -> WebResource:
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/page",
        scheme="https",
        host="example.com",
        port=None,
        path="/page",
        query="",
    )
    db_session.add(resource)
    db_session.flush()
    return resource


def _scan(db_session, site_id: int, created_at: datetime) -> Scan:
    scan = Scan(
        website_property_id=site_id,
        starting_url="https://example.com/",
        status="completed",
        scope_config={},
        created_at=created_at,
    )
    db_session.add(scan)
    db_session.flush()
    return scan


def _snapshot(
    db_session,
    scan_id: int,
    resource_id: int,
    fetched_at: datetime,
    title: str,
) -> ResourceSnapshot:
    snapshot = ResourceSnapshot(
        scan_id=scan_id,
        resource_id=resource_id,
        requested_url="https://example.com/page",
        final_url="https://example.com/page",
        http_status=200,
        content_type="text/html",
        encoding="utf-8",
        crawl_depth=0,
        fetched_at=fetched_at,
        response_time_ms=10,
        response_headers={},
        redirect_chain=[],
        html_blob_id=None,
        raw_html_sha256=None,
        head_sha256=None,
        page_title=title,
        html_language="en",
        meta_description=None,
        meta_robots=None,
        canonical_url=None,
        parsed_head_json={},
        fetch_state="fetched",
        error_type=None,
        error_message=None,
        retrieval_method="full_fetch",
        parse_method="parsed",
        retrieval_http_status=200,
        network_bytes_transferred=100,
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot
