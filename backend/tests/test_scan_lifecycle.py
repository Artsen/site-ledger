from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import ContentBlob, ResourceOccurrence, ResourceSnapshot, Scan, WebResource
from app.services.scan_deletion import delete_scan, preview_scan_deletion
from app.services.scan_queries import list_scan_pages, list_snapshot_inbound_links
from app.storage.content_store import LocalContentStore


def test_scan_specific_inbound_counts_and_query_count(db_session: Session) -> None:
    scan_a, scan_b, target_resource = _two_scan_graph(db_session)
    queries: list[str] = []

    def before_cursor_execute(*args) -> None:
        queries.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        result = list_scan_pages(
            db_session,
            scan_a.id,
            search=None,
            status=None,
            host=None,
            path_prefix=None,
            depth=None,
            min_depth=None,
            max_depth=None,
            error_state="any",
            sort="requested_url",
            direction="asc",
            limit=50,
            offset=0,
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_cursor_execute)

    target = next(page for page in result.items if page.resource_id == target_resource.id)
    assert target.inbound_occurrence_count == 4
    assert target.inbound_source_page_count == 3
    assert "scan-b-source" not in (target.discovery_source or "")
    assert len(queries) <= 2

    scan_b_result = list_scan_pages(
        db_session,
        scan_b.id,
        search=None,
        status=None,
        host=None,
        path_prefix=None,
        depth=None,
        min_depth=None,
        max_depth=None,
        error_state="any",
        sort="requested_url",
        direction="asc",
        limit=50,
        offset=0,
    )
    scan_b_target = next(
        page for page in scan_b_result.items if page.resource_id == target_resource.id
    )
    assert scan_b_target.inbound_occurrence_count == 1
    assert scan_b_target.inbound_source_page_count == 1


def test_inbound_links_are_scan_specific_paginated_and_summarized(db_session: Session) -> None:
    scan_a, _, target_resource = _two_scan_graph(db_session)
    target = (
        db_session.query(ResourceSnapshot)
        .filter_by(scan_id=scan_a.id, resource_id=target_resource.id)
        .one()
    )

    result = list_snapshot_inbound_links(
        db_session,
        snapshot_id=target.id,
        search="Alpha",
        scope_decision=None,
        source_status=None,
        rel=None,
        limit=10,
        offset=0,
    )

    assert result is not None
    assert result.total == 2
    assert result.summary.total_occurrences == 2
    assert result.summary.unique_source_pages == 1
    assert result.summary.unique_anchor_texts == 2
    assert result.summary.nofollow_occurrences == 1
    assert result.summary.self_link_occurrences == 0
    assert all(item.source_page_title == "Alpha source" for item in result.items)

    self_result = list_snapshot_inbound_links(
        db_session,
        snapshot_id=target.id,
        search="Self",
        scope_decision=None,
        source_status=None,
        rel=None,
        limit=10,
        offset=0,
    )
    assert self_result is not None
    assert self_result.summary.self_link_occurrences == 1
    assert self_result.items[0].is_self_link is True


def test_deleting_scan_preserves_other_scan_counts_and_shared_blobs(
    db_session: Session, tmp_path: Path
) -> None:
    scan_a, scan_b, target_resource = _two_scan_graph(db_session)
    store = LocalContentStore(tmp_path)
    shared_blob = store.put_html(db_session, b"<html>shared</html>", "text/html", "utf-8")
    unique_blob = store.put_html(db_session, b"<html>unique</html>", "text/html", "utf-8")
    scan_a_snapshot = (
        db_session.query(ResourceSnapshot)
        .filter(
            ResourceSnapshot.scan_id == scan_a.id,
            ResourceSnapshot.resource_id != target_resource.id,
        )
        .first()
    )
    scan_b_snapshot = db_session.query(ResourceSnapshot).filter_by(scan_id=scan_b.id).first()
    assert scan_a_snapshot is not None
    assert scan_b_snapshot is not None
    scan_a_snapshot.html_blob_id = shared_blob.id
    scan_b_snapshot.html_blob_id = shared_blob.id
    target_snapshot = (
        db_session.query(ResourceSnapshot)
        .filter_by(scan_id=scan_a.id, resource_id=target_resource.id)
        .one()
    )
    target_snapshot.html_blob_id = unique_blob.id
    db_session.commit()

    preview = preview_scan_deletion(db_session, scan_a.id)
    assert preview is not None
    assert preview.can_delete is True
    assert preview.html_blobs_referenced == 2
    assert preview.html_blobs_deleted == 1

    result = delete_scan(db_session, scan_a.id, store)
    assert result is not None
    assert result.html_blobs_deleted == 1
    assert db_session.get(ContentBlob, shared_blob.id) is not None
    assert db_session.get(ContentBlob, unique_blob.id) is None
    assert (tmp_path / shared_blob.storage_key).exists()
    assert not (tmp_path / unique_blob.storage_key).exists()

    scan_b_result = list_scan_pages(
        db_session,
        scan_b.id,
        search=None,
        status=None,
        host=None,
        path_prefix=None,
        depth=None,
        min_depth=None,
        max_depth=None,
        error_state="any",
        sort="requested_url",
        direction="asc",
        limit=50,
        offset=0,
    )
    scan_b_target = next(
        page for page in scan_b_result.items if page.resource_id == target_resource.id
    )
    assert scan_b_target.inbound_occurrence_count == 1
    assert scan_b_target.inbound_source_page_count == 1


def test_running_scan_cannot_be_deleted(db_session: Session, tmp_path: Path) -> None:
    scan = Scan(starting_url="https://example.com/", status="running", scope_config={})
    db_session.add(scan)
    db_session.commit()

    preview = preview_scan_deletion(db_session, scan.id)
    assert preview is not None
    assert preview.can_delete is False

    try:
        delete_scan(db_session, scan.id, LocalContentStore(tmp_path))
    except ValueError as exc:
        assert "terminal scans" in str(exc)
    else:
        raise AssertionError("running scan delete should fail")


def _two_scan_graph(db_session: Session) -> tuple[Scan, Scan, WebResource]:
    target = _resource(db_session, "https://example.com/target", "/target")
    source_a = _resource(db_session, "https://example.com/scan-a-source", "/scan-a-source")
    source_b = _resource(db_session, "https://example.com/scan-b-source", "/scan-b-source")
    scan_a = _scan(db_session, "https://example.com/")
    scan_b = _scan(db_session, "https://example.com/")
    target_a = _snapshot(db_session, scan_a, target, "https://example.com/target", "Target A")
    source_a_snapshot = _snapshot(
        db_session, scan_a, source_a, "https://example.com/scan-a-source", "Alpha source"
    )
    source_b_snapshot = _snapshot(
        db_session, scan_a, source_b, "https://example.com/scan-a-source-2", "Beta source"
    )
    _snapshot(db_session, scan_b, target, "https://example.com/target", "Target B")
    scan_b_source = _snapshot(
        db_session, scan_b, source_b, "https://example.com/scan-b-source", "Scan B source"
    )
    _occurrence(db_session, source_a_snapshot, target, "Alpha primary", rel="nofollow")
    _occurrence(db_session, source_a_snapshot, target, "Alpha duplicate")
    _occurrence(db_session, source_b_snapshot, target, "Beta")
    _occurrence(db_session, target_a, target, "Self")
    _occurrence(db_session, scan_b_source, target, "Other scan")
    db_session.commit()
    return scan_a, scan_b, target


def _scan(db_session: Session, starting_url: str) -> Scan:
    scan = Scan(
        starting_url=starting_url,
        status="completed",
        scope_config={},
        discovered_count=1,
        fetched_count=1,
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
) -> ResourceSnapshot:
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=requested_url,
        final_url=requested_url,
        http_status=200,
        content_type="text/html",
        encoding="utf-8",
        crawl_depth=1,
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
            raw_href="/target",
            resolved_url="https://example.com/target",
            normalized_target_url=target.normalized_url,
            target_resource_id=target.id,
            anchor_text=anchor,
            rel=rel,
            dom_path="html > body > a",
            in_scope=True,
            scope_decision="crawlable",
        )
    )
