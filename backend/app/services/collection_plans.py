from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.accessibility.engine import (
    ACCESSIBILITY_INTEGRATION_VERSION,
    ACCESSIBILITY_NORMALIZATION_VERSION,
    AXE_BUNDLE_SHA256,
    AXE_CORE_VERSION,
    RULESET_PROFILE,
    RULESET_SHA256,
)
from app.config import get_settings
from app.crawler.canonical_document import (
    STRUCTURED_CONTENT_CONFIG_VERSION,
    STRUCTURED_CONTENT_EXTRACTOR_VERSION,
    STRUCTURED_MARKDOWN_RENDERER_VERSION,
)
from app.crawler.url_normalizer import URL_NORMALIZATION_V1_VERSION, URL_NORMALIZATION_V2_VERSION
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
    SitePage,
    UrlIdentityState,
    WebResource,
    WebsiteProperty,
)
from app.schemas.accessibility import (
    OBSERVABILITY_REQUEST_PAGE_LIMIT as ACCESSIBILITY_REQUEST_PAGE_LIMIT,
)
from app.schemas.accessibility import AccessibilityRunCreate
from app.schemas.collection_plans import CollectionPlanRequest
from app.schemas.performance import (
    OBSERVABILITY_REQUEST_PAGE_LIMIT as PERFORMANCE_REQUEST_PAGE_LIMIT,
)
from app.schemas.performance import PerformanceRunCreate
from app.schemas.rendered import RenderRunCreate
from app.services.accessibility_collection import create_accessibility_run
from app.services.background_jobs import (
    enqueue_accessibility_run_job,
    enqueue_performance_run_job,
    enqueue_render_run_job,
    enqueue_structured_content_job,
    request_cancellation,
)
from app.services.collection_plan_serialization import lock_site_for_collection_plan_change
from app.services.job_types import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES
from app.services.performance_collection import create_performance_run
from app.services.performance_providers import (
    CRUX_ADAPTER_VERSION,
    PAGESPEED_ADAPTER_VERSION,
    PERFORMANCE_NORMALIZATION_VERSION,
)
from app.services.render_collection_profile import (
    render_collection_profile,
    render_collection_profile_identity,
)
from app.services.render_runs import create_render_run
from app.services.structured_content import latest_page_content_snapshot_subquery


def accessibility_compatibility_filters(
    model: Any, context: dict[str, Any] | None = None
) -> tuple[Any, ...]:
    identity = context or {
        "axe_core_version": AXE_CORE_VERSION,
        "detector_bundle_sha256": AXE_BUNDLE_SHA256,
        "integration_version": ACCESSIBILITY_INTEGRATION_VERSION,
        "normalization_version": ACCESSIBILITY_NORMALIZATION_VERSION,
        "ruleset_profile": RULESET_PROFILE,
        "ruleset_sha256": RULESET_SHA256,
    }
    return (
        model.axe_core_version == identity["axe_core_version"],
        model.detector_bundle_sha256 == identity["detector_bundle_sha256"],
        model.integration_version == identity["integration_version"],
        model.normalization_version == identity["normalization_version"],
        model.ruleset_profile == identity["ruleset_profile"],
        model.ruleset_sha256 == identity["ruleset_sha256"],
    )


COLLECTION_PLANNER_VERSION = "collection-planner-v2"
STRUCTURED_CONTENT_BATCH_SIZE = 250
RENDER_BATCH_SIZE = 1_000
ACTIVE_RUN_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class Candidate:
    resource_id: int
    url: str
    source_snapshot_id: int | None = None
    content_blob_id: int | None = None
    latest_compatible_observed_at: datetime | None = None


@dataclass(frozen=True)
class Selection:
    site_id: int
    domain: str
    target_mode: str
    context: dict[str, Any]
    context_identity: str
    active: tuple[Candidate, ...]
    eligible: tuple[Candidate, ...]
    covered_ids: frozenset[int]
    in_flight_ids: frozenset[int]
    active_collection_ids: frozenset[int]
    missing_ids: frozenset[int]
    targets: tuple[Candidate, ...]
    target_reasons: dict[int, str]
    universe_sha256: str
    target_sha256: str
    batch_size: int
    collectable: bool
    non_collectable_reason: str | None

    @property
    def ineligible_count(self) -> int:
        return len(self.active) - len(self.eligible)


def _sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _identity(domain: str, context: dict[str, Any]) -> str:
    return f"{domain}-collection-context-v1:{_sha(context)}"


def _current_url_normalization_version_read_only(db: Session) -> str:
    state = db.get(UrlIdentityState, 1)
    if state is not None:
        return state.active_normalization_version
    resource_count = db.scalar(select(func.count(WebResource.id))) or 0
    return URL_NORMALIZATION_V1_VERSION if resource_count else URL_NORMALIZATION_V2_VERSION


def active_page_candidates(db: Session, site_id: int) -> tuple[Candidate, ...]:
    rows = db.execute(
        select(WebResource.id, WebResource.normalized_url)
        .join(SitePage, SitePage.resource_id == WebResource.id)
        .where(
            SitePage.website_property_id == site_id,
            SitePage.workspace_state == "active",
            WebResource.resource_type == "page",
        )
        .order_by(WebResource.id)
    ).all()
    return tuple(Candidate(resource_id=row.id, url=row.normalized_url) for row in rows)


def _canonical_context(
    db: Session, site: WebsiteProperty, request: CollectionPlanRequest
) -> tuple[dict[str, Any], str, bool, str | None]:
    supplied = request.context
    domain = request.evidence_domain
    if domain == "performance":
        provider = supplied.get("provider")
        dimension = supplied.get("dimension")
        allowed = {
            "pagespeed": {"mobile", "desktop"},
            "crux": {"PHONE", "DESKTOP"},
        }
        if provider not in allowed or dimension not in allowed[provider]:
            raise ValueError("Performance context requires a supported provider and dimension.")
        adapter = PAGESPEED_ADAPTER_VERSION if provider == "pagespeed" else CRUX_ADAPTER_VERSION
        context = {
            "provider": provider,
            "dimension": dimension,
            "target_kind": "url",
            "provider_adapter_version": adapter,
            "normalization_version": PERFORMANCE_NORMALIZATION_VERSION,
        }
        configured = bool(get_settings().google_api_key)
        return (
            context,
            _identity(domain, context),
            configured,
            (None if configured else "provider_not_configured"),
        )
    if domain == "accessibility":
        profile = supplied.get("profile")
        if profile not in {"desktop", "mobile"}:
            raise ValueError("Accessibility context requires desktop or mobile profile.")
        context = {
            "profile": profile,
            "axe_core_version": AXE_CORE_VERSION,
            "detector_bundle_sha256": AXE_BUNDLE_SHA256,
            "integration_version": ACCESSIBILITY_INTEGRATION_VERSION,
            "normalization_version": ACCESSIBILITY_NORMALIZATION_VERSION,
            "ruleset_profile": RULESET_PROFILE,
            "ruleset_sha256": RULESET_SHA256,
        }
        return context, _identity(domain, context), True, None
    if domain == "render":
        if supplied:
            raise ValueError("Render context is derived from the current Site configuration.")
        configuration = {
            **site.scope_config,
            "url_normalization_version": _current_url_normalization_version_read_only(db),
        }
        context = render_collection_profile(configuration)
        return context, render_collection_profile_identity(configuration), True, None
    if supplied:
        raise ValueError("Structured content context is fixed by the current extractor.")
    context = {
        "extractor_version": STRUCTURED_CONTENT_EXTRACTOR_VERSION,
        "extractor_config_version": STRUCTURED_CONTENT_CONFIG_VERSION,
        "markdown_renderer_version": STRUCTURED_MARKDOWN_RENDERER_VERSION,
        "source_policy": "latest-successful-html-v1",
    }
    return context, _identity(domain, context), True, None


def _performance_state(
    db: Session, site_id: int, context: dict[str, Any]
) -> tuple[dict[int, datetime], set[int]]:
    latest = {
        int(resource_id): observed_at
        for resource_id, observed_at in db.execute(
            select(
                PerformanceObservation.web_resource_id,
                func.max(PerformanceObservation.observed_at),
            )
            .where(
                PerformanceObservation.website_property_id == site_id,
                PerformanceObservation.web_resource_id.is_not(None),
                PerformanceObservation.provider == context["provider"],
                PerformanceObservation.dimension == context["dimension"],
                PerformanceObservation.target_kind == "url",
                PerformanceObservation.provider_adapter_version
                == context["provider_adapter_version"],
                PerformanceObservation.normalization_version == context["normalization_version"],
                PerformanceObservation.outcome.in_(("ready", "unavailable", "failed")),
            )
            .group_by(PerformanceObservation.web_resource_id)
        )
        if resource_id is not None
    }
    in_flight: set[int] = set()
    runs = db.scalars(
        select(PerformanceRun)
        .join(BackgroundJob, BackgroundJob.performance_run_id == PerformanceRun.id)
        .where(
            PerformanceRun.website_property_id == site_id,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    for run in runs:
        config = run.configuration_json
        dimensions = (
            config.get("pagespeed_strategies", [])
            if context["provider"] == "pagespeed"
            else config.get("crux_form_factors", [])
        )
        if (
            context["provider"] in config.get("providers", [])
            and context["dimension"] in dimensions
        ):
            in_flight.update(int(value) for value in config.get("resource_ids", []))
    return latest, in_flight


def _accessibility_state(
    db: Session, site_id: int, context: dict[str, Any]
) -> tuple[dict[int, datetime], set[int]]:
    latest = {
        int(resource_id): observed_at
        for resource_id, observed_at in db.execute(
            select(
                AccessibilityObservation.web_resource_id,
                func.max(AccessibilityObservation.observed_at),
            )
            .where(
                AccessibilityObservation.website_property_id == site_id,
                AccessibilityObservation.profile == context["profile"],
                *accessibility_compatibility_filters(AccessibilityObservation, context),
                AccessibilityObservation.outcome.in_(("ready", "failed")),
            )
            .group_by(AccessibilityObservation.web_resource_id)
        )
    }
    in_flight: set[int] = set()
    runs = db.scalars(
        select(AccessibilityRun)
        .join(BackgroundJob, BackgroundJob.accessibility_run_id == AccessibilityRun.id)
        .where(
            AccessibilityRun.website_property_id == site_id,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    for run in runs:
        config = run.configuration_json
        if (
            context["profile"] in config.get("profiles", [])
            and run.axe_core_version == context["axe_core_version"]
            and run.detector_bundle_sha256 == context["detector_bundle_sha256"]
            and run.integration_version == context["integration_version"]
            and run.normalization_version == context["normalization_version"]
            and run.ruleset_profile == context["ruleset_profile"]
            and run.ruleset_sha256 == context["ruleset_sha256"]
        ):
            in_flight.update(int(value) for value in config.get("resource_ids", []))
    return latest, in_flight


def _render_state(
    db: Session, site_id: int, context_identity: str
) -> tuple[dict[int, datetime], set[int]]:
    run_rows = db.execute(
        select(RenderRun.id, RenderRun.configuration_json).where(
            RenderRun.website_property_id == site_id
        )
    )
    compatible_run_ids = [
        run_id
        for run_id, configuration in run_rows
        if render_collection_profile_identity(configuration) == context_identity
    ]
    current_profile = render_collection_profile({})
    latest = (
        {
            int(resource_id): observed_at
            for resource_id, observed_at in db.execute(
                select(
                    RenderedObservation.web_resource_id,
                    func.max(
                        func.coalesce(
                            RenderedObservation.finished_at, RenderedObservation.created_at
                        )
                    ),
                )
                .where(
                    RenderedObservation.render_run_id.in_(compatible_run_ids),
                    RenderedObservation.web_resource_id.is_not(None),
                    RenderedObservation.capture_state.not_in(
                        ("capturing", "cancelled", "interrupted")
                    ),
                    or_(
                        RenderedObservation.error_type.is_(None),
                        RenderedObservation.error_type != "host_rate_limit_circuit_open",
                    ),
                    RenderedObservation.renderer_version == current_profile["renderer_version"],
                    RenderedObservation.browser_policy_version
                    == current_profile["browser_policy_version"],
                    RenderedObservation.capture_schema_version
                    == current_profile["capture_schema_version"],
                )
                .group_by(RenderedObservation.web_resource_id)
            )
            if resource_id is not None
        }
        if compatible_run_ids
        else {}
    )
    in_flight: set[int] = set()
    runs = db.scalars(
        select(RenderRun)
        .options(selectinload(RenderRun.targets))
        .join(BackgroundJob, BackgroundJob.render_run_id == RenderRun.id)
        .where(
            RenderRun.website_property_id == site_id,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    for run in runs:
        if render_collection_profile_identity(run.configuration_json) == context_identity:
            in_flight.update(target.web_resource_id for target in run.targets)
    return latest, in_flight


def _structured_state(
    db: Session, site_id: int, active: tuple[Candidate, ...]
) -> tuple[tuple[Candidate, ...], set[int], set[int]]:
    latest = latest_page_content_snapshot_subquery(site_id)
    rows = db.execute(
        select(
            latest.c.resource_id,
            latest.c.source_snapshot_id,
            latest.c.content_blob_id,
            HtmlStructuredContentArtifact.extraction_state,
        )
        .outerjoin(
            HtmlStructuredContentArtifact,
            (HtmlStructuredContentArtifact.content_blob_id == latest.c.content_blob_id)
            & (
                HtmlStructuredContentArtifact.extractor_version
                == STRUCTURED_CONTENT_EXTRACTOR_VERSION
            )
            & (
                HtmlStructuredContentArtifact.extractor_config_version
                == STRUCTURED_CONTENT_CONFIG_VERSION
            ),
        )
        .order_by(latest.c.resource_id)
    ).all()
    by_id = {candidate.resource_id: candidate for candidate in active}
    eligible: list[Candidate] = []
    covered: set[int] = set()
    blob_to_resource: dict[int, int] = {}
    for row in rows:
        base = by_id.get(row.resource_id)
        if base is None:
            continue
        candidate = Candidate(
            resource_id=base.resource_id,
            url=base.url,
            source_snapshot_id=row.source_snapshot_id,
            content_blob_id=row.content_blob_id,
        )
        eligible.append(candidate)
        blob_to_resource[row.content_blob_id] = row.resource_id
        if row.extraction_state in {"ready", "partial", "unavailable"}:
            covered.add(row.resource_id)
    in_flight: set[int] = set()
    jobs = db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.website_property_id == site_id,
            BackgroundJob.job_type == "structured_content_build",
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    for job in jobs:
        for blob_id in job.payload_json.get("content_blob_ids") or []:
            resource_id = blob_to_resource.get(int(blob_id))
            if resource_id is not None:
                in_flight.add(resource_id)
    return tuple(eligible), covered, in_flight


def build_selection(
    db: Session,
    site_id: int,
    request: CollectionPlanRequest,
    *,
    active_override: tuple[Candidate, ...] | None = None,
) -> Selection:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        raise ValueError("Site not found.")
    context, context_identity, collectable, reason = _canonical_context(db, site, request)
    if request.evidence_domain == "structured_content" and request.target_mode == "refresh_current":
        raise ValueError(
            "refresh_current is not applicable to deterministic Structured Content. "
            "Collect new static evidence or use missing_current after the source HTML changes."
        )
    active = active_page_candidates(db, site_id) if active_override is None else active_override
    eligible = active
    if not active:
        latest_compatible: dict[int, datetime] = {}
        covered: set[int] = set()
        in_flight: set[int] = set()
        if request.evidence_domain == "performance":
            settings = get_settings()
            batch_size = min(
                PERFORMANCE_REQUEST_PAGE_LIMIT,
                settings.performance_hard_page_limit,
                settings.performance_max_provider_requests,
            )
        elif request.evidence_domain == "accessibility":
            settings = get_settings()
            batch_size = min(
                ACCESSIBILITY_REQUEST_PAGE_LIMIT,
                settings.accessibility_hard_page_limit,
                settings.accessibility_max_audit_count,
            )
        elif request.evidence_domain == "render":
            batch_size = RENDER_BATCH_SIZE
        else:
            batch_size = STRUCTURED_CONTENT_BATCH_SIZE
    elif request.evidence_domain == "performance":
        latest_compatible, in_flight = _performance_state(db, site_id, context)
        settings = get_settings()
        batch_size = min(
            PERFORMANCE_REQUEST_PAGE_LIMIT,
            settings.performance_hard_page_limit,
            settings.performance_max_provider_requests,
        )
    elif request.evidence_domain == "accessibility":
        latest_compatible, in_flight = _accessibility_state(db, site_id, context)
        settings = get_settings()
        batch_size = min(
            ACCESSIBILITY_REQUEST_PAGE_LIMIT,
            settings.accessibility_hard_page_limit,
            settings.accessibility_max_audit_count,
        )
    elif request.evidence_domain == "render":
        latest_compatible, in_flight = _render_state(db, site_id, context_identity)
        batch_size = RENDER_BATCH_SIZE
    else:
        eligible, covered, in_flight = _structured_state(db, site_id, active)
        latest_compatible = {}
        batch_size = STRUCTURED_CONTENT_BATCH_SIZE
    eligible_ids = {item.resource_id for item in eligible}
    if request.evidence_domain != "structured_content":
        covered = set(latest_compatible) & eligible_ids
    else:
        covered &= eligible_ids
    active_collection = in_flight & eligible_ids
    missing = eligible_ids - covered
    missing_in_flight = active_collection & missing
    target_ids = (
        missing - active_collection
        if request.target_mode == "missing_current"
        else eligible_ids - active_collection
    )
    targets = tuple(
        Candidate(
            resource_id=item.resource_id,
            url=item.url,
            source_snapshot_id=item.source_snapshot_id,
            content_blob_id=item.content_blob_id,
            latest_compatible_observed_at=latest_compatible.get(item.resource_id),
        )
        for item in eligible
        if item.resource_id in target_ids
    )
    target_reasons = {
        item.resource_id: ("refresh_current" if item.resource_id in covered else "missing_current")
        for item in targets
    }
    universe = [[item.resource_id, item.url] for item in active]
    target_identity = [
        [
            item.resource_id,
            item.url,
            item.source_snapshot_id,
            item.content_blob_id,
            target_reasons[item.resource_id],
            (
                item.latest_compatible_observed_at.isoformat()
                if item.latest_compatible_observed_at is not None
                else None
            ),
        ]
        for item in targets
    ]
    universe_sha256 = _sha(universe)
    target_sha256 = _sha(
        {
            "planner_version": COLLECTION_PLANNER_VERSION,
            "site_id": site_id,
            "evidence_domain": request.evidence_domain,
            "target_mode": request.target_mode,
            "context_identity": context_identity,
            "active_page_universe_sha256": universe_sha256,
            "targets": target_identity,
        }
    )
    return Selection(
        site_id=site_id,
        domain=request.evidence_domain,
        target_mode=request.target_mode,
        context=context,
        context_identity=context_identity,
        active=active,
        eligible=eligible,
        covered_ids=frozenset(covered),
        in_flight_ids=frozenset(missing_in_flight),
        active_collection_ids=frozenset(active_collection),
        missing_ids=frozenset(missing),
        targets=targets,
        target_reasons=target_reasons,
        universe_sha256=universe_sha256,
        target_sha256=target_sha256,
        batch_size=batch_size,
        collectable=collectable,
        non_collectable_reason=reason,
    )


def _active_equivalent_plan(db: Session, selection: Selection) -> CollectionPlan | None:
    plans = db.scalars(
        select(CollectionPlan)
        .options(
            selectinload(CollectionPlan.batches).joinedload(CollectionPlanBatch.background_job)
        )
        .where(
            CollectionPlan.website_property_id == selection.site_id,
            CollectionPlan.evidence_domain == selection.domain,
            CollectionPlan.target_mode == selection.target_mode,
            CollectionPlan.context_identity == selection.context_identity,
        )
        .order_by(CollectionPlan.id.desc())
    )
    return next(
        (
            plan
            for plan in plans
            if any(
                batch.background_job is not None
                and batch.background_job.status in ACTIVE_JOB_STATUSES
                for batch in plan.batches
            )
        ),
        None,
    )


def batch_target_counts(target_count: int, batch_size: int) -> list[int]:
    if target_count < 0 or batch_size < 1:
        raise ValueError("Batch bounds are invalid.")
    return [min(batch_size, target_count - start) for start in range(0, target_count, batch_size)]


def create_collection_plan(
    db: Session, site_id: int, request: CollectionPlanRequest
) -> CollectionPlan:
    if lock_site_for_collection_plan_change(db, site_id) is None:
        raise ValueError("Site not found.")
    selection = build_selection(db, site_id, request)
    if not selection.collectable:
        raise ValueError(selection.non_collectable_reason or "Context is not collectable.")
    active = _active_equivalent_plan(db, selection)
    if active is not None:
        raise ValueError(f"Equivalent Collection Plan {active.id} is already active.")
    if not selection.targets:
        if selection.target_mode == "refresh_current":
            raise ValueError("No refreshable targets remain for this context.")
        raise ValueError("No missing current evidence remains for this context.")
    batch_counts = batch_target_counts(len(selection.targets), selection.batch_size)
    batches = []
    start = 0
    for count in batch_counts:
        batches.append(selection.targets[start : start + count])
        start += count
    plan = CollectionPlan(
        website_property_id=site_id,
        planner_version=COLLECTION_PLANNER_VERSION,
        evidence_domain=selection.domain,
        target_mode=selection.target_mode,
        context_identity=selection.context_identity,
        context_json=selection.context,
        active_page_count=len(selection.active),
        active_page_universe_sha256=selection.universe_sha256,
        eligible_count=len(selection.eligible),
        covered_count_at_creation=len(selection.covered_ids),
        in_flight_count_at_creation=len(selection.in_flight_ids),
        active_collection_count_at_creation=len(selection.active_collection_ids),
        missing_count_at_creation=len(selection.missing_ids),
        selection_reason_counts_json={
            reason: sum(value == reason for value in selection.target_reasons.values())
            for reason in ("missing_current", "refresh_current")
        },
        ineligible_count_at_creation=selection.ineligible_count,
        target_count=len(selection.targets),
        batch_size=selection.batch_size,
        batch_count=len(batches),
        target_selection_sha256=selection.target_sha256,
    )
    db.add(plan)
    db.flush()
    for position, target in enumerate(selection.targets):
        db.add(
            CollectionPlanTarget(
                collection_plan_id=plan.id,
                position=position,
                web_resource_id=target.resource_id,
                requested_url=target.url,
                selection_reason=selection.target_reasons[target.resource_id],
                latest_compatible_observed_at=target.latest_compatible_observed_at,
                target_context_json=selection.context,
                source_snapshot_id=target.source_snapshot_id,
                content_blob_id=target.content_blob_id,
            )
        )
    for batch_position, batch_targets in enumerate(batches):
        resource_ids = [target.resource_id for target in batch_targets]
        batch = CollectionPlanBatch(
            collection_plan_id=plan.id,
            position=batch_position,
            target_start_position=batch_position * selection.batch_size,
            target_count=len(batch_targets),
            child_kind=selection.domain,
        )
        db.add(batch)
        if selection.domain == "performance":
            provider = selection.context["provider"]
            performance_run = create_performance_run(
                db,
                site_id,
                PerformanceRunCreate(
                    resource_ids=resource_ids,
                    providers=[provider],
                    pagespeed_strategies=(
                        [selection.context["dimension"]] if provider == "pagespeed" else []
                    ),
                    crux_form_factors=(
                        [selection.context["dimension"]] if provider == "crux" else []
                    ),
                    include_origin_crux=False,
                ),
            )
            job = enqueue_performance_run_job(db, performance_run.id, site_id)
            batch.performance_run_id = performance_run.id
        elif selection.domain == "accessibility":
            accessibility_run = create_accessibility_run(
                db,
                site_id,
                AccessibilityRunCreate(
                    resource_ids=resource_ids, profiles=[selection.context["profile"]]
                ),
            )
            job = enqueue_accessibility_run_job(db, accessibility_run.id, site_id)
            batch.accessibility_run_id = accessibility_run.id
        elif selection.domain == "render":
            render_run = create_render_run(
                db,
                site_id,
                RenderRunCreate(resource_ids=resource_ids, configuration={}),
            )
            job = enqueue_render_run_job(db, render_run)
            batch.render_run_id = render_run.id
        else:
            blob_ids = [
                int(target.content_blob_id)
                for target in batch_targets
                if target.content_blob_id is not None
            ]
            job = enqueue_structured_content_job(
                db,
                site_id=site_id,
                content_blob_ids=blob_ids,
                collection_plan_id=plan.id,
                collection_plan_batch_position=batch_position,
            )
        batch.background_job_id = job.id
    db.commit()
    return get_collection_plan(db, site_id, plan.id) or plan


def _batch_status(batch: CollectionPlanBatch) -> str:
    return batch.background_job.status if batch.background_job is not None else "missing"


def _processed(batch: CollectionPlanBatch) -> int:
    if batch.performance_run is not None:
        return min(batch.target_count, batch.performance_run.completed_count)
    if batch.accessibility_run is not None:
        return min(batch.target_count, batch.accessibility_run.completed_count)
    if batch.render_run is not None:
        return min(
            batch.target_count,
            batch.render_run.completed_count
            + batch.render_run.failed_count
            + batch.render_run.skipped_count,
        )
    job = batch.background_job
    if job is None:
        return 0
    if job.status in {"completed", "completed_with_errors"}:
        return batch.target_count
    return min(batch.target_count, job.progress_current or 0)


def plan_status(plan: CollectionPlan) -> str:
    statuses = [_batch_status(batch) for batch in plan.batches]
    if any(status == "running" for status in statuses):
        return "cancelling" if plan.cancellation_requested_at else "running"
    if any(status == "queued" for status in statuses):
        return "cancelling" if plan.cancellation_requested_at else "queued"
    if any(status in {"failed", "interrupted", "missing"} for status in statuses):
        return "completed_with_errors"
    if any(status == "completed_with_errors" for status in statuses):
        return "completed_with_errors"
    if statuses and all(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status == "cancelled" for status in statuses):
        return "cancelled"
    return "completed"


_PLAN_OPTIONS = (
    selectinload(CollectionPlan.batches).joinedload(CollectionPlanBatch.background_job),
    selectinload(CollectionPlan.batches).joinedload(CollectionPlanBatch.performance_run),
    selectinload(CollectionPlan.batches).joinedload(CollectionPlanBatch.accessibility_run),
    selectinload(CollectionPlan.batches).joinedload(CollectionPlanBatch.render_run),
)


def get_collection_plan(db: Session, site_id: int, plan_id: int) -> CollectionPlan | None:
    return db.scalar(
        select(CollectionPlan)
        .options(*_PLAN_OPTIONS)
        .where(CollectionPlan.id == plan_id, CollectionPlan.website_property_id == site_id)
    )


def list_collection_plans(
    db: Session, site_id: int, *, limit: int, offset: int
) -> tuple[list[CollectionPlan], int]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(CollectionPlan)
            .where(CollectionPlan.website_property_id == site_id)
        )
        or 0
    )
    items = list(
        db.scalars(
            select(CollectionPlan)
            .options(*_PLAN_OPTIONS)
            .where(CollectionPlan.website_property_id == site_id)
            .order_by(CollectionPlan.created_at.desc(), CollectionPlan.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def cancel_collection_plan(db: Session, plan: CollectionPlan) -> CollectionPlan:
    if plan_status(plan) not in {"queued", "running", "cancelling"}:
        return plan
    try:
        plan.cancellation_requested_at = datetime.now(UTC)
        for batch in plan.batches:
            job = batch.background_job
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                continue
            was_queued = job.status == "queued"
            request_cancellation(
                db,
                job,
                "Collection Plan cancellation requested.",
                commit=False,
            )
            if was_queued:
                run = batch.performance_run or batch.accessibility_run or batch.render_run
                if run is not None and run.status == "queued":
                    run.status = "cancelled"
                    run.finished_at = job.finished_at
                    run.error_summary = "Cancelled before execution by Collection Plan."
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_collection_plan(db, plan.website_property_id, plan.id) or plan
