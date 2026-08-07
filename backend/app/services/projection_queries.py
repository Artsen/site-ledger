from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.crawler.resource_classification import RESOURCE_KIND_LABELS
from app.models import (
    Scan,
    ScanLinkProjection,
    ScanPageProjection,
    ScanProjectionBuild,
    ScanResourceProjection,
    ScanSummaryProjection,
    WebResource,
)
from app.schemas.graph import (
    GraphEdgeRead,
    GraphNodeRead,
    GraphResponse,
    GraphScanRead,
    GraphSummaryRead,
)
from app.schemas.resources import ResourceInventoryItem, ResourceInventoryList, ResourceSummary
from app.schemas.scans import PageList, PageRead
from app.services.graph_filters import GraphFilters
from app.services.scan_projections import (
    current_projection_build,
    materialized_metadata,
)


def list_projected_pages(
    db: Session,
    scan_id: int,
    search: str | None,
    status: int | None,
    host: str | None,
    path_prefix: str | None,
    depth: int | None,
    min_depth: int | None,
    max_depth: int | None,
    error_state: Literal["any", "with_errors", "without_errors"],
    sort: str,
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
    rendered_state: str,
    build: ScanProjectionBuild | None = None,
) -> PageList | None:
    build = build or current_projection_build(db, scan_id)
    if build is None:
        return None
    query = select(ScanPageProjection).where(ScanPageProjection.projection_build_id == build.id)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ScanPageProjection.requested_url.ilike(pattern),
                ScanPageProjection.final_url.ilike(pattern),
                ScanPageProjection.page_title.ilike(pattern),
            )
        )
    if status is not None:
        query = query.where(ScanPageProjection.http_status == status)
    if host:
        query = query.where(ScanPageProjection.host == host.casefold())
    if path_prefix:
        query = query.where(ScanPageProjection.path.startswith(path_prefix))
    if depth is not None:
        query = query.where(ScanPageProjection.crawl_depth == depth)
    if min_depth is not None:
        query = query.where(ScanPageProjection.crawl_depth >= min_depth)
    if max_depth is not None:
        query = query.where(ScanPageProjection.crawl_depth <= max_depth)
    if error_state == "with_errors":
        query = query.where(ScanPageProjection.error_type.is_not(None))
    elif error_state == "without_errors":
        query = query.where(ScanPageProjection.error_type.is_(None))
    if rendered_state == "not_requested":
        query = query.where(ScanPageProjection.rendered_capture_state.is_(None))
    elif rendered_state == "captured":
        query = query.where(ScanPageProjection.rendered_capture_state == "completed")
    elif rendered_state == "captured_with_warnings":
        query = query.where(ScanPageProjection.rendered_capture_state == "completed_with_warnings")
    elif rendered_state != "any":
        query = query.where(ScanPageProjection.rendered_capture_state == rendered_state)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "requested_url": ScanPageProjection.requested_url,
        "status": ScanPageProjection.http_status,
        "title": ScanPageProjection.page_title,
        "depth": ScanPageProjection.crawl_depth,
        "content_type": ScanPageProjection.content_type,
        "duration": ScanPageProjection.response_time_ms,
        "inbound": ScanPageProjection.inbound_occurrence_count,
        "rendered_state": func.coalesce(ScanPageProjection.rendered_capture_state, "not_requested"),
        "error": ScanPageProjection.error_type,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    id_order = (
        ScanPageProjection.snapshot_id.desc()
        if direction == "desc"
        else ScanPageProjection.snapshot_id.asc()
    )
    rows = db.scalars(query.order_by(order, id_order).limit(limit).offset(offset))
    return PageList(
        items=[_page_read(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        projection=materialized_metadata(build),
    )


def list_projected_resources(
    db: Session,
    scan_id: int,
    *,
    search: str | None = None,
    resource_kind: str | None = None,
    mime_type: str | None = None,
    extension: str | None = None,
    host: str | None = None,
    status: int | None = None,
    evidence_state: str = "any",
    scope_state: str = "any",
    location_state: str = "any",
    min_size: int | None = None,
    max_size: int | None = None,
    has_multiple_source_pages: bool = False,
    sort: str = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
    build: ScanProjectionBuild | None = None,
) -> ResourceInventoryList | None:
    build = build or current_projection_build(db, scan_id)
    if build is None:
        return None
    query = select(ScanResourceProjection).where(
        ScanResourceProjection.projection_build_id == build.id
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ScanResourceProjection.normalized_url.ilike(pattern),
                ScanResourceProjection.path.ilike(pattern),
            )
        )
    if resource_kind:
        query = query.where(ScanResourceProjection.effective_kind == resource_kind)
    if mime_type:
        query = query.where(ScanResourceProjection.normalized_mime_type.ilike(f"%{mime_type}%"))
    if extension:
        query = query.where(ScanResourceProjection.file_extension == extension.casefold())
    if host:
        query = query.where(ScanResourceProjection.host == host.casefold())
    if status is not None:
        query = query.where(ScanResourceProjection.http_status == status)
    if evidence_state == "observed":
        query = query.where(ScanResourceProjection.observed.is_(True))
    elif evidence_state == "discovered_only":
        query = query.where(ScanResourceProjection.discovered_only.is_(True))
    if scope_state == "in_scope":
        query = query.where(ScanResourceProjection.in_scope_occurrence_count > 0)
    elif scope_state == "out_of_scope":
        query = query.where(ScanResourceProjection.out_of_scope_occurrence_count > 0)
    if location_state != "any":
        scan = db.get(Scan, scan_id)
        internal_host = urlsplit(scan.starting_url).hostname if scan else None
        if internal_host and location_state == "internal":
            query = query.where(ScanResourceProjection.host == internal_host.casefold())
        elif internal_host:
            query = query.where(ScanResourceProjection.host != internal_host.casefold())
    if min_size is not None:
        query = query.where(ScanResourceProjection.declared_content_length >= min_size)
    if max_size is not None:
        query = query.where(ScanResourceProjection.declared_content_length <= max_size)
    if has_multiple_source_pages:
        query = query.where(ScanResourceProjection.source_page_count > 1)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "url": ScanResourceProjection.normalized_url,
        "kind": ScanResourceProjection.effective_kind,
        "mime_type": ScanResourceProjection.normalized_mime_type,
        "http_status": ScanResourceProjection.http_status,
        "declared_size": ScanResourceProjection.declared_content_length,
        "occurrence_count": ScanResourceProjection.occurrence_count,
        "source_page_count": ScanResourceProjection.source_page_count,
        "observed": ScanResourceProjection.observed,
        "in_scope_count": ScanResourceProjection.in_scope_occurrence_count,
        "first_discovered": ScanResourceProjection.first_discovered_at,
        "latest_discovered": ScanResourceProjection.latest_discovered_at,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.scalars(
        query.order_by(order, ScanResourceProjection.resource_id).limit(limit).offset(offset)
    )
    return ResourceInventoryList(
        items=[_resource_item(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        projection=materialized_metadata(build),
    )


def projected_resource_summary(
    db: Session, scan_id: int, build: ScanProjectionBuild | None = None
) -> ResourceSummary | None:
    build = build or current_projection_build(db, scan_id)
    if build is None:
        return None
    summary = db.scalar(
        select(ScanSummaryProjection).where(ScanSummaryProjection.projection_build_id == build.id)
    )
    if summary is None:
        return None
    return ResourceSummary(
        unique_resources=summary.resource_total,
        observed_resources=summary.observed_resource_total,
        discovered_only_resources=summary.discovered_only_resource_total,
        total_occurrences=summary.resource_occurrence_total,
        kind_counts=summary.resource_kind_counts_json,
        projection=materialized_metadata(build),
    )


def get_projected_graph(
    db: Session,
    scan_id: int,
    filters: GraphFilters,
    *,
    build: ScanProjectionBuild | None = None,
    scan: Scan | None = None,
) -> GraphResponse | None:
    build = build or current_projection_build(db, scan_id)
    if build is None:
        return None
    scan = scan or db.scalar(
        select(Scan).options(joinedload(Scan.website_property)).where(Scan.id == scan_id)
    )
    if scan is None:
        return None
    focus_ids: set[int] | None = None
    if filters.focus_snapshot_id is not None:
        exists = db.scalar(
            select(ScanPageProjection.snapshot_id).where(
                ScanPageProjection.projection_build_id == build.id,
                ScanPageProjection.snapshot_id == filters.focus_snapshot_id,
            )
        )
        if exists is None:
            raise ValueError("Focus snapshot does not belong to this scan.")
        focus_ids = _projected_focus_ids(
            db,
            build.id,
            filters.focus_snapshot_id,
            filters.focus_hops,
            filters.max_nodes,
            filters.include_self_links,
        )
    pages_query = select(ScanPageProjection).where(
        ScanPageProjection.projection_build_id == build.id
    )
    if focus_ids is not None:
        pages_query = pages_query.where(ScanPageProjection.snapshot_id.in_(focus_ids))
    pages_query = _apply_graph_page_filters(pages_query, filters)
    available_nodes = db.scalar(select(func.count()).select_from(pages_query.subquery())) or 0
    pages = list(
        db.scalars(
            pages_query.order_by(
                ScanPageProjection.is_starting_page.desc(),
                ScanPageProjection.crawl_depth,
                ScanPageProjection.inbound_source_page_count.desc(),
                ScanPageProjection.outbound_target_count.desc(),
                ScanPageProjection.normalized_url,
                ScanPageProjection.snapshot_id,
            ).limit(filters.max_nodes)
        )
    )
    resource_ids = {page.resource_id for page in pages}
    discovered: list[WebResource] = []
    if filters.include_unfetched and len(pages) < filters.max_nodes:
        discovered = list(
            db.scalars(
                select(WebResource)
                .join(
                    ScanLinkProjection,
                    ScanLinkProjection.target_resource_id == WebResource.id,
                )
                .where(
                    ScanLinkProjection.projection_build_id == build.id,
                    ScanLinkProjection.target_snapshot_id.is_(None),
                    ScanLinkProjection.in_scope_count > 0,
                    WebResource.id.not_in(resource_ids or {-1}),
                )
                .distinct()
                .order_by(WebResource.normalized_url, WebResource.id)
                .limit(filters.max_nodes - len(pages))
            )
        )
        resource_ids.update(item.id for item in discovered)
    source_ids = {page.snapshot_id for page in pages}
    edge_query = select(ScanLinkProjection).where(
        ScanLinkProjection.projection_build_id == build.id,
        ScanLinkProjection.source_snapshot_id.in_(source_ids or {-1}),
        ScanLinkProjection.target_resource_id.in_(resource_ids or {-1}),
    )
    if not filters.include_self_links:
        edge_query = edge_query.where(ScanLinkProjection.self_link.is_(False))
    available_edges = db.scalar(select(func.count()).select_from(edge_query.subquery())) or 0
    edge_occurrences = edge_query.with_only_columns(ScanLinkProjection.occurrence_count).subquery()
    available_occurrences = (
        db.scalar(select(func.coalesce(func.sum(edge_occurrences.c.occurrence_count), 0))) or 0
    )
    edges = list(
        db.scalars(
            edge_query.order_by(
                ScanLinkProjection.source_snapshot_id,
                ScanLinkProjection.target_snapshot_id.asc().nulls_last(),
                ScanLinkProjection.target_resource_id,
            ).limit(filters.max_edges)
        )
    )
    nodes = [_graph_page_node(row) for row in pages]
    discovered_metrics = {
        resource_id: (occurrences, sources)
        for resource_id, occurrences, sources in db.execute(
            select(
                ScanLinkProjection.target_resource_id,
                func.sum(ScanLinkProjection.occurrence_count),
                func.count(func.distinct(ScanLinkProjection.source_snapshot_id)),
            )
            .where(
                ScanLinkProjection.projection_build_id == build.id,
                ScanLinkProjection.target_resource_id.in_(
                    [resource.id for resource in discovered] or [-1]
                ),
            )
            .group_by(ScanLinkProjection.target_resource_id)
        )
    }
    nodes.extend(
        _graph_discovered_node(row, discovered_metrics.get(row.id, (0, 0))) for row in discovered
    )
    graph_edges = [_graph_edge(row) for row in edges]
    reasons: list[str] = []
    if available_nodes > len(pages):
        reasons.append(f"node_limit:{filters.max_nodes}")
    if available_edges > len(edges):
        reasons.append(f"edge_limit:{filters.max_edges}")
    return GraphResponse(
        scan=GraphScanRead.model_validate(scan, from_attributes=True),
        summary=GraphSummaryRead(
            total_available_nodes=available_nodes,
            total_available_edges=available_edges,
            returned_nodes=len(nodes),
            returned_edges=len(graph_edges),
            fetched_nodes=len(pages),
            unfetched_nodes=len(discovered),
            error_nodes=sum(bool(node.error_type) for node in nodes),
            self_link_edges=sum(edge.is_self_link for edge in graph_edges),
            total_occurrences=available_occurrences,
            truncated=bool(reasons),
            truncation_reasons=reasons,
            focused=filters.focus_snapshot_id is not None,
            focus_snapshot_id=filters.focus_snapshot_id,
            focus_hops=filters.focus_hops if filters.focus_snapshot_id is not None else None,
        ),
        nodes=nodes,
        edges=graph_edges,
        effective_filters=_effective_graph_filters(filters),
        projection=materialized_metadata(build),
    )


def _page_read(row: ScanPageProjection) -> PageRead:
    return PageRead(
        id=row.snapshot_id,
        resource_id=row.resource_id,
        requested_url=row.requested_url,
        final_url=row.final_url,
        http_status=row.http_status,
        title=row.page_title,
        depth=row.crawl_depth,
        content_type=row.content_type,
        discovery_source=row.discovery_source,
        inbound_occurrence_count=row.inbound_occurrence_count,
        inbound_source_page_count=row.inbound_source_page_count,
        response_time_ms=row.response_time_ms,
        fetch_state=row.fetch_state,
        error_type=row.error_type,
        network_bytes_transferred=row.network_bytes_transferred,
        rendered_capture_state=row.rendered_capture_state,
    )


def _resource_item(row: ScanResourceProjection) -> ResourceInventoryItem:
    return ResourceInventoryItem(
        resource_id=row.resource_id,
        normalized_url=row.normalized_url,
        host=row.host,
        path=row.path,
        file_extension=row.file_extension,
        effective_kind=row.effective_kind,
        effective_kind_label=RESOURCE_KIND_LABELS.get(row.effective_kind, "Unknown"),
        classification_source=row.classification_source,
        observed=row.observed,
        discovered_only=row.discovered_only,
        snapshot_id=row.latest_snapshot_id,
        final_url=row.final_url,
        http_status=row.http_status,
        normalized_mime_type=row.normalized_mime_type,
        content_disposition_filename=row.content_disposition_filename,
        declared_content_length=row.declared_content_length,
        network_bytes_transferred=row.network_bytes_transferred,
        fetched_at=row.fetched_at,
        response_time_ms=row.response_time_ms,
        occurrence_count=row.occurrence_count,
        source_page_count=row.source_page_count,
        anchor_occurrence_count=row.anchor_occurrence_count,
        embedded_occurrence_count=row.embedded_occurrence_count,
        in_scope_occurrence_count=row.in_scope_occurrence_count,
        out_of_scope_occurrence_count=row.out_of_scope_occurrence_count,
        first_discovered_at=row.first_discovered_at,
        latest_discovered_at=row.latest_discovered_at,
        observation_count=row.observation_count,
        scan_count=1,
    )


def _apply_graph_page_filters(
    query: Select[tuple[ScanPageProjection]], filters: GraphFilters
) -> Select[tuple[ScanPageProjection]]:
    result = query
    if filters.min_depth is not None:
        result = result.where(ScanPageProjection.crawl_depth >= filters.min_depth)
    if filters.max_depth is not None:
        result = result.where(ScanPageProjection.crawl_depth <= filters.max_depth)
    if filters.host:
        result = result.where(ScanPageProjection.host == filters.host.casefold())
    if filters.path_prefix:
        result = result.where(ScanPageProjection.path.startswith(filters.path_prefix))
    if filters.status != "any":
        if filters.status == "none":
            result = result.where(ScanPageProjection.http_status.is_(None))
        else:
            base = int(filters.status[0]) * 100
            result = result.where(
                ScanPageProjection.http_status >= base,
                ScanPageProjection.http_status < base + 100,
            )
    if filters.fetch_state:
        result = result.where(ScanPageProjection.fetch_state == filters.fetch_state)
    if filters.error_state == "with_errors":
        result = result.where(ScanPageProjection.error_type.is_not(None))
    elif filters.error_state == "without_errors":
        result = result.where(ScanPageProjection.error_type.is_(None))
    if filters.min_inbound is not None:
        result = result.where(ScanPageProjection.inbound_occurrence_count >= filters.min_inbound)
    if filters.min_outbound is not None:
        result = result.where(ScanPageProjection.outbound_occurrence_count >= filters.min_outbound)
    return result


def _projected_focus_ids(
    db: Session, build_id: int, focus: int, hops: int, max_nodes: int, include_self: bool
) -> set[int]:
    seen = {focus}
    frontier = {focus}
    for _ in range(hops):
        query = select(
            ScanLinkProjection.source_snapshot_id, ScanLinkProjection.target_snapshot_id
        ).where(
            ScanLinkProjection.projection_build_id == build_id,
            or_(
                ScanLinkProjection.source_snapshot_id.in_(frontier),
                ScanLinkProjection.target_snapshot_id.in_(frontier),
            ),
        )
        if not include_self:
            query = query.where(ScanLinkProjection.self_link.is_(False))
        next_frontier: set[int] = set()
        for source_id, target_id in db.execute(query):
            for candidate in (source_id, target_id):
                if candidate is not None and candidate not in seen:
                    seen.add(candidate)
                    next_frontier.add(candidate)
                    if len(seen) >= max_nodes:
                        return seen
        frontier = next_frontier
        if not frontier:
            break
    return seen


def _graph_page_node(row: ScanPageProjection) -> GraphNodeRead:
    return GraphNodeRead(
        id=f"snapshot:{row.snapshot_id}",
        kind="page",
        snapshot_id=row.snapshot_id,
        resource_id=row.resource_id,
        requested_url=row.requested_url,
        final_url=row.final_url,
        page_title=row.page_title,
        host=row.host,
        path=row.path,
        http_status=row.http_status,
        fetch_state=row.fetch_state,
        error_type=row.error_type,
        crawl_depth=row.crawl_depth,
        content_type=row.content_type,
        response_time_ms=row.response_time_ms,
        inbound_occurrence_count=row.inbound_occurrence_count,
        inbound_source_page_count=row.inbound_source_page_count,
        outbound_occurrence_count=row.outbound_occurrence_count,
        outbound_target_page_count=row.outbound_target_count,
        is_scan_seed=row.is_seed,
        seed_origin_count=row.seed_origin_count,
        is_starting_url=row.is_starting_page,
        redirects=row.redirects,
        canonical_url=row.canonical_url,
        category=_status_family(row.http_status, row.fetch_state, row.error_type),
    )


def _graph_discovered_node(resource: WebResource, metrics: tuple[int | None, int]) -> GraphNodeRead:
    inbound_occurrences, inbound_sources = metrics
    return GraphNodeRead(
        id=f"resource:{resource.id}",
        kind="discovered",
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        host=resource.host,
        path=resource.path,
        fetch_state="discovered",
        inbound_occurrence_count=inbound_occurrences or 0,
        inbound_source_page_count=inbound_sources or 0,
        category="discovered",
    )


def _graph_edge(row: ScanLinkProjection) -> GraphEdgeRead:
    return GraphEdgeRead(
        id=f"{row.source_snapshot_id}-{row.target_resource_id}",
        source=f"snapshot:{row.source_snapshot_id}",
        target=f"snapshot:{row.target_snapshot_id}"
        if row.target_snapshot_id
        else f"resource:{row.target_resource_id}",
        source_snapshot_id=row.source_snapshot_id,
        target_snapshot_id=row.target_snapshot_id,
        target_resource_id=row.target_resource_id,
        occurrence_count=row.occurrence_count,
        unique_anchor_text_count=row.unique_anchor_count,
        nofollow_occurrence_count=row.nofollow_count,
        follow_occurrence_count=row.follow_count,
        empty_anchor_occurrence_count=row.empty_anchor_count,
        is_self_link=row.self_link,
        sample_anchor_texts=row.sample_anchors_json,
        first_discovered_at=row.first_discovered_at,
        last_discovered_at=row.latest_discovered_at,
        scope_decisions=row.scope_counts_json,
        role_counts=row.role_counts_json,
        dom_regions=row.dom_regions_json,
    )


def _status_family(status: int | None, fetch_state: str | None, error_type: str | None) -> str:
    if error_type or fetch_state == "failed":
        return "error"
    return f"{status // 100}xx" if status is not None else "none"


def _effective_graph_filters(filters: GraphFilters) -> dict[str, str | int | bool | None]:
    return {
        key: getattr(filters, key)
        for key in (
            "max_nodes",
            "max_edges",
            "min_depth",
            "max_depth",
            "host",
            "path_prefix",
            "status",
            "fetch_state",
            "error_state",
            "min_inbound",
            "min_outbound",
            "include_self_links",
            "include_unfetched",
            "focus_snapshot_id",
            "focus_hops",
        )
    }
