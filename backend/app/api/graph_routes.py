from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.dependencies import DbSession, PageLimit, PageOffset
from app.api.projection_routes import _projection_http_response
from app.schemas.graph import GraphCapabilitiesRead, GraphEdgeOccurrenceList, GraphResponse
from app.services.graph_config import GRAPH_CONFIG
from app.services.graph_filters import GraphFilters
from app.services.graph_queries import (
    get_graph_capabilities,
    get_scan_graph,
    list_graph_edge_occurrences,
)

router = APIRouter(prefix="/api")


@router.get("/scans/{scan_id}/graph", response_model=GraphResponse)
def get_graph(
    scan_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    max_nodes: int = Query(
        GRAPH_CONFIG.default_node_limit,
        ge=1,
        le=GRAPH_CONFIG.maximum_node_limit,
    ),
    max_edges: int = Query(
        GRAPH_CONFIG.default_edge_limit,
        ge=0,
        le=GRAPH_CONFIG.maximum_edge_limit,
    ),
    min_depth: int | None = Query(default=None, ge=0),
    max_depth: int | None = Query(default=None, ge=0),
    host: str | None = None,
    path_prefix: str | None = None,
    status: Literal["any", "2xx", "3xx", "4xx", "5xx", "none"] = "any",
    fetch_state: str | None = None,
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    min_inbound: int | None = Query(default=None, ge=0),
    min_outbound: int | None = Query(default=None, ge=0),
    include_self_links: bool = True,
    include_unfetched: bool = False,
    focus_snapshot_id: int | None = Query(default=None, ge=1),
    focus_hops: int = Query(
        GRAPH_CONFIG.default_focus_hops,
        ge=1,
        le=GRAPH_CONFIG.maximum_focus_hops,
    ),
) -> GraphResponse | Response:
    if min_depth is not None and max_depth is not None and min_depth > max_depth:
        raise HTTPException(422, "min_depth cannot be greater than max_depth")
    try:
        graph = get_scan_graph(
            db,
            scan_id,
            GraphFilters(
                max_nodes=max_nodes,
                max_edges=max_edges,
                min_depth=min_depth,
                max_depth=max_depth,
                host=host,
                path_prefix=path_prefix,
                status=status,
                fetch_state=fetch_state,
                error_state=error_state,
                min_inbound=min_inbound,
                min_outbound=min_outbound,
                include_self_links=include_self_links,
                include_unfetched=include_unfetched,
                focus_snapshot_id=focus_snapshot_id,
                focus_hops=focus_hops,
            ),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if graph is None:
        raise HTTPException(404, "Scan not found")
    return _projection_http_response(request, response, graph)


@router.get("/graph/capabilities", response_model=GraphCapabilitiesRead)
def graph_capabilities() -> GraphCapabilitiesRead:
    return get_graph_capabilities()


@router.get(
    "/scans/{scan_id}/graph/edges/{edge_id}/occurrences",
    response_model=GraphEdgeOccurrenceList,
)
def get_graph_edge_occurrences(
    scan_id: int,
    edge_id: str,
    db: DbSession,
    search: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> GraphEdgeOccurrenceList:
    result = list_graph_edge_occurrences(
        db,
        scan_id=scan_id,
        edge_id=edge_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Graph edge not found")
    return result
