import argparse
import asyncio
import tempfile
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AiDocumentBlob, AiDocumentReference, AiDocumentRefresh, AiDocumentSnapshot
from app.parsers.ai_documents import parse_ai_index
from app.schemas.ai_documents import AiDocumentSettings, AiDocumentSourceCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.ai_document_queries import get_ai_tree, list_ai_documents, list_ai_refreshes
from app.services.ai_document_sources import create_ai_document_source, execute_ai_document_refresh
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

        @event.listens_for(engine, "before_cursor_execute")
        def count_query(*_args: object) -> None:
            nonlocal query_count
            query_count += 1

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
            refresh_started = perf_counter()
            await execute_ai_document_refresh(
                db, first, transport=httpx.MockTransport(transport), store=store
            )
            db.commit()
            refresh_seconds = perf_counter() - refresh_started
            refresh_queries = query_count
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
            print(f"refresh SQL statements: {refresh_queries:,}")
            print(f"tree: {len(tree.items):,} rows, {tree_seconds:.4f}s, {tree_queries} SQL")
            print(f"files: {files.total:,} rows, {files_seconds:.4f}s, {files_queries} SQL")
            print(f"history: {history.total:,} rows, {history_seconds:.4f}s, {history_queries} SQL")
            print(f"network bytes: {evidence.total_network_bytes:,}")
            print(f"retained bytes: {evidence.total_retained_bytes:,}")
            print(f"stored compressed bytes: {stored_total:,}")
            print(f"deduplicated/compressed savings: {max(0, raw_total - stored_total):,}")
            print(f"database size: {database_path.stat().st_size:,} bytes")
        engine.dispose()


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
