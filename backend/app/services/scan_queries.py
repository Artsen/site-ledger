from typing import Any, Literal

from sqlalchemy import Select, distinct, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.models import RenderedObservation, ResourceOccurrence, ResourceSnapshot, Scan, WebResource
from app.schemas.scans import (
    InboundLinkList,
    InboundLinkRead,
    InboundLinkSummary,
    LinkRead,
    OutgoingLinkList,
    OutgoingLinkSummary,
    PageList,
    PageRead,
    ScanHistory,
)


def list_snapshot_outgoing_links(
    db: Session,
    snapshot_id: int,
    *,
    search: str | None = None,
    scope_decision: str | None = None,
    link_role: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> OutgoingLinkList | None:
    if db.get(ResourceSnapshot, snapshot_id) is None:
        return None
    query = select(ResourceOccurrence).where(
        ResourceOccurrence.source_snapshot_id == snapshot_id,
        ResourceOccurrence.relation_type == "page_link",
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ResourceOccurrence.anchor_text.ilike(pattern),
                ResourceOccurrence.raw_href.ilike(pattern),
                ResourceOccurrence.resolved_url.ilike(pattern),
            )
        )
    if scope_decision:
        query = query.where(ResourceOccurrence.scope_decision == scope_decision)
    if link_role == "legacy_unclassified":
        query = query.where(ResourceOccurrence.link_role.is_(None))
    elif link_role:
        query = query.where(ResourceOccurrence.link_role == link_role)
    filtered = query.subquery()
    total = db.scalar(select(func.count()).select_from(filtered)) or 0
    nofollow = (
        db.scalar(
            select(func.count()).select_from(filtered).where(filtered.c.rel.ilike("%nofollow%"))
        )
        or 0
    )
    in_scope = (
        db.scalar(select(func.count()).select_from(filtered).where(filtered.c.in_scope.is_(True)))
        or 0
    )
    role_counts = {
        (role or "legacy_unclassified"): count
        for role, count in db.execute(
            select(filtered.c.link_role, func.count())
            .select_from(filtered)
            .group_by(filtered.c.link_role)
        )
    }
    occurrences = list(
        db.scalars(query.order_by(ResourceOccurrence.id).limit(limit).offset(offset))
    )
    return OutgoingLinkList(
        items=[LinkRead.model_validate(item) for item in occurrences],
        total=total,
        limit=limit,
        offset=offset,
        summary=OutgoingLinkSummary(
            total_occurrences=total,
            nofollow_occurrences=nofollow,
            in_scope_occurrences=in_scope,
            role_counts=role_counts,
        ),
    )


def list_scan_history(
    db: Session,
    search: str | None,
    status: str | None,
    website_property_id: int | None = None,
    sort: Literal[
        "created_at", "started_at", "finished_at", "status", "starting_url"
    ] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> ScanHistory:
    query = select(Scan).options(joinedload(Scan.website_property))
    if search:
        query = query.where(Scan.starting_url.ilike(f"%{search}%"))
    if status:
        query = query.where(Scan.status == status)
    if website_property_id is not None:
        query = query.where(Scan.website_property_id == website_property_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "created_at": Scan.created_at,
        "started_at": Scan.started_at,
        "finished_at": Scan.finished_at,
        "status": Scan.status,
        "starting_url": Scan.starting_url,
    }
    order_col = sort_map[sort]
    scans = list(
        db.scalars(
            query.order_by(order_col.desc() if direction == "desc" else order_col.asc())
            .limit(limit)
            .offset(offset)
        )
    )
    return ScanHistory(items=scans, total=total, limit=limit, offset=offset)


def list_scan_pages(
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
    sort: Literal["requested_url", "status", "title", "depth", "duration"],
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> PageList:
    source_snapshot = aliased(ResourceSnapshot)
    inbound = (
        select(
            ResourceOccurrence.target_resource_id.label("resource_id"),
            func.count(ResourceOccurrence.id).label("inbound_occurrence_count"),
            func.count(distinct(ResourceOccurrence.source_snapshot_id)).label(
                "inbound_source_page_count"
            ),
            func.min(func.coalesce(source_snapshot.final_url, source_snapshot.requested_url)).label(
                "discovery_source"
            ),
        )
        .join(source_snapshot, ResourceOccurrence.source_snapshot_id == source_snapshot.id)
        .where(source_snapshot.scan_id == scan_id)
        .group_by(ResourceOccurrence.target_resource_id)
        .subquery()
    )
    base = (
        select(
            ResourceSnapshot,
            WebResource,
            RenderedObservation.capture_state,
            inbound.c.inbound_occurrence_count,
            inbound.c.inbound_source_page_count,
            inbound.c.discovery_source,
        )
        .select_from(ResourceSnapshot)
        .join(WebResource)
        .outerjoin(inbound, inbound.c.resource_id == WebResource.id)
        .outerjoin(RenderedObservation, RenderedObservation.snapshot_id == ResourceSnapshot.id)
        .where(ResourceSnapshot.scan_id == scan_id)
    )
    base = _apply_page_filters(
        base, search, status, host, path_prefix, depth, min_depth, max_depth, error_state
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    sort_map = {
        "requested_url": ResourceSnapshot.requested_url,
        "status": ResourceSnapshot.http_status,
        "title": ResourceSnapshot.page_title,
        "depth": ResourceSnapshot.crawl_depth,
        "duration": ResourceSnapshot.response_time_ms,
    }
    order_col = sort_map[sort]
    rows = db.execute(
        base.order_by(order_col.desc() if direction == "desc" else order_col.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PageList(
        items=[
            PageRead(
                id=snapshot.id,
                resource_id=resource.id,
                requested_url=snapshot.requested_url,
                final_url=snapshot.final_url,
                http_status=snapshot.http_status,
                title=snapshot.page_title,
                depth=snapshot.crawl_depth,
                content_type=snapshot.content_type,
                discovery_source=discovery_source,
                inbound_occurrence_count=inbound_occurrence_count or 0,
                inbound_source_page_count=inbound_source_page_count or 0,
                response_time_ms=snapshot.response_time_ms,
                fetch_state=snapshot.fetch_state,
                error_type=snapshot.error_type,
                rendered_capture_state=rendered_capture_state,
            )
            for (
                snapshot,
                resource,
                rendered_capture_state,
                inbound_occurrence_count,
                inbound_source_page_count,
                discovery_source,
            ) in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def list_snapshot_inbound_links(
    db: Session,
    snapshot_id: int,
    search: str | None,
    scope_decision: str | None,
    source_status: int | None,
    rel: str | None,
    link_role: str | None = None,
    sort: Literal["source_url", "anchor_text", "scope_decision", "source_status"] = "source_url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> InboundLinkList | None:
    target = db.get(ResourceSnapshot, snapshot_id)
    if target is None:
        return None

    source_snapshot = aliased(ResourceSnapshot)
    base = (
        select(ResourceOccurrence, source_snapshot)
        .join(source_snapshot, ResourceOccurrence.source_snapshot_id == source_snapshot.id)
        .where(
            ResourceOccurrence.target_resource_id == target.resource_id,
            source_snapshot.scan_id == target.scan_id,
        )
    )
    base = _apply_inbound_filters(
        base, search, scope_decision, source_status, rel, link_role, source_snapshot
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    summary = _inbound_summary(
        db,
        target,
        base,
    )
    sort_map = {
        "source_url": func.coalesce(source_snapshot.final_url, source_snapshot.requested_url),
        "anchor_text": ResourceOccurrence.anchor_text,
        "scope_decision": ResourceOccurrence.scope_decision,
        "source_status": source_snapshot.http_status,
    }
    rows = db.execute(
        base.order_by(sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return InboundLinkList(
        items=[
            InboundLinkRead(
                id=occurrence.id,
                source_snapshot_id=source.id,
                source_resource_id=source.resource_id,
                source_requested_url=source.requested_url,
                source_final_url=source.final_url,
                source_page_title=source.page_title,
                source_http_status=source.http_status,
                source_fetch_state=source.fetch_state,
                source_crawl_depth=source.crawl_depth,
                raw_href=occurrence.raw_href,
                resolved_url=occurrence.resolved_url,
                normalized_target_url=occurrence.normalized_target_url,
                anchor_text=occurrence.anchor_text,
                title=occurrence.title,
                aria_label=occurrence.aria_label,
                rel=occurrence.rel,
                target=occurrence.target,
                dom_path=occurrence.dom_path,
                in_scope=occurrence.in_scope,
                scope_decision=occurrence.scope_decision,
                exclusion_reason=occurrence.exclusion_reason,
                link_role=occurrence.link_role,
                link_role_label=occurrence.link_role_label,
                link_role_rule=occurrence.link_role_rule,
                discovered_at=occurrence.discovered_at,
                is_self_link=source.id == target.id,
            )
            for occurrence, source in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        summary=summary,
    )


def _inbound_summary(
    db: Session,
    target: ResourceSnapshot,
    base: Select[tuple[ResourceOccurrence, ResourceSnapshot]],
) -> InboundLinkSummary:
    filtered = base.subquery()
    total = db.scalar(select(func.count()).select_from(filtered)) or 0
    unique_sources = (
        db.scalar(select(func.count(distinct(filtered.c.id_1))).select_from(filtered)) or 0
    )
    unique_anchor_texts = (
        db.scalar(
            select(func.count(distinct(filtered.c.anchor_text))).where(
                filtered.c.anchor_text.is_not(None),
                filtered.c.anchor_text != "",
            )
        )
        or 0
    )
    nofollow = (
        db.scalar(
            select(func.count()).select_from(filtered).where(filtered.c.rel.ilike("%nofollow%"))
        )
        or 0
    )
    self_links = (
        db.scalar(select(func.count()).select_from(filtered).where(filtered.c.id_1 == target.id))
        or 0
    )
    role_counts = {
        (role or "legacy_unclassified"): count
        for role, count in db.execute(
            select(filtered.c.link_role, func.count())
            .select_from(filtered)
            .group_by(filtered.c.link_role)
        )
    }
    return InboundLinkSummary(
        total_occurrences=total,
        unique_source_pages=unique_sources,
        unique_anchor_texts=unique_anchor_texts,
        nofollow_occurrences=nofollow,
        self_link_occurrences=self_links,
        role_counts=role_counts,
    )


def _apply_page_filters(
    query: Select[tuple[ResourceSnapshot, WebResource, int, int, str]],
    search: str | None,
    status: int | None,
    host: str | None,
    path_prefix: str | None,
    depth: int | None,
    min_depth: int | None,
    max_depth: int | None,
    error_state: str,
) -> Select[tuple[ResourceSnapshot, WebResource, int, int, str]]:
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ResourceSnapshot.requested_url.ilike(pattern),
                ResourceSnapshot.final_url.ilike(pattern),
                ResourceSnapshot.page_title.ilike(pattern),
            )
        )
    if status is not None:
        query = query.where(ResourceSnapshot.http_status == status)
    if host:
        query = query.where(WebResource.host == host.lower())
    if path_prefix:
        query = query.where(WebResource.path.startswith(path_prefix))
    if depth is not None:
        query = query.where(ResourceSnapshot.crawl_depth == depth)
    if min_depth is not None:
        query = query.where(ResourceSnapshot.crawl_depth >= min_depth)
    if max_depth is not None:
        query = query.where(ResourceSnapshot.crawl_depth <= max_depth)
    if error_state == "with_errors":
        query = query.where(ResourceSnapshot.error_type.is_not(None))
    elif error_state == "without_errors":
        query = query.where(ResourceSnapshot.error_type.is_(None))
    return query


def _apply_inbound_filters(
    query: Select[tuple[ResourceOccurrence, ResourceSnapshot]],
    search: str | None,
    scope_decision: str | None,
    source_status: int | None,
    rel: str | None,
    link_role: str | None,
    source_snapshot: Any,
) -> Select[tuple[ResourceOccurrence, ResourceSnapshot]]:
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                source_snapshot.requested_url.ilike(pattern),
                source_snapshot.final_url.ilike(pattern),
                source_snapshot.page_title.ilike(pattern),
                ResourceOccurrence.anchor_text.ilike(pattern),
                ResourceOccurrence.raw_href.ilike(pattern),
                ResourceOccurrence.resolved_url.ilike(pattern),
            )
        )
    if scope_decision:
        query = query.where(ResourceOccurrence.scope_decision == scope_decision)
    if source_status is not None:
        query = query.where(source_snapshot.http_status == source_status)
    if rel:
        query = query.where(ResourceOccurrence.rel.ilike(f"%{rel}%"))
    if link_role == "legacy_unclassified":
        query = query.where(ResourceOccurrence.link_role.is_(None))
    elif link_role:
        query = query.where(ResourceOccurrence.link_role == link_role)
    return query
