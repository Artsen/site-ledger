from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.dependencies import DbSession, PageLimit, PageOffset
from app.browser.config import capabilities as render_capabilities_data
from app.models import (
    RenderedArtifact,
    RenderedConsoleMessage,
    RenderedNetworkEntry,
    RenderedObservation,
    RenderedPageError,
    Scan,
)
from app.schemas.rendered import (
    RenderCapabilitiesRead,
    RenderedArtifactRead,
    RenderedConsoleMessageRead,
    RenderedEventList,
    RenderedNetworkEntryRead,
    RenderedObservationIndexList,
    RenderedObservationRead,
    RenderedPageErrorRead,
)
from app.services.rendered_queries import list_scan_rendered_observations
from app.storage.artifact_store import ArtifactNotFoundError, LocalArtifactStore

router = APIRouter(prefix="/api")


@router.get(
    "/scans/{scan_id}/rendered-observations",
    response_model=RenderedObservationIndexList,
)
def get_scan_rendered_observations(
    scan_id: int,
    db: DbSession,
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
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedObservationIndexList:
    if db.get(Scan, scan_id) is None:
        raise HTTPException(404, "Scan not found")
    return list_scan_rendered_observations(
        db,
        scan_id,
        search=search,
        capture_state=capture_state,
        navigation_status=navigation_status,
        has_warnings=has_warnings,
        has_page_errors=has_page_errors,
        has_console_messages=has_console_messages,
        has_blocked_requests=has_blocked_requests,
        has_viewport_screenshot=has_viewport_screenshot,
        has_full_page_screenshot=has_full_page_screenshot,
        has_rendered_dom=has_rendered_dom,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.get("/rendering/capabilities", response_model=RenderCapabilitiesRead)
def rendering_capabilities() -> dict[str, object]:
    return render_capabilities_data()


def _rendered_read(observation: RenderedObservation) -> RenderedObservationRead:
    data = {
        column.name: getattr(observation, column.name)
        for column in RenderedObservation.__table__.columns
    }
    data["artifacts"] = [
        RenderedArtifactRead(
            id=item.id,
            artifact_type=item.artifact_type,
            width=item.width,
            height=item.height,
            media_type=item.blob.media_type,
            raw_byte_size=item.blob.raw_byte_size,
            stored_byte_size=item.blob.stored_byte_size,
            sha256=item.blob.sha256,
            metadata_json=item.metadata_json,
        )
        for item in observation.artifacts
    ]
    return RenderedObservationRead(**data)


@router.get("/snapshots/{snapshot_id}/rendered", response_model=RenderedObservationRead)
def get_snapshot_rendered(snapshot_id: int, db: DbSession) -> RenderedObservationRead:
    observation = db.scalar(
        select(RenderedObservation).where(RenderedObservation.snapshot_id == snapshot_id)
    )
    if observation is None:
        raise HTTPException(404, "Snapshot has no rendered observation")
    return _rendered_read(observation)


@router.get("/rendered-observations/{rendered_id}", response_model=RenderedObservationRead)
def get_rendered_observation(rendered_id: int, db: DbSession) -> RenderedObservationRead:
    observation = db.get(RenderedObservation, rendered_id)
    if observation is None:
        raise HTTPException(404, "Rendered observation not found")
    return _rendered_read(observation)


@router.get(
    "/rendered-observations/{rendered_id}/artifacts", response_model=list[RenderedArtifactRead]
)
def list_rendered_artifacts(rendered_id: int, db: DbSession) -> list[RenderedArtifactRead]:
    return get_rendered_observation(rendered_id, db).artifacts


@router.get("/rendered-observations/{rendered_id}/network", response_model=RenderedEventList)
def list_rendered_network(
    rendered_id: int,
    db: DbSession,
    search: str | None = None,
    resource_type: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedEventList:
    query = select(RenderedNetworkEntry).where(
        RenderedNetworkEntry.rendered_observation_id == rendered_id
    )
    if search:
        query = query.where(RenderedNetworkEntry.redacted_url.ilike(f"%{search}%"))
    if resource_type:
        query = query.where(RenderedNetworkEntry.resource_type == resource_type)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.order_by(RenderedNetworkEntry.sequence).limit(limit).offset(offset))
    )
    return RenderedEventList(
        items=[RenderedNetworkEntryRead.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rendered-observations/{rendered_id}/console", response_model=RenderedEventList)
def list_rendered_console(
    rendered_id: int,
    db: DbSession,
    search: str | None = None,
    message_type: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedEventList:
    query = select(RenderedConsoleMessage).where(
        RenderedConsoleMessage.rendered_observation_id == rendered_id
    )
    if search:
        query = query.where(RenderedConsoleMessage.text.ilike(f"%{search}%"))
    if message_type:
        query = query.where(RenderedConsoleMessage.message_type == message_type)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.order_by(RenderedConsoleMessage.sequence).limit(limit).offset(offset))
    )
    return RenderedEventList(
        items=[RenderedConsoleMessageRead.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rendered-observations/{rendered_id}/errors", response_model=RenderedEventList)
def list_rendered_errors(
    rendered_id: int,
    db: DbSession,
    search: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RenderedEventList:
    query = select(RenderedPageError).where(
        RenderedPageError.rendered_observation_id == rendered_id
    )
    if search:
        query = query.where(RenderedPageError.message.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(db.scalars(query.order_by(RenderedPageError.sequence).limit(limit).offset(offset)))
    return RenderedEventList(
        items=[RenderedPageErrorRead.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rendered-artifacts/{artifact_id}/content")
def get_rendered_artifact_content(artifact_id: int, request: Request, db: DbSession) -> Response:
    artifact = db.get(RenderedArtifact, artifact_id)
    if artifact is None or artifact.artifact_type not in {
        "rendered_dom",
        "viewport_screenshot",
        "full_page_screenshot",
    }:
        raise HTTPException(404, "Rendered artifact not found")
    store: LocalArtifactStore = request.app.state.artifact_store
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"}
    try:
        if artifact.artifact_type == "rendered_dom":
            return Response(
                store.read(artifact.blob), media_type="text/plain; charset=utf-8", headers=headers
            )
        return FileResponse(store.path_for(artifact.blob), media_type="image/png", headers=headers)
    except ArtifactNotFoundError as exc:
        raise HTTPException(404, "Rendered artifact file is missing") from exc
