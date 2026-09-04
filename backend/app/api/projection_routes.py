import hashlib
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import DbSession
from app.models import (
    Scan,
)
from app.schemas.graph import GraphResponse
from app.schemas.projections import ScanProjectionBuildRead, ScanProjectionStatusRead
from app.schemas.resources import (
    ResourceInventoryList,
    ResourceSummary,
)
from app.schemas.scans import (
    PageList,
)
from app.services.background_jobs import (
    enqueue_scan_projection_job,
)
from app.services.scan_projections import (
    create_projection_build,
    projection_status,
    verify_projection_build,
)

router = APIRouter(prefix="/api")

ProjectionResponseT = TypeVar(
    "ProjectionResponseT", PageList, ResourceInventoryList, ResourceSummary, GraphResponse
)


@router.get("/scans/{scan_id}/projection", response_model=ScanProjectionStatusRead)
def get_scan_projection_status(scan_id: int, db: DbSession) -> ScanProjectionStatusRead:
    result = projection_status(db, scan_id)
    if result is None:
        raise HTTPException(404, "Scan not found")
    return result


@router.post(
    "/scans/{scan_id}/projection/build",
    response_model=ScanProjectionBuildRead,
    status_code=202,
)
def build_scan_projection(scan_id: int, db: DbSession) -> ScanProjectionBuildRead:
    return _queue_scan_projection(db, scan_id, force=False)


@router.post(
    "/scans/{scan_id}/projection/rebuild",
    response_model=ScanProjectionBuildRead,
    status_code=202,
)
def rebuild_scan_projection(scan_id: int, db: DbSession) -> ScanProjectionBuildRead:
    return _queue_scan_projection(db, scan_id, force=True)


@router.post("/scans/{scan_id}/projection/verify")
def verify_scan_projection(scan_id: int, db: DbSession) -> dict[str, object]:
    try:
        return verify_projection_build(db, scan_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def _queue_scan_projection(db: Session, scan_id: int, *, force: bool) -> ScanProjectionBuildRead:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found")
    try:
        build = create_projection_build(db, scan_id, force=force)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if build.status == "queued":
        enqueue_scan_projection_job(db, build.id, scan)
    db.commit()
    db.refresh(build)
    return ScanProjectionBuildRead.model_validate(build)


def _projection_http_response(
    request: Request,
    response: Response,
    result: ProjectionResponseT,
    *,
    immutable: bool = True,
) -> ProjectionResponseT | Response:
    metadata = result.projection
    if metadata is None:
        return result
    response.headers["X-Projection-Source"] = metadata.projection_source
    response.headers["X-Projection-Version"] = metadata.projection_version
    response.headers["X-Projection-Status"] = metadata.projection_status
    if metadata.projection_source != "materialized" or metadata.projection_build_id is None:
        return result
    response.headers["X-Projection-Build-Id"] = str(metadata.projection_build_id)
    if not immutable:
        response.headers["Cache-Control"] = "private, no-cache"
        return result
    identity = (
        f"{request.url.path}?{request.url.query}|{metadata.projection_version}|"
        f"{metadata.projection_build_id}"
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    etag = f'"scan-{metadata.projection_build_id}-{digest[:24]}"'
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "X-Projection-Source": metadata.projection_source,
        "X-Projection-Version": metadata.projection_version,
        "X-Projection-Status": metadata.projection_status,
        "X-Projection-Build-Id": str(metadata.projection_build_id),
    }
    response.headers.update(headers)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return result
