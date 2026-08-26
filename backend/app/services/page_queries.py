from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    HtmlParseArtifact,
    Note,
    PageCategory,
    PageCategoryAssignment,
    RenderedObservation,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.page_workspaces import PageCategoryRead
from app.schemas.scans import (
    PageObservationList,
    PageObservationRead,
    PersistentPageDetail,
    PersistentPageList,
    PersistentPageRead,
)
from app.services.url_identity import resolve_resource_id


def list_site_pages(
    db: Session,
    site_id: int,
    *,
    search: str | None = None,
    host: str | None = None,
    path_prefix: str | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    workflow_status: str | None = None,
    owner: str | None = None,
    unassigned_owner: bool = False,
    has_notes: bool | None = None,
    min_observations: int | None = None,
    workspace_state: Literal["active", "suppressed", "all"] = "active",
    sort: Literal[
        "url",
        "observations",
        "first_observed",
        "latest_observed",
        "owner",
        "workflow",
        "categories",
        "notes",
    ] = "url",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> PersistentPageList | None:
    if db.get(WebsiteProperty, site_id) is None:
        return None
    base = _site_page_query(site_id)
    base = _apply_page_filters(
        base,
        search=search,
        host=host,
        path_prefix=path_prefix,
        category_id=category_id,
        uncategorized=uncategorized,
        workflow_status=workflow_status,
        owner=owner,
        unassigned_owner=unassigned_owner,
        has_notes=has_notes,
        min_observations=min_observations,
        workspace_state=workspace_state,
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    category_count = (
        select(func.count(PageCategoryAssignment.id))
        .where(PageCategoryAssignment.site_page_id == SitePage.id)
        .correlate(SitePage)
        .scalar_subquery()
    )
    note_count = (
        select(func.count(Note.id))
        .where(Note.site_page_id == SitePage.id)
        .correlate(SitePage)
        .scalar_subquery()
    )
    sort_map: dict[str, Any] = {
        "url": WebResource.normalized_url,
        "observations": base.selected_columns.observation_count,
        "first_observed": base.selected_columns.first_observed_at,
        "latest_observed": base.selected_columns.latest_observed_at,
        "owner": SitePage.owner_label,
        "workflow": SitePage.workflow_status,
        "categories": category_count,
        "notes": note_count,
    }
    order = sort_map[sort].desc() if direction == "desc" else sort_map[sort].asc()
    rows = db.execute(base.order_by(order, SitePage.id).limit(limit).offset(offset)).all()
    return _page_list_from_rows(db, rows, total=total, limit=limit, offset=offset)


def get_site_page(db: Session, site_id: int, resource_id: int) -> PersistentPageDetail | None:
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        return None
    resolved_id = resolve_resource_id(db, resource_id)
    if resolved_id is None:
        return None
    row = db.execute(
        _site_page_query(site_id).where(SitePage.resource_id == resolved_id)
    ).one_or_none()
    if row is None:
        return None
    page = _page_list_from_rows(db, [row], total=1, limit=1, offset=0).items[0]
    return PersistentPageDetail(page=page, site_id=site.id, site_name=site.name)


def list_page_observations(
    db: Session,
    site_id: int,
    resource_id: int,
    *,
    scope: Literal["site", "all"] = "site",
    scan_status: str | None = None,
    http_status: int | None = None,
    fetch_state: str | None = None,
    error_state: Literal["any", "with_errors", "without_errors"] = "any",
    retrieval_method: str | None = None,
    parse_method: str | None = None,
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> PageObservationList | None:
    resolved_id = resolve_resource_id(db, resource_id)
    if resolved_id is None:
        return None
    if db.get(WebsiteProperty, site_id) is None or not db.scalar(
        select(SitePage.id).where(
            SitePage.website_property_id == site_id,
            SitePage.resource_id == resolved_id,
        )
    ):
        return None
    artifact = aliased(HtmlParseArtifact)
    query = (
        select(ResourceSnapshot, Scan, WebsiteProperty, artifact, RenderedObservation.capture_state)
        .join(Scan, ResourceSnapshot.scan_id == Scan.id)
        .outerjoin(WebsiteProperty, Scan.website_property_id == WebsiteProperty.id)
        .outerjoin(artifact, ResourceSnapshot.parse_artifact_id == artifact.id)
        .outerjoin(RenderedObservation, RenderedObservation.snapshot_id == ResourceSnapshot.id)
        .where(ResourceSnapshot.resource_id == resolved_id)
    )
    if scope == "site":
        query = query.where(Scan.website_property_id == site_id)
    if scan_status:
        query = query.where(Scan.status == scan_status)
    if http_status is not None:
        query = query.where(ResourceSnapshot.http_status == http_status)
    if fetch_state:
        query = query.where(ResourceSnapshot.fetch_state == fetch_state)
    if error_state == "with_errors":
        query = query.where(ResourceSnapshot.error_type.is_not(None))
    elif error_state == "without_errors":
        query = query.where(ResourceSnapshot.error_type.is_(None))
    if retrieval_method:
        query = query.where(ResourceSnapshot.retrieval_method == retrieval_method)
    if parse_method:
        query = query.where(ResourceSnapshot.parse_method == parse_method)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordering = (
        ResourceSnapshot.fetched_at.desc()
        if direction == "desc"
        else ResourceSnapshot.fetched_at.asc()
    )
    rows = db.execute(
        query.order_by(ordering, ResourceSnapshot.id.desc()).limit(limit).offset(offset)
    ).all()
    return PageObservationList(
        items=[
            PageObservationRead(
                snapshot_id=snapshot.id,
                scan_id=scan.id,
                site_id=site.id if site else None,
                site_name=site.name if site else None,
                scan_created_at=scan.created_at,
                scan_status=scan.status,
                scan_started_at=scan.started_at,
                scan_finished_at=scan.finished_at,
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
                rendered_capture_state=rendered_state,
            )
            for snapshot, scan, site, artifact_row, rendered_state in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _site_page_query(site_id: int) -> Select[Any]:
    all_observations = (
        select(
            ResourceSnapshot.resource_id.label("resource_id"),
            func.count(ResourceSnapshot.id).label("all_observation_count"),
        )
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .where(Scan.website_property_id == site_id)
        .group_by(ResourceSnapshot.resource_id)
        .subquery()
    )
    observations = (
        select(
            ResourceSnapshot.resource_id.label("resource_id"),
            func.count(ResourceSnapshot.id).label("observation_count"),
            func.min(ResourceSnapshot.fetched_at).label("first_observed_at"),
            func.max(ResourceSnapshot.fetched_at).label("latest_observed_at"),
        )
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .where(Scan.website_property_id == site_id)
        .where(
            or_(
                ResourceSnapshot.representation_kind == "html_page",
                ResourceSnapshot.html_blob_id.is_not(None),
                ResourceSnapshot.content_type.ilike("text/html%"),
                ResourceSnapshot.content_type.ilike("application/xhtml+xml%"),
            )
        )
        .group_by(ResourceSnapshot.resource_id)
        .subquery()
    )
    latest_snapshot = aliased(ResourceSnapshot)
    latest_id = (
        select(latest_snapshot.id)
        .join(Scan, latest_snapshot.scan_id == Scan.id)
        .where(
            Scan.website_property_id == site_id,
            latest_snapshot.resource_id == SitePage.resource_id,
        )
        .order_by(latest_snapshot.fetched_at.desc(), latest_snapshot.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return (
        select(
            SitePage,
            WebResource,
            func.coalesce(observations.c.observation_count, 0).label("observation_count"),
            observations.c.first_observed_at,
            observations.c.latest_observed_at,
            latest_id.label("latest_snapshot_id"),
        )
        .join(WebResource, WebResource.id == SitePage.resource_id)
        .outerjoin(observations, observations.c.resource_id == SitePage.resource_id)
        .outerjoin(all_observations, all_observations.c.resource_id == SitePage.resource_id)
        .where(
            SitePage.website_property_id == site_id,
            or_(
                func.coalesce(all_observations.c.all_observation_count, 0) == 0,
                func.coalesce(observations.c.observation_count, 0) > 0,
            ),
        )
    )


def _apply_page_filters(query: Select[Any], **filters: Any) -> Select[Any]:
    search = filters["search"]
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(WebResource.normalized_url.ilike(pattern), WebResource.path.ilike(pattern))
        )
    if filters["host"]:
        query = query.where(WebResource.host == filters["host"].lower())
    if filters["path_prefix"]:
        query = query.where(WebResource.path.startswith(filters["path_prefix"]))
    if filters["workflow_status"]:
        query = query.where(SitePage.workflow_status == filters["workflow_status"])
    if filters["owner"]:
        query = query.where(SitePage.owner_label.ilike(f"%{filters['owner']}%"))
    if filters["unassigned_owner"]:
        query = query.where(SitePage.owner_label.is_(None))
    assignment_exists = select(PageCategoryAssignment.id).where(
        PageCategoryAssignment.site_page_id == SitePage.id
    )
    if filters["category_id"] is not None:
        query = query.where(
            assignment_exists.where(
                PageCategoryAssignment.category_id == filters["category_id"]
            ).exists()
        )
    if filters["uncategorized"]:
        query = query.where(~assignment_exists.exists())
    note_exists = select(Note.id).where(Note.site_page_id == SitePage.id).exists()
    if filters["has_notes"] is True:
        query = query.where(note_exists)
    elif filters["has_notes"] is False:
        query = query.where(~note_exists)
    if filters["min_observations"] is not None:
        query = query.where(
            func.coalesce(query.selected_columns.observation_count, 0)
            >= filters["min_observations"]
        )
    if filters["workspace_state"] != "all":
        query = query.where(SitePage.workspace_state == filters["workspace_state"])
    return query


def _page_list_from_rows(
    db: Session, rows: Sequence[Any], *, total: int, limit: int, offset: int
) -> PersistentPageList:
    site_page_ids = [row[0].id for row in rows]
    latest_ids = [row[5] for row in rows if row[5] is not None]
    latest = (
        {
            snapshot.id: snapshot
            for snapshot in db.scalars(
                select(ResourceSnapshot).where(ResourceSnapshot.id.in_(latest_ids))
            )
        }
        if latest_ids
        else {}
    )
    categories: dict[int, list[PageCategoryRead]] = defaultdict(list)
    if site_page_ids:
        category_rows = db.execute(
            select(PageCategoryAssignment.site_page_id, PageCategory)
            .join(PageCategory, PageCategory.id == PageCategoryAssignment.category_id)
            .where(PageCategoryAssignment.site_page_id.in_(site_page_ids))
            .order_by(PageCategory.sort_order, PageCategory.normalized_name)
        ).all()
        for site_page_id, category in category_rows:
            categories[site_page_id].append(PageCategoryRead.model_validate(category))
    note_counts: dict[int, int] = {}
    if site_page_ids:
        for site_page_id, count in db.execute(
            select(Note.site_page_id, func.count(Note.id))
            .where(Note.site_page_id.in_(site_page_ids))
            .group_by(Note.site_page_id)
        ):
            if site_page_id is not None:
                note_counts[site_page_id] = count
    items = []
    for site_page, resource, count, first_at, latest_at, latest_id in rows:
        snapshot = latest.get(latest_id)
        assigned = categories[site_page.id]
        items.append(
            PersistentPageRead(
                site_page_id=site_page.id,
                resource_id=resource.id,
                normalized_url=resource.normalized_url,
                host=resource.host,
                path=resource.path,
                query=resource.query,
                owner_label=site_page.owner_label,
                workflow_status=site_page.workflow_status,
                workspace_state=site_page.workspace_state,
                suppressed_at=site_page.suppressed_at,
                categories=assigned,
                category_count=len(assigned),
                note_count=note_counts.get(site_page.id, 0),
                associated_at=site_page.created_at,
                observation_count=count,
                first_observed_at=first_at,
                latest_observed_at=latest_at,
                latest_snapshot_id=snapshot.id if snapshot else None,
                latest_scan_id=snapshot.scan_id if snapshot else None,
                latest_http_status=snapshot.http_status if snapshot else None,
                latest_title=snapshot.page_title if snapshot else None,
                latest_retrieval_method=snapshot.retrieval_method if snapshot else None,
                latest_parse_method=snapshot.parse_method if snapshot else None,
                latest_reused_from_snapshot_id=snapshot.reused_from_snapshot_id
                if snapshot
                else None,
                latest_fetch_state=snapshot.fetch_state if snapshot else None,
                latest_error_type=snapshot.error_type if snapshot else None,
                latest_error_message=snapshot.error_message if snapshot else None,
            )
        )
    return PersistentPageList(items=items, total=total, limit=limit, offset=offset)
