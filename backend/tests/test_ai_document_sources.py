import gzip
import hashlib
from collections import Counter
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, func, select

from app.crawler.url_normalizer import normalize_url
from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    ResourceSnapshot,
    UrlSourceEntry,
    WebResource,
)
from app.schemas.ai_documents import AiDocumentSettings, AiDocumentSourceCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.ai_document_persistence import AiDocumentResourceResolver
from app.services.ai_document_queries import list_ai_documents, list_ai_references
from app.services.ai_document_sources import (
    create_ai_document_source,
    delete_ai_source,
    discover_ai_document_sources,
    execute_ai_document_refresh,
    get_ai_source,
    preview_ai_source_deletion,
)
from app.services.repositories import get_or_create_resource
from app.services.site_management import create_site
from app.services.source_refresh import create_source_refresh
from app.storage.ai_document_store import LocalAiDocumentStore


@pytest.mark.asyncio
async def test_discovery_finds_root_well_known_and_header_candidates(db_session) -> None:
    site = create_site(db_session, _site_payload())

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={
                    "Link": '</docs/llms.txt>; rel="llms-txt"',
                    "X-Llms-Txt": "/api/llms.txt",
                },
                text="home",
            )
        if request.url.path == "/.well-known/llms.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="# Docs")

    result = await discover_ai_document_sources(db_session, site.id, httpx.MockTransport(respond))

    assert result is not None
    by_path = {httpx.URL(item.url).path: item for item in result.candidates}
    assert by_path["/llms.txt"].status == "found"
    assert by_path["/.well-known/llms.txt"].status == "not_found"
    assert by_path["/docs/llms.txt"].discovery_method == "http_link_header"
    assert by_path["/api/llms.txt"].discovery_method == "x_llms_txt_header"


@pytest.mark.asyncio
async def test_nested_refresh_retains_exact_evidence_and_provenance(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(
            entry_url="/llms.txt",
            name="AI docs",
            settings=AiDocumentSettings(max_total_documents=20),
        ),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None
    root = (
        b"\xef\xbb\xbf# Root\r\n\r\n## Docs\r\n"
        b"- [Nested](/docs/llms.txt)\r\n"
        b"- [Guide](/guide.md): Main guide\r\n"
        b"- [Self](/llms.txt)\r\n"
        b"- [External](https://outside.example/doc.md)\r\n"
    )
    nested = b"# Nested\n\n## More\n- [Guide too](/guide.md)\n"
    guide = b"# Guide\n\nExact bytes.\r\n"
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        payload, mime = {
            "/llms.txt": (root, "text/plain"),
            "/docs/llms.txt": (nested, "text/plain"),
            "/guide.md": (guide, "text/markdown"),
        }[request.url.path]
        return httpx.Response(200, headers={"content-type": mime, "etag": '"v1"'}, content=payload)

    store = LocalAiDocumentStore(tmp_path / "ai")
    evidence = await execute_ai_document_refresh(
        db_session,
        refresh,
        transport=httpx.MockTransport(respond),
        store=store,
    )
    db_session.commit()

    source_read = get_ai_source(db_session, source.id)
    assert source_read is not None
    assert source_read.latest_refresh_id == evidence.id
    assert source_read.latest_source_refresh_id == refresh.id
    assert evidence.document_fetched_count == 3
    assert requests.count("/guide.md") == 1
    assert evidence.reference_count == 5
    assert evidence.cycle_count == 1
    assert db_session.scalar(select(func.count(ResourceSnapshot.id))) == 0
    snapshots = list(db_session.scalars(select(AiDocumentSnapshot).order_by(AiDocumentSnapshot.id)))
    root_snapshot = snapshots[0]
    assert root_snapshot.raw_sha256 == hashlib.sha256(root).hexdigest()
    assert root_snapshot.blob is not None
    assert gzip.decompress((tmp_path / "ai" / root_snapshot.blob.storage_key).read_bytes()) == root
    guide_snapshot = next(item for item in snapshots if item.requested_url.endswith("/guide.md"))
    assert (
        db_session.scalar(
            select(func.count(AiDocumentReference.id)).where(
                AiDocumentReference.child_snapshot_id == guide_snapshot.id
            )
        )
        == 2
    )
    entries = list(db_session.scalars(select(UrlSourceEntry)))
    assert [item.normalized_url for item in entries] == ["https://example.com/guide.md"]
    origins = entries[0].source_metadata_json["ai_origins"]
    assert len(origins) == 2
    assert {origin["label"] for origin in origins} == {"Guide", "Guide too"}
    external = db_session.scalar(
        select(AiDocumentReference).where(AiDocumentReference.scope_decision == "external")
    )
    assert external is not None and external.inventory_entry_id is None


@pytest.mark.asyncio
async def test_advertised_index_does_not_retain_html_response(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None

    evidence = await execute_ai_document_refresh(
        db_session,
        refresh,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<html><body>Not an AI document</body></html>",
            )
        ),
        store=LocalAiDocumentStore(tmp_path / "ai"),
    )
    db_session.commit()

    snapshot = db_session.scalar(select(AiDocumentSnapshot))
    assert snapshot is not None
    assert snapshot.document_kind == "html_page_reference"
    assert snapshot.retained_blob_id is None
    assert evidence.document_saved_count == 0


@pytest.mark.asyncio
async def test_missing_root_is_neutral_and_transient_statuses_retry(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None
    attempts = 0

    def transient_then_missing(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts == 1 else 404, content=b"Not found")

    evidence = await execute_ai_document_refresh(
        db_session,
        refresh,
        transport=httpx.MockTransport(transient_then_missing),
        store=LocalAiDocumentStore(tmp_path / "ai"),
    )
    db_session.commit()

    snapshot = db_session.scalar(select(AiDocumentSnapshot))
    assert attempts == 2
    assert snapshot is not None and snapshot.fetch_state == "not_found"
    assert snapshot.retained_blob_id is None
    assert evidence.status == "completed"


@pytest.mark.asyncio
async def test_conditional_304_reuses_blob_without_mutating_history(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    store = LocalAiDocumentStore(tmp_path / "ai")
    first = create_source_refresh(db_session, site.id, source.id)
    assert first is not None
    body = b"# Docs\n\n## Links\n- [Guide](/guide.md)\n"

    def first_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/guide.md":
            return httpx.Response(200, headers={"content-type": "text/markdown"}, content=b"guide")
        return httpx.Response(
            200, headers={"content-type": "text/plain", "etag": '"one"'}, content=body
        )

    await execute_ai_document_refresh(
        db_session, first, transport=httpx.MockTransport(first_response), store=store
    )
    db_session.commit()
    first_snapshot = db_session.scalar(
        select(AiDocumentSnapshot).where(AiDocumentSnapshot.requested_url.endswith("/llms.txt"))
    )
    assert first_snapshot is not None
    second = create_source_refresh(db_session, site.id, source.id)
    assert second is not None

    def second_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/guide.md":
            return httpx.Response(304)
        assert request.headers["if-none-match"] == '"one"'
        return httpx.Response(304, headers={"etag": '"one"'})

    await execute_ai_document_refresh(
        db_session, second, transport=httpx.MockTransport(second_response), store=store
    )
    db_session.commit()
    second_snapshot = db_session.scalar(
        select(AiDocumentSnapshot).where(
            AiDocumentSnapshot.refresh_id != first_snapshot.refresh_id,
            AiDocumentSnapshot.requested_url.endswith("/llms.txt"),
        )
    )
    assert second_snapshot is not None
    assert second_snapshot.change_state == "unchanged"
    assert second_snapshot.retained_blob_id == first_snapshot.retained_blob_id
    assert db_session.scalar(select(func.count(AiDocumentBlob.id))) == 2


@pytest.mark.asyncio
async def test_http_200_hash_comparison_marks_unchanged_then_changed(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    store = LocalAiDocumentStore(tmp_path / "ai")

    for body in (b"# Stable\n", b"# Stable\n", b"# Changed\n"):
        refresh = create_source_refresh(db_session, site.id, source.id)
        assert refresh is not None
        await execute_ai_document_refresh(
            db_session,
            refresh,
            transport=httpx.MockTransport(
                lambda _request, body=body: httpx.Response(
                    200,
                    headers={"content-type": "text/plain"},
                    content=body,
                )
            ),
            store=store,
        )
        db_session.commit()

    snapshots = list(db_session.scalars(select(AiDocumentSnapshot).order_by(AiDocumentSnapshot.id)))
    assert [snapshot.change_state for snapshot in snapshots] == ["new", "unchanged", "changed"]
    assert snapshots[0].retained_blob_id == snapshots[1].retained_blob_id
    assert snapshots[2].retained_blob_id != snapshots[1].retained_blob_id
    assert db_session.scalar(select(func.count(AiDocumentBlob.id))) == 2


@pytest.mark.asyncio
async def test_previous_snapshot_lookup_is_scoped_to_source(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source_a = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/a/llms.txt", name="Source A"),
    )
    source_b = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/b/llms.txt", name="Source B"),
    )
    assert source_a is not None and source_b is not None
    store = LocalAiDocumentStore(tmp_path / "ai")

    async def run_initial(source, tag: str) -> None:
        refresh = create_source_refresh(db_session, site.id, source.id)
        assert refresh is not None

        def respond(request: httpx.Request) -> httpx.Response:
            is_index = request.url.path.endswith("llms.txt")
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/plain" if is_index else "text/markdown",
                    "etag": f'"{tag}-{"root" if is_index else "shared"}"',
                },
                content=(
                    b"# Docs\n\n## Files\n- [Shared](/shared.md)\n"
                    if is_index
                    else f"# Shared {tag}\n".encode()
                ),
            )

        await execute_ai_document_refresh(
            db_session,
            refresh,
            transport=httpx.MockTransport(respond),
            store=store,
        )
        db_session.commit()

    await run_initial(source_a, "a")
    await run_initial(source_b, "b")

    refresh = create_source_refresh(db_session, site.id, source_a.id)
    assert refresh is not None

    def respond_unchanged(request: httpx.Request) -> httpx.Response:
        expected = '"a-root"' if request.url.path.endswith("llms.txt") else '"a-shared"'
        assert request.headers["if-none-match"] == expected
        return httpx.Response(304, headers={"etag": expected})

    evidence = await execute_ai_document_refresh(
        db_session,
        refresh,
        transport=httpx.MockTransport(respond_unchanged),
        store=store,
    )
    db_session.commit()

    snapshots = list(
        db_session.scalars(
            select(AiDocumentSnapshot)
            .where(AiDocumentSnapshot.refresh_id == evidence.id)
            .order_by(AiDocumentSnapshot.id)
        )
    )
    assert [snapshot.change_state for snapshot in snapshots] == ["unchanged", "unchanged"]


@pytest.mark.asyncio
async def test_cancellation_preserves_partial_refresh_evidence(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None
    root = "# Docs\n\n## Files\n" + "\n".join(
        f"- [Document {index}](/docs/{index}.md)" for index in range(10)
    )
    served = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal served
        served += 1
        return httpx.Response(
            200,
            headers={
                "content-type": (
                    "text/plain" if request.url.path == "/llms.txt" else "text/markdown"
                )
            },
            text=root if request.url.path == "/llms.txt" else f"# {request.url.path}",
        )

    evidence = await execute_ai_document_refresh(
        db_session,
        refresh,
        transport=httpx.MockTransport(respond),
        should_cancel=lambda: served >= 3,
        store=LocalAiDocumentStore(tmp_path / "ai"),
    )
    db_session.commit()

    snapshots = list(
        db_session.scalars(
            select(AiDocumentSnapshot).where(AiDocumentSnapshot.refresh_id == evidence.id)
        )
    )
    assert evidence.status == "cancelled"
    assert evidence.stop_reason == "cancelled_by_user"
    assert len(snapshots) == 3
    assert all(snapshot.fetch_state == "saved" for snapshot in snapshots)
    assert db_session.scalar(select(func.count(AiDocumentReference.id))) == 10
    assert db_session.scalar(select(func.count(UrlSourceEntry.id))) == 10


def _site_payload() -> WebsitePropertyCreate:
    return WebsitePropertyCreate(
        name="Example Site",
        base_url="https://example.com/",
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"]),
        is_active=True,
    )


def test_resource_resolver_batches_existing_and_new_unique_urls(db_session) -> None:
    existing_url = normalize_url("https://example.com/existing.md")
    new_url = normalize_url("https://example.com/new.md")
    existing = get_or_create_resource(db_session, existing_url)
    resolver = AiDocumentResourceResolver(db_session)

    resolver.resolve_many([existing_url, new_url, new_url])
    first_ids = {url: resource.id for url, resource in resolver.cache.items()}
    resolver.resolve_many([existing_url, new_url])

    assert resolver.cache[existing_url.normalized_url].id == existing.id
    assert {url: resource.id for url, resource in resolver.cache.items()} == first_ids
    assert (
        db_session.scalar(
            select(func.count(WebResource.id)).where(
                WebResource.normalized_url.in_(
                    [existing_url.normalized_url, new_url.normalized_url]
                )
            )
        )
        == 2
    )


@pytest.mark.asyncio
async def test_queries_paginate_and_deletion_preserves_shared_blobs(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    store = LocalAiDocumentStore(tmp_path / "ai")
    sources = []
    for path in ("/llms.txt", "/docs/llms.txt"):
        source = create_ai_document_source(
            db_session,
            site.id,
            AiDocumentSourceCreate(entry_url=path, name=path),
        )
        assert source is not None
        sources.append(source)
        refresh = create_source_refresh(db_session, site.id, source.id)
        assert refresh is not None
        await execute_ai_document_refresh(
            db_session,
            refresh,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "text/plain"},
                    content=b"# Shared\n\n## Docs\n- [Page](/page)\n",
                )
            ),
            store=store,
        )
        db_session.commit()

    latest = db_session.scalar(select(AiDocumentRefresh).order_by(AiDocumentRefresh.id.desc()))
    assert latest is not None
    files = list_ai_documents(
        db_session,
        latest.id,
        search="llms",
        kind="llms_index",
        role=None,
        fetch_state=None,
        parse_state=None,
        changed=None,
        depth=None,
        sort="url",
        direction="asc",
        limit=25,
        offset=0,
    )
    references = list_ai_references(
        db_session,
        latest.id,
        search="Page",
        in_scope=True,
        optional=False,
        fetched=False,
        limit=25,
        offset=0,
    )
    assert files.total == 1
    assert references.total == 1

    preview = preview_ai_source_deletion(db_session, sources[0].id)
    assert preview is not None
    assert preview.shared_blob_count == 1
    blob = db_session.scalar(select(AiDocumentBlob))
    assert blob is not None
    path = store.root / blob.storage_key
    assert delete_ai_source(db_session, sources[0].id, store) == sources[0].id
    assert db_session.get(AiDocumentBlob, blob.id) is not None
    assert path.exists()
    assert delete_ai_source(db_session, sources[1].id, store) == sources[1].id
    assert db_session.get(AiDocumentBlob, blob.id) is None
    assert not path.exists()


@pytest.mark.asyncio
async def test_refresh_query_growth_and_progress_are_bounded(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(
            entry_url="/llms.txt",
            name="AI docs",
            settings=AiDocumentSettings(max_total_documents=150),
        ),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None
    root = "# Docs\n\n## Files\n" + "\n".join(
        f"- [Document {index}](/docs/{index}.md)" for index in range(100)
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/llms.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text=root)
        return httpx.Response(
            200,
            headers={"content-type": "text/markdown"},
            text=f"# {request.url.path}",
        )

    counts: Counter[str] = Counter()

    def count_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = statement.casefold()
        table = next(
            (
                name
                for name in (
                    "web_resources",
                    "ai_document_snapshots",
                    "ai_document_references",
                    "url_source_entries",
                )
                if name in normalized
            ),
            "other",
        )
        counts[f"{normalized.split(maxsplit=1)[0]} {table}"] += 1

    progress: list[int] = []
    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", count_statement)
    try:
        evidence = await execute_ai_document_refresh(
            db_session,
            refresh,
            transport=httpx.MockTransport(respond),
            store=LocalAiDocumentStore(tmp_path / "ai"),
            progress_callback=lambda active: progress.append(active.discovered_entry_count),
        )
        db_session.commit()
    finally:
        event.remove(bind, "before_cursor_execute", count_statement)

    assert sum(counts.values()) <= 500
    assert counts["select web_resources"] <= 4
    assert counts["select url_source_entries"] == 1
    assert counts["insert url_source_entries"] == 1
    assert evidence.document_saved_count == 101
    assert progress == [50, 100, 101]


@pytest.mark.asyncio
async def test_repeated_target_keeps_references_and_batches_inventory(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None
    root = "# Docs\n\n## Files\n" + "\n".join(
        f"- [Declaration {index}](/shared.md)" for index in range(100)
    )
    statement_count = 0

    def count_statement(*_args) -> None:
        nonlocal statement_count
        statement_count += 1

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", count_statement)
    try:
        await execute_ai_document_refresh(
            db_session,
            refresh,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={
                        "content-type": (
                            "text/plain" if request.url.path == "/llms.txt" else "text/markdown"
                        )
                    },
                    text=root if request.url.path == "/llms.txt" else "# Shared",
                )
            ),
            store=LocalAiDocumentStore(tmp_path / "ai"),
        )
        db_session.commit()
    finally:
        event.remove(bind, "before_cursor_execute", count_statement)

    assert statement_count <= 150
    assert db_session.scalar(select(func.count(AiDocumentReference.id))) == 100
    assert db_session.scalar(select(func.count(AiDocumentSnapshot.id))) == 2
    assert db_session.scalar(select(func.count(UrlSourceEntry.id))) == 1
    entry = db_session.scalar(select(UrlSourceEntry))
    assert entry is not None
    assert len(entry.source_metadata_json["ai_origins"]) == 100
    assert db_session.scalar(select(func.count(ResourceSnapshot.id))) == 0


@pytest.mark.asyncio
async def test_identical_files_share_blob_within_refresh(db_session, tmp_path) -> None:
    site = create_site(db_session, _site_payload())
    source = create_ai_document_source(
        db_session,
        site.id,
        AiDocumentSourceCreate(entry_url="/llms.txt", name="AI docs"),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None

    def respond(request: httpx.Request) -> httpx.Response:
        content = (
            b"# Docs\n\n## Files\n- [A](/a.md)\n- [B](/b.md)\n"
            if request.url.path == "/llms.txt"
            else b"# Identical\n"
        )
        return httpx.Response(200, headers={"content-type": "text/markdown"}, content=content)

    await execute_ai_document_refresh(
        db_session,
        refresh,
        transport=httpx.MockTransport(respond),
        store=LocalAiDocumentStore(tmp_path / "ai"),
    )
    db_session.commit()

    child_blob_ids = list(
        db_session.scalars(
            select(AiDocumentSnapshot.retained_blob_id).where(
                AiDocumentSnapshot.requested_url.in_(
                    ["https://example.com/a.md", "https://example.com/b.md"]
                )
            )
        )
    )
    assert len(set(child_blob_ids)) == 1
    assert db_session.scalar(select(func.count(AiDocumentBlob.id))) == 2


def test_blob_store_removes_new_file_when_database_flush_fails(
    db_session, tmp_path, monkeypatch
) -> None:
    store = LocalAiDocumentStore(tmp_path / "ai")

    def fail_flush() -> None:
        raise RuntimeError("database failure")

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="database failure"):
        store.put(db_session, b"evidence", "text/plain", "utf-8")

    assert list(store.root.rglob("*.gz")) == []
    db_session.rollback()


def test_blob_store_does_not_add_row_when_file_write_fails(
    db_session, tmp_path, monkeypatch
) -> None:
    store = LocalAiDocumentStore(tmp_path / "ai")

    def fail_write(_path: Path, _content: bytes) -> int:
        raise OSError("storage failure")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    with pytest.raises(OSError, match="storage failure"):
        store.put(db_session, b"evidence", "text/plain", "utf-8")

    assert db_session.scalar(select(func.count(AiDocumentBlob.id))) == 0
