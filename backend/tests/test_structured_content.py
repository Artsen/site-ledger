from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.crawler.structured_content import extract_structured_content
from app.models import (
    HtmlStructuredContentArtifact,
    HtmlStructuredContentSection,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.site_pages import ensure_site_page
from app.services.structured_content import (
    get_or_create_structured_artifact,
    missing_structured_blob_ids,
    rebuild_structured_artifact,
    verify_structured_artifact,
)
from app.services.structured_content_queries import (
    latest_page_content_snapshot,
    structured_content_for_snapshot,
)
from app.storage.content_store import LocalContentStore


def test_extracts_preamble_heading_hierarchy_regions_and_direct_text() -> None:
    result = extract_structured_content(
        b"""
        <html><head><title>Ignored</title><style>ignored</style></head><body>
          Intro <script>ignored()</script>
          <main><h1> Page <script>ignored()</script> title </h1><p>Hello <a href='/'>world</a>.</p>
          <h3>Skipped level</h3><table><tr><th>A</th><th>B</th></tr>
          <tr><td>1</td><td>2</td></tr></table></main>
          <nav><h2>Navigation</h2><p>Links here</p></nav>
          <footer><h2></h2><p>Footer copy</p></footer>
        </body></html>
        """
    )

    assert result.extraction_state == "ready"
    assert result.document_profile == "headed"
    assert result.heading_counts == {"h1": 1, "h2": 2, "h3": 1, "h4": 0, "h5": 0, "h6": 0}
    section_identity = [
        (section.kind, section.heading_level, section.heading_text) for section in result.sections
    ]
    assert section_identity == [
        ("preamble", None, None),
        ("heading", 1, "Page title"),
        ("heading", 3, "Skipped level"),
        ("heading", 2, "Navigation"),
        ("heading", 2, ""),
    ]
    assert result.sections[2].parent_position == result.sections[1].position
    assert result.sections[3].parent_position == result.sections[1].position
    assert result.sections[1].direct_text == "Hello world."
    assert "A\tB" in result.sections[2].direct_text
    assert result.sections[3].region_key == "nav"
    assert result.sections[4].region_key == "footer"
    assert "Ignored" not in "\n".join(section.direct_text for section in result.sections)
    assert "ignored" not in "\n".join(section.direct_text for section in result.sections)


def test_unheaded_duplicate_h1_malformed_unicode_and_determinism() -> None:
    unheaded = extract_structured_content("<body>Caf\u00e9 \u4e16\u754c</body>".encode())
    assert len(unheaded.sections) == 1
    assert unheaded.sections[0].kind == "unheaded"
    assert unheaded.document_word_count == 2

    source = b"<body><h1>One</h1><h1>Two</h1><p>Tail"
    first = extract_structured_content(source)
    second = extract_structured_content(source)
    assert [section.parent_position for section in first.sections] == [None, None]
    assert first.document_text_sha256 == second.document_text_sha256
    assert first.outline_sha256 == second.outline_sha256
    assert [section.subtree_sha256 for section in first.sections] == [
        section.subtree_sha256 for section in second.sections
    ]
    malformed = extract_structured_content(b"<body><h2>Open<p>Recovered")
    assert malformed.extraction_state == "ready"
    assert malformed.sections[0].heading_text == "Open"

    unavailable = extract_structured_content(b"")
    assert unavailable.extraction_state == "unavailable"
    assert unavailable.document_profile == "unavailable"
    assert unavailable.sections == ()


def test_extraction_bounds_are_explicit_and_total_section_bound_is_respected() -> None:
    result = extract_structured_content(
        b"<body>Preamble<h1>One</h1><h2>Two</h2><h3>Three</h3></body>",
        max_sections=2,
        max_characters=20,
    )
    assert result.extraction_state == "partial"
    assert result.is_truncated is True
    assert result.truncation_reasons == ("section_limit",)
    assert len(result.sections) == 2

    character_limited = extract_structured_content(
        b"<body><h1>Title</h1><p>abcdefghijklmnopqrstuvwxyz</p></body>",
        max_characters=8,
    )
    assert character_limited.extraction_state == "partial"
    assert "character_limit" in character_limited.truncation_reasons
    extracted_source_characters = sum(
        len(section.heading_text or "") + len(section.direct_text)
        for section in character_limited.sections
    )
    assert extracted_source_characters <= 8


def test_persistence_reuses_blob_identity_and_rebuilds_without_touching_raw_blob(
    db_session, tmp_path: Path
) -> None:
    store = LocalContentStore(tmp_path / "html")
    source = b"<html><body><h1>Title</h1><p>Body</p></body></html>"
    blob = store.put_html(db_session, source, "text/html", "utf-8")

    first, reused = get_or_create_structured_artifact(db_session, blob, content=source)
    second, reused_again = get_or_create_structured_artifact(db_session, blob, store=store)
    assert reused is False
    assert reused_again is True
    assert second.id == first.id
    assert first.section_count == 1
    verify_structured_artifact(db_session, first)

    raw_sha = blob.sha256
    rebuilt = rebuild_structured_artifact(db_session, blob, store)
    assert rebuilt is not first
    assert rebuilt.document_text_sha256 == first.document_text_sha256
    assert blob.sha256 == raw_sha
    assert store.get(blob) == source
    assert missing_structured_blob_ids(db_session) == []


def test_content_blob_delete_cascades_artifact_and_sections(db_session, tmp_path: Path) -> None:
    store = LocalContentStore(tmp_path / "html")
    blob = store.put_html(db_session, b"<body><h1>Title</h1>Body</body>", "text/html", "utf-8")
    artifact, _ = get_or_create_structured_artifact(db_session, blob, store=store)
    artifact_id = artifact.id
    section_ids = list(
        db_session.scalars(
            select(HtmlStructuredContentSection.id).where(
                HtmlStructuredContentSection.artifact_id == artifact.id
            )
        )
    )
    db_session.delete(blob)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(HtmlStructuredContentArtifact, artifact_id) is None
    assert not list(
        db_session.scalars(
            select(HtmlStructuredContentSection).where(
                HtmlStructuredContentSection.id.in_(section_ids)
            )
        )
    )


def test_latest_page_query_and_response_preserve_observation_provenance(
    db_session, tmp_path: Path
) -> None:
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/page",
        scheme="https",
        host="example.com",
        port=None,
        path="/page",
        query="",
    )
    db_session.add_all([site, resource])
    db_session.flush()
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    store = LocalContentStore(tmp_path / "html-query")
    source = b"<body><h1>Page</h1><p>Content</p><h2>Details</h2><p>More</p></body>"
    blob = store.put_html(db_session, source, "text/html", "utf-8")
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=200,
        content_type="text/html",
        encoding="utf-8",
        crawl_depth=0,
        fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
        response_time_ms=1,
        response_headers={},
        redirect_chain=[],
        html_blob_id=blob.id,
        raw_html_sha256=blob.sha256,
        fetch_state="fetched",
        retrieval_method="full_fetch",
    )
    db_session.add(snapshot)
    db_session.flush()
    ensure_site_page(db_session, scan=scan, resource=resource, associated_at=snapshot.fetched_at)

    not_prepared = structured_content_for_snapshot(db_session, snapshot, limit=10, offset=0)
    assert not_prepared.status == "not_prepared"
    get_or_create_structured_artifact(db_session, blob, content=source)
    latest = latest_page_content_snapshot(db_session, site.id, resource.id)
    assert latest is not None
    ready = structured_content_for_snapshot(db_session, latest, limit=10, offset=0)
    assert ready.status == "ready"
    assert ready.provenance is not None
    assert ready.provenance.snapshot_id == snapshot.id
    assert ready.provenance.content_blob_id == blob.id
    assert ready.items[0].heading_text == "Page"
    second_page = structured_content_for_snapshot(db_session, latest, limit=1, offset=1)
    assert second_page.total == 2
    assert [item.heading_text for item in second_page.items] == ["Details"]
