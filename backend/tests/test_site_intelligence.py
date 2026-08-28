from datetime import UTC, datetime

from sqlalchemy import event, func, select

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
    ResourceSnapshot,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanComparisonSummary,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.scan_comparisons import SCAN_COMPARISON_ALGORITHM, SCAN_COMPARISON_VERSION
from app.services.site_intelligence import get_site_intelligence


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
        axe_core_version="4.12.1",
        detector_bundle_sha256="a" * 64,
        integration_version="accessibility-engine-v1",
        normalization_version="accessibility-normalization-v1",
        ruleset_profile="wcag22-aa-v1",
        ruleset_rule_count=1,
        ruleset_sha256="b" * 64,
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
                axe_core_version="4.12.1",
                detector_bundle_sha256="a" * 64,
                integration_version="accessibility-engine-v1",
                normalization_version="accessibility-normalization-v1",
                ruleset_profile="wcag22-aa-v1",
                ruleset_sha256="b" * 64,
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


def _structured_artifact(blob_id: int) -> HtmlStructuredContentArtifact:
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
    )


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
