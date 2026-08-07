"""Run a deterministic terminal Scan projection benchmark."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    WebResource,
)
from app.services.graph_filters import GraphFilters
from app.services.graph_queries import get_scan_graph, get_scan_graph_dynamic
from app.services.resource_queries import (
    list_scan_resources,
    list_scan_resources_dynamic,
    scan_resource_summary,
    scan_resource_summary_dynamic,
)
from app.services.scan_projections import (
    SCAN_PROJECTION_VERSION,
    create_projection_build,
    delete_scan_projection_data,
    execute_projection_build,
)
from app.services.scan_queries import list_scan_pages_dynamic, list_scan_pages_routed

PAGE_COUNT = 2_000
REFERENCES_PER_PAGE = 8


def _resource(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    return {
        "resource_type": "page",
        "normalized_url": url,
        "scheme": parts.scheme,
        "host": parts.hostname or "fixture.test",
        "port": parts.port,
        "path": parts.path,
        "query": parts.query,
    }


def _measure(db: Session, name: str, operation: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    statements = 0
    sql_seconds = 0.0
    starts: list[float] = []

    def before(*_args: object) -> None:
        nonlocal statements
        statements += 1
        starts.append(perf_counter())

    def after(*_args: object) -> None:
        nonlocal sql_seconds
        sql_seconds += perf_counter() - starts.pop()

    event.listen(db.bind, "before_cursor_execute", before)
    event.listen(db.bind, "after_cursor_execute", after)
    started = perf_counter()
    try:
        result = operation()
    finally:
        wall_ms = (perf_counter() - started) * 1000
        event.remove(db.bind, "before_cursor_execute", before)
        event.remove(db.bind, "after_cursor_execute", after)
    rows = len(result.items) if hasattr(result, "items") and isinstance(result.items, list) else 1
    return result, {
        "name": name,
        "sql_statements": statements,
        "sql_execution_ms": round(sql_seconds * 1000, 2),
        "wall_ms": round(wall_ms, 2),
        "rows_returned": rows,
    }


def _pages(db: Session, scan_id: int, *, dynamic: bool) -> Any:
    query = list_scan_pages_dynamic if dynamic else list_scan_pages_routed
    return query(
        db,
        scan_id,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "any",
        "requested_url",
        "asc",
        50,
        0,
    )


def _fixture(db: Session) -> tuple[Scan, int]:
    scan = Scan(
        starting_url="https://fixture.test/pages/0",
        status="completed_with_errors",
        scope_config={},
        discovered_count=PAGE_COUNT,
        fetched_count=PAGE_COUNT - 20,
        failed_count=20,
        html_page_observed_count=PAGE_COUNT,
        static_request_attempt_count=PAGE_COUNT + 10,
        static_retry_request_count=10,
        static_recovered_after_retry_count=8,
    )
    db.add(scan)
    db.flush()
    page_urls = [f"https://fixture.test/pages/{index}" for index in range(PAGE_COUNT)]
    shared = [
        ("https://fixture.test/assets/shared.webp", "image"),
        ("https://fixture.test/assets/app.js", "script"),
        ("https://fixture.test/assets/app.css", "stylesheet"),
        ("https://fixture.test/assets/site.woff2", "font"),
        ("https://fixture.test/documents/guide.pdf", "document"),
        ("https://external.test/tracker.js", "script"),
    ]
    unique = [(f"https://fixture.test/images/{index}.webp", "image") for index in range(PAGE_COUNT)]
    resource_rows = [_resource(url) for url in page_urls]
    resource_rows.extend(_resource(url) for url, _kind in shared + unique)
    db.execute(insert(WebResource), resource_rows)
    db.flush()
    resources = {
        url: resource_id
        for resource_id, url in db.execute(select(WebResource.id, WebResource.normalized_url))
    }
    snapshots = [
        {
            "scan_id": scan.id,
            "resource_id": resources[url],
            "requested_url": url,
            "final_url": url if index % 100 else f"{url}/final",
            "http_status": 500 if index % 100 == 0 else 200,
            "content_type": "text/html",
            "crawl_depth": index % 8,
            "fetch_state": "failed" if index % 100 == 0 else "fetched",
            "error_type": "connection_timeout" if index % 100 == 0 else None,
            "error_message": "Synthetic timeout" if index % 100 == 0 else None,
            "representation_kind": "html_page",
            "normalized_mime_type": "text/html",
            "page_title": f"Page {index}",
            "response_time_ms": 20 + index % 200,
            "redirect_chain": [{"status": 301}] if index % 100 == 0 else [],
        }
        for index, url in enumerate(page_urls)
    ]
    db.execute(insert(ResourceSnapshot), snapshots)
    db.flush()
    snapshot_ids: dict[str, int] = {
        url: snapshot_id
        for url, snapshot_id in db.execute(
            select(ResourceSnapshot.requested_url, ResourceSnapshot.id).where(
                ResourceSnapshot.scan_id == scan.id
            )
        )
    }
    reference_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    for index, page_url in enumerate(page_urls):
        source_id = snapshot_ids[page_url]
        targets = [
            (shared[0][0], "image", True),
            (shared[0][0], "image", True),
            (unique[index][0], "image", True),
            (shared[1][0], "script", True),
            (shared[2][0], "stylesheet", True),
            (shared[3][0], "font", True),
            (shared[4][0], "document", True),
            (shared[5][0], "script", False),
        ]
        for position, (url, kind, in_scope) in enumerate(targets):
            reference_rows.append(
                {
                    "source_snapshot_id": source_id,
                    "target_resource_id": resources[url],
                    "relation_type": kind,
                    "element_tag": "a" if kind == "document" else "link",
                    "attribute_name": "href",
                    "raw_url": urlsplit(url).path,
                    "resolved_url": url,
                    "normalized_target_url": url,
                    "inferred_kind": kind,
                    "classification_rule": f"benchmark_{kind}",
                    "dom_path": "body>main" if position % 2 else "body>header",
                    "in_scope": in_scope,
                    "scope_decision": "crawlable" if in_scope else "external_host",
                }
            )
        target_url = page_urls[(index + 1) % PAGE_COUNT]
        link_rows.append(
            {
                "source_snapshot_id": source_id,
                "relation_type": "page_link",
                "raw_href": urlsplit(target_url).path,
                "resolved_url": target_url,
                "normalized_target_url": target_url,
                "target_resource_id": resources[target_url],
                "anchor_text": "Next",
                "dom_path": "body>main>a",
                "in_scope": True,
                "scope_decision": "crawlable",
                "link_role": "content",
                "link_role_rule": "main_content",
            }
        )
    db.execute(insert(ResourceReferenceOccurrence), reference_rows)
    db.execute(insert(ResourceOccurrence), link_rows)
    db.add_all(
        [
            Scan(starting_url="https://fixture.test/partial", status="failed", scope_config={}),
            Scan(starting_url="https://fixture.test/active", status="running", scope_config={}),
        ]
    )
    db.commit()
    return scan, len(reference_rows) + len(link_rows)


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="site-ledger-projection-benchmark-") as directory:
        path = Path(directory) / "projection.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as db:
            scan, occurrence_count = _fixture(db)
            evidence_size = path.stat().st_size
            metrics: list[dict[str, Any]] = []
            dynamic_pages, item = _measure(
                db, "dynamic_page_cold", lambda: _pages(db, scan.id, dynamic=True)
            )
            metrics.append(item)
            _, item = _measure(db, "dynamic_page_warm", lambda: _pages(db, scan.id, dynamic=True))
            metrics.append(item)
            dynamic_resources, item = _measure(
                db,
                "dynamic_resource_cold",
                lambda: list_scan_resources_dynamic(db, scan.id, limit=50),
            )
            metrics.append(item)
            _, item = _measure(
                db,
                "dynamic_resource_warm",
                lambda: list_scan_resources_dynamic(db, scan.id, limit=50),
            )
            metrics.append(item)
            dynamic_summary, item = _measure(
                db, "dynamic_resource_summary", lambda: scan_resource_summary_dynamic(db, scan.id)
            )
            metrics.append(item)
            graph_filters = GraphFilters(max_nodes=400, max_edges=1200)
            dynamic_graph, item = _measure(
                db, "dynamic_graph", lambda: get_scan_graph_dynamic(db, scan.id, graph_filters)
            )
            metrics.append(item)
            build = create_projection_build(db, scan.id)
            db.commit()
            ready, build_metric = _measure(
                db, "projection_build", lambda: execute_projection_build(db, build.id)
            )
            metrics.append(build_metric)
            projected_size = path.stat().st_size
            projected_pages, item = _measure(
                db, "projected_page_cold", lambda: _pages(db, scan.id, dynamic=False)
            )
            metrics.append(item)
            _, item = _measure(
                db, "projected_page_warm", lambda: _pages(db, scan.id, dynamic=False)
            )
            metrics.append(item)
            projected_resources, item = _measure(
                db, "projected_resource_cold", lambda: list_scan_resources(db, scan.id, limit=50)
            )
            metrics.append(item)
            _, item = _measure(
                db, "projected_resource_warm", lambda: list_scan_resources(db, scan.id, limit=50)
            )
            metrics.append(item)
            projected_summary, item = _measure(
                db, "projected_resource_summary", lambda: scan_resource_summary(db, scan.id)
            )
            metrics.append(item)
            projected_graph, item = _measure(
                db, "projected_graph", lambda: get_scan_graph(db, scan.id, graph_filters)
            )
            metrics.append(item)
            rebuild = create_projection_build(db, scan.id, force=True)
            db.commit()
            _, rebuild_metric = _measure(
                db, "projection_rebuild", lambda: execute_projection_build(db, rebuild.id)
            )
            metrics.append(rebuild_metric)
            plans = [
                row[3]
                for row in db.execute(
                    text(
                        "EXPLAIN QUERY PLAN SELECT * FROM scan_resource_projections "
                        "WHERE projection_build_id = :id "
                        "ORDER BY normalized_url LIMIT 50"
                    ),
                    {"id": ready.id},
                )
            ]
            page_equal = [item.model_dump() for item in dynamic_pages.items] == [
                item.model_dump() for item in projected_pages.items
            ]
            resource_equal = [item.model_dump() for item in dynamic_resources.items] == [
                item.model_dump() for item in projected_resources.items
            ]
            summary_equal = dynamic_summary.model_dump(
                exclude={"projection"}
            ) == projected_summary.model_dump(exclude={"projection"})
            graph_equal = [item.model_dump() for item in dynamic_graph.nodes] == [
                item.model_dump() for item in projected_graph.nodes
            ] and [item.model_dump() for item in dynamic_graph.edges] == [
                item.model_dump() for item in projected_graph.edges
            ]
            _, delete_metric = _measure(
                db, "projection_deletion", lambda: delete_scan_projection_data(db, scan.id)
            )
            db.commit()
            metrics.append(delete_metric)
            rows = {
                "pages": ready.page_count,
                "resources": ready.resource_count,
                "links": ready.link_edge_count,
            }
            projected_resource = next(
                item for item in metrics if item["name"] == "projected_resource_cold"
            )
            dynamic_resource = next(
                item for item in metrics if item["name"] == "dynamic_resource_cold"
            )
            result = {
                "projection_version": SCAN_PROJECTION_VERSION,
                "fixture": {
                    "pages": PAGE_COUNT,
                    "occurrences": occurrence_count,
                    "terminal_scans": 2,
                    "active_scans": 1,
                },
                "metrics": metrics,
                "projection_rows": rows,
                "statements_per_projected_row": round(
                    build_metric["sql_statements"] / max(sum(rows.values()), 1), 4
                ),
                "database_size_increase_bytes": projected_size - evidence_size,
                "resource_cold_speedup": round(
                    dynamic_resource["wall_ms"] / projected_resource["wall_ms"], 2
                )
                if projected_resource["wall_ms"]
                else None,
                "equivalence": {
                    "pages": page_equal,
                    "resources": resource_equal,
                    "resource_summary": summary_equal,
                    "graph": graph_equal,
                    "all": page_equal and resource_equal and summary_equal and graph_equal,
                },
                "resource_query_plan": plans,
                "raw_evidence_counts_after_deletion": {
                    "snapshots": db.scalar(
                        select(func.count(ResourceSnapshot.id)).where(
                            ResourceSnapshot.scan_id == scan.id
                        )
                    ),
                    "references": db.scalar(select(func.count(ResourceReferenceOccurrence.id))),
                    "links": db.scalar(
                        select(func.count(ResourceOccurrence.id)),
                    ),
                },
            }
        engine.dispose()
        return result


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
