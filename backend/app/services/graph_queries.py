from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.models import ResourceOccurrence, ResourceSnapshot, Scan, ScanSeed, WebResource
from app.schemas.graph import (
    GraphEdgeOccurrenceList,
    GraphEdgeOccurrenceRead,
    GraphEdgeRead,
    GraphNodeRead,
    GraphResponse,
    GraphScanRead,
    GraphSummaryRead,
)

DEFAULT_GRAPH_NODE_LIMIT = 400
MAX_GRAPH_NODE_LIMIT = 1500
DEFAULT_GRAPH_EDGE_LIMIT = 1200
MAX_GRAPH_EDGE_LIMIT = 5000
SAMPLE_ANCHOR_LIMIT = 5


@dataclass(frozen=True)
class GraphFilters:
    max_nodes: int = DEFAULT_GRAPH_NODE_LIMIT
    max_edges: int = DEFAULT_GRAPH_EDGE_LIMIT
    min_depth: int | None = None
    max_depth: int | None = None
    host: str | None = None
    path_prefix: str | None = None
    status: Literal["any", "2xx", "3xx", "4xx", "5xx", "none"] = "any"
    fetch_state: str | None = None
    error_state: Literal["any", "with_errors", "without_errors"] = "any"
    min_inbound: int | None = None
    min_outbound: int | None = None
    include_self_links: bool = True
    include_unfetched: bool = False
    focus_snapshot_id: int | None = None
    focus_hops: int = 1


@dataclass
class _NodeMetrics:
    inbound_occurrences: int = 0
    inbound_sources: int = 0
    outbound_occurrences: int = 0
    outbound_targets: int = 0
    is_seed: bool = False
    seed_origins: int = 0


def get_scan_graph(db: Session, scan_id: int, filters: GraphFilters) -> GraphResponse | None:
    scan = db.scalar(
        select(Scan).options(joinedload(Scan.website_property)).where(Scan.id == scan_id)
    )
    if scan is None:
        return None
    if filters.focus_snapshot_id is not None and not _snapshot_belongs_to_scan(
        db, scan_id, filters.focus_snapshot_id
    ):
        raise ValueError("Focus snapshot does not belong to this scan.")

    snapshots = _load_snapshot_nodes(db, scan_id, filters)
    if not snapshots:
        return _empty_graph(scan, filters)

    snapshot_by_resource = {snapshot.resource_id: snapshot for snapshot, _resource in snapshots}
    snapshot_ids = {snapshot.id for snapshot, _resource in snapshots}
    metrics = _load_metrics(db, scan_id)
    seed_metrics = _load_seed_metrics(db, scan_id)
    for resource_id, values in seed_metrics.items():
        metrics[resource_id].is_seed = True
        metrics[resource_id].seed_origins = values

    all_edges = _load_edges(db, scan_id, snapshot_by_resource, filters.include_self_links)
    if filters.focus_snapshot_id is not None:
        allowed = _focus_snapshot_ids(all_edges, filters.focus_snapshot_id, filters.focus_hops)
        snapshots = [
            (snapshot, resource) for snapshot, resource in snapshots if snapshot.id in allowed
        ]
        snapshot_ids = {snapshot.id for snapshot, _resource in snapshots}

    filtered_snapshots = [
        (snapshot, resource)
        for snapshot, resource in snapshots
        if _passes_connectivity_filters(snapshot.resource_id, metrics, filters)
    ]
    available_nodes = len(filtered_snapshots)
    ordered_snapshots = sorted(
        filtered_snapshots,
        key=lambda row: _node_limit_key(row[0], row[1], metrics[row[0].resource_id], scan),
    )
    limited_snapshots = ordered_snapshots[: filters.max_nodes]
    included_resource_ids = {snapshot.resource_id for snapshot, _resource in limited_snapshots}

    discovered_nodes = []
    if filters.include_unfetched and len(limited_snapshots) < filters.max_nodes:
        discovered_nodes = _load_discovered_nodes(
            db,
            scan_id,
            snapshot_by_resource=snapshot_by_resource,
            included_resource_ids=included_resource_ids,
            remaining=filters.max_nodes - len(limited_snapshots),
        )
        included_resource_ids.update(resource.id for resource in discovered_nodes)

    included_node_ids = {f"snapshot:{snapshot.id}" for snapshot, _resource in limited_snapshots}
    included_node_ids.update(f"resource:{resource.id}" for resource in discovered_nodes)

    available_edges = [
        edge
        for edge in all_edges
        if edge.source_snapshot_id in snapshot_ids
        and (
            edge.target_snapshot_id in snapshot_ids
            or (
                filters.include_unfetched
                and f"resource:{edge.target_resource_id}" in included_node_ids
            )
        )
    ]
    limited_edges = [
        edge
        for edge in available_edges
        if edge.source in included_node_ids and edge.target in included_node_ids
    ][: filters.max_edges]

    nodes = [
        _node_read(snapshot, resource, metrics[snapshot.resource_id], scan)
        for snapshot, resource in limited_snapshots
    ]
    nodes.extend(
        _discovered_node_read(resource, metrics[resource.id]) for resource in discovered_nodes
    )

    reasons: list[str] = []
    if available_nodes > len(limited_snapshots):
        reasons.append(f"node_limit:{filters.max_nodes}")
    if len(available_edges) > len(limited_edges):
        reasons.append(f"edge_limit:{filters.max_edges}")
    if filters.include_unfetched and len(discovered_nodes) and len(nodes) >= filters.max_nodes:
        reasons.append("unfetched_node_limit")

    return GraphResponse(
        scan=GraphScanRead.model_validate(scan, from_attributes=True),
        summary=GraphSummaryRead(
            total_available_nodes=available_nodes,
            total_available_edges=len(available_edges),
            returned_nodes=len(nodes),
            returned_edges=len(limited_edges),
            fetched_nodes=len(limited_snapshots),
            unfetched_nodes=len(discovered_nodes),
            error_nodes=sum(1 for node in nodes if node.error_type),
            self_link_edges=sum(1 for edge in limited_edges if edge.is_self_link),
            total_occurrences=sum(edge.occurrence_count for edge in limited_edges),
            truncated=bool(reasons),
            truncation_reasons=reasons,
            focused=filters.focus_snapshot_id is not None,
            focus_snapshot_id=filters.focus_snapshot_id,
            focus_hops=filters.focus_hops if filters.focus_snapshot_id is not None else None,
        ),
        nodes=nodes,
        edges=limited_edges,
        effective_filters=_effective_filters(filters),
    )


def list_graph_edge_occurrences(
    db: Session,
    scan_id: int,
    edge_id: str,
    search: str | None,
    limit: int,
    offset: int,
) -> GraphEdgeOccurrenceList | None:
    parsed = _parse_edge_id(edge_id)
    if parsed is None:
        return None
    source_snapshot_id, target_resource_id = parsed
    source_snapshot = db.get(ResourceSnapshot, source_snapshot_id)
    if source_snapshot is None or source_snapshot.scan_id != scan_id:
        return None
    target_snapshot = db.scalar(
        select(ResourceSnapshot).where(
            ResourceSnapshot.scan_id == scan_id,
            ResourceSnapshot.resource_id == target_resource_id,
        )
    )
    base = select(ResourceOccurrence).where(
        ResourceOccurrence.source_snapshot_id == source_snapshot_id,
        ResourceOccurrence.target_resource_id == target_resource_id,
        ResourceOccurrence.relation_type == "page_link",
    )
    if search:
        pattern = f"%{search}%"
        base = base.where(
            or_(
                ResourceOccurrence.anchor_text.ilike(pattern),
                ResourceOccurrence.raw_href.ilike(pattern),
                ResourceOccurrence.resolved_url.ilike(pattern),
                ResourceOccurrence.title.ilike(pattern),
                ResourceOccurrence.aria_label.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    occurrences = list(
        db.scalars(base.order_by(ResourceOccurrence.id.asc()).limit(limit).offset(offset))
    )
    edge = _edge_from_occurrences(
        source_snapshot,
        target_snapshot,
        target_resource_id,
        occurrences
        if total == len(occurrences)
        else _all_edge_occurrences(db, source_snapshot_id, target_resource_id),
    )
    return GraphEdgeOccurrenceList(
        items=[
            GraphEdgeOccurrenceRead(
                id=occurrence.id,
                source_snapshot_id=source_snapshot.id,
                target_snapshot_id=target_snapshot.id if target_snapshot else None,
                raw_href=occurrence.raw_href,
                resolved_url=occurrence.resolved_url,
                normalized_target_url=occurrence.normalized_target_url,
                target_resource_id=occurrence.target_resource_id,
                anchor_text=occurrence.anchor_text,
                title=occurrence.title,
                aria_label=occurrence.aria_label,
                rel=occurrence.rel,
                target=occurrence.target,
                dom_path=occurrence.dom_path,
                in_scope=occurrence.in_scope,
                scope_decision=occurrence.scope_decision,
                exclusion_reason=occurrence.exclusion_reason,
                discovered_at=occurrence.discovered_at,
                is_self_link=source_snapshot.resource_id == target_resource_id,
            )
            for occurrence in occurrences
        ],
        total=total,
        limit=limit,
        offset=offset,
        edge=edge,
    )


def _load_snapshot_nodes(
    db: Session, scan_id: int, filters: GraphFilters
) -> list[tuple[ResourceSnapshot, WebResource]]:
    query = (
        select(ResourceSnapshot, WebResource)
        .join(WebResource)
        .where(ResourceSnapshot.scan_id == scan_id)
    )
    if filters.min_depth is not None:
        query = query.where(ResourceSnapshot.crawl_depth >= filters.min_depth)
    if filters.max_depth is not None:
        query = query.where(ResourceSnapshot.crawl_depth <= filters.max_depth)
    if filters.host:
        query = query.where(WebResource.host == filters.host.lower())
    if filters.path_prefix:
        query = query.where(WebResource.path.startswith(filters.path_prefix))
    if filters.status != "any":
        if filters.status == "none":
            query = query.where(ResourceSnapshot.http_status.is_(None))
        else:
            start = int(filters.status[0]) * 100
            query = query.where(
                ResourceSnapshot.http_status >= start,
                ResourceSnapshot.http_status < start + 100,
            )
    if filters.fetch_state:
        query = query.where(ResourceSnapshot.fetch_state == filters.fetch_state)
    if filters.error_state == "with_errors":
        query = query.where(ResourceSnapshot.error_type.is_not(None))
    elif filters.error_state == "without_errors":
        query = query.where(ResourceSnapshot.error_type.is_(None))
    return [(snapshot, resource) for snapshot, resource in db.execute(query).all()]


def _load_metrics(db: Session, scan_id: int) -> defaultdict[int, _NodeMetrics]:
    metrics: defaultdict[int, _NodeMetrics] = defaultdict(_NodeMetrics)
    source = aliased(ResourceSnapshot)
    target = aliased(ResourceSnapshot)

    inbound_rows = db.execute(
        select(
            ResourceOccurrence.target_resource_id,
            func.count(ResourceOccurrence.id),
            func.count(distinct(ResourceOccurrence.source_snapshot_id)),
        )
        .join(source, ResourceOccurrence.source_snapshot_id == source.id)
        .where(source.scan_id == scan_id, ResourceOccurrence.target_resource_id.is_not(None))
        .group_by(ResourceOccurrence.target_resource_id)
    )
    for resource_id, occurrences, sources in inbound_rows:
        if resource_id is not None:
            metrics[resource_id].inbound_occurrences = occurrences
            metrics[resource_id].inbound_sources = sources

    outbound_rows = db.execute(
        select(
            ResourceSnapshot.resource_id,
            func.count(ResourceOccurrence.id),
            func.count(distinct(ResourceOccurrence.target_resource_id)),
        )
        .join(ResourceOccurrence, ResourceOccurrence.source_snapshot_id == ResourceSnapshot.id)
        .join(
            target,
            (target.scan_id == scan_id)
            & (target.resource_id == ResourceOccurrence.target_resource_id),
            isouter=True,
        )
        .where(ResourceSnapshot.scan_id == scan_id, ResourceOccurrence.relation_type == "page_link")
        .group_by(ResourceSnapshot.resource_id)
    )
    for resource_id, occurrences, targets in outbound_rows:
        metrics[resource_id].outbound_occurrences = occurrences
        metrics[resource_id].outbound_targets = targets
    return metrics


def _load_seed_metrics(db: Session, scan_id: int) -> dict[int, int]:
    rows = db.execute(
        select(ScanSeed.resource_id, func.count())
        .where(ScanSeed.scan_id == scan_id, ScanSeed.resource_id.is_not(None))
        .group_by(ScanSeed.resource_id)
    )
    return {resource_id: count for resource_id, count in rows if resource_id is not None}


def _load_edges(
    db: Session,
    scan_id: int,
    snapshot_by_resource: dict[int, ResourceSnapshot],
    include_self_links: bool,
) -> list[GraphEdgeRead]:
    source = aliased(ResourceSnapshot)
    rows = db.execute(
        select(ResourceOccurrence, source)
        .join(source, ResourceOccurrence.source_snapshot_id == source.id)
        .where(
            source.scan_id == scan_id,
            ResourceOccurrence.relation_type == "page_link",
            ResourceOccurrence.target_resource_id.is_not(None),
        )
        .order_by(
            source.id.asc(),
            ResourceOccurrence.target_resource_id.asc(),
            ResourceOccurrence.id.asc(),
        )
    )
    grouped: dict[tuple[int, int], list[ResourceOccurrence]] = defaultdict(list)
    sources: dict[int, ResourceSnapshot] = {}
    for occurrence, source_snapshot in rows:
        target_resource_id = occurrence.target_resource_id
        if target_resource_id is None:
            continue
        if not include_self_links and source_snapshot.resource_id == target_resource_id:
            continue
        grouped[(source_snapshot.id, target_resource_id)].append(occurrence)
        sources[source_snapshot.id] = source_snapshot

    edges = []
    for (source_snapshot_id, target_resource_id), occurrences in grouped.items():
        edges.append(
            _edge_from_occurrences(
                sources[source_snapshot_id],
                snapshot_by_resource.get(target_resource_id),
                target_resource_id,
                occurrences,
            )
        )
    return sorted(
        edges,
        key=lambda edge: (
            edge.source_snapshot_id,
            edge.target_snapshot_id or 10**12,
            edge.target_resource_id or 10**12,
        ),
    )


def _edge_from_occurrences(
    source_snapshot: ResourceSnapshot,
    target_snapshot: ResourceSnapshot | None,
    target_resource_id: int,
    occurrences: list[ResourceOccurrence],
) -> GraphEdgeRead:
    source_id = f"snapshot:{source_snapshot.id}"
    target_id = (
        f"snapshot:{target_snapshot.id}" if target_snapshot else f"resource:{target_resource_id}"
    )
    anchor_texts = [
        occurrence.anchor_text.strip()
        for occurrence in occurrences
        if occurrence.anchor_text and occurrence.anchor_text.strip()
    ]
    rel_values = [occurrence.rel or "" for occurrence in occurrences]
    nofollow = sum(1 for rel in rel_values if "nofollow" in rel.lower())
    scope_decisions = Counter(occurrence.scope_decision for occurrence in occurrences)
    return GraphEdgeRead(
        id=_edge_id(source_snapshot.id, target_resource_id),
        source=source_id,
        target=target_id,
        source_snapshot_id=source_snapshot.id,
        target_snapshot_id=target_snapshot.id if target_snapshot else None,
        target_resource_id=target_resource_id,
        occurrence_count=len(occurrences),
        unique_anchor_text_count=len(set(anchor_texts)),
        nofollow_occurrence_count=nofollow,
        follow_occurrence_count=len(occurrences) - nofollow,
        empty_anchor_occurrence_count=len(occurrences) - len(anchor_texts),
        is_self_link=source_snapshot.resource_id == target_resource_id,
        sample_anchor_texts=list(dict.fromkeys(anchor_texts))[:SAMPLE_ANCHOR_LIMIT],
        first_discovered_at=min((item.discovered_at for item in occurrences), default=None),
        last_discovered_at=max((item.discovered_at for item in occurrences), default=None),
        scope_decisions=dict(scope_decisions),
    )


def _load_discovered_nodes(
    db: Session,
    scan_id: int,
    snapshot_by_resource: dict[int, ResourceSnapshot],
    included_resource_ids: set[int],
    remaining: int,
) -> list[WebResource]:
    source = aliased(ResourceSnapshot)
    resources = list(
        db.scalars(
            select(WebResource)
            .join(ResourceOccurrence, ResourceOccurrence.target_resource_id == WebResource.id)
            .join(source, ResourceOccurrence.source_snapshot_id == source.id)
            .where(
                source.scan_id == scan_id,
                ResourceOccurrence.in_scope.is_(True),
                ResourceOccurrence.target_resource_id.is_not(None),
                WebResource.id.not_in(snapshot_by_resource.keys() or [-1]),
                WebResource.id.not_in(included_resource_ids or {-1}),
            )
            .distinct()
            .order_by(WebResource.normalized_url.asc(), WebResource.id.asc())
            .limit(remaining)
        )
    )
    return resources


def _node_read(
    snapshot: ResourceSnapshot, resource: WebResource, metrics: _NodeMetrics, scan: Scan
) -> GraphNodeRead:
    return GraphNodeRead(
        id=f"snapshot:{snapshot.id}",
        kind="page",
        snapshot_id=snapshot.id,
        resource_id=resource.id,
        requested_url=snapshot.requested_url,
        final_url=snapshot.final_url,
        page_title=snapshot.page_title,
        host=resource.host,
        path=resource.path,
        http_status=snapshot.http_status,
        fetch_state=snapshot.fetch_state,
        error_type=snapshot.error_type,
        crawl_depth=snapshot.crawl_depth,
        content_type=snapshot.content_type,
        response_time_ms=snapshot.response_time_ms,
        inbound_occurrence_count=metrics.inbound_occurrences,
        inbound_source_page_count=metrics.inbound_sources,
        outbound_occurrence_count=metrics.outbound_occurrences,
        outbound_target_page_count=metrics.outbound_targets,
        is_scan_seed=metrics.is_seed,
        seed_origin_count=metrics.seed_origins,
        is_starting_url=_same_url(scan.starting_url, snapshot.requested_url)
        or _same_url(scan.starting_url, snapshot.final_url),
        redirects=bool(snapshot.redirect_chain),
        canonical_url=snapshot.canonical_url,
        category=_status_family(snapshot.http_status, snapshot.fetch_state, snapshot.error_type),
    )


def _discovered_node_read(resource: WebResource, metrics: _NodeMetrics) -> GraphNodeRead:
    return GraphNodeRead(
        id=f"resource:{resource.id}",
        kind="discovered",
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=None,
        host=resource.host,
        path=resource.path,
        fetch_state="discovered",
        inbound_occurrence_count=metrics.inbound_occurrences,
        inbound_source_page_count=metrics.inbound_sources,
        outbound_occurrence_count=0,
        outbound_target_page_count=0,
        category="discovered",
    )


def _passes_connectivity_filters(
    resource_id: int, metrics: defaultdict[int, _NodeMetrics], filters: GraphFilters
) -> bool:
    values = metrics[resource_id]
    if filters.min_inbound is not None and values.inbound_occurrences < filters.min_inbound:
        return False
    return not (
        filters.min_outbound is not None and values.outbound_occurrences < filters.min_outbound
    )


def _node_limit_key(
    snapshot: ResourceSnapshot, resource: WebResource, metrics: _NodeMetrics, scan: Scan
) -> tuple[int, int, int, int, str, int]:
    starting = 0 if _same_url(scan.starting_url, snapshot.requested_url) else 1
    return (
        starting,
        snapshot.crawl_depth,
        -metrics.inbound_sources,
        -metrics.outbound_targets,
        resource.normalized_url,
        snapshot.id,
    )


def _focus_snapshot_ids(edges: list[GraphEdgeRead], focus_snapshot_id: int, hops: int) -> set[int]:
    neighbors: defaultdict[int, set[int]] = defaultdict(set)
    for edge in edges:
        if edge.target_snapshot_id is None:
            continue
        neighbors[edge.source_snapshot_id].add(edge.target_snapshot_id)
        neighbors[edge.target_snapshot_id].add(edge.source_snapshot_id)
    seen = {focus_snapshot_id}
    queue: deque[tuple[int, int]] = deque([(focus_snapshot_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= hops:
            continue
        for neighbor in sorted(neighbors[current]):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, depth + 1))
    return seen


def _snapshot_belongs_to_scan(db: Session, scan_id: int, snapshot_id: int) -> bool:
    return (
        db.scalar(
            select(func.count(ResourceSnapshot.id)).where(
                ResourceSnapshot.id == snapshot_id, ResourceSnapshot.scan_id == scan_id
            )
        )
        or 0
    ) > 0


def _empty_graph(scan: Scan, filters: GraphFilters) -> GraphResponse:
    return GraphResponse(
        scan=GraphScanRead.model_validate(scan, from_attributes=True),
        summary=GraphSummaryRead(
            total_available_nodes=0,
            total_available_edges=0,
            returned_nodes=0,
            returned_edges=0,
            fetched_nodes=0,
            unfetched_nodes=0,
            error_nodes=0,
            self_link_edges=0,
            total_occurrences=0,
            truncated=False,
            truncation_reasons=[],
            focused=filters.focus_snapshot_id is not None,
            focus_snapshot_id=filters.focus_snapshot_id,
            focus_hops=filters.focus_hops if filters.focus_snapshot_id is not None else None,
        ),
        nodes=[],
        edges=[],
        effective_filters=_effective_filters(filters),
    )


def _effective_filters(filters: GraphFilters) -> dict[str, str | int | bool | None]:
    return {
        "max_nodes": filters.max_nodes,
        "max_edges": filters.max_edges,
        "min_depth": filters.min_depth,
        "max_depth": filters.max_depth,
        "host": filters.host,
        "path_prefix": filters.path_prefix,
        "status": filters.status,
        "fetch_state": filters.fetch_state,
        "error_state": filters.error_state,
        "min_inbound": filters.min_inbound,
        "min_outbound": filters.min_outbound,
        "include_self_links": filters.include_self_links,
        "include_unfetched": filters.include_unfetched,
        "focus_snapshot_id": filters.focus_snapshot_id,
        "focus_hops": filters.focus_hops,
    }


def _all_edge_occurrences(
    db: Session, source_snapshot_id: int, target_resource_id: int
) -> list[ResourceOccurrence]:
    return list(
        db.scalars(
            select(ResourceOccurrence).where(
                ResourceOccurrence.source_snapshot_id == source_snapshot_id,
                ResourceOccurrence.target_resource_id == target_resource_id,
                ResourceOccurrence.relation_type == "page_link",
            )
        )
    )


def _edge_id(source_snapshot_id: int, target_resource_id: int) -> str:
    return f"{source_snapshot_id}-{target_resource_id}"


def _parse_edge_id(edge_id: str) -> tuple[int, int] | None:
    parts = edge_id.split("-", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _status_family(status: int | None, fetch_state: str | None, error_type: str | None) -> str:
    if error_type:
        return "error"
    if status is None:
        return fetch_state or "unknown"
    return f"{status // 100}xx"


def _same_url(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.rstrip("/") == right.rstrip("/")
