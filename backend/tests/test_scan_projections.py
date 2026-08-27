from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, event, func, select

from app.crawler.scope import ScopeConfig
from app.models import (
    ArtifactBlob,
    BackgroundJob,
    PageCategory,
    RenderedArtifact,
    RenderedObservation,
    RenderRunTarget,
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
from app.services.parse_artifacts import HTML_PARSER_VERSION, get_or_create_artifact
from app.services.render_runs import create_scan_render_run
from app.services.rendered_capture import create_observation
from app.services.rendered_deletion import delete_rendered_observations
from app.services.resource_queries import (
    list_scan_resources,
    list_scan_resources_dynamic,
    scan_resource_summary,
    scan_resource_summary_dynamic,
)
from app.services.scan_projections import (
    CURRENT_SCAN_PROJECTION_ALGORITHM,
    LEGACY_COMPATIBLE_SCAN_PROJECTION_ALGORITHMS,
    SCAN_PROJECTION_VERSION,
    ProjectionBuildCancelled,
    create_projection_build,
    current_projection_build,
    delete_scan_projection_data,
    execute_projection_build,
    is_compatible_projection_algorithm,
    projection_status,
)
from app.services.scan_queries import list_scan_pages_dynamic, list_scan_pages_routed
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore

LEGACY_V3_PROJECTION_ALGORITHM = (
    "scan-projection-v1:html-parser-v3-resource-references:resource-classifier-v1:link-role-v1"
)


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
    assert ready.algorithm_identity == CURRENT_SCAN_PROJECTION_ALGORITHM
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


def test_projection_algorithm_compatibility_accepts_current_v2_only() -> None:
    assert not LEGACY_COMPATIBLE_SCAN_PROJECTION_ALGORITHMS
    assert is_compatible_projection_algorithm(CURRENT_SCAN_PROJECTION_ALGORITHM)
    assert not is_compatible_projection_algorithm(LEGACY_V3_PROJECTION_ALGORITHM)
    assert not is_compatible_projection_algorithm("scan-projection-v1:unknown")


def test_legacy_v1_projection_remains_historical_but_is_not_current(db_session) -> None:
    scan = _fixture(db_session, "completed")
    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    ready = execute_projection_build(db_session, build.id)
    ready.projection_version = "scan-projection-v1"
    ready.algorithm_identity = LEGACY_V3_PROJECTION_ALGORITHM
    db_session.commit()

    assert db_session.get(ScanProjectionBuild, ready.id) is not None
    assert current_projection_build(db_session, scan.id) is None
    replacement = create_projection_build(db_session, scan.id)
    assert replacement.id != ready.id
    assert replacement.projection_version == SCAN_PROJECTION_VERSION
    assert ready.projection_version == "scan-projection-v1"
    assert _pages(db_session, scan.id).projection.projection_source == "dynamic"
    status = projection_status(db_session, scan.id)
    assert status is not None
    assert status.projection_source == "dynamic"
    assert status.can_build is False


def test_current_identity_rebuild_preserves_projection_checksum(db_session) -> None:
    scan = _fixture(db_session, "completed")
    first = create_projection_build(db_session, scan.id)
    db_session.commit()
    first_ready = execute_projection_build(db_session, first.id)
    rebuild = create_projection_build(db_session, scan.id, force=True)
    db_session.commit()
    second_ready = execute_projection_build(db_session, rebuild.id)

    assert first_ready.algorithm_identity == CURRENT_SCAN_PROJECTION_ALGORITHM
    assert second_ready.algorithm_identity == CURRENT_SCAN_PROJECTION_ALGORITHM
    assert first_ready.checksum_sha256 == second_ready.checksum_sha256


def test_render_evidence_does_not_change_scan_projection(db_session) -> None:
    scan = _fixture(db_session, "completed")
    first = create_projection_build(db_session, scan.id)
    db_session.commit()
    first_ready = execute_projection_build(db_session, first.id)
    first_rows = _page_projection_payloads(db_session, first_ready.id)

    snapshot, observation = _add_render_evidence(db_session, scan)

    rebuild = create_projection_build(db_session, scan.id, force=True)
    db_session.commit()
    second_ready = execute_projection_build(db_session, rebuild.id)

    assert second_ready.checksum_sha256 == first_ready.checksum_sha256
    assert _page_projection_payloads(db_session, second_ready.id) == first_rows
    rendered_page = next(
        item for item in _pages(db_session, scan.id).items if item.id == snapshot.id
    )
    assert rendered_page.rendered_capture_state == "completed"
    assert db_session.get(ScanProjectionBuild, second_ready.id).checksum_sha256 == (
        first_ready.checksum_sha256
    )


def test_render_deletion_does_not_change_projection_or_leave_stale_page_state(
    db_session, tmp_path
) -> None:
    scan = _fixture(db_session, "completed")
    first = create_projection_build(db_session, scan.id)
    db_session.commit()
    first_ready = execute_projection_build(db_session, first.id)
    first_rows = _page_projection_payloads(db_session, first_ready.id)
    snapshot, observation = _add_render_evidence(db_session, scan)
    rendered_page = next(
        item for item in _pages(db_session, scan.id).items if item.id == snapshot.id
    )
    assert rendered_page.rendered_capture_state == "completed"

    result = delete_rendered_observations(
        db_session,
        [observation.id],
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
    )
    assert result.observations_deleted == 1
    page_after_delete = next(
        item for item in _pages(db_session, scan.id).items if item.id == snapshot.id
    )
    assert page_after_delete.rendered_capture_state is None

    rebuild = create_projection_build(db_session, scan.id, force=True)
    db_session.commit()
    second_ready = execute_projection_build(db_session, rebuild.id)

    assert second_ready.checksum_sha256 == first_ready.checksum_sha256
    assert _page_projection_payloads(db_session, second_ready.id) == first_rows


def test_v4_derived_scan_builds_decoupled_projection(db_session, tmp_path) -> None:
    scan = _fixture(db_session, "completed")
    store = LocalContentStore(tmp_path / "html")
    content = b'<html><head><link rel="alternate canonical" href="/canonical"></head></html>'
    blob = store.put_html(db_session, content, "text/html", "utf-8")
    artifact = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/",
    ).artifact
    snapshot = db_session.scalar(
        select(ResourceSnapshot)
        .where(ResourceSnapshot.scan_id == scan.id)
        .order_by(ResourceSnapshot.id)
    )
    assert snapshot is not None
    snapshot.html_blob_id = blob.id
    snapshot.parse_artifact_id = artifact.id
    snapshot.raw_html_sha256 = blob.sha256
    snapshot.head_sha256 = artifact.head_sha256
    snapshot.canonical_url = artifact.canonical_url
    db_session.commit()

    build = create_projection_build(db_session, scan.id)
    db_session.commit()
    ready = execute_projection_build(db_session, build.id)

    assert artifact.parser_version == HTML_PARSER_VERSION == "html-parser-v4-rel-token-semantics"
    assert ready.algorithm_identity == CURRENT_SCAN_PROJECTION_ALGORITHM
    assert "html-parser" not in ready.algorithm_identity


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


def _page_projection_payloads(db_session, build_id: int) -> list[dict[str, object]]:
    rows = list(
        db_session.scalars(
            select(ScanPageProjection)
            .where(ScanPageProjection.projection_build_id == build_id)
            .order_by(ScanPageProjection.snapshot_id)
        )
    )
    excluded = {"id", "projection_build_id"}
    return [
        {
            column.name: getattr(row, column.name)
            for column in ScanPageProjection.__table__.columns
            if column.name not in excluded
        }
        for row in rows
    ]


def _add_render_evidence(db_session, scan: Scan) -> tuple[ResourceSnapshot, RenderedObservation]:
    snapshot = db_session.scalar(
        select(ResourceSnapshot)
        .where(ResourceSnapshot.scan_id == scan.id)
        .order_by(ResourceSnapshot.id)
    )
    assert snapshot is not None
    run = create_scan_render_run(db_session, scan, [snapshot])
    run.status = "completed"
    db_session.commit()
    target = db_session.scalar(
        select(RenderRunTarget).where(RenderRunTarget.render_run_id == run.id)
    )
    assert target is not None
    observation = create_observation(
        db_session,
        snapshot,
        ScopeConfig.from_dict(scan.scope_config),
        target=target,
    )
    observation.capture_state = "completed"
    observation.finished_at = datetime.now(UTC)
    observation.network_entry_count = 7
    observation.console_message_count = 2
    observation.page_error_count = 1
    blob = ArtifactBlob(
        sha256="a" * 64,
        storage_key="test/render-evidence.png",
        media_type="image/png",
        compression_type="none",
        raw_byte_size=4,
        stored_byte_size=4,
    )
    db_session.add(blob)
    db_session.flush()
    db_session.add(
        RenderedArtifact(
            rendered_observation_id=observation.id,
            artifact_blob_id=blob.id,
            artifact_type="viewport_screenshot",
            width=1280,
            height=720,
            metadata_json={},
        )
    )
    db_session.commit()
    return snapshot, observation
