import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import ResourceOccurrence, ResourceSnapshot, Scan, ScanSeed, WebResource
from app.services.graph_filters import GraphFilters
from app.services.graph_queries import (
    get_graph_capabilities,
    get_scan_graph,
    list_graph_edge_occurrences,
)


def test_graph_nodes_and_edges_are_scan_specific_and_aggregated(db_session: Session) -> None:
    scan_a, scan_b, target, source = _graph_fixture(db_session)

    graph = get_scan_graph(db_session, scan_a.id, GraphFilters())

    assert graph is not None
    assert graph.scan.id == scan_a.id
    assert {node.snapshot_id for node in graph.nodes if node.kind == "page"} == {
        snapshot.id for snapshot in scan_a.snapshots
    }
    assert all("scan-b" not in (node.page_title or "") for node in graph.nodes)
    edge = next(edge for edge in graph.edges if edge.target_resource_id == target.id)
    assert edge.source_snapshot_id == source.id
    assert edge.occurrence_count == 3
    assert edge.unique_anchor_text_count == 1
    assert edge.nofollow_occurrence_count == 1
    assert edge.empty_anchor_occurrence_count == 1

    scan_b_graph = get_scan_graph(db_session, scan_b.id, GraphFilters())
    assert scan_b_graph is not None
    assert scan_b_graph.summary.total_occurrences == 1


def test_graph_capabilities_are_backend_owned() -> None:
    capabilities = get_graph_capabilities()

    assert capabilities.default_node_limit == 100
    assert capabilities.maximum_node_limit == 3000
    assert capabilities.default_edge_limit == 250
    assert capabilities.maximum_edge_limit == 10000
    assert capabilities.default_focus_hops == 1
    assert capabilities.maximum_focus_hops == 3
    assert capabilities.occurrence_page_default == 50
    assert capabilities.occurrence_page_maximum == 200
    assert "2xx" in capabilities.supported_status_filters
    assert "inbound_occurrences" in capabilities.supported_node_size_modes


def test_graph_filters_self_links_unfetched_and_connectivity(db_session: Session) -> None:
    scan, _, target, source = _graph_fixture(db_session)

    without_self = get_scan_graph(db_session, scan.id, GraphFilters(include_self_links=False))
    assert without_self is not None
    assert all(not edge.is_self_link for edge in without_self.edges)

    host_filtered = get_scan_graph(db_session, scan.id, GraphFilters(host="example.com"))
    assert host_filtered is not None
    assert host_filtered.summary.returned_nodes == 3

    path_filtered = get_scan_graph(db_session, scan.id, GraphFilters(path_prefix="/target"))
    assert path_filtered is not None
    assert [node.resource_id for node in path_filtered.nodes] == [target.id]

    connected = get_scan_graph(db_session, scan.id, GraphFilters(min_inbound=1))
    assert connected is not None
    assert {node.resource_id for node in connected.nodes} == {target.id}

    unfetched_target = _resource(db_session, "https://example.com/unfetched", "/unfetched")
    db_session.add(
        ResourceOccurrence(
            source_snapshot_id=source.id,
            raw_href="/unfetched",
            resolved_url=unfetched_target.normalized_url,
            normalized_target_url=unfetched_target.normalized_url,
            target_resource_id=unfetched_target.id,
            anchor_text="Unfetched",
            in_scope=True,
            scope_decision="crawlable",
        )
    )
    db_session.commit()

    hidden = get_scan_graph(db_session, scan.id, GraphFilters(include_unfetched=False))
    shown = get_scan_graph(db_session, scan.id, GraphFilters(include_unfetched=True))
    assert hidden is not None and shown is not None
    assert all(node.kind == "page" for node in hidden.nodes)
    assert any(node.id == f"resource:{unfetched_target.id}" for node in shown.nodes)


def test_graph_limiting_focus_and_edge_occurrences(db_session: Session) -> None:
    scan, _, target, source = _graph_fixture(db_session)

    limited = get_scan_graph(db_session, scan.id, GraphFilters(max_nodes=1, max_edges=1))
    assert limited is not None
    assert limited.summary.truncated is True
    assert limited.nodes[0].is_starting_url is True

    focused = get_scan_graph(
        db_session,
        scan.id,
        GraphFilters(focus_snapshot_id=source.id, focus_hops=1, include_self_links=False),
    )
    assert focused is not None
    assert focused.summary.focused is True
    assert {node.snapshot_id for node in focused.nodes} == {source.id, target.id}

    occurrences = list_graph_edge_occurrences(
        db_session,
        scan.id,
        f"{source.id}-{target.id}",
        search="Alpha",
        limit=1,
        offset=0,
    )
    assert occurrences is not None
    assert occurrences.total == 2
    assert len(occurrences.items) == 1
    assert occurrences.edge is not None
    assert occurrences.edge.occurrence_count == 3

    assert (
        list_graph_edge_occurrences(
            db_session, scan.id + 1, f"{source.id}-{target.id}", None, 10, 0
        )
        is None
    )
    assert (
        list_graph_edge_occurrences(db_session, scan.id, f"{source.id}-999999", None, 10, 0) is None
    )
    with pytest.raises(ValueError):
        get_scan_graph(db_session, scan.id, GraphFilters(focus_snapshot_id=999999))


def test_graph_query_count_is_bounded(db_session: Session) -> None:
    scan, _, _, _ = _graph_fixture(db_session)
    queries: list[str] = []

    def before_cursor_execute(*args) -> None:
        queries.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        graph = get_scan_graph(db_session, scan.id, GraphFilters(include_unfetched=True))
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_cursor_execute)

    assert graph is not None
    assert len(queries) <= 13


def test_duplicate_heavy_edge_occurrence_page_stays_bounded(db_session: Session) -> None:
    scan = _scan(db_session, "https://example.com/")
    source_resource = _resource(db_session, "https://example.com/", "/")
    target_resource = _resource(db_session, "https://example.com/target", "/target")
    source = _snapshot(db_session, scan, source_resource, source_resource.normalized_url, "Home", 0)
    _snapshot(db_session, scan, target_resource, target_resource.normalized_url, "Target", 1)
    db_session.bulk_insert_mappings(
        ResourceOccurrence,
        [
            {
                "source_snapshot_id": source.id,
                "relation_type": "page_link",
                "raw_href": "/target",
                "resolved_url": target_resource.normalized_url,
                "normalized_target_url": target_resource.normalized_url,
                "target_resource_id": target_resource.id,
                "anchor_text": "" if index % 20 == 0 else f"Anchor {index % 11:02d}",
                "rel": "nofollow" if index % 10 == 0 else None,
                "dom_path": "html > body > nav > a" if index % 3 == 0 else "html > body > main > a",
                "in_scope": True,
                "scope_decision": "crawlable",
            }
            for index in range(10_000)
        ],
    )
    db_session.commit()
    queries: list[str] = []

    def before_cursor_execute(*args) -> None:
        queries.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        occurrences = list_graph_edge_occurrences(
            db_session,
            scan.id,
            f"{source.id}-{target_resource.id}",
            search=None,
            limit=50,
            offset=0,
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_cursor_execute)

    assert occurrences is not None
    assert occurrences.total == 10_000
    assert len(occurrences.items) == 50
    assert occurrences.edge is not None
    assert occurrences.edge.occurrence_count == 10_000
    assert occurrences.edge.nofollow_occurrence_count == 1_000
    assert occurrences.edge.empty_anchor_occurrence_count == 500
    assert len(occurrences.edge.sample_anchor_texts) <= 5
    assert occurrences.edge.scope_decisions == {"crawlable": 10_000}
    assert len(queries) <= 6


def _graph_fixture(
    db_session: Session,
) -> tuple[Scan, Scan, WebResource, ResourceSnapshot]:
    scan_a = _scan(db_session, "https://example.com/")
    scan_b = _scan(db_session, "https://example.com/")
    root = _resource(db_session, "https://example.com/", "/")
    target = _resource(db_session, "https://example.com/target", "/target")
    other = _resource(db_session, "https://example.com/other", "/other")
    source_snapshot = _snapshot(db_session, scan_a, root, "https://example.com/", "Home", 0)
    target_snapshot = _snapshot(db_session, scan_a, target, target.normalized_url, "Target", 1)
    _snapshot(db_session, scan_a, other, other.normalized_url, "Other", 2)
    scan_b_source = _snapshot(db_session, scan_b, other, other.normalized_url, "scan-b source", 0)
    _snapshot(db_session, scan_b, target, target.normalized_url, "scan-b target", 1)
    db_session.add(
        ScanSeed(
            scan_id=scan_a.id,
            resource_id=root.id,
            normalized_url=root.normalized_url,
            requested_url=root.normalized_url,
            queue_state="fetched",
            scope_decision="crawlable",
        )
    )
    _occurrence(db_session, source_snapshot, target, "Alpha", rel="nofollow")
    _occurrence(db_session, source_snapshot, target, "Alpha")
    _occurrence(db_session, source_snapshot, target, "")
    _occurrence(db_session, target_snapshot, target, "Self")
    _occurrence(db_session, scan_b_source, target, "Other scan")
    db_session.commit()
    return scan_a, scan_b, target, source_snapshot


def _scan(db_session: Session, starting_url: str) -> Scan:
    scan = Scan(
        starting_url=starting_url,
        status="completed",
        scope_config={},
        discovered_count=3,
        fetched_count=3,
        failed_count=0,
        skipped_count=0,
        queued_count=0,
    )
    db_session.add(scan)
    db_session.flush()
    return scan


def _resource(db_session: Session, normalized_url: str, path: str) -> WebResource:
    resource = WebResource(
        resource_type="page",
        normalized_url=normalized_url,
        scheme="https",
        host="example.com",
        port=None,
        path=path,
        query="",
    )
    db_session.add(resource)
    db_session.flush()
    return resource


def _snapshot(
    db_session: Session,
    scan: Scan,
    resource: WebResource,
    requested_url: str,
    title: str,
    depth: int,
) -> ResourceSnapshot:
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=requested_url,
        final_url=requested_url,
        http_status=200,
        content_type="text/html",
        encoding="utf-8",
        crawl_depth=depth,
        response_time_ms=100 + depth,
        response_headers={},
        redirect_chain=[],
        page_title=title,
        parsed_head_json={},
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


def _occurrence(
    db_session: Session,
    source: ResourceSnapshot,
    target: WebResource,
    anchor: str,
    rel: str | None = None,
) -> None:
    db_session.add(
        ResourceOccurrence(
            source_snapshot_id=source.id,
            raw_href=target.path,
            resolved_url=target.normalized_url,
            normalized_target_url=target.normalized_url,
            target_resource_id=target.id,
            anchor_text=anchor,
            rel=rel,
            dom_path="html > body > a",
            in_scope=True,
            scope_decision="crawlable",
        )
    )
