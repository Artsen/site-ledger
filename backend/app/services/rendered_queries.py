from __future__ import annotations

from typing import Literal, cast

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from app.models import (
    BackgroundJob,
    RenderedArtifact,
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
)
from app.schemas.rendered import (
    RenderedObservationIndexItem,
    RenderedObservationIndexList,
    RenderedObservationSummary,
    RenderRunDetail,
    RenderRunList,
    RenderRunRead,
    RenderRunTargetList,
    RenderRunTargetRead,
)

RenderOutcome = Literal[
    "successful",
    "no_content",
    "redirect",
    "http_error",
    "rate_limited",
    "not_attempted",
    "technical_failure",
    "evidence_deleted",
    "not_attempted_host_throttled",
]

RetainedRenderOutcome = Literal[
    "successful",
    "no_content",
    "redirect",
    "http_error",
    "rate_limited",
    "not_attempted_host_throttled",
    "technical_failure",
]


def list_render_run_targets(
    db: Session,
    run_id: int,
    *,
    search: str | None = None,
    outcomes: list[RenderOutcome] | None = None,
    sort: Literal[
        "page_url",
        "capture_state",
        "duration",
        "navigation_status",
        "warning_count",
        "page_error_count",
        "browser_evidence",
        "capture_time",
    ] = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> RenderRunTargetList:
    artifacts = _artifact_presence_subquery()
    query = (
        select(RenderRunTarget, RenderedObservation, artifacts)
        .outerjoin(
            RenderedObservation,
            RenderedObservation.render_run_target_id == RenderRunTarget.id,
        )
        .outerjoin(artifacts, artifacts.c.observation_id == RenderedObservation.id)
        .where(RenderRunTarget.render_run_id == run_id)
    )
    if search:
        query = query.where(RenderRunTarget.requested_url.ilike(f"%{search}%"))
    if outcomes:
        conditions: list[ColumnElement[bool]] = []
        for outcome in outcomes:
            if outcome == "evidence_deleted":
                conditions.append(
                    RenderedObservation.id.is_(None)
                    & RenderRunTarget.evidence_deleted_at.is_not(None)
                )
            elif outcome == "not_attempted":
                conditions.append(
                    RenderedObservation.id.is_(None) & RenderRunTarget.evidence_deleted_at.is_(None)
                )
            elif outcome == "not_attempted_host_throttled":
                conditions.append(
                    RenderedObservation.id.is_not(None) & _render_outcome_condition("not_attempted")
                )
            else:
                conditions.append(
                    RenderedObservation.id.is_not(None) & _render_outcome_condition(outcome)
                )
        query = query.where(or_(*conditions))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    evidence_count = (
        func.coalesce(artifacts.c.viewport, 0)
        + func.coalesce(artifacts.c.full_page, 0)
        + func.coalesce(artifacts.c.dom, 0)
    )
    sort_map = {
        "page_url": RenderRunTarget.requested_url,
        "capture_state": RenderedObservation.capture_state,
        "duration": RenderedObservation.duration_ms,
        "navigation_status": RenderedObservation.navigation_http_status,
        "warning_count": RenderedObservation.warning_count,
        "page_error_count": RenderedObservation.page_error_count,
        "browser_evidence": evidence_count,
        "capture_time": RenderedObservation.finished_at,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.execute(
        query.order_by(order, RenderRunTarget.position, RenderRunTarget.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return RenderRunTargetList(
        items=[
            RenderRunTargetRead(
                target_id=target.id,
                position=target.position,
                web_resource_id=target.web_resource_id,
                requested_url=target.requested_url,
                source_snapshot_id=target.source_snapshot_id,
                created_at=target.created_at,
                evidence_deleted_at=target.evidence_deleted_at,
                observation_id=observation.id if observation else None,
                capture_state=observation.capture_state if observation else None,
                navigation_http_status=(
                    observation.navigation_http_status if observation else None
                ),
                duration_ms=observation.duration_ms if observation else None,
                warning_count=observation.warning_count if observation else None,
                page_error_count=observation.page_error_count if observation else None,
                has_page_artifacts=bool(viewport or full_page or dom),
                finished_at=observation.finished_at if observation else None,
                presentation_state=_target_presentation_state(target, observation),
            )
            for target, observation, _observation_id, viewport, full_page, dom in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _target_presentation_state(
    target: RenderRunTarget, observation: RenderedObservation | None
) -> str:
    if observation is None:
        return "evidence_deleted" if target.evidence_deleted_at is not None else "not_attempted"
    status = observation.navigation_http_status
    if observation.error_type == "host_rate_limit_circuit_open":
        return "not_attempted_host_throttled"
    if status == 429 or observation.error_type == "navigation_rate_limited":
        return "rate_limited"
    if status in (204, 205):
        return "no_content"
    if status is not None and 300 <= status <= 399:
        return "redirect"
    if status is not None and 400 <= status <= 599:
        return "http_error"
    if (
        observation.capture_state in ("completed", "completed_with_warnings")
        and status is not None
        and 200 <= status <= 299
    ):
        return "successful"
    return "technical_failure"


def list_scan_rendered_observations(
    db: Session,
    scan_id: int,
    *,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_console_messages: bool | None = None,
    has_blocked_requests: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    has_full_page_screenshot: bool | None = None,
    has_rendered_dom: bool | None = None,
    sort: Literal[
        "page_url",
        "capture_state",
        "duration",
        "navigation_status",
        "warning_count",
        "page_error_count",
        "browser_evidence",
        "capture_time",
    ] = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> RenderedObservationIndexList:
    artifacts = (
        select(
            RenderedArtifact.rendered_observation_id.label("observation_id"),
            func.max(
                case((RenderedArtifact.artifact_type == "viewport_screenshot", 1), else_=0)
            ).label("viewport"),
            func.max(
                case((RenderedArtifact.artifact_type == "full_page_screenshot", 1), else_=0)
            ).label("full_page"),
            func.max(case((RenderedArtifact.artifact_type == "rendered_dom", 1), else_=0)).label(
                "dom"
            ),
        )
        .group_by(RenderedArtifact.rendered_observation_id)
        .subquery()
    )
    query = (
        select(RenderedObservation, ResourceSnapshot, artifacts)
        .join(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
        .outerjoin(artifacts, artifacts.c.observation_id == RenderedObservation.id)
        .where(ResourceSnapshot.scan_id == scan_id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ResourceSnapshot.requested_url.ilike(pattern),
                ResourceSnapshot.final_url.ilike(pattern),
                ResourceSnapshot.page_title.ilike(pattern),
                RenderedObservation.document_title.ilike(pattern),
            )
        )
    if capture_state:
        query = query.where(RenderedObservation.capture_state == capture_state)
    if navigation_status is not None:
        query = query.where(RenderedObservation.navigation_http_status == navigation_status)
    for value, count_column in (
        (has_warnings, RenderedObservation.warning_count),
        (has_page_errors, RenderedObservation.page_error_count),
        (has_console_messages, RenderedObservation.console_message_count),
        (has_blocked_requests, RenderedObservation.blocked_request_count),
    ):
        if value is True:
            query = query.where(count_column > 0)
        elif value is False:
            query = query.where(count_column == 0)
    for value, artifact_column in (
        (has_viewport_screenshot, artifacts.c.viewport),
        (has_full_page_screenshot, artifacts.c.full_page),
        (has_rendered_dom, artifacts.c.dom),
    ):
        if value is True:
            query = query.where(artifact_column == 1)
        elif value is False:
            query = query.where(func.coalesce(artifact_column, 0) == 0)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    status = RenderedObservation.navigation_http_status
    state = RenderedObservation.capture_state
    error_type = RenderedObservation.error_type
    is_skipped_after_throttling = func.coalesce(error_type == "host_rate_limit_circuit_open", False)
    is_rate_limited = (status == 429) | func.coalesce(
        error_type == "navigation_rate_limited", False
    )
    is_operational = ~is_skipped_after_throttling
    is_technical_status = or_(
        status.is_(None),
        status < 200,
        status >= 600,
        status.between(200, 299) & status.notin_((204, 205)),
    )
    summary_values = db.execute(
        select(
            func.sum(
                case(
                    (
                        state.in_(("completed", "completed_with_warnings"))
                        & is_operational
                        & ~is_rate_limited
                        & status.between(200, 299)
                        & status.notin_((204, 205)),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(case((is_operational & status.in_((204, 205)), 1), else_=0)),
            func.sum(case((is_operational & status.between(300, 399), 1), else_=0)),
            func.sum(
                case(
                    (is_operational & ~is_rate_limited & status.between(400, 599), 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        is_operational
                        & is_rate_limited
                        & ~func.coalesce(status.in_((204, 205)), False)
                        & ~func.coalesce(status.between(300, 399), False),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (is_skipped_after_throttling, 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        is_operational
                        & ~is_rate_limited
                        & state.in_(("failed", "cancelled", "interrupted"))
                        & is_technical_status,
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .select_from(RenderedObservation)
        .join(ResourceSnapshot)
        .where(ResourceSnapshot.scan_id == scan_id)
    ).one()
    artifact_total = (
        db.scalar(
            select(func.count(RenderedArtifact.id))
            .join(RenderedObservation)
            .join(ResourceSnapshot)
            .where(ResourceSnapshot.scan_id == scan_id)
        )
        or 0
    )
    sort_map = {
        "page_url": func.coalesce(ResourceSnapshot.final_url, ResourceSnapshot.requested_url),
        "capture_state": RenderedObservation.capture_state,
        "duration": RenderedObservation.duration_ms,
        "navigation_status": RenderedObservation.navigation_http_status,
        "warning_count": RenderedObservation.warning_count,
        "page_error_count": RenderedObservation.page_error_count,
        "browser_evidence": func.coalesce(artifacts.c.viewport, 0)
        + func.coalesce(artifacts.c.full_page, 0)
        + func.coalesce(artifacts.c.dom, 0)
        + RenderedObservation.console_message_count
        + RenderedObservation.blocked_request_count,
        "capture_time": RenderedObservation.finished_at,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.execute(
        query.order_by(order, RenderedObservation.id).limit(limit).offset(offset)
    ).all()
    return RenderedObservationIndexList(
        items=[
            RenderedObservationIndexItem(
                id=observation.id,
                snapshot_id=snapshot.id,
                resource_id=snapshot.resource_id,
                page_title=snapshot.page_title or observation.document_title,
                static_final_url=snapshot.final_url or snapshot.requested_url,
                browser_final_url=observation.final_url,
                capture_state=observation.capture_state,
                static_http_status=snapshot.http_status,
                navigation_http_status=observation.navigation_http_status,
                error_type=observation.error_type,
                error_message=observation.error_message,
                duration_ms=observation.duration_ms,
                warning_count=observation.warning_count,
                blocked_request_count=observation.blocked_request_count,
                console_message_count=observation.console_message_count,
                page_error_count=observation.page_error_count,
                has_viewport_screenshot=bool(viewport),
                has_full_page_screenshot=bool(full_page),
                has_rendered_dom=bool(dom),
                finished_at=observation.finished_at,
            )
            for observation, snapshot, _observation_id, viewport, full_page, dom in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        summary=RenderedObservationSummary(
            successful_renders=summary_values[0] or 0,
            no_content_responses=summary_values[1] or 0,
            redirect_responses=summary_values[2] or 0,
            http_error_responses=summary_values[3] or 0,
            rate_limited=summary_values[4] or 0,
            skipped_after_throttling=summary_values[5] or 0,
            technical_failures=summary_values[6] or 0,
            artifacts_retained=artifact_total,
        ),
    )


def list_render_runs(
    db: Session, site_id: int, *, limit: int = 25, offset: int = 0
) -> RenderRunList:
    condition = RenderRun.website_property_id == site_id
    total = db.scalar(select(func.count(RenderRun.id)).where(condition)) or 0
    runs = list(
        db.scalars(
            select(RenderRun)
            .where(condition)
            .order_by(RenderRun.created_at.desc(), RenderRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    jobs = {
        job.render_run_id: job
        for job in db.scalars(
            select(BackgroundJob).where(BackgroundJob.render_run_id.in_([run.id for run in runs]))
        )
    }
    return RenderRunList(
        items=[_render_run_read(db, run, jobs.get(run.id)) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_render_run(
    db: Session,
    site_id: int,
    run_id: int,
    *,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    outcomes: list[RenderOutcome] | None = None,
    sort: Literal[
        "page_url",
        "capture_state",
        "duration",
        "navigation_status",
        "warning_count",
        "page_error_count",
        "browser_evidence",
        "capture_time",
    ] = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> RenderRunDetail | None:
    run = db.scalar(
        select(RenderRun).where(RenderRun.id == run_id, RenderRun.website_property_id == site_id)
    )
    if run is None:
        return None
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.render_run_id == run.id))
    observations = list_render_run_observations(
        db,
        run.id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_viewport_screenshot=has_viewport_screenshot,
        outcomes=outcomes,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return RenderRunDetail(**_render_run_read(db, run, job).model_dump(), observations=observations)


def list_render_run_observations(
    db: Session,
    run_id: int | None,
    *,
    site_id: int | None = None,
    resource_id: int | None = None,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    outcomes: list[RenderOutcome] | None = None,
    sort: Literal[
        "page_url",
        "capture_state",
        "duration",
        "navigation_status",
        "warning_count",
        "page_error_count",
        "browser_evidence",
        "capture_time",
    ] = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> RenderedObservationIndexList:
    if run_id is not None:
        condition = RenderedObservation.render_run_id == run_id
    elif site_id is not None and resource_id is not None:
        condition = RenderedObservation.render_run_id.in_(
            select(RenderRun.id).where(RenderRun.website_property_id == site_id)
        ) & (RenderedObservation.web_resource_id == resource_id)
    else:
        raise ValueError("Run identity or Site Page identity is required.")
    artifacts = _artifact_presence_subquery()
    query = (
        select(RenderedObservation, RenderRunTarget, ResourceSnapshot, artifacts)
        .join(RenderRunTarget, RenderRunTarget.id == RenderedObservation.render_run_target_id)
        .outerjoin(ResourceSnapshot, ResourceSnapshot.id == RenderedObservation.snapshot_id)
        .outerjoin(artifacts, artifacts.c.observation_id == RenderedObservation.id)
        .where(condition)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                RenderRunTarget.requested_url.ilike(pattern),
                RenderedObservation.final_url.ilike(pattern),
                RenderedObservation.document_title.ilike(pattern),
                ResourceSnapshot.page_title.ilike(pattern),
            )
        )
    if capture_state:
        query = query.where(RenderedObservation.capture_state == capture_state)
    if navigation_status is not None:
        query = query.where(RenderedObservation.navigation_http_status == navigation_status)
    for value, count_column in (
        (has_warnings, RenderedObservation.warning_count),
        (has_page_errors, RenderedObservation.page_error_count),
    ):
        if value is True:
            query = query.where(count_column > 0)
        elif value is False:
            query = query.where(count_column == 0)
    if has_viewport_screenshot is True:
        query = query.where(artifacts.c.viewport == 1)
    elif has_viewport_screenshot is False:
        query = query.where(func.coalesce(artifacts.c.viewport, 0) == 0)
    if outcomes:
        query = query.where(or_(*[_render_outcome_condition(value) for value in outcomes]))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "page_url": RenderRunTarget.requested_url,
        "capture_state": RenderedObservation.capture_state,
        "duration": RenderedObservation.duration_ms,
        "navigation_status": RenderedObservation.navigation_http_status,
        "warning_count": RenderedObservation.warning_count,
        "page_error_count": RenderedObservation.page_error_count,
        "browser_evidence": func.coalesce(artifacts.c.viewport, 0)
        + func.coalesce(artifacts.c.full_page, 0)
        + func.coalesce(artifacts.c.dom, 0)
        + RenderedObservation.console_message_count
        + RenderedObservation.blocked_request_count,
        "capture_time": RenderedObservation.finished_at,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.execute(
        query.order_by(order, RenderRunTarget.position, RenderedObservation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return RenderedObservationIndexList(
        items=[
            RenderedObservationIndexItem(
                id=observation.id,
                snapshot_id=observation.snapshot_id,
                render_run_target_id=target.id,
                resource_id=target.web_resource_id,
                page_title=(snapshot.page_title if snapshot else None)
                or observation.document_title,
                static_final_url=(
                    (snapshot.final_url or snapshot.requested_url)
                    if snapshot
                    else target.requested_url
                ),
                browser_final_url=observation.final_url,
                capture_state=observation.capture_state,
                static_http_status=snapshot.http_status if snapshot else None,
                navigation_http_status=observation.navigation_http_status,
                error_type=observation.error_type,
                error_message=observation.error_message,
                duration_ms=observation.duration_ms,
                warning_count=observation.warning_count,
                blocked_request_count=observation.blocked_request_count,
                console_message_count=observation.console_message_count,
                page_error_count=observation.page_error_count,
                has_viewport_screenshot=bool(viewport),
                has_full_page_screenshot=bool(full_page),
                has_rendered_dom=bool(dom),
                finished_at=observation.finished_at,
            )
            for observation, target, snapshot, _observation_id, viewport, full_page, dom in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        summary=_render_summary(db, condition),
    )


def page_render_history(
    db: Session,
    site_id: int,
    resource_id: int,
    *,
    search: str | None = None,
    capture_state: str | None = None,
    navigation_status: int | None = None,
    has_warnings: bool | None = None,
    has_page_errors: bool | None = None,
    has_viewport_screenshot: bool | None = None,
    outcomes: list[RenderOutcome] | None = None,
    sort: Literal[
        "page_url",
        "capture_state",
        "duration",
        "navigation_status",
        "warning_count",
        "page_error_count",
        "browser_evidence",
        "capture_time",
    ] = "capture_time",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> RenderedObservationIndexList:
    return list_render_run_observations(
        db,
        None,
        site_id=site_id,
        resource_id=resource_id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_viewport_screenshot=has_viewport_screenshot,
        outcomes=outcomes,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


def _artifact_presence_subquery() -> Subquery:
    return (
        select(
            RenderedArtifact.rendered_observation_id.label("observation_id"),
            func.max(
                case((RenderedArtifact.artifact_type == "viewport_screenshot", 1), else_=0)
            ).label("viewport"),
            func.max(
                case((RenderedArtifact.artifact_type == "full_page_screenshot", 1), else_=0)
            ).label("full_page"),
            func.max(case((RenderedArtifact.artifact_type == "rendered_dom", 1), else_=0)).label(
                "dom"
            ),
        )
        .group_by(RenderedArtifact.rendered_observation_id)
        .subquery()
    )


def _render_outcome_condition(outcome: RenderOutcome) -> ColumnElement[bool]:
    shared_outcome = (
        "not_attempted_host_throttled"
        if outcome == "not_attempted"
        else cast(RetainedRenderOutcome, outcome)
    )
    return render_outcome_conditions()[shared_outcome]


def render_outcome_conditions(
    *,
    status: ColumnElement[int | None] | InstrumentedAttribute[int | None] = (
        RenderedObservation.navigation_http_status
    ),
    state: ColumnElement[str] | InstrumentedAttribute[str] = RenderedObservation.capture_state,
    error_type: ColumnElement[str | None] | InstrumentedAttribute[str | None] = (
        RenderedObservation.error_type
    ),
) -> dict[RetainedRenderOutcome, ColumnElement[bool]]:
    """Return the mutually exclusive retained-observation outcome contract."""
    skipped = func.coalesce(error_type == "host_rate_limit_circuit_open", False)
    rate_limited = func.coalesce(
        (status == 429) | (error_type == "navigation_rate_limited"),
        False,
    )
    no_content = func.coalesce(status.in_((204, 205)), False)
    redirect = func.coalesce(status.between(300, 399), False)
    http_error = func.coalesce(status.between(400, 599), False) & ~rate_limited
    successful = func.coalesce(
        state.in_(("completed", "completed_with_warnings"))
        & status.between(200, 299)
        & ~no_content,
        False,
    )
    conditions: dict[RetainedRenderOutcome, ColumnElement[bool]] = {
        "successful": successful & ~rate_limited & ~skipped,
        "no_content": no_content & ~skipped,
        "redirect": redirect & ~skipped,
        "http_error": http_error & ~skipped,
        "rate_limited": rate_limited & ~skipped,
        "not_attempted_host_throttled": skipped,
        "technical_failure": ~or_(
            *[
                func.coalesce(value, False)
                for value in (
                    successful,
                    no_content,
                    redirect,
                    http_error,
                    rate_limited,
                    skipped,
                )
            ]
        ),
    }
    return {name: func.coalesce(condition, False) for name, condition in conditions.items()}


def _render_summary(db: Session, condition: ColumnElement[bool]) -> RenderedObservationSummary:
    outcomes = render_outcome_conditions()
    names: tuple[RetainedRenderOutcome, ...] = (
        "successful",
        "no_content",
        "redirect",
        "http_error",
        "rate_limited",
        "not_attempted_host_throttled",
        "technical_failure",
    )
    counts = db.execute(
        select(*[func.count(case((outcomes[name], 1))) for name in names]).where(condition)
    ).one()
    artifact_total = (
        db.scalar(
            select(func.count(RenderedArtifact.id)).join(RenderedObservation).where(condition)
        )
        or 0
    )
    return RenderedObservationSummary(
        successful_renders=counts[0],
        no_content_responses=counts[1],
        redirect_responses=counts[2],
        http_error_responses=counts[3],
        rate_limited=counts[4],
        skipped_after_throttling=counts[5],
        technical_failures=counts[6],
        artifacts_retained=artifact_total,
    )


def _render_run_read(db: Session, run: RenderRun, job: BackgroundJob | None) -> RenderRunRead:
    retained = (
        db.scalar(
            select(func.count(RenderedObservation.id)).where(
                RenderedObservation.render_run_id == run.id
            )
        )
        or 0
    )
    deleted = (
        db.scalar(
            select(func.count(RenderRunTarget.id)).where(
                RenderRunTarget.render_run_id == run.id,
                RenderRunTarget.evidence_deleted_at.is_not(None),
            )
        )
        or 0
    )
    retained_artifacts = (
        db.scalar(
            select(func.count(RenderedArtifact.id))
            .join(RenderedObservation)
            .where(RenderedObservation.render_run_id == run.id)
        )
        or 0
    )
    return RenderRunRead.model_validate(
        {
            **{column.name: getattr(run, column.name) for column in run.__table__.columns},
            "job_id": job.id if job else None,
            "presentation_status": job.status if job else run.status,
            "summary": _render_summary(db, RenderedObservation.render_run_id == run.id),
            "retained_observation_count": retained,
            "deleted_observation_count": deleted,
            "unattempted_target_count": max(run.target_count - retained - deleted, 0),
            "retained_artifact_count": retained_artifacts,
        }
    )
