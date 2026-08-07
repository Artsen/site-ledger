from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PageCategoryRuleRun
from app.schemas.category_rules import (
    AutomaticExclusionPayload,
    CategoryProvenanceList,
    CategoryRuleCreate,
    CategoryRuleDeletePreview,
    CategoryRuleList,
    CategoryRulePreview,
    CategoryRulePreviewRequest,
    CategoryRuleRead,
    CategoryRuleRunList,
    CategoryRuleRunRead,
    CategoryRuleUpdate,
)
from app.services.category_rules import (
    category_provenance,
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    list_runs,
    preview_rule,
    preview_rule_deletion,
    queue_evaluation,
    remove_automatic_exclusion,
    set_automatic_exclusion,
    update_rule,
)

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=250)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/sites/{site_id}/category-rules", response_model=CategoryRuleList)
def get_category_rules(
    site_id: int,
    db: DbSession,
    search: str | None = None,
    category_id: int | None = None,
    active_state: Literal["active", "disabled", "all"] = "all",
    sort: Literal["name", "updated_at", "last_evaluated_at", "match_count"] = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> CategoryRuleList:
    result = list_rules(
        db,
        site_id,
        search=search,
        category_id=category_id,
        active_state=active_state,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post("/sites/{site_id}/category-rules/preview", response_model=CategoryRulePreview)
def post_category_rule_preview(
    site_id: int, payload: CategoryRulePreviewRequest, db: DbSession
) -> CategoryRulePreview:
    try:
        result = preview_rule(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post("/sites/{site_id}/category-rules", response_model=CategoryRuleRead, status_code=201)
def post_category_rule(
    site_id: int, payload: CategoryRuleCreate, db: DbSession
) -> CategoryRuleRead:
    try:
        result = create_rule(db, site_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.post(
    "/sites/{site_id}/category-rules/evaluate", response_model=CategoryRuleRunRead, status_code=202
)
def post_site_category_rule_evaluation(site_id: int, db: DbSession) -> CategoryRuleRunRead:
    try:
        run = queue_evaluation(db, site_id, "manual_recalculate")
        db.commit()
        db.refresh(run)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return CategoryRuleRunRead.model_validate(run)


@router.get("/sites/{site_id}/category-rules/{rule_id}", response_model=CategoryRuleRead)
def get_category_rule(site_id: int, rule_id: int, db: DbSession) -> CategoryRuleRead:
    result = get_rule(db, site_id, rule_id)
    if result is None:
        raise HTTPException(404, "Rule not found")
    return result


@router.patch("/sites/{site_id}/category-rules/{rule_id}", response_model=CategoryRuleRead)
def patch_category_rule(
    site_id: int, rule_id: int, payload: CategoryRuleUpdate, db: DbSession
) -> CategoryRuleRead:
    try:
        result = update_rule(db, site_id, rule_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Rule not found")
    return result


@router.get(
    "/sites/{site_id}/category-rules/{rule_id}/delete-preview",
    response_model=CategoryRuleDeletePreview,
)
def get_category_rule_delete_preview(
    site_id: int, rule_id: int, db: DbSession
) -> CategoryRuleDeletePreview:
    result = preview_rule_deletion(db, site_id, rule_id)
    if result is None:
        raise HTTPException(404, "Rule not found")
    return result


@router.delete("/sites/{site_id}/category-rules/{rule_id}")
def remove_category_rule(site_id: int, rule_id: int, db: DbSession) -> dict[str, int]:
    result = delete_rule(db, site_id, rule_id)
    if result is None:
        raise HTTPException(404, "Rule not found")
    return {"deleted_rule_id": result}


@router.post(
    "/sites/{site_id}/category-rules/{rule_id}/evaluate",
    response_model=CategoryRuleRunRead,
    status_code=202,
)
def post_category_rule_evaluation(site_id: int, rule_id: int, db: DbSession) -> CategoryRuleRunRead:
    if get_rule(db, site_id, rule_id) is None:
        raise HTTPException(404, "Rule not found")
    run = queue_evaluation(db, site_id, "manual_recalculate", rule_id)
    db.commit()
    db.refresh(run)
    return CategoryRuleRunRead.model_validate(run)


@router.get("/sites/{site_id}/category-rule-runs", response_model=CategoryRuleRunList)
def get_category_rule_runs(
    site_id: int,
    db: DbSession,
    status: str | None = None,
    trigger: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal["created_at", "started_at", "finished_at", "status"] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> CategoryRuleRunList:
    result = list_runs(
        db,
        site_id,
        status=status,
        trigger=trigger,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(404, "Site not found")
    return result


@router.get("/sites/{site_id}/category-rule-runs/{run_id}", response_model=CategoryRuleRunRead)
def get_category_rule_run(site_id: int, run_id: int, db: DbSession) -> CategoryRuleRunRead:
    run = db.get(PageCategoryRuleRun, run_id)
    if run is None or run.website_property_id != site_id:
        raise HTTPException(404, "Rule evaluation not found")
    return CategoryRuleRunRead.model_validate(run)


@router.get(
    "/sites/{site_id}/pages/{resource_id}/categories/details", response_model=CategoryProvenanceList
)
def get_page_category_details(
    site_id: int, resource_id: int, db: DbSession
) -> CategoryProvenanceList:
    result = category_provenance(db, site_id, resource_id)
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


@router.post(
    "/sites/{site_id}/pages/{resource_id}/category-exclusions",
    response_model=CategoryProvenanceList,
)
def post_page_category_exclusion(
    site_id: int, resource_id: int, payload: AutomaticExclusionPayload, db: DbSession
) -> CategoryProvenanceList:
    result = set_automatic_exclusion(db, site_id, resource_id, payload)
    if result is None:
        raise HTTPException(404, "Page not found")
    return result


@router.delete(
    "/sites/{site_id}/pages/{resource_id}/category-exclusions/{category_id}",
    response_model=CategoryProvenanceList,
)
def delete_page_category_exclusion(
    site_id: int, resource_id: int, category_id: int, db: DbSession
) -> CategoryProvenanceList:
    result = remove_automatic_exclusion(db, site_id, resource_id, category_id)
    if result is None:
        raise HTTPException(404, "Page not found")
    return result
