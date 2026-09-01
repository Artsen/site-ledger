from datetime import UTC, datetime

from sqlalchemy import event, func, select

from app.accessibility.engine import (
    ACCESSIBILITY_INTEGRATION_VERSION,
    ACCESSIBILITY_NORMALIZATION_VERSION,
    AXE_BUNDLE_SHA256,
    AXE_CORE_VERSION,
    RULESET_PROFILE,
    RULESET_SHA256,
)
from app.crawler.canonical_document import (
    STRUCTURED_CONTENT_CONFIG_VERSION,
    STRUCTURED_CONTENT_EXTRACTOR_VERSION,
    STRUCTURED_MARKDOWN_RENDERER_VERSION,
)
from app.models import (
    AccessibilityObservation,
    AccessibilityRun,
    ContentBlob,
    HtmlStructuredContentArtifact,
    PerformanceObservation,
    PerformanceRun,
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanComparisonSummary,
    SiteInventorySuppression,
    SitePage,
    UrlSource,
    UrlSourceEntry,
    WebResource,
    WebsiteProperty,
)
from app.services.rendered_deletion import delete_rendered_observations
from app.services.scan_comparisons import SCAN_COMPARISON_ALGORITHM, SCAN_COMPARISON_VERSION
from app.services.site_intelligence import get_site_intelligence
from app.services.source_queries import list_inventory
from app.storage.artifact_store import LocalArtifactStore


def test_independent_clocks_and_active_page_universe_exclude_suppressed_history(
    db_session,
) -> None:
    site = WebsiteProperty(
        name="Intelligence fixture",
        base_url="https://example.test/",
        normalized_base_url="https://example.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    resources = []
    for position in range(7):
        resource = WebResource(
            resource_type="page",
            normalized_url=f"https://example.test/{position}",
            scheme="https",
            host="example.test",
            path=f"/{position}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add(
            SitePage(
                website_property_id=site.id,
                resource_id=resource.id,
                workspace_state="active" if position < 5 else "suppressed",
            )
        )
        resources.append(resource)

    monday = datetime(2026, 8, 24, 1, tzinfo=UTC)
    tuesday = datetime(2026, 8, 25, 2, tzinfo=UTC)
    wednesday = datetime(2026, 8, 26, 3, tzinfo=UTC)
    thursday = datetime(2026, 8, 27, 4, tzinfo=UTC)
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=monday,
        finished_at=monday,
        discovered_count=7,
        fetched_count=7,
    )
    render_run = RenderRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=7,
        created_at=tuesday,
        finished_at=tuesday,
    )
    performance_run = PerformanceRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=7,
        request_count=7,
        finished_at=wednesday,
    )
    accessibility_run = AccessibilityRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=7,
        observation_count=7,
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=1,
        ruleset_sha256=RULESET_SHA256,
        finished_at=thursday,
    )
    db_session.add_all([scan, render_run, performance_run, accessibility_run])
    db_session.flush()

    for position, resource in enumerate(resources):
        db_session.add(
            ResourceSnapshot(
                scan_id=scan.id,
                resource_id=resource.id,
                requested_url=resource.normalized_url,
                http_status=200,
                crawl_depth=0,
                fetched_at=monday,
                fetch_state="fetched",
            )
        )
        db_session.add(
            RenderedObservation(
                render_run_id=render_run.id,
                web_resource_id=resource.id,
                capture_state="completed",
                finished_at=tuesday,
                requested_url=resource.normalized_url,
                navigation_http_status=200,
                browser_engine="chromium",
                renderer_version="2",
                browser_policy_version="2",
                capture_schema_version="2",
                viewport_width=1440,
                viewport_height=900,
                device_scale_factor=1,
                locale="en-US",
                timezone_id="UTC",
                color_scheme="light",
                reduced_motion="reduce",
                configuration_fingerprint="c" * 64,
            )
        )
        db_session.add(
            PerformanceObservation(
                performance_run_id=performance_run.id,
                website_property_id=site.id,
                web_resource_id=resource.id,
                provider="pagespeed",
                provider_adapter_version="pagespeed-provider-v1",
                normalization_version="performance-normalization-v1",
                target_kind="url",
                target_key=str(position).zfill(64),
                requested_target=resource.normalized_url,
                dimension="mobile",
                outcome="ready",
                request_descriptor_json={"strategy": "mobile"},
                metrics_json={},
                observed_at=wednesday,
            )
        )
        db_session.add(
            PerformanceObservation(
                performance_run_id=performance_run.id,
                website_property_id=site.id,
                web_resource_id=resource.id,
                provider="crux",
                provider_adapter_version="crux-provider-v1",
                normalization_version="performance-normalization-v1",
                target_kind="url",
                target_key=str(position).zfill(64),
                requested_target=resource.normalized_url,
                dimension="PHONE",
                outcome="unavailable",
                request_descriptor_json={"form_factor": "PHONE"},
                metrics_json={},
                observed_at=wednesday,
            )
        )
        db_session.add(
            AccessibilityObservation(
                accessibility_run_id=accessibility_run.id,
                website_property_id=site.id,
                web_resource_id=resource.id,
                requested_url=resource.normalized_url,
                profile="desktop",
                outcome="ready",
                observed_at=thursday,
                axe_core_version=AXE_CORE_VERSION,
                detector_bundle_sha256=AXE_BUNDLE_SHA256,
                integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
                normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
                ruleset_profile=RULESET_PROFILE,
                ruleset_sha256=RULESET_SHA256,
                profile_json={},
            )
        )
    incompatible_run = AccessibilityRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=1,
        observation_count=1,
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256="f" * 64,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=1,
        ruleset_sha256=RULESET_SHA256,
        finished_at=datetime(2026, 8, 28, 5, tzinfo=UTC),
    )
    db_session.add(incompatible_run)
    db_session.flush()
    db_session.add(
        AccessibilityObservation(
            accessibility_run_id=incompatible_run.id,
            website_property_id=site.id,
            web_resource_id=resources[0].id,
            requested_url=resources[0].normalized_url,
            profile="desktop",
            outcome="ready",
            observed_at=datetime(2026, 8, 28, 5, tzinfo=UTC),
            axe_core_version=AXE_CORE_VERSION,
            detector_bundle_sha256="f" * 64,
            integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
            normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
            ruleset_profile=RULESET_PROFILE,
            ruleset_sha256=RULESET_SHA256,
            violation_rule_count=99,
            violation_node_count=99,
            profile_json={},
        )
    )
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)

    assert result is not None
    assert result.page_population.active_page_total == 5
    assert result.page_population.suppressed_page_total == 2
    assert result.scan.active_page_observed.model_dump() == {
        "observed": 5,
        "eligible": 5,
        "ratio": 1.0,
    }
    assert result.render.retained_coverage.model_dump() == {
        "observed": 5,
        "eligible": 5,
        "ratio": 1.0,
    }
    assert len(result.performance.contexts) == 2
    assert {(item.provider, item.dimension) for item in result.performance.contexts} == {
        ("crux", "PHONE"),
        ("pagespeed", "mobile"),
    }
    assert all(item.coverage.eligible == 5 for item in result.performance.contexts)
    assert all(item.coverage.observed == 5 for item in result.performance.contexts)
    assert result.accessibility.coverage.model_dump() == {
        "observed": 5,
        "eligible": 5,
        "ratio": 1.0,
    }
    assert result.scan.clock.latest_observed_at == monday
    assert result.render.clock.latest_observed_at == tuesday
    assert result.performance.clock.latest_observed_at == wednesday
    assert result.accessibility.clock.latest_observed_at == thursday
    assert result.accessibility.violation_rules == 0
    accessibility_coverage = {
        item.context["profile"]: item
        for item in result.collection_coverage
        if item.evidence_domain == "accessibility"
    }
    assert accessibility_coverage["desktop"].covered == 5
    assert accessibility_coverage["desktop"].missing == 0
    assert accessibility_coverage["mobile"].covered == 0
    assert accessibility_coverage["mobile"].missing == 5
    assert db_session.scalar(select(func.count()).select_from(AccessibilityObservation)) == 8
    assert not hasattr(result, "site_as_of")


def test_site_intelligence_query_count_is_bounded_for_empty_site(db_session) -> None:
    site = WebsiteProperty(
        name="Empty",
        base_url="https://empty.test/",
        normalized_base_url="https://empty.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.commit()
    statements = 0

    def count_statements(*_args: object) -> None:
        nonlocal statements
        statements += 1

    event.listen(db_session.bind, "before_cursor_execute", count_statements)
    try:
        result = get_site_intelligence(db_session, site.id)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_statements)
    assert result is not None
    assert statements <= 20
    assert result.activity.active_job_count == 0
    assert db_session.scalar(select(func.count()).select_from(HtmlStructuredContentArtifact)) == 0
    assert db_session.scalar(select(func.count()).select_from(ScanComparisonBuild)) == 0


def test_structured_content_coverage_follows_latest_eligible_blob(db_session) -> None:
    site = WebsiteProperty(
        name="Structured",
        base_url="https://structured.test/",
        normalized_base_url="https://structured.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://structured.test/page",
        scheme="https",
        host="structured.test",
        path="/page",
        query="",
    )
    blob_a = ContentBlob(
        sha256="1" * 64,
        storage_key="11/old.html.gz",
        content_type="text/html",
        encoding="utf-8",
        raw_byte_size=10,
        stored_byte_size=10,
    )
    blob_b = ContentBlob(
        sha256="2" * 64,
        storage_key="22/new.html.gz",
        content_type="text/html",
        encoding="utf-8",
        raw_byte_size=10,
        stored_byte_size=10,
    )
    db_session.add_all([site, resource, blob_a, blob_b])
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    old_scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    new_scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    db_session.add_all([old_scan, new_scan])
    db_session.flush()
    db_session.add_all(
        [
            ResourceSnapshot(
                scan_id=old_scan.id,
                resource_id=resource.id,
                requested_url=resource.normalized_url,
                crawl_depth=0,
                fetched_at=datetime(2026, 8, 24, tzinfo=UTC),
                fetch_state="fetched",
                html_blob_id=blob_a.id,
            ),
            ResourceSnapshot(
                scan_id=new_scan.id,
                resource_id=resource.id,
                requested_url=resource.normalized_url,
                crawl_depth=0,
                fetched_at=datetime(2026, 8, 25, tzinfo=UTC),
                fetch_state="fetched",
                html_blob_id=blob_b.id,
            ),
            _structured_artifact(blob_a.id),
        ]
    )
    db_session.commit()

    before = get_site_intelligence(db_session, site.id)
    assert before is not None
    assert before.structured_content.eligible_retained_html == 1
    assert before.structured_content.ready == 0
    assert before.structured_content.not_prepared == 1

    db_session.add(_structured_artifact(blob_b.id))
    db_session.commit()
    after = get_site_intelligence(db_session, site.id)
    assert after is not None
    assert after.structured_content.ready == 1
    assert after.structured_content.not_prepared == 0


def test_structured_content_clock_uses_snapshot_observation_not_preparation(db_session) -> None:
    observed_monday = datetime(2026, 8, 24, 9, tzinfo=UTC)
    prepared_friday = datetime(2026, 8, 28, 17, tzinfo=UTC)
    site = WebsiteProperty(
        name="Structured clock",
        base_url="https://structured-clock.test/",
        normalized_base_url="https://structured-clock.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://structured-clock.test/page",
        scheme="https",
        host="structured-clock.test",
        path="/page",
        query="",
    )
    blob = ContentBlob(
        sha256="7" * 64,
        storage_key="77/page.html.gz",
        content_type="text/html",
        encoding="utf-8",
        raw_byte_size=10,
        stored_byte_size=10,
    )
    db_session.add_all([site, resource, blob])
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=observed_monday,
    )
    db_session.add(scan)
    db_session.flush()
    db_session.add_all(
        [
            ResourceSnapshot(
                scan_id=scan.id,
                resource_id=resource.id,
                requested_url=resource.normalized_url,
                crawl_depth=0,
                fetched_at=observed_monday,
                fetch_state="fetched",
                html_blob_id=blob.id,
            ),
            _structured_artifact(blob.id, created_at=prepared_friday),
        ]
    )
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)

    assert result is not None
    assert result.structured_content.clock.oldest_current_observation_at == observed_monday
    assert result.structured_content.clock.newest_current_observation_at == observed_monday
    assert result.structured_content.clock.latest_observed_at == observed_monday
    assert prepared_friday not in result.structured_content.clock.model_dump().values()


def _structured_artifact(
    blob_id: int, *, created_at: datetime | None = None
) -> HtmlStructuredContentArtifact:
    return HtmlStructuredContentArtifact(
        content_blob_id=blob_id,
        extractor_version=STRUCTURED_CONTENT_EXTRACTOR_VERSION,
        extractor_config_version=STRUCTURED_CONTENT_CONFIG_VERSION,
        extraction_state="ready",
        document_profile="headed",
        document_text_sha256="3" * 64,
        outline_sha256="4" * 64,
        canonical_document_sha256="5" * 64,
        markdown_renderer_version=STRUCTURED_MARKDOWN_RENDERER_VERSION,
        markdown_sha256="6" * 64,
        markdown_character_count=10,
        created_at=created_at,
    )


def test_inventory_totals_match_workspace_identity_and_suppression_semantics(db_session) -> None:
    site = WebsiteProperty(
        name="Inventory parity",
        base_url="https://inventory.test/",
        normalized_base_url="https://inventory.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    sources = [
        UrlSource(
            website_property_id=site.id,
            source_type="manual",
            name=name,
            discovery_mode="manual",
            settings_json={},
        )
        for name in ("Primary", "Duplicate")
    ]
    db_session.add_all(sources)
    db_session.flush()

    def entry(source: UrlSource, raw: str, normalized: str | None) -> UrlSourceEntry:
        return UrlSourceEntry(
            url_source_id=source.id,
            raw_url=raw,
            normalized_url=normalized,
            is_current=True,
            validation_state="valid" if normalized else "invalid",
            scope_decision="included" if normalized else "invalid_url",
            source_metadata_json={},
        )

    db_session.add_all(
        [
            entry(
                sources[0], "https://inventory.test/duplicate", "https://inventory.test/duplicate"
            ),
            entry(
                sources[1], "https://inventory.test/duplicate", "https://inventory.test/duplicate"
            ),
            entry(sources[0], "https://inventory.test/current", "https://inventory.test/current"),
            entry(sources[0], "javascript:alert(1)", None),
            entry(sources[1], "javascript:alert(1)", None),
            entry(sources[0], "https://inventory.test/a%2Fb", "https://inventory.test/a/b"),
        ]
    )
    db_session.add_all(
        [
            SiteInventorySuppression(
                website_property_id=site.id,
                target_kind="normalized_url",
                target_value="https://inventory.test/current",
                normalization_version="url-normalization-v2",
            ),
            SiteInventorySuppression(
                website_property_id=site.id,
                target_kind="normalized_url",
                target_value="https://inventory.test/a/b",
                normalization_version="url-normalization-v1",
            ),
        ]
    )
    db_session.commit()

    overview = get_site_intelligence(db_session, site.id)
    active = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        visibility="active",
        limit=100,
        offset=0,
    )
    suppressed = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        visibility="suppressed",
        limit=100,
        offset=0,
    )

    assert overview is not None and active is not None and suppressed is not None
    assert overview.sources.current_inventory_count == active.total
    assert overview.sources.suppressed_inventory_count == suppressed.total
    assert (active.total, suppressed.total) == (2, 2)


def test_only_current_compatible_comparison_is_presented(db_session) -> None:
    site = WebsiteProperty(
        name="Comparison",
        base_url="https://comparison.test/",
        normalized_base_url="https://comparison.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    baseline = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
    )
    target = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
    )
    db_session.add_all([baseline, target])
    db_session.flush()
    comparison = ScanComparison(
        website_property_id=site.id,
        baseline_scan_id=baseline.id,
        target_scan_id=target.id,
    )
    db_session.add(comparison)
    db_session.flush()
    legacy = ScanComparisonBuild(
        scan_comparison_id=comparison.id,
        comparison_version="scan-comparison-v2",
        algorithm_identity="legacy",
        status="ready",
    )
    db_session.add(legacy)
    db_session.flush()
    comparison.current_build_id = legacy.id
    db_session.commit()

    absent = get_site_intelligence(db_session, site.id)
    assert absent is not None
    assert absent.comparison.present is False

    current = ScanComparisonBuild(
        scan_comparison_id=comparison.id,
        comparison_version=SCAN_COMPARISON_VERSION,
        algorithm_identity=SCAN_COMPARISON_ALGORITHM,
        status="ready",
        finished_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    db_session.add(current)
    db_session.flush()
    db_session.add(
        ScanComparisonSummary(
            comparison_build_id=current.id,
            page_counts_json={"substantive_change": 2},
        )
    )
    comparison.current_build_id = current.id
    db_session.commit()

    present = get_site_intelligence(db_session, site.id)
    assert present is not None
    assert present.comparison.present is True
    assert present.comparison.build_id == current.id
    assert present.comparison.page_counts == {"substantive_change": 2}


def test_latest_comparison_follows_target_scan_not_later_rebuild(db_session) -> None:
    site = _comparison_site(db_session, "Comparison chronology")
    scans = [
        Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config={},
            created_at=datetime(2026, 8, day, tzinfo=UTC),
        )
        for day in (20, 21, 24, 25)
    ]
    db_session.add_all(scans)
    db_session.flush()
    older = ScanComparison(
        website_property_id=site.id,
        baseline_scan_id=scans[0].id,
        target_scan_id=scans[1].id,
    )
    newer = ScanComparison(
        website_property_id=site.id,
        baseline_scan_id=scans[2].id,
        target_scan_id=scans[3].id,
    )
    db_session.add_all([older, newer])
    db_session.flush()
    older_rebuilt_later = _current_comparison_build(
        older.id, finished_at=datetime(2026, 8, 28, tzinfo=UTC)
    )
    newer_built_earlier = _current_comparison_build(
        newer.id, finished_at=datetime(2026, 8, 27, tzinfo=UTC)
    )
    db_session.add_all([older_rebuilt_later, newer_built_earlier])
    db_session.flush()
    older.current_build_id = older_rebuilt_later.id
    newer.current_build_id = newer_built_earlier.id
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)

    assert result is not None
    assert result.comparison.comparison_id == newer.id
    assert result.comparison.build_id == newer_built_earlier.id
    assert result.comparison.target_scan_id == scans[3].id


def test_comparison_clock_separates_target_evidence_from_build_completion(db_session) -> None:
    monday = datetime(2026, 8, 24, 9, tzinfo=UTC)
    friday = datetime(2026, 8, 28, 17, tzinfo=UTC)
    site = _comparison_site(db_session, "Comparison clock")
    baseline = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
    )
    target = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=monday,
        finished_at=monday,
    )
    db_session.add_all([baseline, target])
    db_session.flush()
    comparison = ScanComparison(
        website_property_id=site.id,
        baseline_scan_id=baseline.id,
        target_scan_id=target.id,
    )
    db_session.add(comparison)
    db_session.flush()
    build = _current_comparison_build(comparison.id, finished_at=friday)
    db_session.add(build)
    db_session.flush()
    comparison.current_build_id = build.id
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)

    assert result is not None
    assert result.comparison.clock.latest_observed_at == monday
    assert result.comparison.clock.latest_completed_at == friday
    assert result.comparison.clock.source_comparison_id == comparison.id
    assert friday != result.comparison.clock.latest_observed_at


def test_newest_compatible_current_comparison_build_wins_over_newer_legacy(db_session) -> None:
    site = _comparison_site(db_session, "Comparison compatibility")
    scans = [
        Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config={},
            created_at=datetime(2026, 8, day, tzinfo=UTC),
        )
        for day in (20, 21, 24, 25)
    ]
    db_session.add_all(scans)
    db_session.flush()
    compatible = ScanComparison(
        website_property_id=site.id,
        baseline_scan_id=scans[0].id,
        target_scan_id=scans[1].id,
    )
    incompatible = ScanComparison(
        website_property_id=site.id,
        baseline_scan_id=scans[2].id,
        target_scan_id=scans[3].id,
    )
    db_session.add_all([compatible, incompatible])
    db_session.flush()
    current = _current_comparison_build(
        compatible.id, finished_at=datetime(2026, 8, 26, tzinfo=UTC)
    )
    legacy = ScanComparisonBuild(
        scan_comparison_id=incompatible.id,
        comparison_version="scan-comparison-v2",
        algorithm_identity="legacy",
        status="ready",
        finished_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    db_session.add_all([current, legacy])
    db_session.flush()
    compatible.current_build_id = current.id
    incompatible.current_build_id = legacy.id
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)

    assert result is not None
    assert result.comparison.present is True
    assert result.comparison.comparison_id == compatible.id
    assert result.comparison.build_id == current.id


def _comparison_site(db_session, name: str) -> WebsiteProperty:
    site = WebsiteProperty(
        name=name,
        base_url="https://comparison-chronology.test/",
        normalized_base_url="https://comparison-chronology.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    return site


def _current_comparison_build(comparison_id: int, *, finished_at: datetime) -> ScanComparisonBuild:
    return ScanComparisonBuild(
        scan_comparison_id=comparison_id,
        comparison_version=SCAN_COMPARISON_VERSION,
        algorithm_identity=SCAN_COMPARISON_ALGORITHM,
        status="ready",
        finished_at=finished_at,
    )


def test_latest_render_run_targets_are_distinct_from_retained_site_coverage(db_session) -> None:
    site = WebsiteProperty(
        name="Render coverage",
        base_url="https://render-coverage.test/",
        normalized_base_url="https://render-coverage.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    resources: list[WebResource] = []
    for position in range(10):
        resource = WebResource(
            resource_type="page",
            normalized_url=f"https://render-coverage.test/{position}",
            scheme="https",
            host="render-coverage.test",
            path=f"/{position}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
        resources.append(resource)
    old_run = RenderRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=8,
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    latest_run = RenderRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=2,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    db_session.add_all([old_run, latest_run])
    db_session.flush()
    for position, resource in enumerate(resources):
        run = old_run if position < 8 else latest_run
        db_session.add(
            RenderedObservation(
                render_run_id=run.id,
                web_resource_id=resource.id,
                capture_state="completed",
                requested_url=resource.normalized_url,
                navigation_http_status=200,
                finished_at=run.created_at,
                browser_engine="chromium",
                renderer_version="2",
                browser_policy_version="2",
                capture_schema_version="2",
                viewport_width=1440,
                viewport_height=900,
                device_scale_factor=1,
                locale="en-US",
                timezone_id="UTC",
                color_scheme="light",
                reduced_motion="reduce",
                configuration_fingerprint="f" * 64,
            )
        )
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)
    assert result is not None
    assert result.render.latest_run.id == latest_run.id
    assert result.render.latest_run.target_count == 2
    assert result.render.retained_coverage.observed == 10
    assert result.render.retained_coverage.eligible == 10


def test_render_outcomes_partition_current_retained_coverage(db_session) -> None:
    site = WebsiteProperty(
        name="Render outcomes",
        base_url="https://render-outcomes.test/",
        normalized_base_url="https://render-outcomes.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    run = RenderRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=1,
    )
    db_session.add(run)
    db_session.flush()
    outcomes = [
        ("completed", 200, None),
        ("failed", 204, "navigation_http_no_content"),
        ("failed", 205, "navigation_http_no_content"),
        ("failed", 302, "navigation_http_redirect"),
        ("failed", 500, "navigation_http_error"),
        ("failed", 429, "navigation_rate_limited"),
        ("failed", None, "host_rate_limit_circuit_open"),
        ("failed", None, "navigation_failed"),
    ]
    for position, (state, status, error_type) in enumerate(outcomes):
        resource = WebResource(
            resource_type="page",
            normalized_url=f"https://render-outcomes.test/{position}",
            scheme="https",
            host="render-outcomes.test",
            path=f"/{position}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add_all(
            [
                SitePage(website_property_id=site.id, resource_id=resource.id),
                RenderedObservation(
                    render_run_id=run.id,
                    web_resource_id=resource.id,
                    capture_state=state,
                    requested_url=resource.normalized_url,
                    navigation_http_status=status,
                    error_type=error_type,
                    browser_engine="chromium",
                    renderer_version="2",
                    browser_policy_version="2",
                    capture_schema_version="2",
                    viewport_width=1440,
                    viewport_height=900,
                    device_scale_factor=1,
                    locale="en-US",
                    timezone_id="UTC",
                    color_scheme="light",
                    reduced_motion="reduce",
                    configuration_fingerprint=str(position) * 64,
                ),
            ]
        )
    db_session.commit()

    result = get_site_intelligence(db_session, site.id)

    assert result is not None
    assert result.render.retained_coverage.observed == len(outcomes)
    counts = (
        result.render.successful,
        result.render.no_content,
        result.render.redirect,
        result.render.http_error,
        result.render.rate_limited,
        result.render.not_attempted_host_throttled,
        result.render.technical_failure,
    )
    assert counts == (1, 2, 1, 1, 1, 1, 1)
    assert sum(counts) == result.render.retained_coverage.observed
    assert result.render.latest_run.target_count == 1


def test_deleted_newer_render_evidence_is_not_counted_as_retained(db_session, tmp_path) -> None:
    site = WebsiteProperty(
        name="Render deletion",
        base_url="https://render-deletion.test/",
        normalized_base_url="https://render-deletion.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://render-deletion.test/page",
        scheme="https",
        host="render-deletion.test",
        path="/page",
        query="",
    )
    db_session.add_all([site, resource])
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    runs = [
        RenderRun(
            website_property_id=site.id,
            status="completed",
            trigger="site_workspace",
            configuration_json={},
            target_count=1,
            created_at=datetime(2026, 8, day, tzinfo=UTC),
        )
        for day in (24, 25)
    ]
    db_session.add_all(runs)
    db_session.flush()
    targets = [
        RenderRunTarget(
            render_run_id=run.id,
            web_resource_id=resource.id,
            requested_url=resource.normalized_url,
            position=1,
        )
        for run in runs
    ]
    db_session.add_all(targets)
    db_session.flush()
    observations = [
        RenderedObservation(
            render_run_id=run.id,
            render_run_target_id=target.id,
            web_resource_id=resource.id,
            capture_state="completed" if status == 200 else "failed",
            requested_url=resource.normalized_url,
            navigation_http_status=status,
            error_type=None if status == 200 else "navigation_http_error",
            finished_at=run.created_at,
            browser_engine="chromium",
            renderer_version="2",
            browser_policy_version="2",
            capture_schema_version="2",
            viewport_width=1440,
            viewport_height=900,
            device_scale_factor=1,
            locale="en-US",
            timezone_id="UTC",
            color_scheme="light",
            reduced_motion="reduce",
            configuration_fingerprint=str(status) * 32,
        )
        for run, target, status in zip(runs, targets, (200, 500), strict=True)
    ]
    db_session.add_all(observations)
    db_session.commit()

    before = get_site_intelligence(db_session, site.id)
    assert before is not None and before.render.http_error == 1

    delete_rendered_observations(
        db_session,
        [observations[1].id],
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
    )
    after = get_site_intelligence(db_session, site.id)

    assert after is not None
    assert after.render.retained_coverage.observed == 1
    assert after.render.successful == 1
    assert after.render.http_error == 0
