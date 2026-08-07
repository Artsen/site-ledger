from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    PageCategory,
    PageCategoryAssignment,
    PageCategoryAssignmentSupport,
    PageCategoryAutomaticExclusion,
    PageCategoryRule,
    PageCategoryRuleCondition,
    PageCategoryRuleRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.category_rule_evaluator import EVALUATOR_VERSION
from app.services.category_rules import PAGE_BATCH_SIZE, reconcile_site


def run_benchmark(page_count: int = 20_000) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="site-ledger-category-rules-") as directory:
        database = Path(directory) / "benchmark.db"
        engine = create_engine(f"sqlite:///{database}")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        sql_count = 0

        @event.listens_for(engine, "before_cursor_execute")
        def count_sql(*_args: object) -> None:
            nonlocal sql_count
            sql_count += 1

        with sessions() as db:
            fixture_started = time.perf_counter()
            site_id = _fixture(db, page_count)
            fixture_seconds = time.perf_counter() - fixture_started
            initial_size = database.stat().st_size
            sql_count = 0
            first = _measure(db, site_id, "migration_reconciliation")
            first_sql = sql_count
            sql_count = 0
            unchanged = _measure(db, site_id, "manual_recalculate")
            unchanged_sql = sql_count
            sql_count = 0
            edited_rule = db.get(PageCategoryRule, 2)
            assert edited_rule is not None
            edited_rule.conditions[0].value = "/section/changed/"
            db.commit()
            edited = _measure(db, site_id, "rule_updated")
            edited_sql = sql_count
            sql_count = 0
            deleted_rule = db.get(PageCategoryRule, 3)
            assert deleted_rule is not None
            db.delete(deleted_rule)
            db.commit()
            deleted = _measure(db, site_id, "rule_deleted")
            deleted_sql = sql_count
            sql_count = 0
            _append_pages(db, site_id, page_count, 500)
            appended = _measure(db, site_id, "scan_completed")
            appended_sql = sql_count
            final_size = database.stat().st_size
        report = {
            "pages": page_count,
            "categories": 50,
            "rules": 100,
            "conditions": 110,
            "page_batch_size": PAGE_BATCH_SIZE,
            "fixture_seconds": round(fixture_seconds, 3),
            "first": _run_report(first, first_sql),
            "unchanged": _run_report(unchanged, unchanged_sql),
            "rule_edit": _run_report(edited, edited_sql),
            "rule_delete": _run_report(deleted, deleted_sql),
            "new_pages": _run_report(appended, appended_sql),
            "database_size_increase_bytes": final_size - initial_size,
        }
        engine.dispose()
        return report


def _measure(db: Session, site_id: int, trigger: str) -> PageCategoryRuleRun:
    run = PageCategoryRuleRun(
        website_property_id=site_id,
        trigger_type=trigger,
        status="queued",
        configuration_json={},
        evaluator_version=EVALUATOR_VERSION,
    )
    db.add(run)
    db.commit()
    started = time.perf_counter()
    result = reconcile_site(db, run.id)
    result.configuration_json = {
        **result.configuration_json,
        "benchmark_duration_seconds": round(time.perf_counter() - started, 3),
    }
    db.commit()
    return result


def _run_report(run: PageCategoryRuleRun, sql_count: int) -> dict[str, Any]:
    return {
        "duration_seconds": run.configuration_json["benchmark_duration_seconds"],
        "sql_statements": sql_count,
        "match_evaluations": run.page_count * run.rule_count,
        "support_additions": run.rule_supports_added,
        "support_removals": run.rule_supports_removed,
        "assignment_additions": run.effective_assignments_added,
        "assignment_removals": run.effective_assignments_removed,
        "exclusion_suppressions": run.exclusions_suppressing_matches,
        "unchanged_assignments": run.unchanged_count,
    }


def _fixture(db: Session, page_count: int) -> int:
    site = WebsiteProperty(
        name="Benchmark",
        base_url="https://benchmark.example/",
        normalized_base_url="https://benchmark.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    db.add(site)
    db.flush()
    db.execute(
        insert(PageCategory),
        [
            {
                "website_property_id": site.id,
                "name": f"Category {index}",
                "normalized_name": f"category {index}",
                "color_key": "stone",
                "sort_order": index,
                "is_active": index != 49,
            }
            for index in range(50)
        ],
    )
    _append_pages(db, site.id, 0, page_count)
    db.flush()
    rules = []
    for index in range(100):
        rule = PageCategoryRule(
            website_property_id=site.id,
            category_id=(index % 49) + 1,
            name=f"Rule {index}",
            match_mode="all" if index % 2 == 0 else "any",
            is_active=index != 99,
            sort_order=index,
        )
        db.add(rule)
        db.flush()
        operator, value = _pattern(index)
        rules.append(
            PageCategoryRuleCondition(
                rule_id=rule.id,
                target="path",
                operator=operator,
                value=value,
                sort_order=0,
            )
        )
        if index % 10 == 0:
            rules.append(
                PageCategoryRuleCondition(
                    rule_id=rule.id,
                    target="host",
                    operator="equals",
                    value="benchmark.example",
                    sort_order=1,
                )
            )
    db.add_all(rules)
    db.flush()
    db.execute(
        insert(PageCategoryAssignment),
        [
            {"site_page_id": index + 1, "category_id": (index % 49) + 1}
            for index in range(min(100, page_count))
        ],
    )
    assignments = list(db.query(PageCategoryAssignment).all())
    db.execute(
        insert(PageCategoryAssignmentSupport),
        [
            {
                "page_category_assignment_id": assignment.id,
                "support_type": "manual",
                "support_key": "manual",
            }
            for assignment in assignments
        ],
    )
    db.execute(
        insert(PageCategoryAutomaticExclusion),
        [
            {"site_page_id": index + 1, "category_id": (index % 49) + 1}
            for index in range(min(100, page_count))
        ],
    )
    db.commit()
    return site.id


def _append_pages(db: Session, site_id: int, start: int, count: int) -> None:
    resources = [
        {
            "resource_type": "page",
            "normalized_url": f"https://benchmark.example/section/{index % 50}/page-{index}.html",
            "scheme": "https",
            "host": "benchmark.example",
            "path": f"/section/{index % 50}/page-{index}.html",
            "query": "",
        }
        for index in range(start, start + count)
    ]
    db.execute(insert(WebResource), resources)
    resource_ids = list(
        db.scalars(select(WebResource.id).order_by(WebResource.id).offset(start).limit(count))
    )
    db.execute(
        insert(SitePage),
        [
            {"website_property_id": site_id, "resource_id": resource_id}
            for resource_id in resource_ids
        ],
    )
    db.commit()


def _pattern(index: int) -> tuple[str, str]:
    section = index % 50
    return (
        ("equals", f"/section/{section}/page-{section}.html"),
        ("starts_with", f"/section/{section}/"),
        ("ends_with", f"{index}.html"),
        ("contains", f"/section/{section}/"),
        ("glob", f"/section/{section}/*.html"),
        ("regex", rf"^/section/{section}/page-[0-9]+\.html$"),
    )[index % 6]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Page Category Rule reconciliation.")
    parser.add_argument("--pages", type=int, default=20_000)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.pages), indent=2))


if __name__ == "__main__":
    main()
