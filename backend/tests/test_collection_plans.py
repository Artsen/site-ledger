from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

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
from app.crawler.url_normalizer import URL_NORMALIZATION_V1_VERSION
from app.database import get_db
from app.main import create_app
from app.models import (
    AccessibilityObservation,
    AccessibilityRun,
    BackgroundJob,
    CollectionPlan,
    CollectionPlanBatch,
    CollectionPlanTarget,
    HtmlStructuredContentArtifact,
    PerformanceObservation,
    PerformanceRun,
    RenderedObservation,
    RenderRun,
    ResourceSnapshot,
    Scan,
    SitePage,
    UrlIdentityState,
    WebResource,
    WebsiteProperty,
)
from app.schemas.collection_plans import CollectionPlanRequest
from app.services.background_jobs import enqueue_accessibility_run_job
from app.services.collection_plans import (
    batch_target_counts,
    build_selection,
    cancel_collection_plan,
    create_collection_plan,
    get_collection_plan,
    plan_status,
)
from app.services.job_handlers import AccessibilityRunJobHandler
from app.services.job_types import ExecutionOwnershipLost
from app.services.performance_providers import (
    PAGESPEED_ADAPTER_VERSION,
    PERFORMANCE_NORMALIZATION_VERSION,
)
from app.services.render_collection_profile import (
    render_collection_profile,
    render_collection_profile_identity,
)
from app.services.structured_content import build_missing_structured_content
from app.storage.content_store import LocalContentStore


def _site_with_pages(db_session, count: int) -> WebsiteProperty:
    site = WebsiteProperty(
        name="Collection Plan fixture",
        base_url="https://example.test/",
        normalized_base_url="https://example.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    resources = [
        WebResource(
            resource_type="page",
            normalized_url=f"https://example.test/{position}",
            scheme="https",
            host="example.test",
            path=f"/{position}",
            query="",
        )
        for position in range(count)
    ]
    db_session.add_all(resources)
    db_session.flush()
    db_session.add_all(
        [SitePage(website_property_id=site.id, resource_id=resource.id) for resource in resources]
    )
    db_session.commit()
    return site


def test_accessibility_plan_freezes_targets_and_creates_native_batches(db_session) -> None:
    site = _site_with_pages(db_session, 501)
    request = CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"})

    preview = build_selection(db_session, site.id, request)
    repeated = build_selection(db_session, site.id, request)

    assert len(preview.targets) == 501
    assert preview.universe_sha256 == repeated.universe_sha256
    assert preview.target_sha256 == repeated.target_sha256

    plan = create_collection_plan(db_session, site.id, request)

    assert plan.target_count == 501
    assert plan.batch_size == 250
    assert plan.batch_count == 3
    assert [batch.target_count for batch in plan.batches] == [250, 250, 1]
    assert all(batch.accessibility_run_id for batch in plan.batches)
    assert all(batch.background_job_id for batch in plan.batches)
    assert db_session.scalar(select(func.count()).select_from(CollectionPlanTarget)) == 501
    assert db_session.scalar(select(func.count()).select_from(AccessibilityRun)) == 3
    assert db_session.scalar(select(func.count()).select_from(BackgroundJob)) == 3

    current = build_selection(db_session, site.id, request)
    assert len(current.targets) == 0
    assert len(current.in_flight_ids) == 501
    with pytest.raises(ValueError, match="already active"):
        create_collection_plan(db_session, site.id, request)

    new_resource = WebResource(
        resource_type="page",
        normalized_url="https://example.test/new",
        scheme="https",
        host="example.test",
        path="/new",
        query="",
    )
    db_session.add(new_resource)
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=new_resource.id))
    db_session.commit()
    refreshed = build_selection(db_session, site.id, request)
    assert [target.web_resource_id for target in plan.targets] != [
        target.resource_id for target in refreshed.targets
    ]
    assert [target.resource_id for target in refreshed.targets] == [new_resource.id]
    assert plan.target_count == 501


def test_cancel_plan_cancels_queued_jobs_and_native_runs(db_session) -> None:
    site = _site_with_pages(db_session, 2)
    plan = create_collection_plan(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "mobile"}),
    )

    cancelled = cancel_collection_plan(db_session, plan)

    assert plan_status(cancelled) == "cancelled"
    assert cancelled.cancellation_requested_at is not None
    assert all(batch.background_job.status == "cancelled" for batch in cancelled.batches)
    assert all(batch.accessibility_run.status == "cancelled" for batch in cancelled.batches)


def test_collection_plan_relationships_use_set_null_for_child_history() -> None:
    foreign_keys = {
        constraint.columns.keys()[0]: constraint.ondelete
        for constraint in CollectionPlanBatch.__table__.foreign_key_constraints
    }

    assert foreign_keys["background_job_id"] == "SET NULL"
    assert foreign_keys["performance_run_id"] == "SET NULL"
    assert foreign_keys["accessibility_run_id"] == "SET NULL"
    assert foreign_keys["render_run_id"] == "SET NULL"


def test_render_preview_is_read_only_when_url_identity_state_is_not_initialized(
    db_session,
) -> None:
    site = _site_with_pages(db_session, 0)
    assert db_session.get(UrlIdentityState, 1) is None

    selection = build_selection(
        db_session, site.id, CollectionPlanRequest(evidence_domain="render")
    )

    assert selection.targets == ()
    assert db_session.get(UrlIdentityState, 1) is None


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (0, []),
        (1, [1]),
        (249, [249]),
        (250, [250]),
        (251, [250, 1]),
        (500, [250, 250]),
        (501, [250, 250, 1]),
        (935, [250, 250, 250, 185]),
        (2_501, [250] * 10 + [1]),
    ],
)
def test_250_page_batch_boundaries(total: int, expected: list[int]) -> None:
    assert batch_target_counts(total, 250) == expected


@pytest.mark.parametrize(
    ("total", "expected"),
    [(999, [999]), (1_000, [1_000]), (1_001, [1_000, 1]), (2_487, [1_000, 1_000, 487])],
)
def test_render_batch_boundaries(total: int, expected: list[int]) -> None:
    assert batch_target_counts(total, 1_000) == expected


def test_render_collection_profile_ignores_batch_bounds_but_keeps_capture_semantics() -> None:
    small = {
        "render_mode": "starting_page",
        "render_max_pages": 1,
        "max_pages": 1,
        "render_viewport_width": 1440,
        "url_normalization_version": "url-normalization-v2",
    }
    large = {
        **small,
        "render_mode": "all_eligible",
        "render_max_pages": 1_000,
        "max_pages": 1_000,
    }
    different_viewport = {**large, "render_viewport_width": 1024}
    equivalent_numeric_types = {
        **large,
        "render_navigation_timeout_seconds": 30.0,
        "render_load_timeout_seconds": 10.0,
        "render_max_page_duration_seconds": 60.0,
    }

    assert render_collection_profile_identity(small) == render_collection_profile_identity(large)
    assert render_collection_profile_identity(large) == render_collection_profile_identity(
        equivalent_numeric_types
    )
    assert render_collection_profile_identity(large) != render_collection_profile_identity(
        different_viewport
    )


def test_performance_current_failed_and_unavailable_are_covered_but_legacy_is_missing(
    db_session,
) -> None:
    site = _site_with_pages(db_session, 3)
    resources = list(
        db_session.scalars(
            select(WebResource)
            .join(SitePage, SitePage.resource_id == WebResource.id)
            .where(SitePage.website_property_id == site.id)
            .order_by(WebResource.id)
        )
    )
    run = PerformanceRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={},
        target_count=3,
        request_count=3,
    )
    db_session.add(run)
    db_session.flush()
    for position, (resource, outcome) in enumerate(
        zip(resources, ("unavailable", "failed", "ready"), strict=True)
    ):
        db_session.add(
            PerformanceObservation(
                performance_run_id=run.id,
                website_property_id=site.id,
                web_resource_id=resource.id,
                provider="pagespeed",
                provider_adapter_version=(
                    PAGESPEED_ADAPTER_VERSION if position < 2 else "legacy-adapter"
                ),
                normalization_version=PERFORMANCE_NORMALIZATION_VERSION,
                target_kind="url",
                target_key=str(resource.id),
                requested_target=resource.normalized_url,
                dimension="mobile",
                outcome=outcome,
                request_descriptor_json={},
            )
        )
    db_session.commit()
    request = CollectionPlanRequest(
        evidence_domain="performance",
        context={"provider": "pagespeed", "dimension": "mobile"},
    )

    selection = build_selection(db_session, site.id, request)

    assert selection.covered_ids == {resources[0].id, resources[1].id}
    assert [target.resource_id for target in selection.targets] == [resources[2].id]
    db_session.delete(
        db_session.scalar(
            select(PerformanceObservation).where(
                PerformanceObservation.web_resource_id == resources[0].id
            )
        )
    )
    db_session.commit()
    after_deletion = build_selection(db_session, site.id, request)
    assert resources[0].id in {target.resource_id for target in after_deletion.targets}


def test_accessibility_coverage_separates_profiles_and_rejects_old_rulesets(db_session) -> None:
    site = _site_with_pages(db_session, 1)
    resource = db_session.scalar(
        select(WebResource).join(SitePage).where(SitePage.website_property_id == site.id)
    )
    assert resource is not None
    run = AccessibilityRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={"resource_ids": [resource.id], "profiles": ["desktop"]},
        target_count=1,
        observation_count=1,
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=0,
        ruleset_sha256=RULESET_SHA256,
    )
    db_session.add(run)
    db_session.flush()
    observation = AccessibilityObservation(
        accessibility_run_id=run.id,
        website_property_id=site.id,
        web_resource_id=resource.id,
        requested_url=resource.normalized_url,
        profile="desktop",
        outcome="ready",
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_sha256=RULESET_SHA256,
        profile_json={},
    )
    db_session.add(observation)
    db_session.commit()

    desktop = build_selection(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
    )
    mobile = build_selection(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "mobile"}),
    )
    assert desktop.covered_ids == {resource.id}
    assert desktop.targets == ()
    assert [target.resource_id for target in mobile.targets] == [resource.id]

    observation.ruleset_sha256 = "legacy-ruleset"
    db_session.commit()
    legacy = build_selection(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
    )
    assert [target.resource_id for target in legacy.targets] == [resource.id]


def test_render_coverage_uses_batch_stable_profile_and_truthful_attempt_states(
    db_session,
) -> None:
    site = _site_with_pages(db_session, 5)
    resources = list(
        db_session.scalars(
            select(WebResource)
            .join(SitePage)
            .where(SitePage.website_property_id == site.id)
            .order_by(WebResource.id)
        )
    )
    compatible_configuration = {
        "url_normalization_version": URL_NORMALIZATION_V1_VERSION,
        "render_mode": "starting_page",
        "render_max_pages": 1,
        "max_pages": 1,
    }
    incompatible_configuration = {
        **compatible_configuration,
        "render_viewport_width": 1024,
    }
    compatible_run = RenderRun(
        website_property_id=site.id,
        status="completed_with_errors",
        trigger="site_workspace",
        configuration_json=compatible_configuration,
        target_count=4,
    )
    incompatible_run = RenderRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json=incompatible_configuration,
        target_count=1,
    )
    db_session.add_all([compatible_run, incompatible_run])
    db_session.flush()
    current_profile = render_collection_profile({})
    states = (
        ("completed", None),
        ("cancelled", None),
        ("interrupted", None),
        ("failed", "host_rate_limit_circuit_open"),
        ("completed", None),
    )
    for position, (resource, (state, error_type)) in enumerate(zip(resources, states, strict=True)):
        db_session.add(
            RenderedObservation(
                render_run_id=(compatible_run.id if position < 4 else incompatible_run.id),
                web_resource_id=resource.id,
                capture_state=state,
                requested_url=resource.normalized_url,
                error_type=error_type,
                browser_engine="chromium",
                renderer_version=current_profile["renderer_version"],
                browser_policy_version=current_profile["browser_policy_version"],
                capture_schema_version=current_profile["capture_schema_version"],
                viewport_width=1440,
                viewport_height=900,
                device_scale_factor=1,
                locale="en-US",
                timezone_id="UTC",
                color_scheme="light",
                reduced_motion="reduce",
                configuration_fingerprint=str(position) * 64,
            )
        )
    db_session.commit()

    selection = build_selection(
        db_session, site.id, CollectionPlanRequest(evidence_domain="render")
    )

    assert selection.covered_ids == {resources[0].id}
    assert [target.resource_id for target in selection.targets] == [
        resource.id for resource in resources[1:]
    ]
    assert render_collection_profile_identity(compatible_configuration) == (
        selection.context_identity
    )
    assert render_collection_profile_identity(incompatible_configuration) != (
        selection.context_identity
    )


def _structured_artifact(blob_id: int, state: str) -> HtmlStructuredContentArtifact:
    return HtmlStructuredContentArtifact(
        content_blob_id=blob_id,
        extractor_version=STRUCTURED_CONTENT_EXTRACTOR_VERSION,
        extractor_config_version=STRUCTURED_CONTENT_CONFIG_VERSION,
        extraction_state=state,
        document_profile="headed" if state != "unavailable" else "empty",
        document_text_sha256="1" * 64,
        outline_sha256="2" * 64,
        canonical_document_sha256="3" * 64,
        markdown_renderer_version=STRUCTURED_MARKDOWN_RENDERER_VERSION,
        markdown_sha256="4" * 64,
        markdown_character_count=10,
    )


def test_structured_plan_uses_latest_blob_freezes_exact_work_and_fences_persistence(
    db_session, tmp_path
) -> None:
    site = _site_with_pages(db_session, 3)
    resources = list(
        db_session.scalars(
            select(WebResource)
            .join(SitePage)
            .where(SitePage.website_property_id == site.id)
            .order_by(WebResource.id)
        )
    )
    store = LocalContentStore(tmp_path / "collection-plan-content")
    old_blob = store.put_html(db_session, b"<h1>Old</h1>", "text/html", "utf-8")
    frozen_blob = store.put_html(db_session, b"<h1>Frozen</h1>", "text/html", "utf-8")
    unavailable_blob = store.put_html(db_session, b"", "text/html", "utf-8")
    old_scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    current_scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    db_session.add_all([old_scan, current_scan])
    db_session.flush()
    snapshots = [
        ResourceSnapshot(
            scan_id=old_scan.id,
            resource_id=resources[0].id,
            requested_url=resources[0].normalized_url,
            crawl_depth=0,
            fetched_at=datetime(2026, 8, 30, tzinfo=UTC),
            fetch_state="fetched",
            html_blob_id=old_blob.id,
        ),
        ResourceSnapshot(
            scan_id=current_scan.id,
            resource_id=resources[0].id,
            requested_url=resources[0].normalized_url,
            crawl_depth=0,
            fetched_at=datetime(2026, 8, 31, tzinfo=UTC),
            fetch_state="fetched",
            html_blob_id=frozen_blob.id,
        ),
        ResourceSnapshot(
            scan_id=current_scan.id,
            resource_id=resources[1].id,
            requested_url=resources[1].normalized_url,
            crawl_depth=0,
            fetched_at=datetime(2026, 8, 31, tzinfo=UTC),
            fetch_state="fetched",
            html_blob_id=unavailable_blob.id,
        ),
    ]
    db_session.add_all(
        [
            *snapshots,
            _structured_artifact(old_blob.id, "ready"),
            _structured_artifact(unavailable_blob.id, "unavailable"),
        ]
    )
    db_session.commit()

    request = CollectionPlanRequest(evidence_domain="structured_content")
    selection = build_selection(db_session, site.id, request)
    assert len(selection.eligible) == 2
    assert selection.covered_ids == {resources[1].id}
    assert selection.ineligible_count == 1
    assert [(target.resource_id, target.content_blob_id) for target in selection.targets] == [
        (resources[0].id, frozen_blob.id)
    ]

    plan = create_collection_plan(db_session, site.id, request)
    job = plan.batches[0].background_job
    assert job is not None
    assert job.payload_json["content_blob_ids"] == [frozen_blob.id]

    newer_blob = store.put_html(db_session, b"<h1>Newer</h1>", "text/html", "utf-8")
    newer_scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    db_session.add(newer_scan)
    db_session.flush()
    db_session.add(
        ResourceSnapshot(
            scan_id=newer_scan.id,
            resource_id=resources[0].id,
            requested_url=resources[0].normalized_url,
            crawl_depth=0,
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            fetch_state="fetched",
            html_blob_id=newer_blob.id,
        )
    )
    db_session.commit()

    result = build_missing_structured_content(
        db_session, store, site_id=site.id, content_blob_ids=[frozen_blob.id]
    )
    assert result["ready"] == 1
    assert (
        db_session.scalar(
            select(HtmlStructuredContentArtifact).where(
                HtmlStructuredContentArtifact.content_blob_id == frozen_blob.id
            )
        )
        is not None
    )
    assert (
        db_session.scalar(
            select(HtmlStructuredContentArtifact).where(
                HtmlStructuredContentArtifact.content_blob_id == newer_blob.id
            )
        )
        is None
    )

    def lose_ownership(_db) -> None:
        raise ExecutionOwnershipLost("forced ownership loss")

    with pytest.raises(ExecutionOwnershipLost, match="forced ownership loss"):
        build_missing_structured_content(
            db_session,
            store,
            site_id=site.id,
            content_blob_ids=[newer_blob.id],
            fence_domain_mutation=lose_ownership,
        )
    assert (
        db_session.scalar(
            select(HtmlStructuredContentArtifact).where(
                HtmlStructuredContentArtifact.content_blob_id == newer_blob.id
            )
        )
        is None
    )


def test_multi_batch_cancellation_preserves_terminal_work_and_cancels_queued_runs(
    db_session,
) -> None:
    site = _site_with_pages(db_session, 751)
    plan = create_collection_plan(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
    )
    statuses = ("completed", "running", "queued", "queued")
    for batch, status in zip(plan.batches, statuses, strict=True):
        assert batch.background_job is not None and batch.accessibility_run is not None
        batch.background_job.status = status
        batch.accessibility_run.status = status
    db_session.commit()

    cancelled = cancel_collection_plan(db_session, plan)

    assert cancelled.batches[0].background_job.status == "completed"
    assert cancelled.batches[0].accessibility_run.status == "completed"
    assert cancelled.batches[1].background_job.status == "running"
    assert cancelled.batches[1].background_job.cancellation_requested_at is not None
    assert [batch.background_job.status for batch in cancelled.batches[2:]] == [
        "cancelled",
        "cancelled",
    ]
    assert [batch.accessibility_run.status for batch in cancelled.batches[2:]] == [
        "cancelled",
        "cancelled",
    ]
    assert plan_status(cancelled) == "cancelling"


@pytest.mark.asyncio
async def test_plan_created_child_uses_normal_handler_ownership_fence(
    db_session, monkeypatch
) -> None:
    site = _site_with_pages(db_session, 1)
    plan = create_collection_plan(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
    )
    batch = plan.batches[0]
    assert batch.background_job is not None and batch.accessibility_run is not None
    ownership_fence = object()
    captured: dict[str, object] = {}

    async def execute(_factory, run_id, **kwargs):
        captured["run_id"] = run_id
        captured["fence"] = kwargs["fence_domain_mutation"]
        return batch.accessibility_run

    monkeypatch.setattr("app.services.job_handlers.execute_accessibility_run", execute)
    context = SimpleNamespace(
        check_cancelled=lambda: False,
        fence_domain_mutation=ownership_fence,
        progress=lambda **_kwargs: None,
    )
    handler = AccessibilityRunJobHandler(lambda: db_session)

    await handler.execute(batch.background_job, context)

    assert captured == {"run_id": batch.accessibility_run.id, "fence": ownership_fence}


def test_plan_detail_query_count_is_bounded_for_many_batches(db_session) -> None:
    site = _site_with_pages(db_session, 501)
    plan = create_collection_plan(
        db_session,
        site.id,
        CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
    )
    shared_job_id = plan.batches[0].background_job_id
    for position in range(3, 15):
        db_session.add(
            CollectionPlanBatch(
                collection_plan_id=plan.id,
                position=position,
                target_start_position=501,
                target_count=0,
                child_kind="accessibility",
                background_job_id=shared_job_id,
            )
        )
    db_session.commit()
    db_session.expire_all()
    statements = 0

    def count_statements(*_args: object) -> None:
        nonlocal statements
        statements += 1

    event.listen(db_session.bind, "before_cursor_execute", count_statements)
    try:
        loaded = get_collection_plan(db_session, site.id, plan.id)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_statements)
    assert loaded is not None and len(loaded.batches) == 15
    assert statements <= 6


def test_plan_creation_rolls_back_all_children_when_a_batch_enqueue_fails(
    db_session, monkeypatch
) -> None:
    site = _site_with_pages(db_session, 251)
    from app.services import collection_plans

    original = collection_plans.enqueue_accessibility_run_job
    calls = 0

    def fail_second_enqueue(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced enqueue failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(collection_plans, "enqueue_accessibility_run_job", fail_second_enqueue)
    with pytest.raises(RuntimeError, match="forced enqueue failure"):
        create_collection_plan(
            db_session,
            site.id,
            CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
        )
    db_session.rollback()

    for model in (
        CollectionPlanBatch,
        CollectionPlanTarget,
        CollectionPlan,
        AccessibilityRun,
        BackgroundJob,
    ):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


def test_three_thousand_page_selection_is_deterministic_and_query_bounded(
    db_session,
) -> None:
    site = _site_with_pages(db_session, 3_000)
    resources = list(
        db_session.scalars(
            select(WebResource)
            .join(SitePage, SitePage.resource_id == WebResource.id)
            .where(SitePage.website_property_id == site.id)
            .order_by(WebResource.id)
        )
    )
    evidence_run = AccessibilityRun(
        website_property_id=site.id,
        status="completed",
        trigger="site_workspace",
        configuration_json={
            "resource_ids": [item.id for item in resources[:1_500]],
            "profiles": ["desktop"],
        },
        target_count=1_500,
        observation_count=1_500,
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=0,
        ruleset_sha256=RULESET_SHA256,
    )
    db_session.add(evidence_run)
    db_session.flush()
    observations = []
    for position, resource in enumerate(resources[:1_500]):
        observations.append(
            AccessibilityObservation(
                accessibility_run_id=evidence_run.id,
                website_property_id=site.id,
                web_resource_id=resource.id,
                requested_url=resource.normalized_url,
                profile="desktop",
                outcome="ready",
                axe_core_version=AXE_CORE_VERSION,
                detector_bundle_sha256=AXE_BUNDLE_SHA256,
                integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
                normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
                ruleset_profile=RULESET_PROFILE,
                ruleset_sha256=(RULESET_SHA256 if position < 1_000 else "legacy-ruleset"),
                profile_json={},
            )
        )
    db_session.add_all(observations)
    active_run = AccessibilityRun(
        website_property_id=site.id,
        status="queued",
        trigger="site_workspace",
        configuration_json={
            "resource_ids": [item.id for item in resources[1_500:2_000]],
            "profiles": ["desktop"],
        },
        target_count=500,
        observation_count=500,
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=0,
        ruleset_sha256=RULESET_SHA256,
    )
    db_session.add(active_run)
    db_session.flush()
    enqueue_accessibility_run_job(db_session, active_run.id, site.id)
    db_session.commit()
    statements = 0
    selects = 0

    def count_statements(
        _connection, _cursor, statement: str, _parameters, _context, _executemany
    ) -> None:
        nonlocal selects, statements
        statements += 1
        selects += statement.lstrip().upper().startswith("SELECT")

    event.listen(db_session.bind, "before_cursor_execute", count_statements)
    try:
        first = build_selection(
            db_session,
            site.id,
            CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
        )
        first_statements = statements
        first_selects = selects
        statements = 0
        selects = 0
        second = build_selection(
            db_session,
            site.id,
            CollectionPlanRequest(evidence_domain="accessibility", context={"profile": "desktop"}),
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_statements)

    assert len(first.covered_ids) == 1_000
    assert len(first.in_flight_ids) == 500
    assert len(first.targets) == 1_500
    assert first.universe_sha256 == second.universe_sha256
    assert first.target_sha256 == second.target_sha256
    assert first_statements <= 4
    assert first_selects <= 4
    assert statements <= 4
    assert selects <= 4


def test_collection_plan_api_preview_create_read_targets_and_cancel(db_session) -> None:
    site = _site_with_pages(db_session, 3)
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = create_app(session_factory=factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    payload = {
        "evidence_domain": "accessibility",
        "target_mode": "missing_current",
        "context": {"profile": "desktop"},
    }
    with TestClient(app) as client:
        preview = client.post(f"/api/sites/{site.id}/collection-plans/preview", json=payload)
        assert preview.status_code == 200
        assert preview.json()["missing"] == 3
        assert preview.json()["estimated_batch_count"] == 1

        created = client.post(f"/api/sites/{site.id}/collection-plans", json=payload)
        assert created.status_code == 202
        plan_id = created.json()["id"]
        assert created.json()["status"] == "queued"

        listed = client.get(f"/api/sites/{site.id}/collection-plans")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == plan_id

        targets = client.get(f"/api/sites/{site.id}/collection-plans/{plan_id}/targets")
        assert targets.status_code == 200
        assert [item["position"] for item in targets.json()["items"]] == [0, 1, 2]

        cancelled = client.post(f"/api/sites/{site.id}/collection-plans/{plan_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
