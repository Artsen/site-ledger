"""Run a deterministic Scan comparison benchmark."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, WebResource, WebsiteProperty
from app.services.comparison_queries import (
    get_comparison_overview,
    list_comparison_links,
    list_comparison_pages,
    list_comparison_resources,
)
from app.services.scan_comparisons import (
    SCAN_COMPARISON_VERSION,
    create_comparison,
    create_comparison_build,
    execute_comparison_build,
)
from app.services.scan_projections import create_projection_build, execute_projection_build

PAGE_COUNT = 2_000


def _measure(db: Session, name: str, operation: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    statements = 0

    def before(*_args: object) -> None:
        nonlocal statements
        statements += 1

    event.listen(db.bind, "before_cursor_execute", before)
    started = perf_counter()
    try:
        result = operation()
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        event.remove(db.bind, "before_cursor_execute", before)
    return result, {
        "name": name,
        "wall_ms": round(elapsed_ms, 2),
        "sql_statements": statements,
        "rows_returned": len(result.items) if hasattr(result, "items") else 1,
    }


def _fixture(db: Session) -> tuple[WebsiteProperty, Scan, Scan]:
    site = WebsiteProperty(
        name="Comparison benchmark",
        base_url="https://fixture.test/",
        normalized_base_url="https://fixture.test/",
        group_key="benchmark",
        platform_key="unknown",
        ownership_key="unknown",
        display_timezone="UTC",
        scope_config={},
    )
    baseline = Scan(
        website_property=site,
        starting_url=site.base_url,
        status="completed",
        stop_reason="queue_empty",
        scope_config={"max_pages": PAGE_COUNT},
    )
    target = Scan(
        website_property=site,
        starting_url=site.base_url,
        status="completed",
        stop_reason="queue_empty",
        scope_config={"max_pages": PAGE_COUNT},
    )
    db.add_all([site, baseline, target])
    db.flush()
    urls = [f"https://fixture.test/pages/{index}" for index in range(PAGE_COUNT)]
    db.execute(
        insert(WebResource),
        [
            {
                "resource_type": "page",
                "normalized_url": url,
                "scheme": "https",
                "host": "fixture.test",
                "path": f"/pages/{index}",
                "query": "",
            }
            for index, url in enumerate(urls)
        ],
    )
    resources: dict[str, int] = {
        url: resource_id
        for url, resource_id in db.execute(select(WebResource.normalized_url, WebResource.id)).all()
    }
    snapshots: list[dict[str, Any]] = []
    for scan, is_target in ((baseline, False), (target, True)):
        for index, url in enumerate(urls):
            changed = is_target and index % 10 == 0
            snapshots.append(
                {
                    "scan_id": scan.id,
                    "resource_id": resources[url],
                    "requested_url": url,
                    "final_url": url,
                    "http_status": 200,
                    "content_type": "text/html",
                    "normalized_mime_type": "text/html",
                    "crawl_depth": index % 6,
                    "fetch_state": "fetched",
                    "representation_kind": "html_page",
                    "raw_html_sha256": (
                        f"{index:064x}" if not changed else f"{index + PAGE_COUNT:064x}"
                    ),
                    "head_sha256": f"{index:064x}",
                    "page_title": f"Page {index}",
                    "response_time_ms": 25 + index % 100 + (5 if is_target else 0),
                    "network_bytes_transferred": 1_000 + index % 200,
                }
            )
    db.execute(insert(ResourceSnapshot), snapshots)
    snapshot_ids = {
        (scan_id, resource_id): snapshot_id
        for scan_id, resource_id, snapshot_id in db.execute(
            select(ResourceSnapshot.scan_id, ResourceSnapshot.resource_id, ResourceSnapshot.id)
        )
    }
    links: list[dict[str, Any]] = []
    for scan in (baseline, target):
        for index, url in enumerate(urls):
            target_url = urls[(index + 1) % PAGE_COUNT]
            links.append(
                {
                    "source_snapshot_id": snapshot_ids[(scan.id, resources[url])],
                    "relation_type": "page_link",
                    "raw_href": f"/pages/{(index + 1) % PAGE_COUNT}",
                    "resolved_url": target_url,
                    "normalized_target_url": target_url,
                    "target_resource_id": resources[target_url],
                    "anchor_text": "Next",
                    "in_scope": True,
                    "scope_decision": "crawlable",
                    "link_role": "main_content",
                    "link_role_rule": "main_content",
                }
            )
    db.execute(insert(ResourceOccurrence), links)
    db.commit()
    for scan in (baseline, target):
        projection = create_projection_build(db, scan.id)
        db.commit()
        execute_projection_build(db, projection.id)
    return site, baseline, target


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="site-ledger-comparison-benchmark-", ignore_cleanup_errors=True
    ) as directory:
        path = Path(directory) / "comparison.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as db:
            site, baseline, target = _fixture(db)
            prepared_size = path.stat().st_size
            comparison = create_comparison(db, site.id, baseline.id, target.id)
            build = create_comparison_build(db, comparison.id)
            db.commit()
            ready, initial = _measure(
                db, "comparison_build", lambda: execute_comparison_build(db, build.id)
            )
            comparison_size = path.stat().st_size
            metrics = [initial]
            operations = (
                ("overview", lambda: get_comparison_overview(db, site.id, comparison.id)),
                (
                    "page_list",
                    lambda: list_comparison_pages(
                        db, site.id, comparison.id, changed_only=False, limit=50
                    ),
                ),
                (
                    "resource_list",
                    lambda: list_comparison_resources(db, site.id, comparison.id, limit=50),
                ),
                (
                    "link_list",
                    lambda: list_comparison_links(db, site.id, comparison.id, limit=50),
                ),
            )
            for name, operation in operations:
                _, metric = _measure(db, name, operation)
                metrics.append(metric)
            rebuild = create_comparison_build(db, comparison.id, force=True)
            db.commit()
            rebuilt, rebuild_metric = _measure(
                db, "comparison_rebuild", lambda: execute_comparison_build(db, rebuild.id)
            )
            metrics.append(rebuild_metric)
            result = {
                "comparison_version": SCAN_COMPARISON_VERSION,
                "fixture": {"pages_per_scan": PAGE_COUNT, "links_per_scan": PAGE_COUNT},
                "result_rows": {
                    "pages": ready.page_result_count,
                    "resources": ready.resource_result_count,
                    "links": ready.link_result_count,
                },
                "metrics": metrics,
                "database_size_increase_bytes": comparison_size - prepared_size,
                "checksum_equivalent": (
                    ready.comparison_checksum_sha256 == rebuilt.comparison_checksum_sha256
                ),
            }
        engine.dispose()
        return result


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
