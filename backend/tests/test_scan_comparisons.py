import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanComparisonLinkResult,
    ScanComparisonPageResult,
    ScanComparisonResourceResult,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.comparison_queries import (
    link_occurrence_diff,
    list_comparison_pages,
    page_change_history,
    page_source_diff,
)
from app.services.scan_comparisons import (
    ComparisonBuildCancelled,
    ComparisonEligibilityError,
    create_comparison,
    create_comparison_build,
    current_comparison_build,
    delete_comparison,
    execute_comparison_build,
    mark_comparison_build_terminal,
    queue_waiting_comparisons_for_scan,
)
from app.services.scan_projections import create_projection_build, execute_projection_build
from app.storage.content_store import LocalContentStore


def test_comparison_eligibility_is_same_site_terminal_and_directional(db_session) -> None:
    site, baseline, target, _ = _fixture(db_session)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)

    assert comparison.baseline_scan_id == baseline.id
    assert comparison.target_scan_id == target.id
    with pytest.raises(ComparisonEligibilityError, match="different"):
        create_comparison(db_session, site.id, baseline.id, baseline.id)

    target.status = "running"
    db_session.flush()
    with pytest.raises(ComparisonEligibilityError, match="terminal"):
        create_comparison(db_session, site.id, target.id, baseline.id)

    target.status = "completed"
    other_site = _site(db_session, "https://other.example/")
    target.website_property_id = other_site.id
    db_session.flush()
    with pytest.raises(ComparisonEligibilityError, match="this Site"):
        create_comparison(db_session, site.id, baseline.id, target.id)


def test_build_compares_pages_resources_links_and_is_deterministic(db_session) -> None:
    site, baseline, target, resources = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()

    ready = execute_comparison_build(db_session, build.id)
    first_checksum = ready.comparison_checksum_sha256
    pages = list(
        db_session.scalars(
            select(ScanComparisonPageResult)
            .where(ScanComparisonPageResult.comparison_build_id == ready.id)
            .order_by(ScanComparisonPageResult.normalized_url)
        )
    )
    by_resource = {row.resource_id: row for row in pages}

    assert ready.status == "ready"
    assert ready.comparison_version == "scan-comparison-v2"
    assert ready.algorithm_identity.endswith("scan-projection-v1")
    assert ready.baseline_projection_checksum
    assert ready.target_projection_checksum
    assert by_resource[resources[0].id].change_state == "metadata_change"
    assert by_resource[resources[0].id].content_changed is False
    assert by_resource[resources[0].id].exact_source_state == "changed"
    assert by_resource[resources[1].id].change_state == "technical_change"
    assert by_resource[resources[1].id].inbound_links_changed is True
    assert by_resource[resources[2].id].presence_state == "not_observed_in_target"
    assert by_resource[resources[2].id].target_presence_detail == "fetch_failed"
    assert by_resource[resources[3].id].presence_state == "newly_observed"
    assert not any(row.presence_state == "removed" for row in pages)
    assert db_session.scalar(
        select(func.count(ScanComparisonResourceResult.id)).where(
            ScanComparisonResourceResult.comparison_build_id == ready.id
        )
    )
    assert db_session.scalar(
        select(func.count(ScanComparisonLinkResult.id)).where(
            ScanComparisonLinkResult.comparison_build_id == ready.id
        )
    )

    rebuild = create_comparison_build(db_session, comparison.id, force=True)
    db_session.commit()
    rebuilt = execute_comparison_build(db_session, rebuild.id)
    assert rebuilt.comparison_checksum_sha256 == first_checksum
    assert current_comparison_build(db_session, comparison.id).id == rebuilt.id
    assert db_session.get(ScanComparisonBuild, ready.id).status == "superseded"


def test_build_releases_sqlite_write_lock_before_progress_callbacks(db_session) -> None:
    site, baseline, target, _ = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    phases: list[str] = []

    def update_progress(phase: str, _current: int, _total: int) -> None:
        phases.append(phase)
        with Session(db_session.get_bind()) as progress_db:
            progress_db.execute(
                update(WebsiteProperty).where(WebsiteProperty.id == site.id).values(name=site.name)
            )
            progress_db.commit()

    ready = execute_comparison_build(db_session, build.id, progress=update_progress)

    assert ready.status == "ready"
    assert "comparing_pages" in phases
    assert phases[-1] == "activating"


def test_failed_or_cancelled_rebuild_preserves_ready_build(db_session, monkeypatch) -> None:
    site, baseline, target, _ = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    first = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    ready = execute_comparison_build(db_session, first.id)

    cancelled = create_comparison_build(db_session, comparison.id, force=True)
    db_session.commit()
    with pytest.raises(ComparisonBuildCancelled):
        execute_comparison_build(db_session, cancelled.id, should_cancel=lambda: True)
    assert current_comparison_build(db_session, comparison.id).id == ready.id

    failed = create_comparison_build(db_session, comparison.id, force=True)
    db_session.commit()

    def fail_validation(*args, **kwargs):
        raise RuntimeError("forced comparison validation failure")

    monkeypatch.setattr("app.services.scan_comparisons._validate_build", fail_validation)
    with pytest.raises(RuntimeError, match="forced comparison"):
        execute_comparison_build(db_session, failed.id)
    assert current_comparison_build(db_session, comparison.id).id == ready.id
    assert db_session.get(ScanComparisonBuild, failed.id).status == "failed"


def test_missing_projection_waits_then_queues_once_both_are_ready(db_session) -> None:
    site, baseline, target, _ = _fixture(db_session)
    baseline_projection = create_projection_build(db_session, baseline.id)
    db_session.commit()
    execute_projection_build(db_session, baseline_projection.id)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)

    assert build.status == "waiting_for_projections"
    assert queue_waiting_comparisons_for_scan(db_session, baseline.id) == []

    target_projection = create_projection_build(db_session, target.id)
    db_session.commit()
    execute_projection_build(db_session, target_projection.id)
    assert queue_waiting_comparisons_for_scan(db_session, target.id) == [build.id]
    db_session.commit()
    jobs = list(
        db_session.scalars(
            select(BackgroundJob).where(BackgroundJob.scan_comparison_id == comparison.id)
        )
    )
    assert len(jobs) == 1
    assert jobs[0].job_type == "scan_comparison_build"


def test_interrupted_rebuild_preserves_previous_ready_build(db_session) -> None:
    site, baseline, target, _ = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    first = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    ready = execute_comparison_build(db_session, first.id)
    interrupted = create_comparison_build(db_session, comparison.id, force=True)

    mark_comparison_build_terminal(
        db_session,
        interrupted.id,
        "failed",
        "worker_lease_expired",
        "Worker interrupted during comparison build.",
    )

    assert current_comparison_build(db_session, comparison.id).id == ready.id
    assert db_session.get(ScanComparisonBuild, interrupted.id).status == "failed"


def test_exact_occurrence_diff_preserves_duplicate_multiplicity(db_session) -> None:
    site, baseline, target, resources = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    execute_comparison_build(db_session, build.id)

    result = link_occurrence_diff(
        db_session,
        site.id,
        comparison.id,
        resources[0].id,
        resources[1].id,
        limit=50,
        offset=0,
    )

    assert result is not None
    assert result.compared_baseline_count == 2
    assert result.compared_target_count == 3
    assert sum(item.count for item in result.items if item.state == "present_in_both") == 2
    assert sum(item.count for item in result.items if item.state == "newly_observed") == 1


def test_source_diff_is_bounded_plain_text_evidence(db_session, tmp_path) -> None:
    site, baseline, target, resources = _fixture(db_session)
    store = LocalContentStore(tmp_path / "content")
    before = db_session.scalar(
        select(ResourceSnapshot).where(
            ResourceSnapshot.scan_id == baseline.id,
            ResourceSnapshot.resource_id == resources[0].id,
        )
    )
    after = db_session.scalar(
        select(ResourceSnapshot).where(
            ResourceSnapshot.scan_id == target.id,
            ResourceSnapshot.resource_id == resources[0].id,
        )
    )
    assert before is not None and after is not None
    before.html_blob_id = store.put_html(
        db_session, b"<main>before</main>", "text/html", "utf-8"
    ).id
    after.html_blob_id = store.put_html(
        db_session,
        b"<main>after<script>window.executed=true</script></main>",
        "text/html",
        "utf-8",
    ).id
    db_session.commit()
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    execute_comparison_build(db_session, build.id)

    result = page_source_diff(db_session, store, site.id, comparison.id, resources[0].id)

    assert result is not None
    assert result.state == "available"
    assert "<script>window.executed=true</script>" in result.diff_text
    assert result.output_truncated is False


def test_source_diff_exact_retains_and_meaningful_suppresses_only_incapsula_cb(
    db_session, tmp_path
) -> None:
    site, baseline, target, resources = _fixture(db_session)
    store = LocalContentStore(tmp_path / "content")
    before = db_session.scalar(
        select(ResourceSnapshot).where(
            ResourceSnapshot.scan_id == baseline.id,
            ResourceSnapshot.resource_id == resources[0].id,
        )
    )
    after = db_session.scalar(
        select(ResourceSnapshot).where(
            ResourceSnapshot.scan_id == target.id,
            ResourceSnapshot.resource_id == resources[0].id,
        )
    )
    assert before is not None and after is not None
    baseline_html = b'<main>Same</main><script src="/_Incapsula_Resource?ns=4&cb=111"></script>'
    target_html = b'<main>Same</main><script src="/_Incapsula_Resource?ns=4&cb=222"></script>'
    before_blob = store.put_html(db_session, baseline_html, "text/html", "utf-8")
    after_blob = store.put_html(db_session, target_html, "text/html", "utf-8")
    before.html_blob_id = before_blob.id
    before.raw_html_sha256 = before_blob.sha256
    after.html_blob_id = after_blob.id
    after.raw_html_sha256 = after_blob.sha256
    after.page_title = before.page_title
    extra_target_link = db_session.scalar(
        select(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id == after.id)
    )
    assert extra_target_link is not None
    db_session.delete(extra_target_link)
    db_session.commit()
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    execute_comparison_build(db_session, build.id, store=store)

    page = list_comparison_pages(
        db_session,
        site.id,
        comparison.id,
        changed_only=False,
        limit=50,
        offset=0,
    ).items[0]
    exact = page_source_diff(
        db_session, store, site.id, comparison.id, resources[0].id, mode="exact"
    )
    meaningful = page_source_diff(
        db_session, store, site.id, comparison.id, resources[0].id, mode="meaningful"
    )

    assert page.exact_source_state == "changed"
    assert page.normalized_source_state == "same"
    assert page.document_content_state == "same"
    assert page.primary_change_class == "normalization_only"
    assert exact is not None and "cb=111" in exact.diff_text and "cb=222" in exact.diff_text
    assert meaningful is not None and meaningful.state == "identical"
    assert meaningful.diff_text == ""


def test_page_change_history_tracks_observation_gaps(db_session) -> None:
    site, baseline, target, resources = _fixture(db_session)
    gap = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed_with_errors",
        scope_config={},
    )
    db_session.add(gap)
    db_session.flush()
    baseline.created_at = baseline.created_at.replace(year=2024)
    gap.created_at = gap.created_at.replace(year=2025)
    target.created_at = target.created_at.replace(year=2026)
    db_session.add(
        SitePage(
            website_property_id=site.id,
            resource_id=resources[1].id,
            workflow_status="unreviewed",
        )
    )
    db_session.commit()

    history = page_change_history(db_session, site.id, resources[1].id, limit=50, offset=0)

    assert history is not None
    assert history.total == 2
    assert history.items[0].change_label == "First observation"
    assert history.items[1].change_label == "No tracked change"
    assert history.items[1].intervening_scan_count == 1
    assert history.items[1].intervening_unsuccessful_observation_count == 1


def test_comparison_deletion_removes_only_derived_rows(db_session) -> None:
    site, baseline, target, _ = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    execute_comparison_build(db_session, build.id)
    snapshot_count = db_session.scalar(select(func.count(ResourceSnapshot.id)))

    assert delete_comparison(db_session, comparison.id) is True
    assert db_session.get(ScanComparison, comparison.id) is None
    assert db_session.scalar(select(func.count(ResourceSnapshot.id))) == snapshot_count
    assert db_session.get(Scan, baseline.id) is not None
    assert db_session.get(Scan, target.id) is not None


def test_ready_page_list_is_materialized_and_paginated(db_session) -> None:
    site, baseline, target, _ = _fixture(db_session)
    _prepare(db_session, baseline, target)
    comparison = create_comparison(db_session, site.id, baseline.id, target.id)
    build = create_comparison_build(db_session, comparison.id)
    db_session.commit()
    execute_comparison_build(db_session, build.id)

    result = list_comparison_pages(
        db_session,
        site.id,
        comparison.id,
        changed_only=False,
        sort="changed_field_count",
        direction="desc",
        limit=2,
        offset=0,
    )

    assert result is not None
    assert result.total == 4
    assert len(result.items) == 2
    assert result.items[0].changed_field_count >= result.items[1].changed_field_count


def _fixture(db_session):
    site = _site(db_session, "https://example.com/")
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
            ("https://example.com/old", "/old"),
            ("https://example.com/new", "/new"),
            ("https://example.com/app.js", "/app.js"),
        )
    ]
    db_session.add_all(resources)
    db_session.flush()
    baseline = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={"max_pages": 100},
        stop_reason="queue_empty",
    )
    target = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={"max_pages": 100},
        stop_reason="queue_empty",
    )
    db_session.add_all([baseline, target])
    db_session.flush()
    baseline_snapshots = [
        _snapshot(baseline.id, resources[0], "home-a", "head-a", "Home"),
        _snapshot(baseline.id, resources[1], "about", "about-head", "About"),
        _snapshot(baseline.id, resources[2], "old", "old-head", "Old"),
        _resource_snapshot(baseline.id, resources[4], 200, "application/javascript", 1200),
    ]
    target_snapshots = [
        _snapshot(target.id, resources[0], "home-b", "head-b", "Home updated"),
        _snapshot(target.id, resources[1], "about", "about-head", "About"),
        _snapshot(target.id, resources[3], "new", "new-head", "New"),
        ResourceSnapshot(
            scan_id=target.id,
            resource_id=resources[2].id,
            requested_url=resources[2].normalized_url,
            final_url=None,
            http_status=None,
            content_type=None,
            crawl_depth=1,
            fetch_state="failed",
            error_type="connection_timeout",
            representation_kind="unknown",
        ),
        _resource_snapshot(target.id, resources[4], 304, "text/javascript", 1250),
    ]
    db_session.add_all([*baseline_snapshots, *target_snapshots])
    db_session.flush()
    for snapshot, count in ((baseline_snapshots[0], 2), (target_snapshots[0], 3)):
        for _ in range(count):
            db_session.add(
                ResourceOccurrence(
                    source_snapshot_id=snapshot.id,
                    relation_type="page_link",
                    raw_href="/about",
                    resolved_url=resources[1].normalized_url,
                    normalized_target_url=resources[1].normalized_url,
                    target_resource_id=resources[1].id,
                    anchor_text="About",
                    in_scope=True,
                    scope_decision="crawlable",
                    link_role="main_content",
                    link_role_rule="main_content",
                )
            )
    for snapshot in (baseline_snapshots[0], target_snapshots[0]):
        db_session.add(
            ResourceReferenceOccurrence(
                source_snapshot_id=snapshot.id,
                target_resource_id=resources[4].id,
                relation_type="script",
                element_tag="script",
                attribute_name="src",
                raw_url="/app.js",
                resolved_url=resources[4].normalized_url,
                normalized_target_url=resources[4].normalized_url,
                inferred_kind="script",
                classification_rule="element_script_src",
                in_scope=True,
                scope_decision="crawlable",
            )
        )
    db_session.commit()
    return site, baseline, target, resources


def _site(db_session, base_url: str) -> WebsiteProperty:
    site = WebsiteProperty(
        name=base_url,
        base_url=base_url,
        normalized_base_url=base_url,
        description=None,
        group_key="default",
        locale=None,
        platform_key="unknown",
        ownership_key="unknown",
        display_timezone="America/New_York",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    return site


def _snapshot(
    scan_id: int,
    resource: WebResource,
    content_hash: str,
    head_hash: str,
    title: str,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        scan_id=scan_id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=200,
        content_type="text/html",
        crawl_depth=1,
        fetch_state="fetched",
        representation_kind="html_page",
        raw_html_sha256=content_hash,
        head_sha256=head_hash,
        page_title=title,
        response_time_ms=20,
        network_bytes_transferred=100,
    )


def _resource_snapshot(
    scan_id: int,
    resource: WebResource,
    status: int,
    mime: str,
    size: int,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        scan_id=scan_id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=status,
        content_type=mime,
        normalized_mime_type=mime,
        crawl_depth=1,
        fetch_state="fetched",
        representation_kind="script",
        declared_content_length=size,
        network_bytes_transferred=size,
    )


def _prepare(db_session, *scans: Scan) -> None:
    for scan in scans:
        build = create_projection_build(db_session, scan.id)
        db_session.commit()
        execute_projection_build(db_session, build.id)
