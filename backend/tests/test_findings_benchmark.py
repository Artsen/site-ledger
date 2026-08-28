from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import event, insert, select

from app.models import (
    Finding,
    FindingAssessment,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.finding_evaluations import create_evaluation, execute_evaluation


def test_finding_evaluation_scales_with_operational_issues_not_page_selects(db_session) -> None:
    page_count = 3_000
    site = WebsiteProperty(
        name="Finding benchmark",
        base_url="https://scale.test/",
        normalized_base_url="https://scale.test/",
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
                "normalized_url": f"https://scale.test/{index}",
                "scheme": "https",
                "host": "scale.test",
                "path": f"/{index}",
                "query": "",
            }
            for index in range(page_count)
        ],
    )
    resource_ids = list(db_session.scalars(select(WebResource.id).order_by(WebResource.id)))
    db_session.execute(
        insert(SitePage),
        [
            {
                "website_property_id": site.id,
                "resource_id": resource_id,
                "workflow_status": "unreviewed",
                "workspace_state": "active",
            }
            for resource_id in resource_ids
        ],
    )

    first_at = datetime(2026, 8, 27, tzinfo=UTC)
    first = _scan(db_session, site.id, first_at)
    db_session.execute(
        insert(ResourceSnapshot),
        [
            _snapshot(first.id, resource_id, first_at, 404 if index < 200 else 200, "fetched")
            for index, resource_id in enumerate(resource_ids)
        ],
    )
    first_evaluation, _ = create_evaluation(db_session, site.id)
    execute_evaluation(db_session, first_evaluation.id)
    db_session.commit()

    second_at = first_at + timedelta(hours=1)
    second = _scan(db_session, site.id, second_at)
    snapshots = []
    for index, resource_id in enumerate(resource_ids):
        if 50 <= index < 150:
            snapshots.append(_snapshot(second.id, resource_id, second_at, 500, "fetched"))
        elif 150 <= index < 200:
            snapshots.append(_snapshot(second.id, resource_id, second_at, None, "failed"))
        else:
            snapshots.append(_snapshot(second.id, resource_id, second_at, 200, "fetched"))
    db_session.execute(insert(ResourceSnapshot), snapshots)
    evaluation, _ = create_evaluation(db_session, site.id)
    db_session.commit()

    statements = 0
    selects = 0
    started = perf_counter()

    def count_sql(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        nonlocal statements, selects
        statements += 1
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    event.listen(db_session.bind, "before_cursor_execute", count_sql)
    try:
        result = execute_evaluation(db_session, evaluation.id)
        db_session.commit()
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_sql)
    duration = perf_counter() - started

    assert result.assessments == 200
    assert result.resolved_findings == 50
    assert result.detected == 100
    assert result.unknown == 50
    assert db_session.query(Finding).count() == 200
    assert db_session.query(FindingAssessment).count() == 400
    assert selects <= 12
    assert statements < 1_000
    assert duration < 15
    print(
        f"finding benchmark: pages={page_count} assessments={result.assessments} "
        f"sql={statements} selects={selects} duration={duration:.3f}s"
    )


def _scan(db_session, site_id: int, moment: datetime) -> Scan:
    scan = Scan(
        website_property_id=site_id,
        starting_url="https://scale.test/",
        status="completed",
        scope_config={},
        created_at=moment,
        finished_at=moment,
    )
    db_session.add(scan)
    db_session.flush()
    return scan


def _snapshot(
    scan_id: int, resource_id: int, moment: datetime, status: int | None, state: str
) -> dict[str, object]:
    return {
        "scan_id": scan_id,
        "resource_id": resource_id,
        "requested_url": f"https://scale.test/{resource_id}",
        "http_status": status,
        "crawl_depth": 0,
        "fetched_at": moment,
        "fetch_state": state,
        "inspected_prefix_byte_count": 0,
    }
