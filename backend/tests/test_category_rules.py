from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    PageCategoryAssignment,
    PageCategoryAssignmentSupport,
    PageCategoryAutomaticExclusion,
    PageCategoryRuleRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.category_rules import (
    AutomaticExclusionPayload,
    CategoryRuleConditionPayload,
    CategoryRuleCreate,
    CategoryRulePreviewRequest,
    CategoryRuleRunRead,
)
from app.schemas.page_workspaces import PageCategoryCreate, PageMetadataUpdate
from app.schemas.sites import WebsitePropertyUpdate
from app.services.background_jobs import recover_expired_jobs
from app.services.category_rule_evaluator import compile_conditions, resource_matches
from app.services.category_rules import (
    category_provenance,
    create_rule,
    list_rules,
    list_runs,
    preview_rule,
    reconcile_site,
    remove_automatic_exclusion,
    set_automatic_exclusion,
)
from app.services.page_categories import create_category
from app.services.site_pages import update_page_metadata


def test_condition_targets_operators_modes_and_case_behavior(db_session: Session) -> None:
    resource = _resource(db_session, "/Blog/guide.PDF", query="lang=ES")
    cases = [
        ("normalized_url", "contains", "example.com/Blog", True),
        ("host", "equals", "EXAMPLE.COM", True),
        ("path", "starts_with", "/blog/", True),
        ("path", "ends_with", ".pdf", True),
        ("path", "glob", "/blog/*.pdf", True),
        ("path", "regex", r"^/blog/.+\.pdf$", True),
        ("query", "contains", "lang=es", True),
        ("filename", "equals", "guide.pdf", True),
    ]
    for target, operator, value, expected in cases:
        condition = CategoryRuleConditionPayload(
            target=target,
            operator=operator,
            value=value,  # type: ignore[arg-type]
        )
        assert resource_matches(resource, compile_conditions([condition]), "all") is expected
    sensitive = CategoryRuleConditionPayload(
        target="path", operator="starts_with", value="/blog/", case_sensitive=True
    )
    negated = CategoryRuleConditionPayload(
        target="path", operator="contains", value="missing", negate=True
    )
    assert not resource_matches(resource, compile_conditions([sensitive]), "all")
    assert resource_matches(resource, compile_conditions([sensitive, negated]), "any")
    assert resource_matches(resource, compile_conditions([negated]), "all")


def test_rule_validation_rejects_invalid_or_unbounded_definitions() -> None:
    with pytest.raises(ValidationError, match="Invalid regular expression"):
        CategoryRuleConditionPayload(target="path", operator="regex", value="[")
    with pytest.raises(ValidationError):
        CategoryRuleConditionPayload(
            target="host", operator="equals", value="example.com", case_sensitive=True
        )
    with pytest.raises(ValidationError):
        CategoryRuleConditionPayload(target="path", operator="regex", value="x" * 2049)
    with pytest.raises(ValidationError):
        CategoryRulePreviewRequest(category_id=1, conditions=[])


def test_preview_is_non_mutating_and_matches_reconciliation(db_session: Session) -> None:
    site, pages = _site_with_pages(db_session, ["/blog/a", "/docs/b", "/blog/c"])
    category = create_category(db_session, site.id, PageCategoryCreate(name="Blog"))
    assert category is not None
    definition = CategoryRulePreviewRequest(
        category_id=category.id,
        match_mode="all",
        conditions=[
            CategoryRuleConditionPayload(target="path", operator="starts_with", value="/blog/")
        ],
    )
    preview = preview_rule(db_session, site.id, definition)
    assert preview is not None
    assert preview.total_pages_evaluated == 3
    assert preview.matching_pages == 2
    assert preview.would_gain_automatic_support == 2
    assert db_session.query(PageCategoryAssignment).count() == 0
    assert db_session.query(PageCategoryRuleRun).count() == 0

    rule = create_rule(
        db_session,
        site.id,
        CategoryRuleCreate(name="Blog paths", **definition.model_dump(exclude={"rule_id"})),
    )
    assert rule is not None
    run = db_session.query(PageCategoryRuleRun).one()
    assert db_session.query(BackgroundJob).count() == 1
    reconcile_site(db_session, run.id)
    serialized = CategoryRuleRunRead.model_validate(run).model_dump_json()
    assert '"started_at":"' in serialized
    assert "+00:00" in serialized or "Z" in serialized
    assert set(db_session.scalars(select(PageCategoryAssignment.site_page_id))) == {
        pages[0].id,
        pages[2].id,
    }


def test_multiple_rule_manual_and_exclusion_support_semantics(db_session: Session) -> None:
    site, pages = _site_with_pages(db_session, ["/blog/article"])
    page = pages[0]
    category = create_category(db_session, site.id, PageCategoryCreate(name="Blog"))
    assert category is not None
    for name, operator, value in (
        ("Blog prefix", "starts_with", "/blog/"),
        ("Article suffix", "ends_with", "article"),
    ):
        create_rule(
            db_session,
            site.id,
            CategoryRuleCreate(
                name=name,
                category_id=category.id,
                conditions=[
                    CategoryRuleConditionPayload(target="path", operator=operator, value=value)  # type: ignore[arg-type]
                ],
            ),
        )
    run = db_session.query(PageCategoryRuleRun).one()
    reconcile_site(db_session, run.id)
    assignment = db_session.query(PageCategoryAssignment).one()
    assert (
        db_session.query(PageCategoryAssignmentSupport)
        .filter_by(page_category_assignment_id=assignment.id, support_type="rule")
        .count()
        == 2
    )

    update_page_metadata(db_session, page, PageMetadataUpdate(category_ids=[category.id]))
    assert (
        db_session.query(PageCategoryAssignmentSupport)
        .filter_by(page_category_assignment_id=assignment.id, support_type="manual")
        .count()
        == 1
    )
    set_automatic_exclusion(
        db_session,
        site.id,
        page.resource_id,
        AutomaticExclusionPayload(category_id=category.id),
    )
    reconcile_site(db_session, run.id)
    assert db_session.query(PageCategoryAssignment).count() == 1
    assert (
        db_session.query(PageCategoryAssignmentSupport).filter_by(support_type="rule").count() == 0
    )

    update_page_metadata(db_session, page, PageMetadataUpdate(category_ids=[]))
    assert db_session.query(PageCategoryAssignment).count() == 0
    assert db_session.query(PageCategoryAutomaticExclusion).count() == 1
    details = category_provenance(db_session, site.id, page.resource_id)
    assert details is not None and details.items[0].automatic_exclusion

    remove_automatic_exclusion(db_session, site.id, page.resource_id, category.id)
    reconcile_site(db_session, run.id)
    assert db_session.query(PageCategoryAssignment).count() == 1
    assert (
        db_session.query(PageCategoryAssignmentSupport).filter_by(support_type="rule").count() == 2
    )


def test_timezone_validation_and_utc_round_trip(db_session: Session) -> None:
    site = WebsiteProperty(
        name="Timezone",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        display_timezone="America/New_York",
        scope_config={},
        is_active=True,
        created_at=datetime(2026, 8, 7, 2, 23, tzinfo=UTC),
    )
    db_session.add(site)
    db_session.commit()
    db_session.expire(site)
    assert site.created_at.tzinfo is UTC
    assert (
        WebsitePropertyUpdate(display_timezone="America/Los_Angeles").display_timezone
        == "America/Los_Angeles"
    )
    assert WebsitePropertyUpdate(display_timezone="").display_timezone is None
    with pytest.raises(ValidationError, match="valid IANA"):
        WebsitePropertyUpdate(display_timezone="EDT")


def test_reconciliation_query_count_is_batch_oriented(db_session: Session) -> None:
    site, _ = _site_with_pages(db_session, [f"/docs/page-{index}" for index in range(100)])
    category = create_category(db_session, site.id, PageCategoryCreate(name="Docs"))
    assert category is not None
    create_rule(
        db_session,
        site.id,
        CategoryRuleCreate(
            name="Docs paths",
            category_id=category.id,
            conditions=[
                CategoryRuleConditionPayload(target="path", operator="starts_with", value="/docs/")
            ],
        ),
    )
    run = db_session.query(PageCategoryRuleRun).one()
    statements = 0

    def count_statement(*_args: object) -> None:
        nonlocal statements
        statements += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        reconcile_site(db_session, run.id)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)
    assert statements < 30
    assert db_session.query(PageCategoryAssignment).count() == 100


def test_expired_rule_job_marks_run_interrupted(db_session: Session) -> None:
    site, _ = _site_with_pages(db_session, ["/docs/a"])
    category = create_category(db_session, site.id, PageCategoryCreate(name="Docs"))
    assert category is not None
    create_rule(
        db_session,
        site.id,
        CategoryRuleCreate(
            name="Docs",
            category_id=category.id,
            conditions=[
                CategoryRuleConditionPayload(target="path", operator="starts_with", value="/docs/")
            ],
        ),
    )
    run = db_session.query(PageCategoryRuleRun).one()
    job = db_session.query(BackgroundJob).one()
    run.status = "running"
    job.status = "running"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert recover_expired_jobs(db_session) == 1
    assert run.status == "interrupted"
    assert run.error_type == "lease_expired"


def test_rule_and_history_tables_support_every_displayed_sort(db_session: Session) -> None:
    site, _ = _site_with_pages(db_session, ["/docs/a"])
    category = create_category(db_session, site.id, PageCategoryCreate(name="Docs"))
    assert category is not None
    create_rule(
        db_session,
        site.id,
        CategoryRuleCreate(
            name="Docs",
            category_id=category.id,
            conditions=[
                CategoryRuleConditionPayload(target="path", operator="starts_with", value="/docs/")
            ],
        ),
    )
    rule_sorts = (
        "active",
        "name",
        "category",
        "mode",
        "condition_count",
        "match_count",
        "excluded_count",
        "last_evaluated_at",
    )
    history_sorts = (
        "trigger",
        "status",
        "started_at",
        "page_count",
        "rule_count",
        "match_count",
        "supports_delta",
        "assignments_delta",
        "excluded_count",
        "evaluator",
    )
    for sort in rule_sorts:
        result = list_rules(db_session, site.id, sort=sort, direction="asc")  # type: ignore[arg-type]
        assert result is not None and result.total == 1
    for sort in history_sorts:
        result = list_runs(db_session, site.id, sort=sort, direction="desc")  # type: ignore[arg-type]
        assert result is not None and result.total == 1


def _site_with_pages(db: Session, paths: list[str]) -> tuple[WebsiteProperty, list[SitePage]]:
    site = WebsiteProperty(
        name="Rules",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    db.add(site)
    db.flush()
    pages = []
    for path in paths:
        resource = _resource(db, path)
        page = SitePage(website_property_id=site.id, resource_id=resource.id)
        db.add(page)
        db.flush()
        pages.append(page)
    db.commit()
    return site, pages


def _resource(db: Session, path: str, query: str = "") -> WebResource:
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://example.com{path}{'?' + query if query else ''}",
        scheme="https",
        host="example.com",
        path=path,
        query=query,
    )
    db.add(resource)
    db.flush()
    return resource
