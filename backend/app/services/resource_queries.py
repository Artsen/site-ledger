from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from sqlalchemy import Select, case, distinct, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.crawler.resource_classification import RESOURCE_KIND_LABELS, file_extension
from app.models import (
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.schemas.resources import (
    ResourceDetail,
    ResourceHistoryItem,
    ResourceHistoryList,
    ResourceInventoryItem,
    ResourceInventoryList,
    ResourceOccurrenceList,
    ResourceOccurrenceRead,
    ResourceSummary,
)

ResourceSort = Literal[
    "url",
    "kind",
    "mime_type",
    "http_status",
    "declared_size",
    "occurrence_count",
    "source_page_count",
    "observed",
    "in_scope_count",
    "first_discovered",
    "latest_discovered",
]


def list_scan_resources(
    db: Session,
    scan_id: int,
    *,
    search: str | None = None,
    resource_kind: str | None = None,
    mime_type: str | None = None,
    extension: str | None = None,
    host: str | None = None,
    status: int | None = None,
    evidence_state: Literal["any", "observed", "discovered_only"] = "any",
    scope_state: Literal["any", "in_scope", "out_of_scope"] = "any",
    location_state: Literal["any", "internal", "external"] = "any",
    min_size: int | None = None,
    max_size: int | None = None,
    has_multiple_source_pages: bool = False,
    sort: ResourceSort = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> ResourceInventoryList | None:
    from app.services.projection_queries import list_projected_resources
    from app.services.scan_projections import dynamic_metadata, resolve_projection_context

    context = resolve_projection_context(db, scan_id)

    projected = (
        list_projected_resources(
            db,
            scan_id,
            search=search,
            resource_kind=resource_kind,
            mime_type=mime_type,
            extension=extension,
            host=host,
            status=status,
            evidence_state=evidence_state,
            scope_state=scope_state,
            location_state=location_state,
            min_size=min_size,
            max_size=max_size,
            has_multiple_source_pages=has_multiple_source_pages,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
            build=context.build,
        )
        if context.build is not None
        else None
    )
    if projected is not None:
        return projected
    result = list_scan_resources_dynamic(
        db,
        scan_id,
        search=search,
        resource_kind=resource_kind,
        mime_type=mime_type,
        extension=extension,
        host=host,
        status=status,
        evidence_state=evidence_state,
        scope_state=scope_state,
        location_state=location_state,
        min_size=min_size,
        max_size=max_size,
        has_multiple_source_pages=has_multiple_source_pages,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
        _scan=context.scan,
    )
    if result is not None:
        result.projection = dynamic_metadata(context.scan)
    return result


def list_scan_resources_dynamic(
    db: Session,
    scan_id: int,
    *,
    search: str | None = None,
    resource_kind: str | None = None,
    mime_type: str | None = None,
    extension: str | None = None,
    host: str | None = None,
    status: int | None = None,
    evidence_state: Literal["any", "observed", "discovered_only"] = "any",
    scope_state: Literal["any", "in_scope", "out_of_scope"] = "any",
    location_state: Literal["any", "internal", "external"] = "any",
    min_size: int | None = None,
    max_size: int | None = None,
    has_multiple_source_pages: bool = False,
    sort: ResourceSort = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
    _scan: Scan | None = None,
) -> ResourceInventoryList | None:
    scan = _scan or db.get(Scan, scan_id)
    if scan is None:
        return None
    query = _resource_aggregate(_evidence_query(scan_id=scan_id))
    query = _apply_filters(
        query,
        search=search,
        resource_kind=resource_kind,
        mime_type=mime_type,
        extension=extension,
        host=host,
        status=status,
        evidence_state=evidence_state,
        scope_state=scope_state,
        location_state=location_state,
        internal_host=urlsplit(scan.starting_url).hostname,
        min_size=min_size,
        max_size=max_size,
        has_multiple_source_pages=has_multiple_source_pages,
    )
    return _execute_inventory(db, query, sort, direction, limit, offset)


def list_site_resources(
    db: Session,
    site_id: int,
    *,
    search: str | None = None,
    resource_kind: str | None = None,
    mime_type: str | None = None,
    extension: str | None = None,
    host: str | None = None,
    status: int | None = None,
    evidence_state: Literal["any", "observed", "discovered_only"] = "any",
    scope_state: Literal["any", "in_scope", "out_of_scope"] = "any",
    location_state: Literal["any", "internal", "external"] = "any",
    min_size: int | None = None,
    max_size: int | None = None,
    has_multiple_source_pages: bool = False,
    sort: ResourceSort = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> ResourceInventoryList | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    query = _resource_aggregate(_evidence_query(site_id=site_id))
    query = _apply_filters(
        query,
        search=search,
        resource_kind=resource_kind,
        mime_type=mime_type,
        extension=extension,
        host=host,
        status=status,
        evidence_state=evidence_state,
        scope_state=scope_state,
        location_state=location_state,
        internal_host=urlsplit(site.base_url).hostname,
        min_size=min_size,
        max_size=max_size,
        has_multiple_source_pages=has_multiple_source_pages,
    )
    return _execute_inventory(db, query, sort, direction, limit, offset)


def scan_resource_summary(db: Session, scan_id: int) -> ResourceSummary | None:
    from app.services.projection_queries import projected_resource_summary
    from app.services.scan_projections import dynamic_metadata, resolve_projection_context

    context = resolve_projection_context(db, scan_id)
    projected = (
        projected_resource_summary(db, scan_id, context.build)
        if context.build is not None
        else None
    )
    if projected is not None:
        return projected
    result = scan_resource_summary_dynamic(db, scan_id, context.scan)
    if result is not None:
        result.projection = dynamic_metadata(context.scan)
    return result


def scan_resource_summary_dynamic(
    db: Session, scan_id: int, _scan: Scan | None = None
) -> ResourceSummary | None:
    if _scan is None and db.get(Scan, scan_id) is None:
        return None
    return _summary(db, _resource_aggregate(_evidence_query(scan_id=scan_id)))


def site_resource_summary(db: Session, site_id: int) -> ResourceSummary | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    return _summary(db, _resource_aggregate(_evidence_query(site_id=site_id)))


def get_scan_resource(db: Session, scan_id: int, resource_id: int) -> ResourceDetail | None:
    query = _resource_aggregate(_evidence_query(scan_id=scan_id)).where(
        WebResource.id == resource_id
    )
    listed = _execute_inventory(db, query, "url", "asc", 1, 0)
    if not listed.items:
        return None
    item = listed.items[0]
    snapshot = db.get(ResourceSnapshot, item.snapshot_id) if item.snapshot_id else None
    return ResourceDetail(
        resource=item,
        requested_url=snapshot.requested_url if snapshot else None,
        response_body_state=snapshot.response_body_state if snapshot else None,
        inspected_prefix_byte_count=snapshot.inspected_prefix_byte_count if snapshot else 0,
    )


def get_site_resource(db: Session, site_id: int, resource_id: int) -> ResourceDetail | None:
    query = _resource_aggregate(_evidence_query(site_id=site_id)).where(
        WebResource.id == resource_id
    )
    listed = _execute_inventory(db, query, "url", "asc", 1, 0)
    if not listed.items:
        return None
    item = listed.items[0]
    snapshot = db.get(ResourceSnapshot, item.snapshot_id) if item.snapshot_id else None
    return ResourceDetail(
        resource=item,
        requested_url=snapshot.requested_url if snapshot else None,
        response_body_state=snapshot.response_body_state if snapshot else None,
        inspected_prefix_byte_count=snapshot.inspected_prefix_byte_count if snapshot else 0,
    )


def list_resource_occurrences(
    db: Session,
    resource_id: int,
    *,
    scan_id: int | None = None,
    site_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ResourceOccurrenceList:
    source = aliased(ResourceSnapshot)
    anchor = (
        select(
            ResourceOccurrence.id.label("occurrence_id"),
            literal("anchor").label("occurrence_source"),
            source.id.label("source_snapshot_id"),
            source.resource_id.label("source_resource_id"),
            func.coalesce(source.final_url, source.requested_url).label("source_url"),
            source.page_title.label("source_title"),
            ResourceOccurrence.relation_type,
            literal(None).label("element_tag"),
            literal(None).label("attribute_name"),
            ResourceOccurrence.raw_href.label("raw_url"),
            ResourceOccurrence.resolved_url,
            ResourceOccurrence.anchor_text,
            literal(None).label("alt_text"),
            literal(None).label("srcset_descriptor"),
            ResourceOccurrence.rel,
            literal(None).label("media"),
            literal(None).label("type_hint"),
            literal(None).label("as_hint"),
            ResourceOccurrence.scope_decision,
            ResourceOccurrence.in_scope,
            ResourceOccurrence.dom_path,
            ResourceOccurrence.discovered_at,
            source.scan_id.label("scan_id"),
        )
        .join(source, source.id == ResourceOccurrence.source_snapshot_id)
        .where(ResourceOccurrence.target_resource_id == resource_id)
    )
    embedded = (
        select(
            ResourceReferenceOccurrence.id.label("occurrence_id"),
            literal("embedded").label("occurrence_source"),
            source.id.label("source_snapshot_id"),
            source.resource_id.label("source_resource_id"),
            func.coalesce(source.final_url, source.requested_url).label("source_url"),
            source.page_title.label("source_title"),
            ResourceReferenceOccurrence.relation_type,
            ResourceReferenceOccurrence.element_tag,
            ResourceReferenceOccurrence.attribute_name,
            ResourceReferenceOccurrence.raw_url,
            ResourceReferenceOccurrence.resolved_url,
            literal(None).label("anchor_text"),
            ResourceReferenceOccurrence.alt_text,
            ResourceReferenceOccurrence.srcset_descriptor,
            ResourceReferenceOccurrence.rel,
            ResourceReferenceOccurrence.media,
            ResourceReferenceOccurrence.type_hint,
            ResourceReferenceOccurrence.as_hint,
            ResourceReferenceOccurrence.scope_decision,
            ResourceReferenceOccurrence.in_scope,
            ResourceReferenceOccurrence.dom_path,
            ResourceReferenceOccurrence.discovered_at,
            source.scan_id.label("scan_id"),
        )
        .join(source, source.id == ResourceReferenceOccurrence.source_snapshot_id)
        .where(ResourceReferenceOccurrence.target_resource_id == resource_id)
    )
    combined = union_all(anchor, embedded).subquery()
    query = select(combined)
    if scan_id is not None:
        query = query.where(combined.c.scan_id == scan_id)
    if site_id is not None:
        query = query.join(Scan, Scan.id == combined.c.scan_id).where(
            Scan.website_property_id == site_id
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(combined.c.discovered_at, combined.c.occurrence_id)
        .limit(limit)
        .offset(offset)
    ).mappings()
    return ResourceOccurrenceList(
        items=[
            ResourceOccurrenceRead(**{key: row[key] for key in ResourceOccurrenceRead.model_fields})
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def list_site_resource_history(
    db: Session, site_id: int, resource_id: int, *, limit: int = 50, offset: int = 0
) -> ResourceHistoryList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    evidence = _evidence_query(site_id=site_id).subquery()
    aggregate = (
        select(
            evidence.c.scan_id,
            func.max(evidence.c.snapshot_id).label("snapshot_id"),
            func.max(case((evidence.c.observed.is_(True), 1), else_=0)).label("observed"),
            func.coalesce(
                func.max(case((evidence.c.observed.is_(True), evidence.c.kind))),
                func.max(evidence.c.kind),
            ).label("effective_kind"),
            func.max(evidence.c.mime_type).label("mime_type"),
            func.max(evidence.c.http_status).label("http_status"),
            func.max(evidence.c.declared_size).label("declared_size"),
            func.sum(case((evidence.c.occurrence_source != "observed", 1), else_=0)).label(
                "occurrence_count"
            ),
            func.max(evidence.c.evidence_at).label("observed_at"),
        )
        .where(evidence.c.resource_id == resource_id)
        .group_by(evidence.c.scan_id)
        .subquery()
    )
    query = select(
        aggregate,
        Scan.created_at.label("scan_created_at"),
        Scan.status.label("scan_status"),
    ).join(Scan, Scan.id == aggregate.c.scan_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(Scan.created_at.desc(), Scan.id.desc()).limit(limit).offset(offset)
    ).mappings()
    return ResourceHistoryList(
        items=[
            ResourceHistoryItem(
                resource_id=resource_id,
                scan_id=row["scan_id"],
                scan_created_at=row["scan_created_at"],
                scan_status=row["scan_status"],
                observed=bool(row["observed"]),
                discovered_only=not bool(row["observed"]),
                effective_kind=row["effective_kind"] or "unknown",
                normalized_mime_type=row["mime_type"],
                http_status=row["http_status"],
                declared_content_length=row["declared_size"],
                occurrence_count=row["occurrence_count"] or 0,
                observed_at=row["observed_at"],
                snapshot_id=row["snapshot_id"],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _evidence_query(*, scan_id: int | None = None, site_id: int | None = None) -> Any:
    source = aliased(ResourceSnapshot)
    observed_rank = func.row_number().over(
        partition_by=ResourceSnapshot.resource_id,
        order_by=(ResourceSnapshot.fetched_at.desc(), ResourceSnapshot.id.desc()),
    )
    observed = select(
        ResourceSnapshot.resource_id.label("resource_id"),
        ResourceSnapshot.scan_id.label("scan_id"),
        ResourceSnapshot.id.label("snapshot_id"),
        literal(True).label("observed"),
        ResourceSnapshot.representation_kind.label("kind"),
        ResourceSnapshot.representation_rule.label("rule"),
        ResourceSnapshot.normalized_mime_type.label("mime_type"),
        ResourceSnapshot.file_extension.label("extension"),
        ResourceSnapshot.final_url.label("final_url"),
        ResourceSnapshot.http_status.label("http_status"),
        ResourceSnapshot.content_disposition_filename.label("filename"),
        ResourceSnapshot.declared_content_length.label("declared_size"),
        ResourceSnapshot.network_bytes_transferred.label("network_bytes"),
        ResourceSnapshot.fetched_at.label("fetched_at"),
        ResourceSnapshot.response_time_ms.label("response_time_ms"),
        literal("observed").label("occurrence_source"),
        literal(None).label("occurrence_id"),
        literal(None).label("source_snapshot_id"),
        literal(None).label("in_scope"),
        ResourceSnapshot.fetched_at.label("evidence_at"),
        observed_rank.label("observed_rank"),
    ).where(ResourceSnapshot.representation_kind.not_in(("html_page", "unknown")))
    embedded = select(
        ResourceReferenceOccurrence.target_resource_id.label("resource_id"),
        source.scan_id.label("scan_id"),
        literal(None).label("snapshot_id"),
        literal(False).label("observed"),
        ResourceReferenceOccurrence.inferred_kind.label("kind"),
        ResourceReferenceOccurrence.classification_rule.label("rule"),
        literal(None).label("mime_type"),
        literal(None).label("extension"),
        literal(None).label("final_url"),
        literal(None).label("http_status"),
        literal(None).label("filename"),
        literal(None).label("declared_size"),
        literal(None).label("network_bytes"),
        literal(None).label("fetched_at"),
        literal(None).label("response_time_ms"),
        literal("embedded").label("occurrence_source"),
        ResourceReferenceOccurrence.id.label("occurrence_id"),
        source.id.label("source_snapshot_id"),
        ResourceReferenceOccurrence.in_scope.label("in_scope"),
        ResourceReferenceOccurrence.discovered_at.label("evidence_at"),
        literal(None).label("observed_rank"),
    ).join(source, source.id == ResourceReferenceOccurrence.source_snapshot_id)
    anchor_kind = _extension_kind_case(WebResource.path)
    anchor = (
        select(
            ResourceOccurrence.target_resource_id.label("resource_id"),
            source.scan_id.label("scan_id"),
            literal(None).label("snapshot_id"),
            literal(False).label("observed"),
            anchor_kind.label("kind"),
            literal("extension").label("rule"),
            literal(None).label("mime_type"),
            literal(None).label("extension"),
            literal(None).label("final_url"),
            literal(None).label("http_status"),
            literal(None).label("filename"),
            literal(None).label("declared_size"),
            literal(None).label("network_bytes"),
            literal(None).label("fetched_at"),
            literal(None).label("response_time_ms"),
            literal("anchor").label("occurrence_source"),
            ResourceOccurrence.id.label("occurrence_id"),
            source.id.label("source_snapshot_id"),
            ResourceOccurrence.in_scope.label("in_scope"),
            ResourceOccurrence.discovered_at.label("evidence_at"),
            literal(None).label("observed_rank"),
        )
        .join(source, source.id == ResourceOccurrence.source_snapshot_id)
        .join(WebResource, WebResource.id == ResourceOccurrence.target_resource_id)
        .where(ResourceOccurrence.target_resource_id.is_not(None), anchor_kind != "unknown")
    )
    if scan_id is not None:
        observed = observed.where(ResourceSnapshot.scan_id == scan_id)
        embedded = embedded.where(source.scan_id == scan_id)
        anchor = anchor.where(source.scan_id == scan_id)
    if site_id is not None:
        observed = observed.join(Scan, Scan.id == ResourceSnapshot.scan_id).where(
            Scan.website_property_id == site_id
        )
        embedded = embedded.join(Scan, Scan.id == source.scan_id).where(
            Scan.website_property_id == site_id
        )
        anchor = anchor.join(Scan, Scan.id == source.scan_id).where(
            Scan.website_property_id == site_id
        )
    return union_all(observed, embedded, anchor)


def _resource_aggregate(evidence_query: Select[Any]) -> Select[Any]:
    evidence = evidence_query.subquery()
    latest_observed = evidence.c.observed_rank == 1
    observed_kind = func.max(case((latest_observed, evidence.c.kind)))
    observed_rule = func.max(case((latest_observed, evidence.c.rule)))
    observed_count = func.sum(case((evidence.c.observed.is_(True), 1), else_=0))
    return (
        select(
            WebResource.id.label("resource_id"),
            WebResource.normalized_url,
            WebResource.host,
            WebResource.path,
            func.coalesce(
                func.max(evidence.c.extension), _extension_value_case(WebResource.path)
            ).label("file_extension"),
            func.coalesce(observed_kind, func.max(evidence.c.kind), "unknown").label(
                "effective_kind"
            ),
            func.coalesce(observed_rule, func.max(evidence.c.rule), "fallback_unknown").label(
                "classification_source"
            ),
            observed_count.label("observed_count"),
            func.max(case((latest_observed, evidence.c.snapshot_id))).label("snapshot_id"),
            func.max(case((latest_observed, evidence.c.final_url))).label("final_url"),
            func.max(case((latest_observed, evidence.c.http_status))).label("http_status"),
            func.max(case((latest_observed, evidence.c.mime_type))).label("mime_type"),
            func.max(case((latest_observed, evidence.c.filename))).label("filename"),
            func.max(case((latest_observed, evidence.c.declared_size))).label("declared_size"),
            func.max(case((latest_observed, evidence.c.network_bytes))).label("network_bytes"),
            func.max(case((latest_observed, evidence.c.fetched_at))).label("fetched_at"),
            func.max(case((latest_observed, evidence.c.response_time_ms))).label(
                "response_time_ms"
            ),
            func.sum(case((evidence.c.occurrence_source != "observed", 1), else_=0)).label(
                "occurrence_count"
            ),
            func.count(distinct(evidence.c.source_snapshot_id)).label("source_page_count"),
            func.sum(case((evidence.c.occurrence_source == "anchor", 1), else_=0)).label(
                "anchor_count"
            ),
            func.sum(case((evidence.c.occurrence_source == "embedded", 1), else_=0)).label(
                "embedded_count"
            ),
            func.sum(case((evidence.c.in_scope.is_(True), 1), else_=0)).label("in_scope_count"),
            func.sum(case((evidence.c.in_scope.is_(False), 1), else_=0)).label("out_scope_count"),
            func.min(
                case((evidence.c.occurrence_source != "observed", evidence.c.evidence_at))
            ).label("first_discovered"),
            func.max(
                case((evidence.c.occurrence_source != "observed", evidence.c.evidence_at))
            ).label("latest_discovered"),
            func.count(distinct(evidence.c.scan_id)).label("scan_count"),
        )
        .join(WebResource, WebResource.id == evidence.c.resource_id)
        .group_by(WebResource.id)
    )


def _apply_filters(query: Select[Any], **filters: Any) -> Select[Any]:
    if filters["search"]:
        pattern = f"%{filters['search']}%"
        query = query.having(
            or_(WebResource.normalized_url.ilike(pattern), WebResource.path.ilike(pattern))
        )
    if filters["resource_kind"]:
        query = query.having(query.selected_columns.effective_kind == filters["resource_kind"])
    if filters["mime_type"]:
        query = query.having(query.selected_columns.mime_type.ilike(f"%{filters['mime_type']}%"))
    if filters["extension"]:
        query = query.having(
            query.selected_columns.file_extension == filters["extension"].casefold()
        )
    if filters["host"]:
        query = query.having(WebResource.host == filters["host"].casefold())
    if filters["status"] is not None:
        query = query.having(query.selected_columns.http_status == filters["status"])
    if filters["evidence_state"] == "observed":
        query = query.having(query.selected_columns.observed_count > 0)
    elif filters["evidence_state"] == "discovered_only":
        query = query.having(query.selected_columns.observed_count == 0)
    if filters["scope_state"] == "in_scope":
        query = query.having(query.selected_columns.in_scope_count > 0)
    elif filters["scope_state"] == "out_of_scope":
        query = query.having(query.selected_columns.out_scope_count > 0)
    if filters["location_state"] == "internal" and filters["internal_host"]:
        query = query.having(WebResource.host == filters["internal_host"].casefold())
    elif filters["location_state"] == "external" and filters["internal_host"]:
        query = query.having(WebResource.host != filters["internal_host"].casefold())
    if filters["min_size"] is not None:
        query = query.having(query.selected_columns.declared_size >= filters["min_size"])
    if filters["max_size"] is not None:
        query = query.having(query.selected_columns.declared_size <= filters["max_size"])
    if filters["has_multiple_source_pages"]:
        query = query.having(query.selected_columns.source_page_count > 1)
    return query


def _execute_inventory(
    db: Session,
    query: Select[Any],
    sort: ResourceSort,
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> ResourceInventoryList:
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_map = {
        "url": query.selected_columns.normalized_url,
        "kind": query.selected_columns.effective_kind,
        "mime_type": query.selected_columns.mime_type,
        "http_status": query.selected_columns.http_status,
        "declared_size": query.selected_columns.declared_size,
        "occurrence_count": query.selected_columns.occurrence_count,
        "source_page_count": query.selected_columns.source_page_count,
        "observed": query.selected_columns.observed_count,
        "in_scope_count": query.selected_columns.in_scope_count,
        "first_discovered": query.selected_columns.first_discovered,
        "latest_discovered": query.selected_columns.latest_discovered,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.execute(query.order_by(order, WebResource.id).limit(limit).offset(offset)).mappings()
    items = [
        ResourceInventoryItem(
            resource_id=row["resource_id"],
            normalized_url=row["normalized_url"],
            host=row["host"],
            path=row["path"],
            file_extension=row["file_extension"] or file_extension(row["normalized_url"]),
            effective_kind=row["effective_kind"],
            effective_kind_label=RESOURCE_KIND_LABELS.get(row["effective_kind"], "Unknown"),
            classification_source=row["classification_source"],
            observed=(row["observed_count"] or 0) > 0,
            discovered_only=(row["observed_count"] or 0) == 0,
            snapshot_id=row["snapshot_id"],
            final_url=row["final_url"],
            http_status=row["http_status"],
            normalized_mime_type=row["mime_type"],
            content_disposition_filename=row["filename"],
            declared_content_length=row["declared_size"],
            network_bytes_transferred=row["network_bytes"],
            fetched_at=row["fetched_at"],
            response_time_ms=row["response_time_ms"],
            occurrence_count=row["occurrence_count"] or 0,
            source_page_count=row["source_page_count"] or 0,
            anchor_occurrence_count=row["anchor_count"] or 0,
            embedded_occurrence_count=row["embedded_count"] or 0,
            in_scope_occurrence_count=row["in_scope_count"] or 0,
            out_of_scope_occurrence_count=row["out_scope_count"] or 0,
            first_discovered_at=row["first_discovered"],
            latest_discovered_at=row["latest_discovered"],
            observation_count=row["observed_count"] or 0,
            scan_count=row["scan_count"] or 0,
        )
        for row in rows
    ]
    return ResourceInventoryList(items=items, total=total, limit=limit, offset=offset)


def _summary(db: Session, query: Select[Any]) -> ResourceSummary:
    aggregate = query.subquery()
    row = db.execute(
        select(
            func.count(),
            func.sum(case((aggregate.c.observed_count > 0, 1), else_=0)),
            func.sum(case((aggregate.c.observed_count == 0, 1), else_=0)),
            func.sum(aggregate.c.occurrence_count),
        ).select_from(aggregate)
    ).one()
    kind_counts = {
        kind: count
        for kind, count in db.execute(
            select(aggregate.c.effective_kind, func.count())
            .select_from(aggregate)
            .group_by(aggregate.c.effective_kind)
        )
    }
    return ResourceSummary(
        unique_resources=row[0] or 0,
        observed_resources=row[1] or 0,
        discovered_only_resources=row[2] or 0,
        total_occurrences=row[3] or 0,
        kind_counts=kind_counts,
    )


def _extension_kind_case(path: Any) -> Any:
    lower = func.lower(path)
    groups = {
        "image": (".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"),
        "document": (
            ".csv",
            ".doc",
            ".docx",
            ".ods",
            ".odt",
            ".pdf",
            ".ppt",
            ".pptx",
            ".rtf",
            ".txt",
            ".xls",
            ".xlsx",
        ),
        "stylesheet": (".css",),
        "script": (".cjs", ".js", ".mjs"),
        "font": (".eot", ".otf", ".ttf", ".woff", ".woff2"),
        "video": (".avi", ".mkv", ".mov", ".mp4", ".webm"),
        "audio": (".flac", ".m4a", ".mp3", ".ogg", ".wav"),
        "archive": (".7z", ".gz", ".jar", ".rar", ".tar", ".zip"),
        "feed": (".atom", ".rss"),
        "manifest": (".webmanifest",),
        "structured_data": (".json", ".jsonld", ".xml"),
    }
    clauses = []
    for kind, suffixes in groups.items():
        clauses.append((or_(*(lower.endswith(suffix) for suffix in suffixes)), kind))
    return case(*clauses, else_="unknown")


def _extension_value_case(path: Any) -> Any:
    lower = func.lower(path)
    extensions = (
        "avif",
        "gif",
        "ico",
        "jpeg",
        "jpg",
        "png",
        "svg",
        "webp",
        "csv",
        "doc",
        "docx",
        "ods",
        "odt",
        "pdf",
        "ppt",
        "pptx",
        "rtf",
        "txt",
        "xls",
        "xlsx",
        "css",
        "cjs",
        "js",
        "mjs",
        "eot",
        "otf",
        "ttf",
        "woff",
        "woff2",
        "avi",
        "mkv",
        "mov",
        "mp4",
        "webm",
        "flac",
        "m4a",
        "mp3",
        "ogg",
        "wav",
        "7z",
        "gz",
        "jar",
        "rar",
        "tar",
        "zip",
        "atom",
        "rss",
        "webmanifest",
        "json",
        "jsonld",
        "xml",
    )
    return case(
        *((lower.endswith(f".{extension}"), extension) for extension in extensions), else_=None
    )
