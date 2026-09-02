from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Finding,
    FindingAssessment,
    FindingEvidenceReference,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.finding_detectors import CURRENT_FINDING_DETECTORS
from app.services.finding_evaluations import create_evaluation, execute_evaluation

PAGE_COUNT = 3_000
LINKS_PER_PAGE = 10


def run_benchmark(
    page_count: int = PAGE_COUNT, links_per_page: int = LINKS_PER_PAGE
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="site-ledger-finding-benchmark-") as directory:
        engine = create_engine(
            f"sqlite:///{Path(directory) / 'benchmark.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as db:
            _build_fixture(db, page_count, links_per_page)
            statements = 0
            selects = 0

            def count_statement(
                _connection: Any,
                _cursor: Any,
                statement: str,
                _parameters: Any,
                _context: Any,
                _executemany: bool,
            ) -> None:
                nonlocal statements, selects
                statements += 1
                if statement.lstrip().upper().startswith("SELECT"):
                    selects += 1

            event.listen(engine, "before_cursor_execute", count_statement)
            started = time.perf_counter()
            evaluation, created = create_evaluation(db, 1)
            assert created
            result = execute_evaluation(db, evaluation.id)
            db.commit()
            wall_time_seconds = time.perf_counter() - started
            event.remove(engine, "before_cursor_execute", count_statement)
            report = {
                "page_count": page_count,
                "resource_occurrence_count": page_count * links_per_page,
                "detector_count": len(CURRENT_FINDING_DETECTORS),
                "outcome_count": result.detected + result.clear + result.unknown,
                "select_count": selects,
                "total_sql_statements": statements,
                "wall_time_seconds": round(wall_time_seconds, 3),
                "finding_count": db.scalar(select(func.count(Finding.id))) or 0,
                "assessment_count": db.scalar(select(func.count(FindingAssessment.id))) or 0,
                "evidence_reference_count": db.scalar(
                    select(func.count(FindingEvidenceReference.id))
                )
                or 0,
            }
        engine.dispose()
    return report


def _build_fixture(db: Session, page_count: int, links_per_page: int) -> None:
    moment = datetime(2026, 9, 2, tzinfo=UTC)
    db.add(
        WebsiteProperty(
            id=1,
            name="Finding benchmark",
            base_url="https://benchmark.test/",
            normalized_base_url="https://benchmark.test/",
            group_key="Other",
            platform_key="Other",
            ownership_key="Unknown",
            scope_config={},
        )
    )
    db.add(
        Scan(
            id=1,
            website_property_id=1,
            starting_url="https://benchmark.test/",
            status="completed",
            scope_config={},
            created_at=moment,
            finished_at=moment,
            url_normalization_version="url-normalization-v2",
        )
    )
    db.flush()
    db.bulk_insert_mappings(
        WebResource,
        [
            {
                "id": index,
                "resource_type": "page",
                "normalization_version": "url-normalization-v2",
                "normalized_url": f"https://benchmark.test/page/{index}",
                "scheme": "https",
                "host": "benchmark.test",
                "path": f"/page/{index}",
                "query": "",
            }
            for index in range(1, page_count + 1)
        ],
    )
    db.bulk_insert_mappings(
        SitePage,
        [
            {
                "id": index,
                "website_property_id": 1,
                "resource_id": index,
                "workflow_status": "unreviewed",
                "workspace_state": "active",
            }
            for index in range(1, page_count + 1)
        ],
    )
    db.bulk_insert_mappings(
        ResourceSnapshot,
        [
            {
                "id": index,
                "scan_id": 1,
                "resource_id": index,
                "requested_url": f"https://benchmark.test/page/{index}",
                "final_url": f"https://benchmark.test/page/{index}",
                "http_status": 404 if index % 100 == 0 else 200,
                "crawl_depth": 1,
                "fetched_at": moment,
                "fetch_state": "fetched",
                "page_title": f"Page {index}",
                "parsed_head_json": {"links": []},
                "representation_kind": "html_page",
            }
            for index in range(1, page_count + 1)
        ],
    )
    db.bulk_insert_mappings(
        ResourceOccurrence,
        [
            {
                "source_snapshot_id": source_id,
                "relation_type": "page_link",
                "normalized_target_url": f"https://benchmark.test/page/{target_id}",
                "target_resource_id": target_id,
                "in_scope": False,
                "scope_decision": "already_seen",
                "link_role": "main_content",
                "link_role_rule": "ancestor_main",
            }
            for source_id in range(1, page_count + 1)
            for offset in range(1, links_per_page + 1)
            for target_id in [((source_id + offset - 1) % page_count) + 1]
        ],
    )
    db.commit()


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
