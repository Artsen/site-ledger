from __future__ import annotations

from typing import Literal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import RenderedArtifact, RenderedObservation, ResourceSnapshot
from app.schemas.rendered import (
    RenderedObservationIndexItem,
    RenderedObservationIndexList,
    RenderedObservationSummary,
)


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
