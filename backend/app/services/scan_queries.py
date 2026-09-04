from typing import Any, Literal

from sqlalchemy import Select, distinct, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.models import (
    RenderedObservation,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
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
    SnapshotRead,
)


def get_snapshot_detail(db: Session, snapshot_id: int) -> SnapshotRead | None:
    row = db.execute(
        select(
            ResourceSnapshot,
            Scan.website_property_id,
            WebsiteProperty.name,
            SitePage.id,
        )
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .outerjoin(WebsiteProperty, WebsiteProperty.id == Scan.website_property_id)
        .outerjoin(
            SitePage,
            (SitePage.website_property_id == Scan.website_property_id)
            & (SitePage.resource_id == ResourceSnapshot.resource_id),
        )
        .options(joinedload(ResourceSnapshot.blob))
        .where(ResourceSnapshot.id == snapshot_id)
    ).one_or_none()
    if row is None:
        return None
    snapshot, website_property_id, website_property_name, site_page_id = row
    content_type = (snapshot.content_type or "").lower()
    is_html_page = bool(
        snapshot.representation_kind == "html_page"
        or snapshot.html_blob_id is not None
        or content_type.startswith("text/html")
        or content_type.startswith("application/xhtml+xml")
    )
    result = SnapshotRead.model_validate(snapshot, from_attributes=True)
    result.html_raw_byte_size = snapshot.blob.raw_byte_size if snapshot.blob else None
    result.html_stored_byte_size = snapshot.blob.stored_byte_size if snapshot.blob else None
    result.website_property_id = website_property_id
    result.website_property_name = website_property_name
    result.site_page_id = site_page_id
    result.has_persistent_page = bool(is_html_page and site_page_id is not None)
    result.is_html_page = is_html_page
    return result


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
        "created_at",
        "started_at",
        "finished_at",
        "status",
        "starting_url",
        "duration",
        "discovered_count",
        "stop_reason",
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
        "duration": func.julianday(func.coalesce(Scan.finished_at, Scan.started_at))
        - func.julianday(Scan.started_at),
        "discovered_count": Scan.discovered_count,
        "stop_reason": Scan.stop_reason,
    }
    order_col = sort_map[sort]
    order = order_col.desc() if direction == "desc" else order_col.asc()
    id_order = Scan.id.desc() if direction == "desc" else Scan.id.asc()
    scans = list(db.scalars(query.order_by(order, id_order).limit(limit).offset(offset)))
    from app.services.scan_render_authority import scan_reads

    return ScanHistory(items=scan_reads(db, scans), total=total, limit=limit, offset=offset)


def list_scan_pages_routed(
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
    sort: Literal[
        "requested_url",
        "status",
        "title",
        "depth",
        "content_type",
        "duration",
        "inbound",
        "rendered_state",
        "error",
    ],
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
    rendered_state: Literal[
        "any",
        "not_requested",
        "captured",
        "captured_with_warnings",
        "failed",
        "skipped",
        "interrupted",
    ] = "any",
) -> PageList:
    from app.services.projection_queries import list_projected_pages
    from app.services.scan_projections import dynamic_metadata, resolve_projection_context

    context = resolve_projection_context(db, scan_id)

    projected = (
        list_projected_pages(
            db,
            scan_id,
            search,
            status,
            host,
            path_prefix,
            depth,
            min_depth,
            max_depth,
            error_state,
            sort,
            direction,
            limit,
            offset,
            rendered_state,
            context.build,
        )
        if context.build is not None
        else None
    )
    if projected is not None:
        return projected
    result = list_scan_pages_dynamic(
        db,
        scan_id,
        search,
        status,
        host,
        path_prefix,
        depth,
        min_depth,
        max_depth,
        error_state,
        sort,
        direction,
        limit,
        offset,
        rendered_state,
    )
    result.projection = dynamic_metadata(context.scan)
    return result


def list_scan_pages_dynamic(
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
    sort: Literal[
        "requested_url",
        "status",
        "title",
        "depth",
        "content_type",
        "duration",
        "inbound",
        "rendered_state",
        "error",
    ],
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
    rendered_state: Literal[
        "any",
        "not_requested",
        "captured",
        "captured_with_warnings",
        "failed",
        "skipped",
        "interrupted",
    ] = "any",
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
        .where(
            ResourceSnapshot.scan_id == scan_id,
            or_(
                ResourceSnapshot.representation_kind == "html_page",
                ResourceSnapshot.html_blob_id.is_not(None),
                ResourceSnapshot.content_type.ilike("text/html%"),
                ResourceSnapshot.content_type.ilike("application/xhtml+xml%"),
            ),
        )
    )
    base = _apply_page_filters(
        base, search, status, host, path_prefix, depth, min_depth, max_depth, error_state
    )
    if rendered_state == "not_requested":
        base = base.where(RenderedObservation.id.is_(None))
    elif rendered_state == "captured":
        base = base.where(RenderedObservation.capture_state == "completed")
    elif rendered_state == "captured_with_warnings":
        base = base.where(RenderedObservation.capture_state == "completed_with_warnings")
    elif rendered_state != "any":
        base = base.where(RenderedObservation.capture_state == rendered_state)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    sort_map = {
        "requested_url": ResourceSnapshot.requested_url,
        "status": ResourceSnapshot.http_status,
        "title": ResourceSnapshot.page_title,
        "depth": ResourceSnapshot.crawl_depth,
        "content_type": ResourceSnapshot.content_type,
        "duration": ResourceSnapshot.response_time_ms,
        "inbound": func.coalesce(inbound.c.inbound_occurrence_count, 0),
        "rendered_state": func.coalesce(RenderedObservation.capture_state, "not_requested"),
        "error": ResourceSnapshot.error_type,
    }
    order_col = sort_map[sort]
    order = order_col.desc() if direction == "desc" else order_col.asc()
    id_order = ResourceSnapshot.id.desc() if direction == "desc" else ResourceSnapshot.id.asc()
    rows = db.execute(base.order_by(order, id_order).limit(limit).offset(offset)).all()
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
    sort: Literal[
        "source_url",
        "source_status",
        "source_depth",
        "anchor_text",
        "link_role",
        "raw_href",
        "rel",
        "scope_decision",
        "discovered_at",
    ] = "source_url",
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
        "source_depth": source_snapshot.crawl_depth,
        "link_role": ResourceOccurrence.link_role,
        "raw_href": ResourceOccurrence.raw_href,
        "rel": ResourceOccurrence.rel,
        "discovered_at": ResourceOccurrence.discovered_at,
    }
    rows = db.execute(
        base.order_by(
            sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc(),
            ResourceOccurrence.id.desc() if direction == "desc" else ResourceOccurrence.id.asc(),
        )
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


# Keep the raw query as the stable service-level equivalence oracle. API routes use
# list_scan_pages_routed so ordinary terminal-Scan reads can select projections.
list_scan_pages = list_scan_pages_dynamic
