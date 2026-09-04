from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CollectionPlan, CollectionPlanTarget, WebsiteProperty
from app.schemas.collection_plans import (
    CollectionCoverageRead,
    CollectionPlanBatchRead,
    CollectionPlanList,
    CollectionPlanPreview,
    CollectionPlanProgress,
    CollectionPlanRead,
    CollectionPlanRequest,
    CollectionPlanTargetList,
    CollectionPlanTargetRead,
    CollectionPreviewTarget,
)
from app.services.collection_plans import (
    Selection,
    _processed,
    build_selection,
    cancel_collection_plan,
    create_collection_plan,
    get_collection_plan,
    list_collection_plans,
    plan_status,
)

router = APIRouter(prefix="/api", tags=["collection-plans"])
DbSession = Annotated[Session, Depends(get_db)]


def _coverage(selection: Selection) -> CollectionCoverageRead:
    target_total = len(selection.targets)
    return CollectionCoverageRead(
        evidence_domain=selection.domain,
        target_mode=selection.target_mode,
        context_identity=selection.context_identity,
        context=selection.context,
        active_page_count=len(selection.active),
        active_page_universe_sha256=selection.universe_sha256,
        eligible=len(selection.eligible),
        covered=len(selection.covered_ids),
        in_flight=len(selection.in_flight_ids),
        active_collection=len(selection.active_collection_ids),
        missing=len(selection.missing_ids),
        ineligible=selection.ineligible_count,
        batch_size=selection.batch_size,
        estimated_batch_count=(target_total + selection.batch_size - 1) // selection.batch_size,
        collectable=selection.collectable,
        non_collectable_reason=selection.non_collectable_reason,
    )


def _read(plan: CollectionPlan) -> CollectionPlanRead:
    batches = [
        CollectionPlanBatchRead(
            id=batch.id,
            position=batch.position,
            target_start_position=batch.target_start_position,
            target_count=batch.target_count,
            child_kind=batch.child_kind,
            status=batch.background_job.status if batch.background_job else "missing",
            processed_target_count=_processed(batch),
            background_job_id=batch.background_job_id,
            performance_run_id=batch.performance_run_id,
            accessibility_run_id=batch.accessibility_run_id,
            render_run_id=batch.render_run_id,
            created_at=batch.created_at,
        )
        for batch in plan.batches
    ]
    statuses = [batch.status for batch in batches]
    progress = CollectionPlanProgress(
        batch_count=len(batches),
        queued_batches=statuses.count("queued"),
        running_batches=statuses.count("running"),
        completed_batches=sum(
            status in {"completed", "completed_with_errors"} for status in statuses
        ),
        failed_batches=sum(status in {"failed", "interrupted", "missing"} for status in statuses),
        cancelled_batches=statuses.count("cancelled"),
        target_count=plan.target_count,
        processed_target_count=sum(batch.processed_target_count for batch in batches),
    )
    return CollectionPlanRead(
        id=plan.id,
        website_property_id=plan.website_property_id,
        planner_version=plan.planner_version,
        evidence_domain=plan.evidence_domain,
        target_mode=plan.target_mode,
        context_identity=plan.context_identity,
        context=plan.context_json,
        active_page_count=plan.active_page_count,
        active_page_universe_sha256=plan.active_page_universe_sha256,
        eligible_count=plan.eligible_count,
        covered_count_at_creation=plan.covered_count_at_creation,
        in_flight_count_at_creation=plan.in_flight_count_at_creation,
        active_collection_count_at_creation=plan.active_collection_count_at_creation,
        missing_count_at_creation=plan.missing_count_at_creation,
        selection_reason_counts=plan.selection_reason_counts_json,
        ineligible_count_at_creation=plan.ineligible_count_at_creation,
        target_count=plan.target_count,
        batch_size=plan.batch_size,
        batch_count=plan.batch_count,
        target_selection_sha256=plan.target_selection_sha256,
        cancellation_requested_at=plan.cancellation_requested_at,
        created_at=plan.created_at,
        status=plan_status(plan),
        progress=progress,
        batches=batches,
    )


@router.post("/sites/{site_id}/collection-plans/preview", response_model=CollectionPlanPreview)
def preview_collection_plan(
    site_id: int,
    payload: CollectionPlanRequest,
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CollectionPlanPreview:
    try:
        selection = build_selection(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == "Site not found." else 422, str(exc)) from exc
    items = selection.targets[offset : offset + limit]
    return CollectionPlanPreview(
        **_coverage(selection).model_dump(),
        targets=[
            CollectionPreviewTarget(
                position=offset + index,
                web_resource_id=target.resource_id,
                requested_url=target.url,
                selection_reason=selection.target_reasons[target.resource_id],
                latest_compatible_observed_at=target.latest_compatible_observed_at,
                target_context=selection.context,
                source_snapshot_id=target.source_snapshot_id,
                content_blob_id=target.content_blob_id,
            )
            for index, target in enumerate(items)
        ],
        target_total=len(selection.targets),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/sites/{site_id}/collection-plans", response_model=CollectionPlanRead, status_code=202
)
def create_plan(site_id: int, payload: CollectionPlanRequest, db: DbSession) -> CollectionPlanRead:
    try:
        return _read(create_collection_plan(db, site_id, payload))
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        status = (
            404
            if message == "Site not found."
            else 409
            if "already active" in message or message.startswith("No ")
            else 422
        )
        raise HTTPException(status, message) from exc


@router.get("/sites/{site_id}/collection-plans", response_model=CollectionPlanList)
def list_plans(
    site_id: int,
    db: DbSession,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CollectionPlanList:
    if db.get(WebsiteProperty, site_id) is None:
        raise HTTPException(404, "Site not found")
    items, total = list_collection_plans(db, site_id, limit=limit, offset=offset)
    return CollectionPlanList(
        items=[_read(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sites/{site_id}/collection-plans/{plan_id}", response_model=CollectionPlanRead)
def get_plan(site_id: int, plan_id: int, db: DbSession) -> CollectionPlanRead:
    plan = get_collection_plan(db, site_id, plan_id)
    if plan is None:
        raise HTTPException(404, "Collection Plan not found")
    return _read(plan)


@router.get(
    "/sites/{site_id}/collection-plans/{plan_id}/targets",
    response_model=CollectionPlanTargetList,
)
def list_targets(
    site_id: int,
    plan_id: int,
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CollectionPlanTargetList:
    if get_collection_plan(db, site_id, plan_id) is None:
        raise HTTPException(404, "Collection Plan not found")
    total = (
        db.scalar(
            select(func.count())
            .select_from(CollectionPlanTarget)
            .where(CollectionPlanTarget.collection_plan_id == plan_id)
        )
        or 0
    )
    rows = db.scalars(
        select(CollectionPlanTarget)
        .where(CollectionPlanTarget.collection_plan_id == plan_id)
        .order_by(CollectionPlanTarget.position)
        .limit(limit)
        .offset(offset)
    )
    return CollectionPlanTargetList(
        items=[
            CollectionPlanTargetRead(
                id=row.id,
                position=row.position,
                web_resource_id=row.web_resource_id,
                requested_url=row.requested_url,
                selection_reason=row.selection_reason,
                latest_compatible_observed_at=row.latest_compatible_observed_at,
                target_context=row.target_context_json,
                source_snapshot_id=row.source_snapshot_id,
                content_blob_id=row.content_blob_id,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/sites/{site_id}/collection-plans/{plan_id}/cancel",
    response_model=CollectionPlanRead,
)
def cancel_plan(site_id: int, plan_id: int, db: DbSession) -> CollectionPlanRead:
    plan = get_collection_plan(db, site_id, plan_id)
    if plan is None:
        raise HTTPException(404, "Collection Plan not found")
    return _read(cancel_collection_plan(db, plan))
