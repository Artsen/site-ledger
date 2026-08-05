from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass

from sqlalchemy import event

from app.database import SessionLocal
from app.services.graph_filters import GraphFilters
from app.services.graph_queries import get_scan_graph, list_graph_edge_occurrences


@dataclass(frozen=True)
class GraphBenchmarkResult:
    scan_id: int
    query_count: int
    elapsed_ms: float
    response_bytes: int
    returned_nodes: int
    returned_edges: int
    available_nodes: int
    available_edges: int
    total_occurrences: int
    occurrence_query_count: int | None = None
    occurrence_elapsed_ms: float | None = None
    occurrence_response_bytes: int | None = None
    occurrence_total: int | None = None
    occurrence_returned: int | None = None


def run_benchmark(scan_id: int, edge_id: str | None = None) -> GraphBenchmarkResult:
    queries: list[str] = []

    def before_cursor_execute(*args: object) -> None:
        queries.append(str(args[2]))

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", before_cursor_execute)
        try:
            start = time.perf_counter()
            graph = get_scan_graph(db, scan_id, GraphFilters())
            elapsed_ms = (time.perf_counter() - start) * 1000
        finally:
            event.remove(db.bind, "before_cursor_execute", before_cursor_execute)
        if graph is None:
            raise ValueError(f"Scan {scan_id} was not found.")
        response = graph.model_dump_json()
        occurrence_query_count = None
        occurrence_elapsed_ms = None
        occurrence_response_bytes = None
        occurrence_total = None
        occurrence_returned = None
        if edge_id:
            occurrence_queries: list[str] = []

            def before_occurrence_cursor_execute(*args: object) -> None:
                occurrence_queries.append(str(args[2]))

            event.listen(db.bind, "before_cursor_execute", before_occurrence_cursor_execute)
            try:
                occurrence_start = time.perf_counter()
                occurrences = list_graph_edge_occurrences(
                    db,
                    scan_id=scan_id,
                    edge_id=edge_id,
                    search=None,
                    limit=50,
                    offset=0,
                )
                occurrence_elapsed_ms = (time.perf_counter() - occurrence_start) * 1000
            finally:
                event.remove(db.bind, "before_cursor_execute", before_occurrence_cursor_execute)
            if occurrences is None:
                raise ValueError(f"Edge {edge_id} was not found in scan {scan_id}.")
            occurrence_json = occurrences.model_dump_json()
            occurrence_query_count = len(occurrence_queries)
            occurrence_response_bytes = len(occurrence_json.encode("utf-8"))
            occurrence_total = occurrences.total
            occurrence_returned = len(occurrences.items)
        return GraphBenchmarkResult(
            scan_id=scan_id,
            query_count=len(queries),
            elapsed_ms=round(elapsed_ms, 2),
            response_bytes=len(response.encode("utf-8")),
            returned_nodes=graph.summary.returned_nodes,
            returned_edges=graph.summary.returned_edges,
            available_nodes=graph.summary.total_available_nodes,
            available_edges=graph.summary.total_available_edges,
            total_occurrences=graph.summary.total_occurrences,
            occurrence_query_count=occurrence_query_count,
            occurrence_elapsed_ms=round(occurrence_elapsed_ms, 2)
            if occurrence_elapsed_ms is not None
            else None,
            occurrence_response_bytes=occurrence_response_bytes,
            occurrence_total=occurrence_total,
            occurrence_returned=occurrence_returned,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark graph query shape for a saved scan.")
    parser.add_argument("scan_id", type=int)
    parser.add_argument("--edge-id")
    args = parser.parse_args()
    print(json.dumps(asdict(run_benchmark(args.scan_id, args.edge_id)), indent=2))


if __name__ == "__main__":
    main()
