import gzip
import hashlib

import httpx
import pytest
from sqlalchemy import func, select

from app.models import (
    AiDocumentBlob,
    AiDocumentReference,
    AiDocumentSnapshot,
    ResourceSnapshot,
    UrlSourceEntry,
)
from app.schemas.ai_documents import AiDocumentSettings, AiDocumentSourceCreate
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.services.ai_document_sources import (
    create_ai_document_source,
    discover_ai_document_sources,
    execute_ai_document_refresh,
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
    assert entries[0].source_metadata_json["parent_snapshot_id"]
    external = db_session.scalar(
        select(AiDocumentReference).where(AiDocumentReference.scope_decision == "external")
    )
    assert external is not None and external.inventory_entry_id is None


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
