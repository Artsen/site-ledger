from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    BackgroundJob,
    WebResource,
)
from app.schemas.accessibility import (
    AccessibilityNodeRead,
    AccessibilityObservationList,
    AccessibilityObservationRead,
    AccessibilityPageSummary,
    AccessibilityPageSummaryList,
    AccessibilityRuleAggregate,
    AccessibilityRuleAggregateList,
    AccessibilityRuleDetail,
    AccessibilityRuleOccurrence,
    AccessibilityRunDetail,
    AccessibilityRunList,
    AccessibilityRunRead,
    AccessibilitySummary,
)
from app.schemas.jobs import WorkerHealth
from app.services.background_jobs import presentation_status, worker_health


def list_accessibility_runs(
    db: Session, site_id: int, *, limit: int, offset: int
) -> AccessibilityRunList:
    base = select(AccessibilityRun).where(AccessibilityRun.website_property_id == site_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    runs = list(
        db.scalars(
            base.order_by(AccessibilityRun.created_at.desc(), AccessibilityRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    jobs = {
        job.accessibility_run_id: job
        for job in db.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.accessibility_run_id.in_([run.id for run in runs]))
            .order_by(BackgroundJob.id.desc())
        )
        if job.accessibility_run_id is not None
    }
    health = worker_health(db, get_settings().job_worker_offline_seconds)
    return AccessibilityRunList(
        items=[_run_read(run, jobs.get(run.id), health) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_accessibility_run(
    db: Session, site_id: int, run_id: int, *, limit: int, offset: int
) -> AccessibilityRunDetail | None:
    run = db.scalar(
        select(AccessibilityRun).where(
            AccessibilityRun.id == run_id, AccessibilityRun.website_property_id == site_id
        )
    )
    if run is None:
        return None
    observations = _observation_list(
        db,
        select(AccessibilityObservation).where(
            AccessibilityObservation.accessibility_run_id == run_id
        ),
        limit=limit,
        offset=offset,
    )
    job = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.accessibility_run_id == run_id)
        .order_by(BackgroundJob.id.desc())
        .limit(1)
    )
    health = worker_health(db, get_settings().job_worker_offline_seconds)
    return AccessibilityRunDetail(
        **_run_read(run, job, health).model_dump(), observations=observations
    )


def latest_accessibility(
    db: Session, site_id: int, *, limit: int, offset: int
) -> AccessibilityObservationList:
    latest_ids = _latest_ids(site_id)
    return _observation_list(
        db,
        select(AccessibilityObservation).where(AccessibilityObservation.id.in_(latest_ids)),
        limit=limit,
        offset=offset,
    )


def page_accessibility_history(
    db: Session, site_id: int, resource_id: int, *, limit: int, offset: int
) -> AccessibilityObservationList:
    return _observation_list(
        db,
        select(AccessibilityObservation).where(
            AccessibilityObservation.website_property_id == site_id,
            AccessibilityObservation.web_resource_id == resource_id,
        ),
        limit=limit,
        offset=offset,
    )


def page_latest_accessibility(
    db: Session, site_id: int, resource_id: int
) -> AccessibilityObservationList:
    ranked = (
        select(
            AccessibilityObservation.id.label("observation_id"),
            func.row_number()
            .over(
                partition_by=AccessibilityObservation.profile,
                order_by=(
                    AccessibilityObservation.observed_at.desc(),
                    AccessibilityObservation.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            AccessibilityObservation.website_property_id == site_id,
            AccessibilityObservation.web_resource_id == resource_id,
        )
        .subquery()
    )
    return _observation_list(
        db,
        select(AccessibilityObservation).where(
            AccessibilityObservation.id.in_(
                select(ranked.c.observation_id).where(ranked.c.position == 1)
            )
        ),
        limit=2,
        offset=0,
    )


def accessibility_summary(db: Session, site_id: int) -> AccessibilitySummary:
    latest = (
        select(AccessibilityObservation)
        .where(AccessibilityObservation.id.in_(_latest_ids(site_id)))
        .subquery()
    )
    values = db.execute(
        select(
            func.count(func.distinct(latest.c.web_resource_id)),
            func.count(func.distinct(latest.c.profile)),
            func.count(
                func.distinct(case((latest.c.violation_rule_count > 0, latest.c.web_resource_id)))
            ),
            func.coalesce(func.sum(latest.c.violation_rule_count), 0),
            func.coalesce(func.sum(latest.c.violation_node_count), 0),
            func.coalesce(func.sum(latest.c.incomplete_rule_count), 0),
            func.count(case((latest.c.outcome == "failed", 1))),
            func.max(latest.c.observed_at),
        )
    ).one()
    impact_rows = db.execute(
        select(AccessibilityRuleEvidence.impact, func.count())
        .join(
            AccessibilityObservation,
            AccessibilityObservation.id == AccessibilityRuleEvidence.accessibility_observation_id,
        )
        .where(
            AccessibilityObservation.id.in_(_latest_ids(site_id)),
            AccessibilityObservation.outcome == "ready",
            AccessibilityRuleEvidence.result_type == "violation",
        )
        .group_by(AccessibilityRuleEvidence.impact)
    ).all()
    return AccessibilitySummary(
        pages_audited=values[0],
        profiles_audited=values[1],
        pages_with_violations=values[2],
        violation_rules=values[3],
        affected_nodes=values[4],
        needs_review_rules=values[5],
        failed_latest=values[6],
        latest_observed_at=values[7],
        impact_counts={(impact or "unknown"): count for impact, count in impact_rows},
    )


def accessibility_pages(
    db: Session,
    site_id: int,
    *,
    search: str | None,
    outcome: str | None,
    impact: str | None,
    has_violations: bool | None,
    needs_review: bool | None,
    sort: str,
    direction: str,
    limit: int,
    offset: int,
) -> AccessibilityPageSummaryList:
    latest = (
        select(AccessibilityObservation)
        .where(AccessibilityObservation.id.in_(_latest_ids(site_id)))
        .subquery()
    )
    grouped = (
        select(
            latest.c.web_resource_id.label("page_id"),
            WebResource.normalized_url.label("page_url"),
            func.max(latest.c.observed_at).label("last_audited_at"),
            func.max(case((latest.c.profile == "desktop", latest.c.outcome), else_=None)).label(
                "desktop_outcome"
            ),
            func.max(case((latest.c.profile == "mobile", latest.c.outcome), else_=None)).label(
                "mobile_outcome"
            ),
            func.max(
                case((latest.c.profile == "desktop", latest.c.violation_rule_count), else_=0)
            ).label("desktop_violations"),
            func.max(
                case((latest.c.profile == "mobile", latest.c.violation_rule_count), else_=0)
            ).label("mobile_violations"),
            func.count(
                func.distinct(
                    case(
                        (
                            (AccessibilityRuleEvidence.result_type == "violation")
                            & (AccessibilityRuleEvidence.impact == "critical"),
                            AccessibilityRuleEvidence.id,
                        )
                    )
                )
            ).label("critical_rules"),
            func.count(
                func.distinct(
                    case(
                        (
                            (AccessibilityRuleEvidence.result_type == "violation")
                            & (AccessibilityRuleEvidence.impact == "serious"),
                            AccessibilityRuleEvidence.id,
                        )
                    )
                )
            ).label("serious_rules"),
            func.count(
                func.distinct(
                    case(
                        (
                            AccessibilityRuleEvidence.result_type == "incomplete",
                            AccessibilityRuleEvidence.id,
                        )
                    )
                )
            ).label("needs_review_rules"),
        )
        .join(WebResource, WebResource.id == latest.c.web_resource_id)
        .outerjoin(
            AccessibilityRuleEvidence,
            AccessibilityRuleEvidence.accessibility_observation_id == latest.c.id,
        )
        .group_by(latest.c.web_resource_id, WebResource.normalized_url)
    )
    if search:
        grouped = grouped.where(WebResource.normalized_url.ilike(f"%{search.strip()}%"))
    rows = grouped.subquery()
    filters: list[ColumnElement[bool]] = []
    if outcome:
        filters.append((rows.c.desktop_outcome == outcome) | (rows.c.mobile_outcome == outcome))
    if impact == "critical":
        filters.append(rows.c.critical_rules > 0)
    elif impact == "serious":
        filters.append(rows.c.serious_rules > 0)
    if has_violations is True:
        filters.append((rows.c.desktop_violations > 0) | (rows.c.mobile_violations > 0))
    elif has_violations is False:
        filters.append((rows.c.desktop_violations == 0) & (rows.c.mobile_violations == 0))
    if needs_review is True:
        filters.append(rows.c.needs_review_rules > 0)
    elif needs_review is False:
        filters.append(rows.c.needs_review_rules == 0)
    selected = select(rows).where(*filters)
    total = db.scalar(select(func.count()).select_from(selected.subquery())) or 0
    sort_columns = {
        "page": rows.c.page_url,
        "audited": rows.c.last_audited_at,
        "desktop": rows.c.desktop_violations,
        "mobile": rows.c.mobile_violations,
        "critical": rows.c.critical_rules,
        "serious": rows.c.serious_rules,
        "needs_review": rows.c.needs_review_rules,
    }
    sort_column = sort_columns.get(sort, rows.c.last_audited_at)
    order = sort_column.asc() if direction == "asc" else sort_column.desc()
    result = db.execute(selected.order_by(order, rows.c.page_id).limit(limit).offset(offset)).all()
    return AccessibilityPageSummaryList(
        items=[AccessibilityPageSummary(**row._mapping) for row in result],
        total=total,
        limit=limit,
        offset=offset,
    )


def accessibility_rules(
    db: Session,
    site_id: int,
    *,
    result_type: str | None,
    impact: str | None,
    profile: str | None,
    limit: int,
    offset: int,
) -> AccessibilityRuleAggregateList:
    filters = [
        AccessibilityObservation.id.in_(_latest_ids(site_id)),
        AccessibilityObservation.outcome == "ready",
    ]
    if result_type:
        filters.append(AccessibilityRuleEvidence.result_type == result_type)
    if impact:
        filters.append(AccessibilityRuleEvidence.impact == impact)
    if profile:
        filters.append(AccessibilityObservation.profile == profile)
    grouped = (
        select(
            AccessibilityRuleEvidence.rule_id,
            AccessibilityRuleEvidence.result_type,
            AccessibilityRuleEvidence.impact,
            func.max(AccessibilityRuleEvidence.help).label("help"),
            func.max(AccessibilityRuleEvidence.help_url).label("help_url"),
            func.max(AccessibilityRuleEvidence.tags_json).label("tags"),
            func.count(func.distinct(AccessibilityObservation.web_resource_id)).label("pages"),
            func.sum(AccessibilityRuleEvidence.node_count).label("nodes"),
            func.max(case((AccessibilityObservation.profile == "desktop", 1), else_=0)).label(
                "desktop"
            ),
            func.max(case((AccessibilityObservation.profile == "mobile", 1), else_=0)).label(
                "mobile"
            ),
        )
        .join(
            AccessibilityObservation,
            AccessibilityObservation.id == AccessibilityRuleEvidence.accessibility_observation_id,
        )
        .where(*filters)
        .group_by(
            AccessibilityRuleEvidence.rule_id,
            AccessibilityRuleEvidence.result_type,
            AccessibilityRuleEvidence.impact,
        )
        .subquery()
    )
    total = db.scalar(select(func.count()).select_from(grouped)) or 0
    rows = db.execute(
        select(grouped)
        .order_by(grouped.c.pages.desc(), grouped.c.nodes.desc(), grouped.c.rule_id)
        .limit(limit)
        .offset(offset)
    ).all()
    return AccessibilityRuleAggregateList(
        items=[
            AccessibilityRuleAggregate(
                rule_id=row.rule_id,
                result_type=row.result_type,
                impact=row.impact,
                help=row.help,
                help_url=row.help_url,
                tags=json_tags(row.tags),
                pages_affected=row.pages,
                affected_nodes=row.nodes,
                profiles=[
                    name
                    for name, present in (("desktop", row.desktop), ("mobile", row.mobile))
                    if present
                ],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def accessibility_rule_detail(
    db: Session, site_id: int, rule_id: str, *, result_type: str, limit: int, offset: int
) -> AccessibilityRuleDetail | None:
    base = (
        select(
            AccessibilityNodeEvidence,
            AccessibilityRuleEvidence,
            AccessibilityObservation,
            WebResource,
        )
        .join(
            AccessibilityRuleEvidence,
            AccessibilityRuleEvidence.id
            == AccessibilityNodeEvidence.accessibility_rule_evidence_id,
        )
        .join(
            AccessibilityObservation,
            AccessibilityObservation.id == AccessibilityRuleEvidence.accessibility_observation_id,
        )
        .join(WebResource, WebResource.id == AccessibilityObservation.web_resource_id)
        .where(
            AccessibilityObservation.id.in_(_latest_ids(site_id)),
            AccessibilityObservation.outcome == "ready",
            AccessibilityRuleEvidence.rule_id == rule_id,
            AccessibilityRuleEvidence.result_type == result_type,
        )
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(AccessibilityObservation.observed_at.desc(), AccessibilityNodeEvidence.id)
        .limit(limit)
        .offset(offset)
    ).all()
    if not rows:
        return None
    first_rule = rows[0][1]
    pages = (
        db.scalar(
            select(func.count(func.distinct(AccessibilityObservation.web_resource_id)))
            .join(
                AccessibilityRuleEvidence,
                AccessibilityRuleEvidence.accessibility_observation_id
                == AccessibilityObservation.id,
            )
            .where(
                AccessibilityObservation.id.in_(_latest_ids(site_id)),
                AccessibilityRuleEvidence.rule_id == rule_id,
                AccessibilityRuleEvidence.result_type == result_type,
            )
        )
        or 0
    )
    return AccessibilityRuleDetail(
        rule_id=first_rule.rule_id,
        help=first_rule.help,
        description=first_rule.description,
        help_url=first_rule.help_url,
        tags=first_rule.tags_json,
        impact=first_rule.impact,
        pages_affected=pages,
        affected_nodes=total,
        total=total,
        limit=limit,
        offset=offset,
        occurrences=[
            AccessibilityRuleOccurrence(
                observation_id=observation.id,
                page_id=resource.id,
                page_url=resource.normalized_url,
                profile=observation.profile,
                observed_at=observation.observed_at,
                result_type=rule.result_type,
                impact=rule.impact,
                node=AccessibilityNodeRead.model_validate(node, from_attributes=True),
            )
            for node, rule, observation, resource in rows
        ],
    )


def observation_read(observation: AccessibilityObservation) -> AccessibilityObservationRead:
    return AccessibilityObservationRead(
        **{
            column.name: getattr(observation, column.name)
            for column in observation.__table__.columns
            if column.name != "payload_blob_id"
        },
        page_url=observation.web_resource.normalized_url,
        payload_sha256=observation.payload_blob.sha256 if observation.payload_blob else None,
        payload_raw_byte_size=observation.payload_blob.raw_byte_size
        if observation.payload_blob
        else None,
        payload_stored_byte_size=observation.payload_blob.stored_byte_size
        if observation.payload_blob
        else None,
    )


def _latest_ids(site_id: int) -> Select[tuple[int]]:
    ranked = (
        select(
            AccessibilityObservation.id.label("observation_id"),
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
        .where(AccessibilityObservation.website_property_id == site_id)
        .subquery()
    )
    return select(ranked.c.observation_id).where(ranked.c.position == 1)


def _observation_list(
    db: Session,
    base: Select[tuple[AccessibilityObservation]],
    *,
    limit: int,
    offset: int,
) -> AccessibilityObservationList:
    statement = base.options(
        selectinload(AccessibilityObservation.web_resource),
        selectinload(AccessibilityObservation.payload_blob),
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    observations = list(
        db.scalars(
            statement.order_by(
                AccessibilityObservation.observed_at.desc(), AccessibilityObservation.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return AccessibilityObservationList(
        items=[observation_read(item) for item in observations],
        total=total,
        limit=limit,
        offset=offset,
    )


def _run_read(
    run: AccessibilityRun, job: BackgroundJob | None, health: WorkerHealth
) -> AccessibilityRunRead:
    return AccessibilityRunRead(
        **{column.name: getattr(run, column.name) for column in run.__table__.columns},
        job_id=job.id if job else None,
        presentation_status=presentation_status(job, health) if job else run.status,
    )


def json_tags(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
