from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.crawler.canonical_document import (
    STRUCTURED_CONTENT_CONFIG_VERSION,
    STRUCTURED_CONTENT_EXTRACTOR_VERSION,
    STRUCTURED_MARKDOWN_RENDERER_VERSION,
)
from app.models import (
    AccessibilityObservation,
    AccessibilityRun,
    BackgroundJob,
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
    SiteInventorySuppression,
    SitePage,
    SourceRefresh,
    UrlSource,
    UrlSourceEntry,
    WebsiteProperty,
)
from app.schemas.site_intelligence import (
    AccessibilityIntelligenceRead,
    ActiveJobRead,
    ActivityIntelligenceRead,
    ComparisonIntelligenceRead,
    CoverageRead,
    EvidenceClock,
    PagePopulationRead,
    PerformanceContextRead,
    PerformanceIntelligenceRead,
    RenderIntelligenceRead,
    RenderLatestRunRead,
    ScanIntelligenceRead,
    SiteIntelligenceRead,
    SourcesIntelligenceRead,
    StructuredContentIntelligenceRead,
)
from app.services.scan_comparisons import SCAN_COMPARISON_ALGORITHM, SCAN_COMPARISON_VERSION
from app.services.scan_projections import TERMINAL_SCAN_STATUSES


def _coverage(observed: int, eligible: int) -> CoverageRead:
    return CoverageRead(
        observed=observed,
        eligible=eligible,
        ratio=(observed / eligible if eligible else None),
    )


def _active_pages(site_id: int) -> Select[tuple[int]]:
    return select(SitePage.resource_id).where(
        SitePage.website_property_id == site_id,
        SitePage.workspace_state == "active",
    )


def get_site_intelligence(db: Session, site_id: int) -> SiteIntelligenceRead | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None

    population = _page_population(db, site_id)
    active_total = population.active_page_total
    return SiteIntelligenceRead(
        site_id=site_id,
        page_population=population,
        scan=_scan_state(db, site_id, active_total),
        comparison=_comparison_state(db, site_id),
        structured_content=_structured_content_state(db, site_id, active_total),
        render=_render_state(db, site_id, active_total),
        performance=_performance_state(db, site_id, active_total),
        accessibility=_accessibility_state(db, site_id, active_total),
        sources=_sources_state(db, site_id),
        activity=_activity_state(db, site_id),
    )


def _page_population(db: Session, site_id: int) -> PagePopulationRead:
    rows = db.execute(
        select(SitePage.workspace_state, SitePage.workflow_status, func.count())
        .where(SitePage.website_property_id == site_id)
        .group_by(SitePage.workspace_state, SitePage.workflow_status)
    ).all()
    active = sum(count for state, _workflow, count in rows if state == "active")
    suppressed = sum(count for state, _workflow, count in rows if state == "suppressed")
    workflow: dict[str, int] = defaultdict(int)
    for state, name, count in rows:
        if state == "active":
            workflow[name] += count
    return PagePopulationRead(
        active_page_total=active,
        suppressed_page_total=suppressed,
        workspace_page_total=active + suppressed,
        workflow_counts=dict(workflow),
    )


def _scan_state(db: Session, site_id: int, active_total: int) -> ScanIntelligenceRead:
    scan = db.scalar(
        select(Scan)
        .where(Scan.website_property_id == site_id, Scan.status.in_(TERMINAL_SCAN_STATUSES))
        .order_by(Scan.created_at.desc(), Scan.id.desc())
        .limit(1)
    )
    empty = _coverage(0, active_total)
    if scan is None:
        return ScanIntelligenceRead(
            present=False,
            active_page_observed=empty,
            active_page_fetched=empty,
            clock=EvidenceClock(),
        )
    observed, fetched = db.execute(
        select(
            func.count(func.distinct(ResourceSnapshot.resource_id)),
            func.count(
                func.distinct(
                    case((ResourceSnapshot.fetch_state == "fetched", ResourceSnapshot.resource_id))
                )
            ),
        ).where(
            ResourceSnapshot.scan_id == scan.id,
            ResourceSnapshot.resource_id.in_(_active_pages(site_id)),
        )
    ).one()
    return ScanIntelligenceRead(
        present=True,
        id=scan.id,
        status=scan.status,
        created_at=scan.created_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        discovered_count=scan.discovered_count,
        fetched_count=scan.fetched_count,
        failed_count=scan.failed_count,
        skipped_count=scan.skipped_count,
        stop_reason=scan.stop_reason,
        fatal_error_message=scan.fatal_error_message,
        active_page_observed=_coverage(observed or 0, active_total),
        active_page_fetched=_coverage(fetched or 0, active_total),
        clock=EvidenceClock(
            latest_observed_at=scan.finished_at or scan.created_at,
            latest_completed_at=scan.finished_at,
            source_scan_id=scan.id,
            source_status=scan.status,
        ),
    )


def _comparison_state(db: Session, site_id: int) -> ComparisonIntelligenceRead:
    row = db.execute(
        select(ScanComparison, ScanComparisonBuild, ScanComparisonSummary)
        .join(ScanComparisonBuild, ScanComparison.current_build_id == ScanComparisonBuild.id)
        .outerjoin(
            ScanComparisonSummary,
            ScanComparisonSummary.comparison_build_id == ScanComparisonBuild.id,
        )
        .where(
            ScanComparison.website_property_id == site_id,
            ScanComparisonBuild.status == "ready",
            ScanComparisonBuild.comparison_version == SCAN_COMPARISON_VERSION,
            ScanComparisonBuild.algorithm_identity == SCAN_COMPARISON_ALGORITHM,
        )
        .order_by(ScanComparisonBuild.finished_at.desc(), ScanComparisonBuild.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return ComparisonIntelligenceRead(present=False, clock=EvidenceClock())
    comparison, build, summary = row
    return ComparisonIntelligenceRead(
        present=True,
        comparison_id=comparison.id,
        build_id=build.id,
        baseline_scan_id=comparison.baseline_scan_id,
        target_scan_id=comparison.target_scan_id,
        comparison_version=build.comparison_version,
        algorithm_identity=build.algorithm_identity,
        page_counts=summary.page_counts_json if summary else {},
        resource_counts=summary.resource_counts_json if summary else {},
        link_counts=summary.link_counts_json if summary else {},
        clock=EvidenceClock(
            latest_observed_at=build.finished_at or build.created_at,
            latest_completed_at=build.finished_at,
            source_comparison_id=comparison.id,
            source_status=build.status,
        ),
    )


def _structured_content_state(
    db: Session, site_id: int, active_total: int
) -> StructuredContentIntelligenceRead:
    ranked = (
        select(
            ResourceSnapshot.resource_id,
            ResourceSnapshot.html_blob_id,
            func.coalesce(ResourceSnapshot.fetched_at, Scan.created_at).label("observed_at"),
            func.row_number()
            .over(
                partition_by=ResourceSnapshot.resource_id,
                order_by=(
                    func.coalesce(ResourceSnapshot.fetched_at, Scan.created_at).desc(),
                    ResourceSnapshot.id.desc(),
                ),
            )
            .label("position"),
        )
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .where(
            Scan.website_property_id == site_id,
            ResourceSnapshot.resource_id.in_(_active_pages(site_id)),
            ResourceSnapshot.fetch_state == "fetched",
            ResourceSnapshot.html_blob_id.is_not(None),
        )
        .subquery()
    )
    current = select(ranked).where(ranked.c.position == 1).subquery()
    values = db.execute(
        select(
            func.count(current.c.resource_id),
            func.count(case((HtmlStructuredContentArtifact.extraction_state == "ready", 1))),
            func.count(case((HtmlStructuredContentArtifact.extraction_state == "partial", 1))),
            func.count(case((HtmlStructuredContentArtifact.extraction_state == "unavailable", 1))),
            func.count(HtmlStructuredContentArtifact.id),
            func.min(HtmlStructuredContentArtifact.created_at),
            func.max(HtmlStructuredContentArtifact.created_at),
        )
        .select_from(current)
        .outerjoin(
            HtmlStructuredContentArtifact,
            and_(
                HtmlStructuredContentArtifact.content_blob_id == current.c.html_blob_id,
                HtmlStructuredContentArtifact.extractor_version
                == STRUCTURED_CONTENT_EXTRACTOR_VERSION,
                HtmlStructuredContentArtifact.extractor_config_version
                == STRUCTURED_CONTENT_CONFIG_VERSION,
            ),
        )
    ).one()
    eligible, ready, partial, unavailable, prepared, oldest, newest = values
    return StructuredContentIntelligenceRead(
        extractor_version=STRUCTURED_CONTENT_EXTRACTOR_VERSION,
        extractor_config_version=STRUCTURED_CONTENT_CONFIG_VERSION,
        markdown_renderer_version=STRUCTURED_MARKDOWN_RENDERER_VERSION,
        active_pages=active_total,
        eligible_retained_html=eligible or 0,
        ready=ready or 0,
        partial=partial or 0,
        unavailable=unavailable or 0,
        not_prepared=max((eligible or 0) - (prepared or 0), 0),
        ineligible=max(active_total - (eligible or 0), 0),
        coverage=_coverage(prepared or 0, eligible or 0),
        clock=EvidenceClock(
            oldest_current_observation_at=oldest,
            newest_current_observation_at=newest,
            latest_observed_at=newest,
        ),
    )


def _render_state(db: Session, site_id: int, active_total: int) -> RenderIntelligenceRead:
    site_scan_ids = select(Scan.id).where(Scan.website_property_id == site_id)
    site_run_filter = or_(
        RenderRun.website_property_id == site_id,
        RenderRun.source_scan_id.in_(site_scan_ids),
    )
    run = db.scalar(
        select(RenderRun)
        .where(site_run_filter)
        .order_by(RenderRun.created_at.desc(), RenderRun.id.desc())
        .limit(1)
    )
    ranked = (
        select(
            RenderedObservation.id,
            RenderedObservation.web_resource_id,
            RenderedObservation.capture_state,
            RenderedObservation.navigation_http_status,
            RenderedObservation.error_type,
            RenderedObservation.finished_at,
            func.row_number()
            .over(
                partition_by=RenderedObservation.web_resource_id,
                order_by=(
                    func.coalesce(
                        RenderedObservation.finished_at, RenderedObservation.created_at
                    ).desc(),
                    RenderedObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .join(RenderRun, RenderRun.id == RenderedObservation.render_run_id)
        .where(
            site_run_filter,
            RenderedObservation.web_resource_id.in_(_active_pages(site_id)),
        )
        .subquery()
    )
    current = select(ranked).where(ranked.c.position == 1).subquery()
    status = current.c.navigation_http_status
    successful = (
        current.c.capture_state.in_(("completed", "completed_with_warnings"))
        & status.between(200, 299)
        & status.notin_((204, 205))
    )
    rate_limited = (status == 429) | (current.c.error_type == "navigation_rate_limited")
    values = db.execute(
        select(
            func.count(current.c.id),
            func.count(case((successful, 1))),
            func.count(case((rate_limited, 1))),
            func.count(case((status.between(300, 599) & ~rate_limited, 1))),
            func.count(case((~successful & ~rate_limited & ~status.between(300, 599), 1))),
            func.min(current.c.finished_at),
            func.max(current.c.finished_at),
        ).select_from(current)
    ).one()
    covered, success, limited, http_non_success, technical, oldest, newest = values
    return RenderIntelligenceRead(
        latest_run=RenderLatestRunRead(
            present=run is not None,
            id=run.id if run else None,
            status=run.status if run else None,
            target_count=run.target_count if run else 0,
            created_at=run.created_at if run else None,
            started_at=run.started_at if run else None,
            finished_at=run.finished_at if run else None,
        ),
        retained_coverage=_coverage(covered or 0, active_total),
        successful=success or 0,
        rate_limited=limited or 0,
        http_non_success=http_non_success or 0,
        technical_failure=technical or 0,
        clock=EvidenceClock(
            latest_observed_at=newest,
            latest_completed_at=run.finished_at if run else None,
            oldest_current_observation_at=oldest,
            newest_current_observation_at=newest,
            source_run_id=run.id if run else None,
            source_status=run.status if run else None,
        ),
    )


def _performance_state(db: Session, site_id: int, active_total: int) -> PerformanceIntelligenceRead:
    run = db.scalar(
        select(PerformanceRun)
        .where(PerformanceRun.website_property_id == site_id)
        .order_by(PerformanceRun.created_at.desc(), PerformanceRun.id.desc())
        .limit(1)
    )
    identity = (
        PerformanceObservation.provider,
        PerformanceObservation.dimension,
        PerformanceObservation.target_kind,
        PerformanceObservation.provider_adapter_version,
        PerformanceObservation.normalization_version,
    )
    ranked = (
        select(
            *identity,
            PerformanceObservation.web_resource_id,
            PerformanceObservation.outcome,
            PerformanceObservation.observed_at,
            func.row_number()
            .over(
                partition_by=(*identity, PerformanceObservation.web_resource_id),
                order_by=(
                    PerformanceObservation.observed_at.desc(),
                    PerformanceObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            PerformanceObservation.website_property_id == site_id,
            PerformanceObservation.target_kind == "url",
            PerformanceObservation.web_resource_id.in_(_active_pages(site_id)),
        )
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.provider,
            ranked.c.dimension,
            ranked.c.target_kind,
            ranked.c.provider_adapter_version,
            ranked.c.normalization_version,
            func.count(),
            func.count(case((ranked.c.outcome == "ready", 1))),
            func.count(case((ranked.c.outcome == "unavailable", 1))),
            func.count(case((ranked.c.outcome == "failed", 1))),
            func.min(ranked.c.observed_at),
            func.max(ranked.c.observed_at),
        )
        .where(ranked.c.position == 1)
        .group_by(
            *[
                ranked.c[name]
                for name in (
                    "provider",
                    "dimension",
                    "target_kind",
                    "provider_adapter_version",
                    "normalization_version",
                )
            ]
        )
        .order_by(ranked.c.provider, ranked.c.dimension)
    ).all()
    contexts = [
        PerformanceContextRead(
            provider=row[0],
            dimension=row[1],
            target_kind=row[2],
            provider_adapter_version=row[3],
            normalization_version=row[4],
            ready=row[6],
            unavailable=row[7],
            failed=row[8],
            coverage=_coverage(row[5], active_total),
            clock=EvidenceClock(
                latest_observed_at=row[10],
                oldest_current_observation_at=row[9],
                newest_current_observation_at=row[10],
            ),
        )
        for row in rows
    ]
    newest = max(
        (
            item.clock.newest_current_observation_at
            for item in contexts
            if item.clock.newest_current_observation_at
        ),
        default=None,
    )
    return PerformanceIntelligenceRead(
        contexts=contexts,
        latest_run_id=run.id if run else None,
        latest_run_status=run.status if run else None,
        clock=EvidenceClock(
            latest_observed_at=newest,
            latest_completed_at=run.finished_at if run else None,
            source_run_id=run.id if run else None,
            source_status=run.status if run else None,
        ),
    )


def _accessibility_state(
    db: Session, site_id: int, active_total: int
) -> AccessibilityIntelligenceRead:
    run = db.scalar(
        select(AccessibilityRun)
        .where(AccessibilityRun.website_property_id == site_id)
        .order_by(AccessibilityRun.created_at.desc(), AccessibilityRun.id.desc())
        .limit(1)
    )
    ranked = (
        select(
            AccessibilityObservation.web_resource_id,
            AccessibilityObservation.profile,
            AccessibilityObservation.outcome,
            AccessibilityObservation.violation_rule_count,
            AccessibilityObservation.violation_node_count,
            AccessibilityObservation.incomplete_rule_count,
            AccessibilityObservation.observed_at,
            func.row_number()
            .over(
                partition_by=(
                    AccessibilityObservation.web_resource_id,
                    AccessibilityObservation.profile,
                ),
                order_by=(
                    AccessibilityObservation.observed_at.desc(),
                    AccessibilityObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            AccessibilityObservation.website_property_id == site_id,
            AccessibilityObservation.web_resource_id.in_(_active_pages(site_id)),
        )
        .subquery()
    )
    current = select(ranked).where(ranked.c.position == 1).subquery()
    values = db.execute(
        select(
            func.count(func.distinct(current.c.web_resource_id)),
            func.count(
                func.distinct(case((current.c.outcome == "ready", current.c.web_resource_id)))
            ),
            func.count(
                func.distinct(case((current.c.outcome == "failed", current.c.web_resource_id)))
            ),
            func.count(
                func.distinct(case((current.c.violation_rule_count > 0, current.c.web_resource_id)))
            ),
            func.coalesce(func.sum(current.c.violation_rule_count), 0),
            func.coalesce(func.sum(current.c.violation_node_count), 0),
            func.coalesce(func.sum(current.c.incomplete_rule_count), 0),
            func.min(current.c.observed_at),
            func.max(current.c.observed_at),
        ).select_from(current)
    ).one()
    return AccessibilityIntelligenceRead(
        coverage=_coverage(values[0] or 0, active_total),
        ready_pages=values[1] or 0,
        failed_pages=values[2] or 0,
        pages_with_violations=values[3] or 0,
        violation_rules=values[4] or 0,
        affected_nodes=values[5] or 0,
        needs_review_rules=values[6] or 0,
        clock=EvidenceClock(
            latest_observed_at=values[8],
            latest_completed_at=run.finished_at if run else None,
            oldest_current_observation_at=values[7],
            newest_current_observation_at=values[8],
            source_run_id=run.id if run else None,
            source_status=run.status if run else None,
        ),
    )


def _sources_state(db: Session, site_id: int) -> SourcesIntelligenceRead:
    active, inactive = db.execute(
        select(
            func.count(case((UrlSource.is_active.is_(True), 1))),
            func.count(case((UrlSource.is_active.is_(False), 1))),
        ).where(UrlSource.website_property_id == site_id)
    ).one()
    latest_refresh = db.execute(
        select(SourceRefresh.status, SourceRefresh.finished_at)
        .join(UrlSource, UrlSource.id == SourceRefresh.url_source_id)
        .where(UrlSource.website_property_id == site_id)
        .order_by(
            func.coalesce(SourceRefresh.finished_at, SourceRefresh.started_at).desc(),
            SourceRefresh.id.desc(),
        )
        .limit(1)
    ).first()
    suppressed_match = exists(
        select(SiteInventorySuppression.id).where(
            SiteInventorySuppression.website_property_id == site_id,
            or_(
                and_(
                    SiteInventorySuppression.target_kind == "normalized_url",
                    SiteInventorySuppression.target_value == UrlSourceEntry.normalized_url,
                ),
                and_(
                    SiteInventorySuppression.target_kind == "raw_url",
                    SiteInventorySuppression.target_value == UrlSourceEntry.raw_url,
                ),
            ),
        )
    )
    inventory_identity = func.coalesce(UrlSourceEntry.normalized_url, UrlSourceEntry.raw_url)
    current, suppressed = db.execute(
        select(
            func.count(func.distinct(case((~suppressed_match, inventory_identity)))),
            func.count(func.distinct(case((suppressed_match, inventory_identity)))),
        )
        .select_from(UrlSourceEntry)
        .join(UrlSource, UrlSource.id == UrlSourceEntry.url_source_id)
        .where(UrlSource.website_property_id == site_id, UrlSourceEntry.is_current.is_(True))
    ).one()
    return SourcesIntelligenceRead(
        active_source_count=active or 0,
        inactive_source_count=inactive or 0,
        current_inventory_count=current or 0,
        suppressed_inventory_count=suppressed or 0,
        latest_refresh_status=latest_refresh[0] if latest_refresh else None,
        latest_refresh_finished_at=latest_refresh[1] if latest_refresh else None,
    )


def _activity_state(db: Session, site_id: int) -> ActivityIntelligenceRead:
    scan_ids = select(Scan.id).where(Scan.website_property_id == site_id)
    source_ids = select(UrlSource.id).where(UrlSource.website_property_id == site_id)
    refresh_ids = select(SourceRefresh.id).where(SourceRefresh.url_source_id.in_(source_ids))
    comparison_ids = select(ScanComparison.id).where(ScanComparison.website_property_id == site_id)
    performance_ids = select(PerformanceRun.id).where(PerformanceRun.website_property_id == site_id)
    accessibility_ids = select(AccessibilityRun.id).where(
        AccessibilityRun.website_property_id == site_id
    )
    render_ids = select(RenderRun.id).where(RenderRun.website_property_id == site_id)
    ownership = or_(
        BackgroundJob.website_property_id == site_id,
        BackgroundJob.scan_id.in_(scan_ids),
        BackgroundJob.source_refresh_id.in_(refresh_ids),
        BackgroundJob.scan_comparison_id.in_(comparison_ids),
        BackgroundJob.performance_run_id.in_(performance_ids),
        BackgroundJob.accessibility_run_id.in_(accessibility_ids),
        BackgroundJob.render_run_id.in_(render_ids),
    )
    active_filter = and_(BackgroundJob.status.in_(("queued", "running")), ownership)
    queued, running = db.execute(
        select(
            func.count(case((BackgroundJob.status == "queued", 1))),
            func.count(case((BackgroundJob.status == "running", 1))),
        ).where(active_filter)
    ).one()
    jobs = list(
        db.scalars(
            select(BackgroundJob)
            .where(active_filter)
            .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
            .limit(10)
        )
    )
    return ActivityIntelligenceRead(
        active_job_count=(queued or 0) + (running or 0),
        queued_count=queued or 0,
        running_count=running or 0,
        jobs=[ActiveJobRead.model_validate(job, from_attributes=True) for job in jobs],
    )
