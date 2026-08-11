import pytest
from sqlalchemy import delete, event, func, select

from app.models import (
    BackgroundJob,
    PageCategory,
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    ScanLinkProjection,
    ScanPageProjection,
    ScanProjectionBuild,
    ScanProjectionState,
    ScanResourceProjection,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.graph_filters import GraphFilters
from app.services.graph_queries import get_scan_graph, get_scan_graph_dynamic
from app.services.job_handlers import _enqueue_projection_for_terminal_scan
from app.services.job_types import JOB_TYPE_SCAN_PROJECTION_BUILD
from app.services.resource_queries import (
    list_scan_resources,
    list_scan_resources_dynamic,
    scan_resource_summary,
    scan_resource_summary_dynamic,
)
from app.services.scan_projections import (
    SCAN_PROJECTION_VERSION,
    ProjectionBuildCancelled,
    create_projection_build,
    current_projection_build,
    delete_scan_projection_data,
    execute_projection_build,
    projection_status,
)
from app.services.scan_queries import list_scan_pages_dynamic, list_scan_pages_routed


def test_projection_build_activates_equivalent_page_resource_and_graph_reads(db_session) -> None:
    scan = _fixture(db_session, "completed")
    dynamic_pages = _pages_dynamic(db_session, scan.id)
    dynamic_resources = list_scan_resources_dynamic(db_session, scan.id)
    dynamic_summary = scan_resource_summary_dynamic(db_session, scan.id)
    dynamic_graph = get_scan_graph_dynamic(db_session, scan.id, GraphFilters())
    raw_counts = _raw_counts(db_session)

    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    ready = execute_projection_build(db_session, build.id)

    assert ready.status == "ready"
    assert ready.projection_version == SCAN_PROJECTION_VERSION
    assert current_projection_build(db_session, scan.id) is not None
    assert _raw_counts(db_session) == raw_counts
    projected_pages = _pages(db_session, scan.id)
    projected_resources = list_scan_resources(db_session, scan.id)
    projected_summary = scan_resource_summary(db_session, scan.id)
    projected_graph = get_scan_graph(db_session, scan.id, GraphFilters())
    assert dynamic_resources is not None and projected_resources is not None
    assert dynamic_summary is not None and projected_summary is not None
    assert dynamic_graph is not None and projected_graph is not None
    assert projected_pages.projection is not None
    assert projected_pages.projection.projection_source == "materialized"
    assert [item.model_dump() for item in projected_pages.items] == [
        item.model_dump() for item in dynamic_pages.items
    ]
    assert [item.model_dump() for item in projected_resources.items] == [
        item.model_dump() for item in dynamic_resources.items
    ]
    assert projected_summary.model_dump(exclude={"projection"}) == dynamic_summary.model_dump(
        exclude={"projection"}
    )
    assert [item.model_dump() for item in projected_graph.nodes] == [
        item.model_dump() for item in dynamic_graph.nodes
    ]
    assert [item.model_dump() for item in projected_graph.edges] == [
        item.model_dump() for item in dynamic_graph.edges
    ]


def test_mutable_site_metadata_does_not_change_scan_projection(db_session) -> None:
    scan = _fixture(db_session, "completed")
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        description=None,
        group_key="default",
        locale=None,
        platform_key="unknown",
        ownership_key="unknown",
        display_timezone=None,
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    scan.website_property_id = site.id
    db_session.commit()

    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    ready = execute_projection_build(db_session, build.id)
    immutable_state = (
        ready.id,
        ready.projection_version,
        ready.checksum_sha256,
        ready.created_at,
        ready.started_at,
        ready.finished_at,
    )

    resource = db_session.scalar(select(WebResource).where(WebResource.path == "/"))
    assert resource is not None
    db_session.add(
        SitePage(website_property_id=site.id, resource_id=resource.id, workflow_status="unreviewed")
    )
    db_session.add(
        PageCategory(
            website_property_id=site.id,
            name="Marketing",
            normalized_name="marketing",
            description=None,
            color_key="teal",
            sort_order=0,
            is_active=True,
        )
    )
    site.display_timezone = "America/New_York"
    db_session.commit()
    db_session.refresh(ready)

    assert (
        ready.id,
        ready.projection_version,
        ready.checksum_sha256,
        ready.created_at,
        ready.started_at,
        ready.finished_at,
    ) == immutable_state
    assert current_projection_build(db_session, scan.id).id == ready.id


def test_terminal_scan_queues_projection_job_but_active_scan_does_not(db_session) -> None:
    terminal = _fixture(db_session, "completed")
    active = Scan(starting_url="https://active.example/", status="running", scope_config={})
    db_session.add(active)
    db_session.commit()

    _enqueue_projection_for_terminal_scan(db_session, terminal)
    _enqueue_projection_for_terminal_scan(db_session, active)

    jobs = list(
        db_session.scalars(
            select(BackgroundJob).where(BackgroundJob.job_type == JOB_TYPE_SCAN_PROJECTION_BUILD)
        )
    )
    assert len(jobs) == 1
    assert jobs[0].scan_id == terminal.id


def test_projection_resource_query_count_is_bounded(db_session) -> None:
    scan = _fixture(db_session, "completed")
    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    execute_projection_build(db_session, build.id)
    statements: list[str] = []

    def count_statement(*args) -> None:
        statements.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", count_statement)
    try:
        result = list_scan_resources(db_session, scan.id, limit=1)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_statement)

    assert result is not None and result.total == 1
    assert len(statements) <= 4
    assert not any("resource_reference_occurrences" in item for item in statements)
    assert not any("resource_occurrences" in item for item in statements)


def test_active_scan_cannot_build_and_uses_dynamic_reads(db_session) -> None:
    scan = _fixture(db_session, "running")

    result = _pages(db_session, scan.id)

    assert result.projection is not None
    assert result.projection.projection_source == "dynamic"
    assert result.projection.projection_status == "not_terminal"
    try:
        create_projection_build(db_session, scan.id)
    except ValueError as exc:
        assert "terminal" in str(exc)
    else:
        raise AssertionError("Active Scan unexpectedly accepted a projection build")


def test_scan_cascade_removes_all_projection_rows(db_session) -> None:
    scan = _fixture(db_session, "completed")
    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    execute_projection_build(db_session, build.id)

    delete_scan_projection_data(db_session, scan.id)
    db_session.execute(delete(Scan).where(Scan.id == scan.id))
    db_session.commit()

    assert db_session.scalar(select(func.count(ScanProjectionBuild.id))) == 0
    assert db_session.scalar(select(func.count(ScanPageProjection.id))) == 0
    assert db_session.scalar(select(func.count(ScanResourceProjection.id))) == 0
    assert db_session.scalar(select(func.count(ScanLinkProjection.id))) == 0


def test_duplicate_build_request_returns_the_active_build(db_session) -> None:
    scan = _fixture(db_session, "completed")

    first = create_projection_build(db_session, scan.id)
    second = create_projection_build(db_session, scan.id)

    assert second.id == first.id
    assert (
        db_session.scalar(
            select(func.count(ScanProjectionBuild.id)).where(
                ScanProjectionBuild.scan_id == scan.id,
                ScanProjectionBuild.active_key.is_not(None),
            )
        )
        == 1
    )


def test_failed_rebuild_preserves_current_ready_build(db_session, monkeypatch) -> None:
    scan = _fixture(db_session, "completed")
    first = create_projection_build(db_session, scan.id)
    db_session.commit()
    ready = execute_projection_build(db_session, first.id)
    raw_counts = _raw_counts(db_session)
    rebuild = create_projection_build(db_session, scan.id, force=True)
    db_session.commit()
    rebuilding_status = projection_status(db_session, scan.id)
    assert rebuilding_status is not None
    assert rebuilding_status.projection_source == "materialized"
    assert rebuilding_status.projection_status == "queued"
    assert rebuilding_status.current_build.id == ready.id

    def fail_validation(*args, **kwargs):
        raise RuntimeError("forced validation failure")

    monkeypatch.setattr("app.services.scan_projections._validate_build", fail_validation)
    with pytest.raises(RuntimeError, match="forced validation failure"):
        execute_projection_build(db_session, rebuild.id)

    state = db_session.get(ScanProjectionState, scan.id)
    assert state is not None and state.current_build_id == ready.id
    assert current_projection_build(db_session, scan.id).id == ready.id
    assert db_session.get(ScanProjectionBuild, rebuild.id).status == "failed"
    failed_status = projection_status(db_session, scan.id)
    assert failed_status is not None
    assert failed_status.projection_source == "materialized"
    assert failed_status.projection_status == "failed"
    assert failed_status.current_build.id == ready.id
    assert _raw_counts(db_session) == raw_counts


def test_cancelled_first_build_cleans_staging_and_uses_dynamic_fallback(db_session) -> None:
    scan = _fixture(db_session, "completed")
    build = create_projection_build(db_session, scan.id)
    db_session.commit()

    with pytest.raises(ProjectionBuildCancelled):
        execute_projection_build(db_session, build.id, should_cancel=lambda: True)

    assert current_projection_build(db_session, scan.id) is None
    assert db_session.get(ScanProjectionBuild, build.id).status == "cancelled"
    assert (
        db_session.scalar(
            select(func.count(ScanPageProjection.id)).where(
                ScanPageProjection.projection_build_id == build.id
            )
        )
        == 0
    )
    assert _pages(db_session, scan.id).projection.projection_source == "dynamic"


def test_version_mismatch_preserves_rows_but_routes_to_dynamic(db_session) -> None:
    scan = _fixture(db_session, "completed")
    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    ready = execute_projection_build(db_session, build.id)
    ready.projection_version = "scan-projection-v0"
    db_session.commit()

    assert current_projection_build(db_session, scan.id) is None
    result = _pages(db_session, scan.id)
    assert result.projection.projection_source == "dynamic"
    assert (
        db_session.scalar(
            select(func.count(ScanPageProjection.id)).where(
                ScanPageProjection.projection_build_id == ready.id
            )
        )
        == 2
    )


def test_projection_graph_query_count_is_bounded(db_session) -> None:
    scan = _fixture(db_session, "completed")
    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    execute_projection_build(db_session, build.id)
    statements: list[str] = []

    def count_statement(*args) -> None:
        statements.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", count_statement)
    try:
        result = get_scan_graph(db_session, scan.id, GraphFilters(include_unfetched=True))
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_statement)

    assert result is not None
    assert len(statements) <= 8
    assert not any("resource_occurrences" in statement for statement in statements)


def _fixture(db_session, status: str) -> Scan:
    scan = Scan(starting_url="https://example.com/", status=status, scope_config={})
    db_session.add(scan)
    db_session.flush()
    resources = [
        WebResource(
            resource_type="page",
            normalized_url=url,
            scheme="https",
            host="example.com",
            port=None,
            path=path,
            query="",
        )
        for url, path in (
            ("https://example.com/", "/"),
            ("https://example.com/about", "/about"),
            ("https://example.com/app.js", "/app.js"),
        )
    ]
    db_session.add_all(resources)
    db_session.flush()
    snapshots = [
        ResourceSnapshot(
            scan_id=scan.id,
            resource_id=resource.id,
            requested_url=resource.normalized_url,
            final_url=resource.normalized_url,
            http_status=200,
            content_type="text/html",
            crawl_depth=index,
            fetch_state="fetched",
            representation_kind="html_page",
            page_title="Home" if index == 0 else "About",
            response_time_ms=10 + index,
        )
        for index, resource in enumerate(resources[:2])
    ]
    db_session.add_all(snapshots)
    db_session.flush()
    db_session.add_all(
        [
            ResourceOccurrence(
                source_snapshot_id=snapshots[0].id,
                relation_type="page_link",
                raw_href="/about",
                resolved_url=resources[1].normalized_url,
                normalized_target_url=resources[1].normalized_url,
                target_resource_id=resources[1].id,
                anchor_text="About",
                in_scope=True,
                scope_decision="crawlable",
                link_role="content",
                link_role_rule="main_content",
            ),
            ResourceOccurrence(
                source_snapshot_id=snapshots[0].id,
                relation_type="page_link",
                raw_href="/about",
                resolved_url=resources[1].normalized_url,
                normalized_target_url=resources[1].normalized_url,
                target_resource_id=resources[1].id,
                anchor_text="About again",
                rel="nofollow",
                in_scope=True,
                scope_decision="crawlable",
                link_role="content",
                link_role_rule="main_content",
            ),
        ]
    )
    db_session.add(
        ResourceReferenceOccurrence(
            source_snapshot_id=snapshots[0].id,
            target_resource_id=resources[2].id,
            relation_type="script",
            element_tag="script",
            attribute_name="src",
            raw_url="/app.js",
            resolved_url=resources[2].normalized_url,
            normalized_target_url=resources[2].normalized_url,
            inferred_kind="script",
            classification_rule="element_script_src",
            in_scope=True,
            scope_decision="crawlable",
        )
    )
    db_session.commit()
    return scan


def _pages(db_session, scan_id: int):
    return list_scan_pages_routed(
        db_session,
        scan_id,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "any",
        "requested_url",
        "asc",
        50,
        0,
    )


def _pages_dynamic(db_session, scan_id: int):
    return list_scan_pages_dynamic(
        db_session,
        scan_id,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "any",
        "requested_url",
        "asc",
        50,
        0,
    )


def _raw_counts(db_session) -> tuple[int, int, int]:
    return (
        db_session.scalar(select(func.count(ResourceSnapshot.id))) or 0,
        db_session.scalar(select(func.count(ResourceOccurrence.id))) or 0,
        db_session.scalar(select(func.count(ResourceReferenceOccurrence.id))) or 0,
    )
