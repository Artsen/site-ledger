import hashlib
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Scan, ScanComparison, ScanComparisonBuild
from app.schemas.comparisons import (
    ComparisonLinkList,
    ComparisonLinkRead,
    ComparisonPageList,
    ComparisonPageRead,
    ComparisonResourceList,
    ComparisonResourceRead,
    OccurrenceDiffList,
    PageChangeHistoryList,
    ScanComparisonBuildRead,
    ScanComparisonCreate,
    ScanComparisonJobProgress,
    ScanComparisonList,
    ScanComparisonOverview,
    SourceDiffRead,
)
from app.services.background_jobs import (
    active_job_for_comparison,
    enqueue_scan_comparison_job,
    enqueue_scan_projection_job,
    request_cancellation,
)
from app.services.comparison_queries import (
    get_comparison_link,
    get_comparison_overview,
    get_comparison_page,
    get_comparison_resource,
    link_occurrence_diff,
    list_comparison_links,
    list_comparison_pages,
    list_comparison_resources,
    list_comparisons,
    page_change_history,
    page_source_diff,
)
from app.services.scan_comparisons import (
    SCAN_COMPARISON_VERSION,
    ComparisonEligibilityError,
    create_comparison,
    create_comparison_build,
    current_comparison_build,
    delete_comparison,
)
from app.services.scan_projections import create_projection_build, current_projection_build

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=250)]
Offset = Annotated[int, Query(ge=0)]
T = TypeVar("T")


@router.get("/sites/{site_id}/comparisons", response_model=ScanComparisonList)
def get_comparisons(
    site_id: int, db: DbSession, limit: Limit = 50, offset: Offset = 0
) -> ScanComparisonList:
    return list_comparisons(db, site_id, limit=limit, offset=offset)


@router.post(
    "/sites/{site_id}/comparisons",
    response_model=ScanComparisonOverview,
    status_code=202,
)
def post_comparison(
    site_id: int, payload: ScanComparisonCreate, db: DbSession
) -> ScanComparisonOverview:
    try:
        comparison = create_comparison(
            db, site_id, payload.baseline_scan_id, payload.target_scan_id
        )
        build = create_comparison_build(db, comparison.id)
        _queue_dependencies(db, comparison, build)
        db.commit()
    except ComparisonEligibilityError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = get_comparison_overview(db, site_id, comparison.id)
    assert result is not None
    return result


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}",
    response_model=ScanComparisonOverview,
)
def get_comparison(
    site_id: int,
    comparison_id: int,
    request: Request,
    response: Response,
    db: DbSession,
) -> ScanComparisonOverview | Response:
    result = get_comparison_overview(db, site_id, comparison_id)
    if result is None:
        raise HTTPException(404, "Comparison not found")
    build = current_comparison_build(db, comparison_id)
    return _immutable_response(request, response, result, build.id if build else None)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/status",
    response_model=ScanComparisonOverview,
)
def get_comparison_status(
    site_id: int, comparison_id: int, db: DbSession
) -> ScanComparisonOverview:
    result = get_comparison_overview(db, site_id, comparison_id)
    if result is None:
        raise HTTPException(404, "Comparison not found")
    job = active_job_for_comparison(db, comparison_id)
    result.active_job = ScanComparisonJobProgress.model_validate(job) if job else None
    return result


@router.post(
    "/sites/{site_id}/comparisons/{comparison_id}/rebuild",
    response_model=ScanComparisonBuildRead,
    status_code=202,
)
def rebuild_comparison(site_id: int, comparison_id: int, db: DbSession) -> ScanComparisonBuildRead:
    comparison = _comparison_or_404(db, site_id, comparison_id)
    build = create_comparison_build(db, comparison.id, force=True)
    _queue_dependencies(db, comparison, build)
    db.commit()
    db.refresh(build)
    return ScanComparisonBuildRead.model_validate(build)


@router.post(
    "/sites/{site_id}/comparisons/{comparison_id}/cancel",
    response_model=ScanComparisonOverview,
)
def cancel_comparison(site_id: int, comparison_id: int, db: DbSession) -> ScanComparisonOverview:
    _comparison_or_404(db, site_id, comparison_id)
    job = active_job_for_comparison(db, comparison_id)
    if job:
        request_cancellation(db, job, "Comparison cancellation requested.")
    result = get_comparison_overview(db, site_id, comparison_id)
    assert result is not None
    return result


@router.delete("/sites/{site_id}/comparisons/{comparison_id}")
def remove_comparison(site_id: int, comparison_id: int, db: DbSession) -> dict[str, int]:
    _comparison_or_404(db, site_id, comparison_id)
    try:
        delete_comparison(db, comparison_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted_comparison_id": comparison_id}


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/pages",
    response_model=ComparisonPageList,
)
def get_comparison_pages(
    site_id: int,
    comparison_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    search: str | None = None,
    presence: str | None = None,
    change: str | None = None,
    content: str | None = None,
    head: str | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    changed_only: bool = True,
    http_changed: bool | None = None,
    baseline_status: int | None = None,
    target_status: int | None = None,
    redirect_changed: bool | None = None,
    links_changed: bool | None = None,
    rendered_changed: bool | None = None,
    sort: str = "url",
    direction: str = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> ComparisonPageList | Response:
    result = list_comparison_pages(
        db,
        site_id,
        comparison_id,
        search=search,
        presence=presence,
        change=change,
        content=content,
        head=head,
        host=host,
        path_prefix=path_prefix,
        changed_only=changed_only,
        http_changed=http_changed,
        baseline_status=baseline_status,
        target_status=target_status,
        redirect_changed=redirect_changed,
        links_changed=links_changed,
        rendered_changed=rendered_changed,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(409, "Comparison results are not ready")
    return _immutable_response(request, response, result, result.comparison_build_id)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/pages/{resource_id}",
    response_model=ComparisonPageRead,
)
def get_comparison_page_detail(
    site_id: int,
    comparison_id: int,
    resource_id: int,
    request: Request,
    response: Response,
    db: DbSession,
) -> ComparisonPageRead | Response:
    result = get_comparison_page(db, site_id, comparison_id, resource_id)
    if result is None:
        raise HTTPException(404, "Page comparison not found")
    build = current_comparison_build(db, comparison_id)
    assert build is not None
    return _immutable_response(request, response, result, build.id)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/pages/{resource_id}/source-diff",
    response_model=SourceDiffRead,
)
def get_page_source_diff(
    site_id: int,
    comparison_id: int,
    resource_id: int,
    request: Request,
    db: DbSession,
    mode: Literal["exact", "meaningful"] = "exact",
) -> SourceDiffRead:
    result = page_source_diff(
        db,
        request.app.state.content_store,
        site_id,
        comparison_id,
        resource_id,
        mode=mode,
    )
    if result is None:
        raise HTTPException(404, "Page comparison not found")
    return result


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/resources",
    response_model=ComparisonResourceList,
)
def get_comparison_resources(
    site_id: int,
    comparison_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    search: str | None = None,
    presence: str | None = None,
    change: str | None = None,
    kind: str | None = None,
    mime: str | None = None,
    host: str | None = None,
    status_changed: bool | None = None,
    observed_state_changed: bool | None = None,
    sort: str = "url",
    direction: str = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> ComparisonResourceList | Response:
    result = list_comparison_resources(
        db,
        site_id,
        comparison_id,
        search=search,
        presence=presence,
        change=change,
        kind=kind,
        mime=mime,
        host=host,
        status_changed=status_changed,
        observed_state_changed=observed_state_changed,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(409, "Comparison results are not ready")
    return _immutable_response(request, response, result, result.comparison_build_id)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/resources/{resource_id}",
    response_model=ComparisonResourceRead,
)
def get_comparison_resource_detail(
    site_id: int,
    comparison_id: int,
    resource_id: int,
    request: Request,
    response: Response,
    db: DbSession,
) -> ComparisonResourceRead | Response:
    result = get_comparison_resource(db, site_id, comparison_id, resource_id)
    if result is None:
        raise HTTPException(404, "Resource comparison not found")
    build = current_comparison_build(db, comparison_id)
    assert build is not None
    return _immutable_response(request, response, result, build.id)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/links",
    response_model=ComparisonLinkList,
)
def get_comparison_links(
    site_id: int,
    comparison_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    search: str | None = None,
    presence: str | None = None,
    change: str | None = None,
    role: str | None = None,
    scope: str | None = None,
    min_occurrence_delta: int | None = None,
    sort: str = "source",
    direction: str = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> ComparisonLinkList | Response:
    result = list_comparison_links(
        db,
        site_id,
        comparison_id,
        search=search,
        presence=presence,
        change=change,
        role=role,
        scope=scope,
        min_occurrence_delta=min_occurrence_delta,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(409, "Comparison results are not ready")
    return _immutable_response(request, response, result, result.comparison_build_id)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/links/{source_resource_id}/{target_resource_id}",
    response_model=ComparisonLinkRead,
)
def get_comparison_link_detail(
    site_id: int,
    comparison_id: int,
    source_resource_id: int,
    target_resource_id: int,
    request: Request,
    response: Response,
    db: DbSession,
) -> ComparisonLinkRead | Response:
    result = get_comparison_link(db, site_id, comparison_id, source_resource_id, target_resource_id)
    if result is None:
        raise HTTPException(404, "Link comparison not found")
    build = current_comparison_build(db, comparison_id)
    assert build is not None
    return _immutable_response(request, response, result, build.id)


@router.get(
    "/sites/{site_id}/comparisons/{comparison_id}/links/{source_resource_id}/{target_resource_id}/occurrences",
    response_model=OccurrenceDiffList,
)
def get_link_occurrence_diff(
    site_id: int,
    comparison_id: int,
    source_resource_id: int,
    target_resource_id: int,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
) -> OccurrenceDiffList:
    result = link_occurrence_diff(
        db,
        site_id,
        comparison_id,
        source_resource_id,
        target_resource_id,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Link comparison not found")
    return result


@router.get(
    "/sites/{site_id}/pages/{resource_id}/change-history",
    response_model=PageChangeHistoryList,
)
def get_page_change_history(
    site_id: int,
    resource_id: int,
    db: DbSession,
    request: Request,
    limit: Limit = 50,
    offset: Offset = 0,
) -> PageChangeHistoryList:
    result = page_change_history(
        db,
        site_id,
        resource_id,
        store=request.app.state.content_store,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


def _queue_dependencies(
    db: Session, comparison: ScanComparison, build: ScanComparisonBuild
) -> None:
    for scan_id in (comparison.baseline_scan_id, comparison.target_scan_id):
        if current_projection_build(db, scan_id) is None:
            scan = db.get(Scan, scan_id)
            assert scan is not None
            projection = create_projection_build(db, scan_id)
            if projection.status == "queued":
                enqueue_scan_projection_job(db, projection.id, scan)
    if build.status == "queued":
        enqueue_scan_comparison_job(
            db,
            build.id,
            comparison.id,
            comparison.website_property_id,
        )


def _comparison_or_404(db: Session, site_id: int, comparison_id: int) -> ScanComparison:
    comparison = db.get(ScanComparison, comparison_id)
    if comparison is None or comparison.website_property_id != site_id:
        raise HTTPException(404, "Comparison not found")
    return comparison


def _immutable_response(
    request: Request, response: Response, result: T, build_id: int | None
) -> T | Response:
    if build_id is None:
        return result
    identity = f"{request.url.path}?{request.url.query}|{SCAN_COMPARISON_VERSION}|{build_id}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    etag = f'"comparison-{build_id}-{digest[:24]}"'
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "X-Comparison-Version": SCAN_COMPARISON_VERSION,
        "X-Comparison-Build-Id": str(build_id),
    }
    response.headers.update(headers)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return result
