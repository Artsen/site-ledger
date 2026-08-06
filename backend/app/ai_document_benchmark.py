import argparse
import asyncio
import hashlib
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    AiDocumentValidation,
    UrlSourceEntry,
)
from app.parsers.ai_documents import parse_ai_index
from app.schemas.ai_documents import AiDocumentSettings, AiDocumentSourceCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.ai_document_queries import get_ai_tree, list_ai_documents, list_ai_refreshes
from app.services.ai_document_sources import (
    create_ai_document_source,
    execute_ai_document_refresh,
    preview_ai_source_deletion,
)
from app.services.site_management import create_site
from app.services.source_refresh import create_source_refresh
from app.storage.ai_document_store import LocalAiDocumentStore


async def run(document_count: int) -> None:
    with tempfile.TemporaryDirectory(prefix="site-ledger-ai-benchmark-") as directory:
        root = Path(directory)
        database_path = root / "benchmark.db"
        engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(engine)
        query_count = 0
        query_categories: Counter[str] = Counter()
        sql_started = 0.0
        sql_seconds = 0.0

        @event.listens_for(engine, "before_cursor_execute")
        def count_query(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            nonlocal query_count, sql_started
            query_count += 1
            query_categories[_query_category(statement)] += 1
            sql_started = perf_counter()

        @event.listens_for(engine, "after_cursor_execute")
        def time_query(*_args: object) -> None:
            nonlocal sql_seconds
            sql_seconds += perf_counter() - sql_started

        store = LocalAiDocumentStore(root / "evidence")
        root_content = _root_fixture(document_count)
        parse_started = perf_counter()
        parsed = parse_ai_index(root_content, "https://example.com/llms.txt")
        parse_seconds = perf_counter() - parse_started
        with Session(engine, expire_on_commit=False) as db:
            site = create_site(
                db,
                WebsitePropertyCreate(
                    name="AI benchmark",
                    base_url="https://example.com/",
                    description=None,
                    group_key="Benchmark",
                    locale=None,
                    platform_key="Static",
                    ownership_key="Local",
                    scope_config=ScopeConfigPayload(
                        allowed_host_patterns=["example.com"],
                        max_html_response_bytes=5_000_000,
                    ),
                    is_active=True,
                ),
            )
            source = create_ai_document_source(
                db,
                site.id,
                AiDocumentSourceCreate(
                    entry_url="/llms.txt",
                    name="Benchmark AI docs",
                    settings=AiDocumentSettings(max_total_documents=min(5000, document_count + 10)),
                ),
            )
            assert source is not None
            responses = _responses(root_content, document_count)

            def transport(request: httpx.Request) -> httpx.Response:
                status, headers, content = responses.get(
                    request.url.path, (404, {"content-type": "text/plain"}, b"")
                )
                return httpx.Response(status, headers=headers, content=content)

            first = create_source_refresh(db, site.id, source.id)
            assert first is not None
            query_count = 0
            query_categories.clear()
            sql_seconds = 0.0
            database_size_before = database_path.stat().st_size
            performance_metrics: dict[str, float | int] = {}
            refresh_started = perf_counter()
            await execute_ai_document_refresh(
                db,
                first,
                transport=httpx.MockTransport(transport),
                store=store,
                performance_metrics=performance_metrics,
            )
            db.commit()
            refresh_seconds = perf_counter() - refresh_started
            refresh_queries = query_count
            refresh_query_categories = query_categories.copy()
            refresh_sql_seconds = sql_seconds
            evidence = db.scalar(select(AiDocumentRefresh).order_by(AiDocumentRefresh.id.desc()))
            assert evidence is not None
            query_count = 0
            tree_started = perf_counter()
            tree = get_ai_tree(db, evidence.id)
            tree_seconds = perf_counter() - tree_started
            tree_queries = query_count
            query_count = 0
            files_started = perf_counter()
            files = list_ai_documents(
                db,
                evidence.id,
                search=None,
                kind=None,
                role=None,
                fetch_state=None,
                parse_state=None,
                changed=None,
                depth=None,
                sort="url",
                direction="asc",
                limit=250,
                offset=0,
            )
            files_seconds = perf_counter() - files_started
            files_queries = query_count
            query_count = 0
            history_started = perf_counter()
            history = list_ai_refreshes(db, source.id, 50, 0)
            history_seconds = perf_counter() - history_started
            history_queries = query_count
            raw_total = (
                db.scalar(select(func.sum(AiDocumentSnapshot.network_bytes_transferred))) or 0
            )
            stored_total = db.scalar(select(func.sum(AiDocumentBlob.stored_byte_size))) or 0
            reference_total = db.scalar(select(func.count(AiDocumentReference.id))) or 0
            inventory_total = db.scalar(select(func.count(UrlSourceEntry.id))) or 0
            validation_codes = list(
                db.scalars(select(AiDocumentValidation.code).order_by(AiDocumentValidation.id))
            )
            classifications = Counter(db.scalars(select(AiDocumentSnapshot.document_kind)).all())
            parse_states = Counter(db.scalars(select(AiDocumentSnapshot.parse_state)).all())
            stored_hashes = sorted(
                value
                for value in db.scalars(select(AiDocumentSnapshot.raw_sha256))
                if value is not None
            )
            expected_hashes = sorted(
                hashlib.sha256(content).hexdigest()
                for status, _headers, content in responses.values()
                if status == 200
            )
            duplicate_target_count = (
                db.scalar(
                    select(func.count(AiDocumentReference.id)).where(
                        AiDocumentReference.normalized_target_url == "https://example.com/docs/1.md"
                    )
                )
                or 0
            )
            external_count = (
                db.scalar(
                    select(func.count(AiDocumentReference.id)).where(
                        AiDocumentReference.in_scope.is_(False)
                    )
                )
                or 0
            )
            preview = preview_ai_source_deletion(db, source.id)
            assert preview is not None
            expected_document_total = document_count + 5
            expected_reference_total = document_count + 8
            expected_inventory_total = document_count + 2
            assert evidence.document_saved_count == expected_document_total
            assert reference_total == expected_reference_total
            assert inventory_total == expected_inventory_total
            assert stored_hashes == expected_hashes
            assert classifications == Counter(
                {
                    "llms_index": 2,
                    "llms_full": 1,
                    "markdown_document": document_count,
                    "openapi_specification": 1,
                    "asyncapi_specification": 1,
                }
            )
            assert parse_states == Counter({"parsed": 2, "not_applicable": document_count + 3})
            assert evidence.cycle_count == 1
            assert duplicate_target_count == 3
            assert external_count == 1
            assert validation_codes == []
            assert evidence.document_changed_count == expected_document_total
            assert evidence.document_unchanged_count == 0
            assert evidence.status == "completed"
            assert preview.snapshot_count == expected_document_total
            assert preview.reference_count == expected_reference_total
            assert preview.current_inventory_origin_count == expected_inventory_total
            failed_snapshot = db.scalar(
                select(AiDocumentSnapshot).where(AiDocumentSnapshot.fetch_state == "failed")
            )
            print(f"documents requested: {document_count:,}")
            print(f"refresh status: {evidence.status}")
            if failed_snapshot:
                print(
                    "first fetch failure: "
                    f"{failed_snapshot.error_type}: {failed_snapshot.error_message}"
                )
            print(f"references parsed: {len(parsed.references):,}")
            print(f"references persisted: {reference_total:,}")
            print(f"parse duration: {parse_seconds:.4f}s")
            print(f"fetch/persistence/inventory duration: {refresh_seconds:.4f}s")
            print(f"SQL execution duration: {refresh_sql_seconds:.4f}s")
            print(
                "inventory rebuild duration: "
                f"{float(performance_metrics['inventory_seconds']):.4f}s"
            )
            print(f"peak batch size: {int(performance_metrics['peak_batch_size']):,}")
            print(f"refresh SQL statements: {refresh_queries:,}")
            print(
                "statements per saved document: "
                f"{refresh_queries / max(1, evidence.document_saved_count):.2f}"
            )
            print(f"statements per reference: {refresh_queries / max(1, reference_total):.2f}")
            print("refresh SQL categories:")
            for category, count in refresh_query_categories.most_common():
                print(f"  {category}: {count:,}")
            print(f"tree: {len(tree.items):,} rows, {tree_seconds:.4f}s, {tree_queries} SQL")
            print(f"files: {files.total:,} rows, {files_seconds:.4f}s, {files_queries} SQL")
            print(f"history: {history.total:,} rows, {history_seconds:.4f}s, {history_queries} SQL")
            print(f"network bytes: {evidence.total_network_bytes:,}")
            print(f"retained bytes: {evidence.total_retained_bytes:,}")
            print(f"stored compressed bytes: {stored_total:,}")
            print(f"deduplicated/compressed savings: {max(0, raw_total - stored_total):,}")
            print(f"database size: {database_path.stat().st_size:,} bytes")
            print(
                "database size increase: "
                f"{database_path.stat().st_size - database_size_before:,} bytes"
            )
            print(f"inventory entries: {inventory_total:,}")
            print("correctness equivalence: passed")
            print("query plans:")
            for name, details in _query_plans(db, source.id).items():
                print(f"  {name}: {' | '.join(details)}")
        engine.dispose()


def _query_category(statement: str) -> str:
    normalized = " ".join(statement.casefold().split())
    verb = normalized.split(" ", 1)[0].upper() if normalized else "UNKNOWN"
    tables = (
        "web_resources",
        "ai_document_snapshots",
        "ai_document_references",
        "ai_document_blobs",
        "ai_document_validations",
        "url_source_entries",
        "ai_document_refreshes",
        "source_refreshes",
        "url_sources",
        "website_properties",
    )
    table = next((name for name in tables if name in normalized), "other")
    return f"{verb} {table}"


def _query_plans(db: Session, source_id: int) -> dict[str, list[str]]:
    statements = {
        "resource lookup": (
            "EXPLAIN QUERY PLAN SELECT id FROM web_resources "
            "WHERE normalized_url IN ('https://example.com/docs/1.md')"
        ),
        "prior snapshot lookup": (
            "EXPLAIN QUERY PLAN SELECT max(s.id) FROM ai_document_snapshots AS s "
            "JOIN ai_document_refreshes AS ar ON ar.id = s.refresh_id "
            "JOIN source_refreshes AS sr ON sr.id = ar.source_refresh_id "
            f"WHERE sr.url_source_id = {source_id} AND s.resource_id IN (1, 2) "
            "AND s.retained_blob_id IS NOT NULL GROUP BY s.resource_id"
        ),
        "source entry lookup": (
            "EXPLAIN QUERY PLAN SELECT id FROM url_source_entries "
            f"WHERE url_source_id = {source_id}"
        ),
        "blob hash lookup": (
            "EXPLAIN QUERY PLAN SELECT id FROM ai_document_blobs WHERE sha256 = 'benchmark'"
        ),
        "current entry expiration": (
            "EXPLAIN QUERY PLAN UPDATE url_source_entries SET is_current = 0 "
            f"WHERE url_source_id = {source_id} AND is_current = 1"
        ),
    }
    return {
        name: [str(row[3]) for row in db.execute(text(statement)).all()]
        for name, statement in statements.items()
    }


def _root_fixture(document_count: int) -> bytes:
    rows = ["# Benchmark", "", "> Deterministic AI document fixture", "", "## Documents"]
    rows.extend(
        [
            "- [Nested](/docs/llms.txt)",
            "- [Duplicate](/docs/1.md)",
            "- [Corpus](/llms-full.txt)",
            "- [OpenAPI](/openapi.json)",
            "- [AsyncAPI](/asyncapi.yaml)",
            "- [External](https://outside.example/doc.md)",
        ]
    )
    rows.extend(f"- [Document {index}](/docs/{index}.md)" for index in range(document_count))
    return "\n".join(rows).encode()


def _responses(root: bytes, document_count: int) -> dict[str, tuple[int, dict[str, str], bytes]]:
    responses = {
        "/llms.txt": (
            200,
            {"content-type": "text/plain", "etag": '"root"'},
            root,
        ),
        "/docs/llms.txt": (
            200,
            {"content-type": "text/plain"},
            b"# Nested\n\n## Cycle\n- [Root](/llms.txt)\n- [Shared](/docs/1.md)\n",
        ),
        "/llms-full.txt": (
            200,
            {"content-type": "text/plain"},
            b"# Full corpus\n",
        ),
        "/openapi.json": (
            200,
            {"content-type": "application/json"},
            b'{"openapi":"3.1.0"}',
        ),
        "/asyncapi.yaml": (
            200,
            {"content-type": "application/yaml"},
            b"asyncapi: 3.0.0\n",
        ),
    }
    for index in range(document_count):
        responses[f"/docs/{index}.md"] = (
            200,
            {"content-type": "text/markdown"},
            f"# Document {index}\n".encode(),
        )
    return responses


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark AI Document Source persistence and queries."
    )
    parser.add_argument("--documents", type=int, default=2000)
    args = parser.parse_args()
    asyncio.run(run(max(1, args.documents)))
