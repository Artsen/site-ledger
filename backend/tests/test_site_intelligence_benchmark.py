from time import perf_counter

from sqlalchemy import event, insert, select

from app.models import (
    ResourceSnapshot,
    Scan,
    SitePage,
    UrlSource,
    UrlSourceEntry,
    WebResource,
    WebsiteProperty,
)
from app.services.inventory_lifecycle import summarize_current_inventory
from app.services.site_intelligence import get_site_intelligence


def test_site_intelligence_scale_fixture_keeps_query_count_bounded(db_session) -> None:
    active_total = 3000
    historical_total = 200
    site = WebsiteProperty(
        name="Intelligence benchmark",
        base_url="https://benchmark.test/",
        normalized_base_url="https://benchmark.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    db_session.execute(
        insert(WebResource),
        [
            {
                "resource_type": "page",
                "normalized_url": f"https://benchmark.test/{position}",
                "scheme": "https",
                "host": "benchmark.test",
                "path": f"/{position}",
                "query": "",
            }
            for position in range(active_total + historical_total)
        ],
    )
    resource_ids = list(
        db_session.scalars(
            select(WebResource.id)
            .where(WebResource.host == "benchmark.test")
            .order_by(WebResource.id)
        )
    )
    db_session.execute(
        insert(SitePage),
        [
            {
                "website_property_id": site.id,
                "resource_id": resource_id,
                "workspace_state": "active" if position < active_total else "suppressed",
            }
            for position, resource_id in enumerate(resource_ids)
        ],
    )
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        discovered_count=len(resource_ids),
        fetched_count=len(resource_ids),
    )
    db_session.add(scan)
    db_session.flush()
    db_session.execute(
        insert(ResourceSnapshot),
        [
            {
                "scan_id": scan.id,
                "resource_id": resource_id,
                "requested_url": f"https://benchmark.test/{position}",
                "http_status": 200,
                "crawl_depth": 1,
                "fetch_state": "fetched",
            }
            for position, resource_id in enumerate(resource_ids)
        ],
    )
    source = UrlSource(
        website_property_id=site.id,
        source_type="manual",
        name="Scale Inventory",
        discovery_mode="manual",
        settings_json={},
    )
    db_session.add(source)
    db_session.flush()
    db_session.execute(
        insert(UrlSourceEntry),
        [
            {
                "url_source_id": source.id,
                "normalized_url": f"https://benchmark.test/{position}",
                "raw_url": f"https://benchmark.test/{position}",
                "is_current": True,
                "source_metadata_json": {},
                "validation_state": "valid",
                "scope_decision": "included",
            }
            for position in range(active_total + historical_total)
        ],
    )
    db_session.commit()
    inventory_statement_count = 0

    def count_inventory_statements(*_args: object) -> None:
        nonlocal inventory_statement_count
        inventory_statement_count += 1

    event.listen(db_session.bind, "before_cursor_execute", count_inventory_statements)
    try:
        inventory = summarize_current_inventory(db_session, site)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_inventory_statements)
    assert inventory.active_count == active_total + historical_total
    assert inventory.suppressed_count == 0
    assert inventory_statement_count <= 8
    db_session.expire_all()
    statement_count = 0

    def count_statements(*_args: object) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(db_session.bind, "before_cursor_execute", count_statements)
    started = perf_counter()
    try:
        result = get_site_intelligence(db_session, site.id)
    finally:
        elapsed = perf_counter() - started
        event.remove(db_session.bind, "before_cursor_execute", count_statements)

    assert result is not None
    assert result.page_population.active_page_total == active_total
    assert result.page_population.suppressed_page_total == historical_total
    assert result.scan.active_page_observed.observed == active_total
    assert result.sources.current_inventory_count == active_total + historical_total
    assert statement_count <= 22
    assert elapsed < 10
