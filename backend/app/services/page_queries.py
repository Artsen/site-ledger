from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import HtmlParseArtifact, ResourceSnapshot, Scan, WebResource, WebsiteProperty
from app.schemas.scans import (
    PageObservationList,
    PageObservationRead,
    PersistentPageDetail,
    PersistentPageList,
    PersistentPageRead,
)


def list_site_pages(
    db: Session,
    site_id: int,
    *,
    search: str | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    sort: Literal["url", "observations", "first_observed", "latest_observed"] = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> PersistentPageList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    latest_snapshot = aliased(ResourceSnapshot)
    latest_id = (
        select(latest_snapshot.id)
        .join(Scan, latest_snapshot.scan_id == Scan.id)
        .where(
            Scan.website_property_id == site_id,
            latest_snapshot.resource_id == WebResource.id,
        )
        .order_by(latest_snapshot.fetched_at.desc(), latest_snapshot.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    base = (
        select(
            WebResource,
            func.count(ResourceSnapshot.id).label("observation_count"),
            func.min(ResourceSnapshot.fetched_at).label("first_observed_at"),
            func.max(ResourceSnapshot.fetched_at).label("latest_observed_at"),
            latest_id.label("latest_snapshot_id"),
        )
        .join(ResourceSnapshot, ResourceSnapshot.resource_id == WebResource.id)
        .join(Scan, ResourceSnapshot.scan_id == Scan.id)
        .where(Scan.website_property_id == site_id)
        .group_by(WebResource.id)
    )
    base = _apply_page_filters(base, search, host, path_prefix)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    sort_map: dict[str, Any] = {
        "url": WebResource.normalized_url,
        "observations": "observation_count",
        "first_observed": "first_observed_at",
        "latest_observed": "latest_observed_at",
    }
    sort_col = sort_map[sort]
    if isinstance(sort_col, str):
        ordered = base.order_by(
            getattr(base.selected_columns, sort_col).desc()
            if direction == "desc"
            else getattr(base.selected_columns, sort_col).asc()
        )
    else:
        ordered = base.order_by(sort_col.desc() if direction == "desc" else sort_col.asc())
    rows = db.execute(ordered.limit(limit).offset(offset)).all()
    latest_ids = [latest_snapshot_id for *_rest, latest_snapshot_id in rows if latest_snapshot_id]
    latest_by_id = _latest_snapshot_map(db, latest_ids)
    return PersistentPageList(
        items=[
            _page_read(
                resource,
                observation_count,
                first_observed_at,
                latest_observed_at,
                latest_by_id.get(latest_snapshot_id),
            )
            for (
                resource,
                observation_count,
                first_observed_at,
                latest_observed_at,
                latest_snapshot_id,
            ) in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_site_page(db: Session, site_id: int, resource_id: int) -> PersistentPageDetail | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    page = _page_for_resource(db, site_id, resource_id)
    if page is None:
        return None
    return PersistentPageDetail(page=page, site_id=site.id, site_name=site.name)


def list_page_observations(
    db: Session,
    site_id: int,
    resource_id: int,
    *,
    scope: Literal["site", "all"] = "site",
    limit: int = 50,
    offset: int = 0,
) -> PageObservationList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    artifact = aliased(HtmlParseArtifact)
    query = (
        select(ResourceSnapshot, Scan, WebsiteProperty, artifact)
        .join(Scan, ResourceSnapshot.scan_id == Scan.id)
        .outerjoin(WebsiteProperty, Scan.website_property_id == WebsiteProperty.id)
        .outerjoin(artifact, ResourceSnapshot.parse_artifact_id == artifact.id)
        .where(ResourceSnapshot.resource_id == resource_id)
    )
    if scope == "site":
        query = query.where(Scan.website_property_id == site_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(ResourceSnapshot.fetched_at.desc(), ResourceSnapshot.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PageObservationList(
        items=[
            PageObservationRead(
                snapshot_id=snapshot.id,
                scan_id=scan.id,
                site_id=site.id if site else None,
                site_name=site.name if site else None,
                scan_created_at=scan.created_at,
                observed_at=snapshot.fetched_at,
                requested_url=snapshot.requested_url,
                final_url=snapshot.final_url,
                http_status=snapshot.http_status,
                retrieval_http_status=snapshot.retrieval_http_status,
                fetch_state=snapshot.fetch_state,
                error_type=snapshot.error_type,
                crawl_depth=snapshot.crawl_depth,
                response_time_ms=snapshot.response_time_ms,
                content_type=snapshot.content_type,
                raw_html_sha256=snapshot.raw_html_sha256,
                head_sha256=snapshot.head_sha256,
                page_title=snapshot.page_title,
                canonical_url=snapshot.canonical_url,
                retrieval_method=snapshot.retrieval_method,
                parse_method=snapshot.parse_method,
                content_blob_id=snapshot.html_blob_id,
                parse_artifact_id=snapshot.parse_artifact_id,
                reused_from_snapshot_id=snapshot.reused_from_snapshot_id,
                network_bytes_transferred=snapshot.network_bytes_transferred,
                parser_version=artifact_row.parser_version if artifact_row else None,
            )
            for snapshot, scan, site, artifact_row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _page_for_resource(db: Session, site_id: int, resource_id: int) -> PersistentPageRead | None:
    latest_snapshot = aliased(ResourceSnapshot)
    latest_id = (
        select(latest_snapshot.id)
        .join(Scan, latest_snapshot.scan_id == Scan.id)
        .where(
            Scan.website_property_id == site_id,
            latest_snapshot.resource_id == WebResource.id,
        )
        .order_by(latest_snapshot.fetched_at.desc(), latest_snapshot.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    row = db.execute(
        select(
            WebResource,
            func.count(ResourceSnapshot.id).label("observation_count"),
            func.min(ResourceSnapshot.fetched_at).label("first_observed_at"),
            func.max(ResourceSnapshot.fetched_at).label("latest_observed_at"),
            latest_id.label("latest_snapshot_id"),
        )
        .join(ResourceSnapshot, ResourceSnapshot.resource_id == WebResource.id)
        .join(Scan, ResourceSnapshot.scan_id == Scan.id)
        .where(Scan.website_property_id == site_id, WebResource.id == resource_id)
        .group_by(WebResource.id)
    ).one_or_none()
    if row is None:
        return None
    resource, observation_count, first_observed_at, latest_observed_at, latest_snapshot_id = row
    latest_snapshot_obj = (
        db.get(ResourceSnapshot, latest_snapshot_id) if latest_snapshot_id is not None else None
    )
    return _page_read(
        resource,
        observation_count,
        first_observed_at,
        latest_observed_at,
        latest_snapshot_obj,
    )


def _apply_page_filters(
    query: Select[tuple[WebResource, int, object, object, int]],
    search: str | None,
    host: str | None,
    path_prefix: str | None,
) -> Select[tuple[WebResource, int, object, object, int]]:
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                WebResource.normalized_url.ilike(pattern),
                WebResource.path.ilike(pattern),
            )
        )
    if host:
        query = query.where(WebResource.host == host.lower())
    if path_prefix:
        query = query.where(WebResource.path.startswith(path_prefix))
    return query


def _latest_snapshot_map(
    db: Session, snapshot_ids: list[int | None]
) -> dict[int | None, ResourceSnapshot]:
    ids = [snapshot_id for snapshot_id in snapshot_ids if snapshot_id is not None]
    if not ids:
        return {}
    snapshots = db.scalars(select(ResourceSnapshot).where(ResourceSnapshot.id.in_(ids)))
    return {snapshot.id: snapshot for snapshot in snapshots}


def _page_read(
    resource: WebResource,
    observation_count: int,
    first_observed_at: object,
    latest_observed_at: object,
    latest_snapshot: ResourceSnapshot | None,
) -> PersistentPageRead:
    return PersistentPageRead(
        resource_id=resource.id,
        normalized_url=resource.normalized_url,
        host=resource.host,
        path=resource.path,
        query=resource.query,
        observation_count=observation_count,
        first_observed_at=first_observed_at,
        latest_observed_at=latest_observed_at,
        latest_snapshot_id=latest_snapshot.id if latest_snapshot else None,
        latest_scan_id=latest_snapshot.scan_id if latest_snapshot else None,
        latest_http_status=latest_snapshot.http_status if latest_snapshot else None,
        latest_title=latest_snapshot.page_title if latest_snapshot else None,
        latest_retrieval_method=latest_snapshot.retrieval_method if latest_snapshot else None,
        latest_parse_method=latest_snapshot.parse_method if latest_snapshot else None,
        latest_reused_from_snapshot_id=latest_snapshot.reused_from_snapshot_id
        if latest_snapshot
        else None,
    )
