"""Run a deterministic local structured Page content benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.crawler.canonical_document import extract_canonical_document, render_markdown
from app.database import Base
from app.models import (
    ContentBlob,
    HtmlStructuredContentArtifact,
    HtmlStructuredContentNode,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.structured_content import (
    get_or_create_structured_artifact,
    rebuild_structured_artifact,
)
from app.services.structured_content_queries import (
    structured_content_for_snapshot,
    structured_document_for_snapshot,
)
from app.storage.content_store import LocalContentStore

DEFAULT_OBSERVATIONS = 2_000
DEFAULT_UNIQUE_BLOBS = 1_500


def run_benchmark(
    observation_count: int = DEFAULT_OBSERVATIONS,
    unique_blob_count: int = DEFAULT_UNIQUE_BLOBS,
) -> dict[str, Any]:
    if unique_blob_count > observation_count:
        raise ValueError("unique_blob_count cannot exceed observation_count")
    with tempfile.TemporaryDirectory(prefix="site-ledger-structured-content-") as directory:
        root = Path(directory)
        database_path = root / "benchmark.db"
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        store = LocalContentStore(root / "html")
        sources = [_fixture_html(index) for index in range(unique_blob_count)]
        extraction_latencies: list[float] = []
        persistence_latencies: list[float] = []
        reuse_latencies: list[float] = []
        query_latencies: list[float] = []
        markdown_latencies: list[float] = []
        rebuild_latencies: list[float] = []
        deterministic = True

        tracemalloc.start()
        benchmark_started = time.perf_counter()
        with session_factory() as db:
            scan, resource = _seed_domain(db)
            blobs: list[ContentBlob] = []
            for source in sources:
                started = time.perf_counter()
                first = extract_canonical_document(source)
                extraction_latencies.append(time.perf_counter() - started)
                repeated = extract_canonical_document(source)
                deterministic = deterministic and (
                    first.canonical_document_sha256 == repeated.canonical_document_sha256
                    and first.markdown_sha256 == repeated.markdown_sha256
                )
                blob = store.put_html(db, source, "text/html", "utf-8")
                started = time.perf_counter()
                get_or_create_structured_artifact(db, blob, content=source)
                persistence_latencies.append(time.perf_counter() - started)
                blobs.append(blob)
            db.commit()

            snapshots = []
            for index in range(observation_count):
                blob = blobs[index % unique_blob_count]
                snapshots.append(
                    ResourceSnapshot(
                        scan_id=scan.id,
                        resource_id=resource.id,
                        requested_url=f"https://benchmark.example/page-{index}",
                        final_url=f"https://benchmark.example/page-{index}",
                        http_status=200,
                        content_type="text/html",
                        encoding="utf-8",
                        crawl_depth=index % 5,
                        response_headers={},
                        redirect_chain=[],
                        html_blob_id=blob.id,
                        raw_html_sha256=blob.sha256,
                        fetch_state="fetched",
                        retrieval_method=(
                            "conditional_not_modified"
                            if index >= unique_blob_count
                            else "full_fetch"
                        ),
                    )
                )
            db.add_all(snapshots)
            db.commit()

            for snapshot in snapshots[unique_blob_count:]:
                blob = blobs[(snapshot.id - 1) % unique_blob_count]
                started = time.perf_counter()
                _, reused = get_or_create_structured_artifact(db, blob, store=store)
                reuse_latencies.append(time.perf_counter() - started)
                deterministic = deterministic and reused
            for snapshot in snapshots[: min(200, len(snapshots))]:
                started = time.perf_counter()
                structured_content_for_snapshot(db, snapshot, limit=500, offset=0)
                structured_document_for_snapshot(db, snapshot, limit=500, offset=0)
                query_latencies.append(time.perf_counter() - started)

            artifacts = list(
                db.scalars(
                    select(HtmlStructuredContentArtifact)
                    .order_by(HtmlStructuredContentArtifact.id)
                    .limit(min(50, unique_blob_count))
                )
            )
            before_rebuild = {
                artifact.content_blob_id: (
                    artifact.canonical_document_sha256,
                    artifact.outline_sha256,
                    render_markdown(artifact.nodes),
                    artifact.markdown_sha256,
                    [
                        (node.position, node.semantic_sha256, node.subtree_sha256)
                        for node in artifact.nodes
                    ],
                )
                for artifact in artifacts
            }
            for artifact in artifacts:
                started = time.perf_counter()
                markdown = render_markdown(artifact.nodes)
                markdown_latencies.append(time.perf_counter() - started)
                deterministic = deterministic and bool(markdown or artifact.node_count == 1)
                rebuild_blob = db.get(ContentBlob, artifact.content_blob_id)
                if rebuild_blob is None:
                    deterministic = False
                    continue
                started = time.perf_counter()
                rebuilt = rebuild_structured_artifact(db, rebuild_blob, store)
                rebuild_latencies.append(time.perf_counter() - started)
                deterministic = deterministic and before_rebuild[rebuild_blob.id] == (
                    rebuilt.canonical_document_sha256,
                    rebuilt.outline_sha256,
                    render_markdown(rebuilt.nodes),
                    rebuilt.markdown_sha256,
                    [
                        (node.position, node.semantic_sha256, node.subtree_sha256)
                        for node in rebuilt.nodes
                    ],
                )
            db.commit()

            artifact_count = db.scalar(select(func.count(HtmlStructuredContentArtifact.id))) or 0
            node_count = db.scalar(select(func.count(HtmlStructuredContentNode.id))) or 0
            blob_count = db.scalar(select(func.count(ContentBlob.id))) or 0

        elapsed = time.perf_counter() - benchmark_started
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        database_bytes = database_path.stat().st_size
        html_storage_bytes = sum(path.stat().st_size for path in (root / "html").rglob("*.gz"))
        result: dict[str, Any] = {
            "fixture": {
                "observations": observation_count,
                "unique_blobs": unique_blob_count,
                "reused_observations": observation_count - unique_blob_count,
                "artifacts": artifact_count,
                "structural_nodes": node_count,
                "structural_nodes_per_blob": round(node_count / max(blob_count, 1), 3),
                "content_blobs": blob_count,
            },
            "duration_seconds": round(elapsed, 3),
            "extraction_latency_ms": _percentiles(extraction_latencies),
            "persistence_latency_ms": _percentiles(persistence_latencies),
            "exact_reuse_lookup_latency_ms": _percentiles(reuse_latencies),
            "api_query_latency_ms": _percentiles(query_latencies),
            "markdown_render_latency_ms": _percentiles(markdown_latencies),
            "v2_rebuild_latency_ms": _percentiles(rebuild_latencies),
            "database_bytes": database_bytes,
            "compressed_html_storage_bytes": html_storage_bytes,
            "peak_memory_bytes": peak_memory,
            "deterministic_rebuild_equivalence": deterministic,
        }
        result["targets"] = {
            "duration_under_60_seconds": elapsed < 60,
            "reuse_p95_under_20_ms": result["exact_reuse_lookup_latency_ms"]["p95"] < 20,
            "api_p95_under_100_ms": result["api_query_latency_ms"]["p95"] < 100,
            "peak_memory_under_512_mib": peak_memory < 512 * 1024 * 1024,
            "database_under_250_mib": database_bytes < 250 * 1024 * 1024,
        }
        engine.dispose()
        return result


def _seed_domain(db: Session) -> tuple[Scan, WebResource]:
    site = WebsiteProperty(
        name="Structured content benchmark",
        base_url="https://benchmark.example/",
        normalized_base_url="https://benchmark.example/",
        description=None,
        group_key="benchmark",
        locale="en-US",
        platform_key="fixture",
        ownership_key="fixture",
        scope_config={},
        is_active=True,
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://benchmark.example/",
        scheme="https",
        host="benchmark.example",
        port=None,
        path="/",
        query="",
    )
    db.add_all([site, resource])
    db.flush()
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
    )
    db.add(scan)
    db.flush()
    return scan, resource


def _fixture_html(index: int) -> bytes:
    if index % 20 == 0:
        return f"<html><body>Unheaded document {index} with source text.</body></html>".encode()
    depth = 6 if index % 25 == 0 else 3
    headings = "".join(
        f"<h{min(level, 6)}>Section {index}.{level}</h{min(level, 6)}>"
        f"<p>Deterministic body text for section {level} on page {index}.</p>"
        for level in range(1, depth + 1)
    )
    table = (
        "<table>"
        + "".join(f"<tr><td>Row {row}</td><td>{index + row}</td></tr>" for row in range(30))
        + "</table>"
        if index % 40 == 0
        else ""
    )
    return (
        f"<html><head><title>Page {index}</title></head><body>"
        f"<header><nav>Global navigation {index}</nav></header><main>{headings}{table}</main>"
        f"<footer>Footer policy links {index}</footer></body></html>"
    ).encode()


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(value * 1000 for value in values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(max(ordered), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=int, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--unique-blobs", type=int, default=DEFAULT_UNIQUE_BLOBS)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.observations, args.unique_blobs), indent=2))


if __name__ == "__main__":
    main()
