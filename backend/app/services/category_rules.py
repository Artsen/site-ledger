from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BackgroundJob,
    PageCategory,
    PageCategoryAssignment,
    PageCategoryAssignmentSupport,
    PageCategoryAutomaticExclusion,
    PageCategoryRule,
    PageCategoryRuleCondition,
    PageCategoryRuleRevision,
    PageCategoryRuleRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.category_rules import (
    AutomaticExclusionPayload,
    CategoryProvenanceList,
    CategoryProvenanceRead,
    CategoryProvenanceRule,
    CategoryRuleConditionPayload,
    CategoryRuleCreate,
    CategoryRuleDeletePreview,
    CategoryRuleList,
    CategoryRulePreview,
    CategoryRulePreviewPage,
    CategoryRulePreviewRequest,
    CategoryRuleRead,
    CategoryRuleRunList,
    CategoryRuleRunRead,
    CategoryRuleUpdate,
)
from app.services import background_jobs
from app.services.category_rule_evaluator import (
    EVALUATOR_VERSION,
    CompiledCondition,
    compile_conditions,
    resource_matches,
)
from app.services.job_types import ACTIVE_JOB_STATUSES, JOB_TYPE_CATEGORY_RULE_EVALUATION

PAGE_BATCH_SIZE = 500
MAX_ACTIVE_RULES = 2_000


def list_rules(
    db: Session,
    site_id: int,
    *,
    search: str | None = None,
    category_id: int | None = None,
    active_state: Literal["active", "disabled", "all"] = "all",
    sort: Literal[
        "active",
        "name",
        "category",
        "mode",
        "condition_count",
        "match_count",
        "excluded_count",
        "updated_at",
        "last_evaluated_at",
    ] = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> CategoryRuleList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    query = (
        select(PageCategoryRule, PageCategory.name)
        .join(PageCategory, PageCategory.id == PageCategoryRule.category_id)
        .where(PageCategoryRule.website_property_id == site_id)
    )
    if search:
        query = query.where(PageCategoryRule.name.ilike(f"%{search}%"))
    if category_id is not None:
        query = query.where(PageCategoryRule.category_id == category_id)
    if active_state != "all":
        query = query.where(PageCategoryRule.is_active.is_(active_state == "active"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    condition_count = (
        select(func.count(PageCategoryRuleCondition.id))
        .where(PageCategoryRuleCondition.rule_id == PageCategoryRule.id)
        .correlate(PageCategoryRule)
        .scalar_subquery()
    )
    sort_column = {
        "active": PageCategoryRule.is_active,
        "name": PageCategoryRule.name,
        "category": PageCategory.name,
        "mode": PageCategoryRule.match_mode,
        "condition_count": condition_count,
        "updated_at": PageCategoryRule.updated_at,
        "last_evaluated_at": PageCategoryRule.last_evaluated_at,
        "match_count": PageCategoryRule.current_match_count,
        "excluded_count": PageCategoryRule.current_excluded_count,
    }[sort]
    order = sort_column.desc() if direction == "desc" else sort_column.asc()
    ids = [
        row[0]
        for row in db.execute(
            query.with_only_columns(PageCategoryRule.id)
            .order_by(order, PageCategoryRule.id)
            .limit(limit)
            .offset(offset)
        )
    ]
    rules = _rules_by_ids(db, ids)
    category_names: dict[int, str] = {
        category_id: name
        for category_id, name in db.execute(
            select(PageCategory.id, PageCategory.name).where(
                PageCategory.website_property_id == site_id
            )
        )
    }
    return CategoryRuleList(
        items=[
            _read_rule(rules[rule_id], category_names[rules[rule_id].category_id])
            for rule_id in ids
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_rule(db: Session, site_id: int, rule_id: int) -> CategoryRuleRead | None:
    rule = _rule(db, site_id, rule_id)
    if rule is None:
        return None
    category = db.get(PageCategory, rule.category_id)
    return _read_rule(rule, category.name if category else "Deleted category")


def preview_rule(
    db: Session, site_id: int, payload: CategoryRulePreviewRequest
) -> CategoryRulePreview | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    _require_category(db, site_id, payload.category_id)
    if payload.rule_id is not None and _rule(db, site_id, payload.rule_id) is None:
        raise ValueError("Rule not found.")
    started = time.perf_counter()
    compiled = compile_conditions(payload.conditions)
    exclusions = set(
        db.scalars(
            select(PageCategoryAutomaticExclusion.site_page_id).where(
                PageCategoryAutomaticExclusion.category_id == payload.category_id,
                PageCategoryAutomaticExclusion.site_page_id.in_(
                    select(SitePage.id).where(
                        SitePage.website_property_id == site_id,
                        SitePage.workspace_state == "active",
                    )
                ),
            )
        )
    )
    matching: set[int] = set()
    excluded: set[int] = set()
    matching_samples: list[CategoryRulePreviewPage] = []
    nonmatching_samples: list[CategoryRulePreviewPage] = []
    total = 0
    rows = db.execute(
        select(SitePage.id, WebResource)
        .join(WebResource, WebResource.id == SitePage.resource_id)
        .where(
            SitePage.website_property_id == site_id,
            SitePage.workspace_state == "active",
        )
        .order_by(SitePage.id)
    ).yield_per(PAGE_BATCH_SIZE)
    for page_id, resource in rows:
        total += 1
        if resource_matches(resource, compiled, payload.match_mode):
            matching.add(page_id)
            if page_id in exclusions:
                excluded.add(page_id)
            if len(matching_samples) < 10:
                matching_samples.append(
                    CategoryRulePreviewPage(
                        resource_id=resource.id, normalized_url=resource.normalized_url
                    )
                )
        elif len(nonmatching_samples) < 5:
            nonmatching_samples.append(
                CategoryRulePreviewPage(
                    resource_id=resource.id, normalized_url=resource.normalized_url
                )
            )
    currently_assigned = set(
        db.scalars(
            select(PageCategoryAssignment.site_page_id)
            .join(SitePage, SitePage.id == PageCategoryAssignment.site_page_id)
            .where(
                SitePage.website_property_id == site_id,
                SitePage.workspace_state == "active",
                PageCategoryAssignment.category_id == payload.category_id,
            )
        )
    )
    existing_rule_support: set[int] = set()
    if payload.rule_id is not None:
        existing_rule_support = set(
            db.scalars(
                select(PageCategoryAssignment.site_page_id)
                .join(
                    PageCategoryAssignmentSupport,
                    PageCategoryAssignmentSupport.page_category_assignment_id
                    == PageCategoryAssignment.id,
                )
                .join(SitePage, SitePage.id == PageCategoryAssignment.site_page_id)
                .where(
                    PageCategoryAssignmentSupport.rule_id == payload.rule_id,
                    SitePage.workspace_state == "active",
                )
            )
        )
    desired = matching - excluded
    return CategoryRulePreview(
        total_pages_evaluated=total,
        matching_pages=len(matching),
        currently_assigned=len(currently_assigned),
        would_gain_automatic_support=len(desired - existing_rule_support),
        would_lose_automatic_support=len(existing_rule_support - desired),
        excluded_matches=len(excluded),
        sample_matching_pages=matching_samples,
        sample_non_matching_pages=nonmatching_samples,
        evaluation_duration_ms=round((time.perf_counter() - started) * 1000),
    )


def create_rule(db: Session, site_id: int, payload: CategoryRuleCreate) -> CategoryRuleRead | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    category = _require_category(db, site_id, payload.category_id)
    if not category.is_active:
        raise ValueError("Archived categories cannot receive automatic assignments.")
    if payload.is_active:
        _enforce_active_limit(db, site_id)
    rule = PageCategoryRule(
        website_property_id=site_id,
        category_id=payload.category_id,
        name=payload.name,
        description=payload.description,
        match_mode=payload.match_mode,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
    )
    db.add(rule)
    db.flush()
    _replace_conditions(db, rule, payload.conditions)
    _record_revision(db, rule, "created")
    queue_evaluation(db, site_id, "rule_created", rule.id)
    db.commit()
    return _read_rule(_rule(db, site_id, rule.id), category.name)  # type: ignore[arg-type]


def update_rule(
    db: Session, site_id: int, rule_id: int, payload: CategoryRuleUpdate
) -> CategoryRuleRead | None:
    rule = _rule(db, site_id, rule_id)
    if rule is None:
        return None
    old_active = rule.is_active
    if payload.category_id is not None:
        category = _require_category(db, site_id, payload.category_id)
        if rule.is_active and not category.is_active:
            raise ValueError("Archived categories cannot receive automatic assignments.")
        rule.category_id = payload.category_id
    for field in ("name", "description", "match_mode", "is_active", "sort_order"):
        if field in payload.model_fields_set and getattr(payload, field) is not None:
            setattr(rule, field, getattr(payload, field))
    category = _require_category(db, site_id, rule.category_id)
    if rule.is_active and not category.is_active:
        raise ValueError("Archived categories cannot receive automatic assignments.")
    if rule.is_active and not old_active:
        _enforce_active_limit(db, site_id)
    if payload.conditions is not None:
        _replace_conditions(db, rule, payload.conditions)
    rule.current_revision_number += 1
    action = (
        "enabled"
        if rule.is_active and not old_active
        else "disabled"
        if old_active and not rule.is_active
        else "updated"
    )
    _record_revision(db, rule, action)
    queue_evaluation(db, site_id, f"rule_{action}", rule.id)
    db.commit()
    return _read_rule(_rule(db, site_id, rule.id), category.name)  # type: ignore[arg-type]


def preview_rule_deletion(
    db: Session, site_id: int, rule_id: int
) -> CategoryRuleDeletePreview | None:
    read = get_rule(db, site_id, rule_id)
    if read is None:
        return None
    assignments = list(
        db.scalars(
            select(PageCategoryAssignment)
            .join(
                PageCategoryAssignmentSupport,
                PageCategoryAssignmentSupport.page_category_assignment_id
                == PageCategoryAssignment.id,
            )
            .where(PageCategoryAssignmentSupport.rule_id == rule_id)
        )
    )
    assignment_ids = [item.id for item in assignments]
    retained = 0
    if assignment_ids:
        retained = (
            db.scalar(
                select(
                    func.count(
                        func.distinct(PageCategoryAssignmentSupport.page_category_assignment_id)
                    )
                ).where(
                    PageCategoryAssignmentSupport.page_category_assignment_id.in_(assignment_ids),
                    PageCategoryAssignmentSupport.rule_id != rule_id,
                )
            )
            or 0
        )
    return CategoryRuleDeletePreview(
        rule=read,
        rule_support_count=len(assignments),
        effective_assignments_removed=len(assignments) - retained,
        effective_assignments_retained=retained,
    )


def delete_rule(db: Session, site_id: int, rule_id: int) -> int | None:
    rule = _rule(db, site_id, rule_id)
    if rule is None:
        return None
    rule.current_revision_number += 1
    _record_revision(db, rule, "deleted")
    db.flush()
    db.delete(rule)
    db.flush()
    queue_evaluation(db, site_id, "rule_deleted", rule_id)
    db.commit()
    return rule_id


def disable_rules_for_category(db: Session, site_id: int, category_id: int) -> int:
    rules = list(
        db.scalars(
            select(PageCategoryRule)
            .options(selectinload(PageCategoryRule.conditions))
            .where(
                PageCategoryRule.website_property_id == site_id,
                PageCategoryRule.category_id == category_id,
                PageCategoryRule.is_active.is_(True),
            )
        )
    )
    for rule in rules:
        rule.is_active = False
        rule.current_revision_number += 1
        _record_revision(db, rule, "disabled")
    if rules:
        queue_evaluation(db, site_id, "category_archived")
    return len(rules)


def queue_evaluation(
    db: Session, site_id: int, trigger_type: str, trigger_rule_id: int | None = None
) -> PageCategoryRuleRun:
    active_job = db.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.job_type == JOB_TYPE_CATEGORY_RULE_EVALUATION,
            BackgroundJob.website_property_id == site_id,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(BackgroundJob.id.desc())
    )
    if active_job is not None:
        payload = dict(active_job.payload_json)
        payload["rerun_requested"] = active_job.status == "running"
        payload["latest_trigger_type"] = trigger_type
        payload["latest_trigger_rule_id"] = trigger_rule_id
        active_job.payload_json = payload
        run_id = int(payload["run_id"])
        run = db.get(PageCategoryRuleRun, run_id)
        if run is None:
            raise RuntimeError("Active Category Rule job has no run record.")
        return run
    return _create_evaluation_run(db, site_id, trigger_type, trigger_rule_id)


def create_followup_evaluation(
    db: Session, site_id: int, trigger_type: str, trigger_rule_id: int | None = None
) -> PageCategoryRuleRun:
    """Queue the requested rerun while the finishing job still holds its lease."""
    return _create_evaluation_run(db, site_id, trigger_type, trigger_rule_id)


def _create_evaluation_run(
    db: Session, site_id: int, trigger_type: str, trigger_rule_id: int | None
) -> PageCategoryRuleRun:
    run = PageCategoryRuleRun(
        website_property_id=site_id,
        trigger_type=trigger_type,
        trigger_rule_id=trigger_rule_id,
        status="queued",
        configuration_json={},
        evaluator_version=EVALUATOR_VERSION,
    )
    db.add(run)
    db.flush()
    background_jobs.enqueue_category_rule_job(db, run.id, site_id)
    return run


def reconcile_site(
    db: Session,
    run_id: int,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> PageCategoryRuleRun:
    run = db.get(PageCategoryRuleRun, run_id)
    if run is None:
        raise ValueError("Category Rule run not found.")
    run.status = "running"
    run.started_at = datetime.now(UTC)
    rules = list(
        db.scalars(
            select(PageCategoryRule)
            .join(PageCategory, PageCategory.id == PageCategoryRule.category_id)
            .options(selectinload(PageCategoryRule.conditions))
            .where(
                PageCategoryRule.website_property_id == run.website_property_id,
                PageCategoryRule.is_active.is_(True),
                PageCategory.is_active.is_(True),
            )
            .order_by(PageCategoryRule.id)
        )
    )
    compiled = {
        rule.id: compile_conditions([_condition_payload(c) for c in rule.conditions])
        for rule in rules
    }
    run.rule_count = len(rules)
    run.condition_count = sum(len(rule.conditions) for rule in rules)
    run.configuration_json = {
        "rules": [{"id": rule.id, "revision": rule.current_revision_number} for rule in rules],
        "page_batch_size": PAGE_BATCH_SIZE,
    }
    total_pages = (
        db.scalar(
            select(func.count(SitePage.id)).where(
                SitePage.website_property_id == run.website_property_id,
                SitePage.workspace_state == "active",
            )
        )
        or 0
    )
    run.page_count = total_pages
    db.commit()
    counters: defaultdict[str, int] = defaultdict(int)
    rule_matches: defaultdict[int, int] = defaultdict(int)
    rule_excluded: defaultdict[int, int] = defaultdict(int)
    for offset in range(0, total_pages, PAGE_BATCH_SIZE):
        if should_cancel and should_cancel():
            run = db.get(PageCategoryRuleRun, run_id)
            if run:
                run.status = "cancelled"
                run.finished_at = datetime.now(UTC)
                db.commit()
            return run  # type: ignore[return-value]
        pages = [
            (page_id, resource)
            for page_id, resource in db.execute(
                select(SitePage.id, WebResource)
                .join(WebResource, WebResource.id == SitePage.resource_id)
                .where(
                    SitePage.website_property_id == run.website_property_id,
                    SitePage.workspace_state == "active",
                )
                .order_by(SitePage.id)
                .limit(PAGE_BATCH_SIZE)
                .offset(offset)
            )
        ]
        _reconcile_batch(db, rules, compiled, pages, counters, rule_matches, rule_excluded)
        db.commit()
        if progress:
            progress(min(offset + len(pages), total_pages), total_pages)
    if should_cancel and should_cancel():
        run = db.get(PageCategoryRuleRun, run_id)
        if run:
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            db.commit()
        return run  # type: ignore[return-value]
    now = datetime.now(UTC)
    for rule in rules:
        rule.current_match_count = rule_matches[rule.id]
        rule.current_excluded_count = rule_excluded[rule.id]
        rule.last_evaluated_at = now
    run = db.get(PageCategoryRuleRun, run_id)
    if run is None:
        raise RuntimeError("Category Rule run disappeared.")
    run.status = "completed"
    run.finished_at = now
    for field in (
        "match_count",
        "rule_supports_added",
        "rule_supports_removed",
        "effective_assignments_added",
        "effective_assignments_removed",
        "exclusions_suppressing_matches",
        "unchanged_count",
    ):
        setattr(run, field, counters[field])
    db.commit()
    return run


def _reconcile_batch(
    db: Session,
    rules: list[PageCategoryRule],
    compiled: dict[int, list[CompiledCondition]],
    pages: Sequence[tuple[int, WebResource]],
    counters: defaultdict[str, int],
    rule_matches: defaultdict[int, int],
    rule_excluded: defaultdict[int, int],
) -> None:
    page_ids = [page_id for page_id, _ in pages]
    exclusions = set(
        db.execute(
            select(
                PageCategoryAutomaticExclusion.site_page_id,
                PageCategoryAutomaticExclusion.category_id,
            ).where(PageCategoryAutomaticExclusion.site_page_id.in_(page_ids))
        ).all()
    )
    desired: set[tuple[int, int, int]] = set()
    for page_id, resource in pages:
        for rule in rules:
            if resource_matches(resource, compiled[rule.id], rule.match_mode):
                rule_matches[rule.id] += 1
                counters["match_count"] += 1
                if (page_id, rule.category_id) in exclusions:
                    rule_excluded[rule.id] += 1
                    counters["exclusions_suppressing_matches"] += 1
                else:
                    desired.add((page_id, rule.category_id, rule.id))
    assignments = list(
        db.scalars(
            select(PageCategoryAssignment).where(PageCategoryAssignment.site_page_id.in_(page_ids))
        )
    )
    assignment_map = {(a.site_page_id, a.category_id): a for a in assignments}
    missing_assignments = sorted(
        {(page_id, category_id) for page_id, category_id, _ in desired} - set(assignment_map)
    )
    if missing_assignments:
        db.execute(
            insert(PageCategoryAssignment),
            [
                {"site_page_id": page_id, "category_id": category_id}
                for page_id, category_id in missing_assignments
            ],
        )
        counters["effective_assignments_added"] += len(missing_assignments)
        assignments = list(
            db.scalars(
                select(PageCategoryAssignment).where(
                    PageCategoryAssignment.site_page_id.in_(page_ids)
                )
            )
        )
        assignment_map = {(a.site_page_id, a.category_id): a for a in assignments}
    assignment_ids = [a.id for a in assignment_map.values()]
    assignment_key_by_id = {assignment.id: key for key, assignment in assignment_map.items()}
    supports = (
        list(
            db.scalars(
                select(PageCategoryAssignmentSupport).where(
                    PageCategoryAssignmentSupport.page_category_assignment_id.in_(assignment_ids)
                )
            )
        )
        if assignment_ids
        else []
    )
    existing_rule = {
        (*assignment_key_by_id[s.page_category_assignment_id], s.rule_id): s
        for s in supports
        if s.support_type == "rule" and s.rule_id is not None
    }
    stale = [support.id for key, support in existing_rule.items() if key not in desired]
    if stale:
        db.execute(
            delete(PageCategoryAssignmentSupport).where(PageCategoryAssignmentSupport.id.in_(stale))
        )
        counters["rule_supports_removed"] += len(stale)
    missing_supports = sorted(desired - set(existing_rule))
    if missing_supports:
        db.execute(
            insert(PageCategoryAssignmentSupport),
            [
                {
                    "page_category_assignment_id": assignment_map[(page_id, category_id)].id,
                    "support_type": "rule",
                    "rule_id": rule_id,
                    "support_key": f"rule:{rule_id}",
                }
                for page_id, category_id, rule_id in missing_supports
            ],
        )
        counters["rule_supports_added"] += len(missing_supports)
    counters["unchanged_count"] += len(desired & set(existing_rule))
    db.flush()
    unsupported_ids = list(
        db.scalars(
            select(PageCategoryAssignment.id).where(
                PageCategoryAssignment.site_page_id.in_(page_ids),
                ~select(PageCategoryAssignmentSupport.id)
                .where(
                    PageCategoryAssignmentSupport.page_category_assignment_id
                    == PageCategoryAssignment.id
                )
                .exists(),
            )
        )
    )
    if unsupported_ids:
        db.execute(
            delete(PageCategoryAssignment).where(PageCategoryAssignment.id.in_(unsupported_ids))
        )
        counters["effective_assignments_removed"] += len(unsupported_ids)


def list_runs(
    db: Session,
    site_id: int,
    *,
    status: str | None = None,
    trigger: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal[
        "trigger",
        "created_at",
        "started_at",
        "finished_at",
        "status",
        "page_count",
        "rule_count",
        "match_count",
        "supports_delta",
        "assignments_delta",
        "excluded_count",
        "evaluator",
    ] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> CategoryRuleRunList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    query = select(PageCategoryRuleRun).where(PageCategoryRuleRun.website_property_id == site_id)
    if status:
        query = query.where(PageCategoryRuleRun.status == status)
    if trigger:
        query = query.where(PageCategoryRuleRun.trigger_type == trigger)
    if date_from:
        query = query.where(PageCategoryRuleRun.created_at >= date_from)
    if date_to:
        query = query.where(PageCategoryRuleRun.created_at <= date_to)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_column = {
        "trigger": PageCategoryRuleRun.trigger_type,
        "created_at": PageCategoryRuleRun.created_at,
        "started_at": PageCategoryRuleRun.started_at,
        "finished_at": PageCategoryRuleRun.finished_at,
        "status": PageCategoryRuleRun.status,
        "page_count": PageCategoryRuleRun.page_count,
        "rule_count": PageCategoryRuleRun.rule_count,
        "match_count": PageCategoryRuleRun.match_count,
        "supports_delta": PageCategoryRuleRun.rule_supports_added
        - PageCategoryRuleRun.rule_supports_removed,
        "assignments_delta": PageCategoryRuleRun.effective_assignments_added
        - PageCategoryRuleRun.effective_assignments_removed,
        "excluded_count": PageCategoryRuleRun.exclusions_suppressing_matches,
        "evaluator": PageCategoryRuleRun.evaluator_version,
    }[sort]
    order = sort_column.desc() if direction == "desc" else sort_column.asc()
    id_order = (
        PageCategoryRuleRun.id.desc() if direction == "desc" else PageCategoryRuleRun.id.asc()
    )
    items = list(db.scalars(query.order_by(order, id_order).limit(limit).offset(offset)))
    return CategoryRuleRunList(
        items=[CategoryRuleRunRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def category_provenance(
    db: Session, site_id: int, resource_id: int
) -> CategoryProvenanceList | None:
    from app.services.site_pages import find_site_page

    page = find_site_page(db, site_id, resource_id)
    if page is None:
        return None
    resource = db.get(WebResource, page.resource_id)
    assignments = list(
        db.scalars(
            select(PageCategoryAssignment).where(PageCategoryAssignment.site_page_id == page.id)
        )
    )
    assignment_ids = [a.id for a in assignments]
    supports = (
        list(
            db.scalars(
                select(PageCategoryAssignmentSupport).where(
                    PageCategoryAssignmentSupport.page_category_assignment_id.in_(assignment_ids)
                )
            )
        )
        if assignment_ids
        else []
    )
    support_by_assignment: defaultdict[int, list[PageCategoryAssignmentSupport]] = defaultdict(list)
    for support in supports:
        support_by_assignment[support.page_category_assignment_id].append(support)
    exclusions = set(
        db.scalars(
            select(PageCategoryAutomaticExclusion.category_id).where(
                PageCategoryAutomaticExclusion.site_page_id == page.id
            )
        )
    )
    categories = {
        c.id: c
        for c in db.scalars(select(PageCategory).where(PageCategory.website_property_id == site_id))
    }
    active_rules = list(
        db.scalars(
            select(PageCategoryRule)
            .options(selectinload(PageCategoryRule.conditions))
            .where(
                PageCategoryRule.website_property_id == site_id,
                PageCategoryRule.is_active.is_(True),
            )
        )
    )
    matching: defaultdict[int, list[CategoryProvenanceRule]] = defaultdict(list)
    if resource:
        for rule in active_rules:
            if resource_matches(
                resource,
                compile_conditions([_condition_payload(c) for c in rule.conditions]),
                rule.match_mode,
            ):
                matching[rule.category_id].append(
                    CategoryProvenanceRule(id=rule.id, name=rule.name)
                )
    by_category = {a.category_id: a for a in assignments}
    items = []
    for category_id in sorted(set(by_category) | exclusions):
        category = categories.get(category_id)
        if not category:
            continue
        assignment = by_category.get(category_id)
        manual = bool(
            assignment
            and any(s.support_type == "manual" for s in support_by_assignment[assignment.id])
        )
        rules = matching[category_id]
        excluded = category_id in exclusions
        reason = (
            "Manual"
            if manual and not rules
            else "Manual and automatic"
            if manual
            else f"{len(rules)} matching Rule{'s' if len(rules) != 1 else ''}"
            if rules and not excluded
            else "Automatic Rules excluded"
        )
        items.append(
            CategoryProvenanceRead(
                category_id=category_id,
                category_name=category.name,
                manually_assigned=manual,
                matching_rules=rules,
                automatic_exclusion=excluded,
                effective=assignment is not None,
                effective_reason=reason,
            )
        )
    return CategoryProvenanceList(items=items)


def set_automatic_exclusion(
    db: Session, site_id: int, resource_id: int, payload: AutomaticExclusionPayload
) -> CategoryProvenanceList | None:
    from app.services.site_pages import find_site_page

    page = find_site_page(db, site_id, resource_id)
    if page is None:
        return None
    _require_category(db, site_id, payload.category_id)
    existing = db.scalar(
        select(PageCategoryAutomaticExclusion).where(
            PageCategoryAutomaticExclusion.site_page_id == page.id,
            PageCategoryAutomaticExclusion.category_id == payload.category_id,
        )
    )
    if existing:
        existing.reason = payload.reason
    else:
        db.add(
            PageCategoryAutomaticExclusion(
                site_page_id=page.id, category_id=payload.category_id, reason=payload.reason
            )
        )
    queue_evaluation(db, site_id, "manual_recalculate")
    db.commit()
    return category_provenance(db, site_id, page.resource_id)


def remove_automatic_exclusion(
    db: Session, site_id: int, resource_id: int, category_id: int
) -> CategoryProvenanceList | None:
    from app.services.site_pages import find_site_page

    page = find_site_page(db, site_id, resource_id)
    if page is None:
        return None
    db.execute(
        delete(PageCategoryAutomaticExclusion).where(
            PageCategoryAutomaticExclusion.site_page_id == page.id,
            PageCategoryAutomaticExclusion.category_id == category_id,
        )
    )
    queue_evaluation(db, site_id, "manual_recalculate")
    db.commit()
    return category_provenance(db, site_id, page.resource_id)


def _rule(db: Session, site_id: int, rule_id: int) -> PageCategoryRule | None:
    return db.scalar(
        select(PageCategoryRule)
        .options(selectinload(PageCategoryRule.conditions))
        .where(PageCategoryRule.id == rule_id, PageCategoryRule.website_property_id == site_id)
    )


def _rules_by_ids(db: Session, ids: list[int]) -> dict[int, PageCategoryRule]:
    if not ids:
        return {}
    return {
        rule.id: rule
        for rule in db.scalars(
            select(PageCategoryRule)
            .options(selectinload(PageCategoryRule.conditions))
            .where(PageCategoryRule.id.in_(ids))
        )
    }


def _read_rule(rule: PageCategoryRule, category_name: str) -> CategoryRuleRead:
    return CategoryRuleRead(
        id=rule.id,
        website_property_id=rule.website_property_id,
        category_id=rule.category_id,
        category_name=category_name,
        name=rule.name,
        description=rule.description,
        match_mode=rule.match_mode,
        is_active=rule.is_active,
        sort_order=rule.sort_order,
        current_revision_number=rule.current_revision_number,
        current_match_count=rule.current_match_count,
        current_excluded_count=rule.current_excluded_count,
        last_evaluated_at=rule.last_evaluated_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        conditions=rule.conditions,
    )


def _require_category(db: Session, site_id: int, category_id: int) -> PageCategory:
    category = db.scalar(
        select(PageCategory).where(
            PageCategory.id == category_id, PageCategory.website_property_id == site_id
        )
    )
    if category is None:
        raise ValueError("Category does not belong to this Site.")
    return category


def _replace_conditions(
    db: Session, rule: PageCategoryRule, conditions: list[CategoryRuleConditionPayload]
) -> None:
    db.execute(
        delete(PageCategoryRuleCondition).where(PageCategoryRuleCondition.rule_id == rule.id)
    )
    db.add_all(
        PageCategoryRuleCondition(rule_id=rule.id, **condition.model_dump())
        for condition in conditions
    )
    db.flush()
    db.expire(rule, ["conditions"])


def _condition_payload(condition: PageCategoryRuleCondition) -> CategoryRuleConditionPayload:
    return CategoryRuleConditionPayload(
        target=condition.target,
        operator=condition.operator,
        value=condition.value,
        negate=condition.negate,
        case_sensitive=condition.case_sensitive,
        sort_order=condition.sort_order,
    )


def _definition(rule: PageCategoryRule) -> dict[str, object]:
    return {
        "name": rule.name,
        "description": rule.description,
        "category_id": rule.category_id,
        "match_mode": rule.match_mode,
        "is_active": rule.is_active,
        "sort_order": rule.sort_order,
        "conditions": [_condition_payload(c).model_dump() for c in rule.conditions],
    }


def _record_revision(db: Session, rule: PageCategoryRule, action: str) -> None:
    db.add(
        PageCategoryRuleRevision(
            rule_id=rule.id,
            website_property_id=rule.website_property_id,
            category_id=rule.category_id,
            revision_number=rule.current_revision_number,
            action=action,
            definition_json=_definition(rule),
        )
    )


def _enforce_active_limit(db: Session, site_id: int) -> None:
    count = (
        db.scalar(
            select(func.count(PageCategoryRule.id)).where(
                PageCategoryRule.website_property_id == site_id,
                PageCategoryRule.is_active.is_(True),
            )
        )
        or 0
    )
    if count >= MAX_ACTIVE_RULES:
        raise ValueError(f"A Site may have at most {MAX_ACTIVE_RULES} active Rules.")
