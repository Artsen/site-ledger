import gzip
import hashlib

import httpx
import pytest
from sqlalchemy import func, select

from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentRefresh,
    AiDocumentSnapshot,
    ResourceSnapshot,
    UrlSourceEntry,
)
from app.schemas.ai_documents import AiDocumentSettings, AiDocumentSourceCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.ai_document_queries import list_ai_documents, list_ai_references
from app.services.ai_document_sources import (
    create_ai_document_source,
    delete_ai_source,
    discover_ai_document_sources,
    execute_ai_document_refresh,
    get_ai_source,
    preview_ai_source_deletion,
)
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
