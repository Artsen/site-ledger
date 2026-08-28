from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.structured_content_routes import router
from app.crawler.canonical_document import (
    STRUCTURED_CONTENT_CONFIG_VERSION,
    STRUCTURED_CONTENT_EXTRACTOR_VERSION,
    STRUCTURED_MARKDOWN_RENDERER_VERSION,
    extract_canonical_document,
    render_markdown,
)
from app.database import get_db
from app.models import (
    HtmlStructuredContentArtifact,
    HtmlStructuredContentNode,
    HtmlStructuredContentSection,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.structured_content import (
    get_or_create_structured_artifact,
    rebuild_structured_artifact,
)
from app.services.structured_content_queries import structured_document_for_snapshot
from app.storage.content_store import LocalContentStore


def test_same_blob_different_observation_context_reuses_identical_v2_document(
    db_session, tmp_path: Path
) -> None:
    source = b"""
    <html><body><main><h1>Guide</h1>
      <p>Read <a href="../guide?view=full#intro">the guide</a>.</p>
      <figure><img src="/images/guide.png" alt="Guide cover"><figcaption>Cover</figcaption></figure>
    </main></body></html>
    """
    store = LocalContentStore(tmp_path / "html")
    blob = store.put_html(db_session, source, "text/html", "utf-8")
    sites = [
        WebsiteProperty(
            name=f"Context {index}",
            base_url=base,
            normalized_base_url=base,
            group_key="test",
            platform_key="test",
            ownership_key="test",
            scope_config={},
        )
        for index, base in enumerate(("https://one.example/a/", "https://two.example/b/"), 1)
    ]
    db_session.add_all(sites)
    db_session.flush()
    snapshots: list[ResourceSnapshot] = []
    for index, site in enumerate(sites, 1):
        resource = WebResource(
            resource_type="page",
            normalized_url=f"{site.base_url}page",
            scheme="https",
            host=f"{index}.example",
            path=f"/{index}/page",
            query="",
        )
        scan = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="completed",
            scope_config={},
            created_at=datetime(2026, 8, 27, tzinfo=UTC) + timedelta(hours=index),
        )
        db_session.add_all([resource, scan])
        db_session.flush()
        snapshots.append(
            ResourceSnapshot(
                scan_id=scan.id,
                resource_id=resource.id,
                requested_url=f"{site.base_url}requested/page",
                final_url=f"{site.base_url}final/page",
                http_status=200,
                content_type="text/html",
                encoding="utf-8",
                crawl_depth=0,
                fetched_at=datetime(2026, 8, 27, tzinfo=UTC) + timedelta(hours=index),
                response_headers={},
                redirect_chain=[],
                html_blob_id=blob.id,
                raw_html_sha256=blob.sha256,
                fetch_state="fetched",
                retrieval_method="full_fetch",
            )
        )
    db_session.add_all(snapshots)
    db_session.commit()

    first, reused = get_or_create_structured_artifact(db_session, blob, content=source)
    second, reused_again = get_or_create_structured_artifact(db_session, blob, store=store)

    assert reused is False
    assert reused_again is True
    assert second.id == first.id
    assert (
        first.extractor_version == STRUCTURED_CONTENT_EXTRACTOR_VERSION == "structured-content-v2"
    )
    assert (
        first.extractor_config_version
        == STRUCTURED_CONTENT_CONFIG_VERSION
        == "canonical-document-v1"
    )
    assert (
        first.markdown_renderer_version
        == STRUCTURED_MARKDOWN_RENDERER_VERSION
        == "structured-markdown-v1"
    )
    assert first.canonical_document_sha256 == second.canonical_document_sha256
    assert first.markdown_sha256 == second.markdown_sha256
    assert [node.semantic_sha256 for node in first.nodes] == [
        node.semantic_sha256 for node in second.nodes
    ]
    assert [node.subtree_sha256 for node in first.nodes] == [
        node.subtree_sha256 for node in second.nodes
    ]
    markdown = render_markdown(first.nodes)
    assert "(../guide?view=full#intro)" in markdown
    assert "(/images/guide.png)" in markdown
    assert "https://one.example" not in markdown
    assert "https://two.example" not in markdown
    assert (
        len(
            db_session.scalars(
                select(ResourceSnapshot).where(ResourceSnapshot.html_blob_id == blob.id)
            ).all()
        )
        == 2
    )


def test_rich_structure_and_exact_markdown_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures" / "structured_content_v2"
    document = extract_canonical_document((fixture / "rich.html").read_bytes())
    kinds = {node.kind for node in document.nodes}

    assert {
        "document",
        "section",
        "heading",
        "paragraph",
        "list",
        "list_item",
        "figure",
        "caption",
        "blockquote",
        "code_block",
        "table",
        "table_row",
        "table_cell",
        "definition_list",
        "definition_term",
        "definition_description",
        "thematic_break",
    } <= kinds
    assert document.markdown == (fixture / "rich.md").read_text(encoding="utf-8")
    assert (
        document.markdown_sha256
        == extract_canonical_document((fixture / "rich.html").read_bytes()).markdown_sha256
    )
    link = next(run for node in document.nodes for run in node.inline if run["kind"] == "link")
    image = next(run for node in document.nodes for run in node.inline if run["kind"] == "image")
    assert link["href"] == "../guide?view=full#intro"
    assert image["src"] == "/images/cover.png"
    assert image["alt"] == "Guide cover"
    assert image["title"] == "Cover"
    assert all("onclick" not in node.source_attributes for node in document.nodes)
    cells = [node for node in document.nodes if node.kind == "table_cell"]
    assert any(node.semantic["rowspan"] == 2 for node in cells)
    assert any(node.semantic["colspan"] == 2 for node in cells)


def test_heading_section_is_synthetic_but_heading_tag_is_source_truth() -> None:
    document = extract_canonical_document(b"<h1>Title</h1>")
    section = next(node for node in document.nodes if node.kind == "section")
    heading = next(node for node in document.nodes if node.kind == "heading")

    assert section.source_tag is None
    assert section.semantic == {"section_kind": "heading", "level": 1}
    assert heading.source_tag == "h1"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            b"<table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table>",
            "| Name | Value |\n| --- | --- |\n| A | 1 |\n",
        ),
        (
            b"<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>",
            "|  |  |\n| --- | --- |\n| A | B |\n| 1 | 2 |\n",
        ),
        (
            b"<table><tr><th>Label</th><td>Value</td></tr><tr><td>A</td><td>1</td></tr></table>",
            "|  |  |\n| --- | --- |\n| Label | Value |\n| A | 1 |\n",
        ),
    ],
)
def test_markdown_tables_do_not_invent_source_header_cells(source: bytes, expected: str) -> None:
    first = extract_canonical_document(source)
    second = extract_canonical_document(source)

    assert first.markdown == expected
    assert first.markdown == second.markdown
    assert first.markdown_sha256 == second.markdown_sha256
    assert first.canonical_document_sha256 == second.canonical_document_sha256


def test_markdown_destinations_escape_syntax_without_changing_canonical_values() -> None:
    href = r"../guides/a b(1)\windows?q=two words#part(2)"
    src = r"/images/a b(1)\cover.png?size=large#hero"
    document = extract_canonical_document(
        f'<p><a href="{href}">Guide</a><img src="{src}" alt="Cover"></p>'.encode()
    )
    link = next(run for node in document.nodes for run in node.inline if run["kind"] == "link")
    image = next(run for node in document.nodes for run in node.inline if run["kind"] == "image")

    assert link["href"] == href
    assert image["src"] == src
    assert "[Guide](<../guides/a b(1)\\\\windows?q=two words#part(2)>)" in document.markdown
    assert "![Cover](</images/a b(1)\\\\cover.png?size=large#hero>)" in document.markdown


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"<h1>One</h1><h1>Two</h1><h3></h3>", {"headings": [1, 1, 3], "empty": True}),
        (b"<ol><li>A<ol><li>B</li></ol></li></ol>", {"kinds": {"list", "list_item"}}),
        (b"<a href='?q=a%20b#x'>Query</a><img src='../a.png' alt='A'>", {"urls": True}),
        (
            b"<header>H</header><nav>N</nav><main>M</main><article>A</article><aside>S</aside><footer>F</footer>",
            {"regions": {"header", "nav", "main", "article", "aside", "footer"}},
        ),
        (
            b"<script>bad</script><style>bad</style><template>bad</template><noscript>bad</noscript><svg><text>bad</text></svg><p>Good</p>",
            {"excluded": True},
        ),
        (
            "<meta charset='utf-8'><p>Café &amp; 世界</p>".encode(),
            {"text": "Café & 世界"},
        ),
        (b"<h2>Open<p>Recovered", {"kinds": {"heading", "paragraph"}}),
        (
            b"<custom-card data-ignored='x'><p>Inside</p></custom-card>",
            {"kinds": {"generic_block", "paragraph"}},
        ),
        (b"", {"profile": "unavailable"}),
    ],
)
def test_canonical_conformance_corpus(source: bytes, expected: dict[str, object]) -> None:
    document = extract_canonical_document(source)
    nodes = document.nodes
    if "headings" in expected:
        assert [node.semantic["level"] for node in nodes if node.kind == "heading"] == expected[
            "headings"
        ]
        assert any(node.kind == "heading" and node.text == "" for node in nodes)
    if "kinds" in expected:
        assert expected["kinds"] <= {node.kind for node in nodes}  # type: ignore[operator]
    if expected.get("urls"):
        runs = [run for node in nodes for run in node.inline]
        assert any(run.get("href") == "?q=a%20b#x" for run in runs)
        assert any(run.get("src") == "../a.png" for run in runs)
    if "regions" in expected:
        assert expected["regions"] <= {node.region_key for node in nodes}  # type: ignore[operator]
    if expected.get("excluded"):
        assert "bad" not in document.markdown
        assert "Good" in document.markdown
    if "text" in expected:
        assert expected["text"] in document.markdown
    if "profile" in expected:
        assert document.document_profile == expected["profile"]


def test_wrapper_dom_paths_do_not_change_semantic_identity() -> None:
    first = extract_canonical_document(b"<main><p>Hello</p></main>")
    wrapped = extract_canonical_document(b"<main><div><div><p>Hello</p></div></div></main>")
    assert first.canonical_document_sha256 == wrapped.canonical_document_sha256
    assert first.markdown == wrapped.markdown


def test_bounds_are_explicit_deterministic_and_never_claim_completeness() -> None:
    source = (
        b"<body>"
        + b"".join(
            f"<p data-{index}='ignored'>Paragraph {index} with text.</p>".encode()
            for index in range(30)
        )
        + b"</body>"
    )
    first = extract_canonical_document(source, max_nodes=8, max_characters=60, max_inline_runs=5)
    second = extract_canonical_document(source, max_nodes=8, max_characters=60, max_inline_runs=5)
    assert first.extraction_state == "partial"
    assert first.is_truncated is True
    assert set(first.truncation_reasons) & {"node_limit", "character_limit", "inline_run_limit"}
    assert first.canonical_document_sha256 == second.canonical_document_sha256
    assert first.markdown == second.markdown

    deep = extract_canonical_document(
        ("<div>" * 10 + "<p>Too deep</p>" + "</div>" * 10).encode(),
        max_depth=4,
    )
    attributed = extract_canonical_document(
        ("<p title='" + "x" * 9_000 + "'>Bounded attribute</p>").encode()
    )
    assert deep.extraction_state == "partial"
    assert "depth_limit" in deep.truncation_reasons
    assert attributed.extraction_state == "partial"
    assert "source_attribute_limit" in attributed.truncation_reasons
    assert all(
        sum(len(key) + len(value) for key, value in node.source_attributes.items()) <= 8_192
        for node in attributed.nodes
    )


def test_v2_rebuild_is_field_for_field_deterministic_and_v1_remains_untouched(
    db_session, tmp_path: Path
) -> None:
    source = (
        Path(__file__).parent / "fixtures" / "structured_content_v2" / "rich.html"
    ).read_bytes()
    store = LocalContentStore(tmp_path / "rebuild")
    blob = store.put_html(db_session, source, "text/html", "utf-8")
    v1 = HtmlStructuredContentArtifact(
        content_blob_id=blob.id,
        extractor_version="structured-content-v1",
        extractor_config_version="default-v1",
        extraction_state="ready",
        document_profile="headed",
        section_count=1,
        heading_count=1,
        heading_counts_json={"h1": 1},
        document_word_count=2,
        document_character_count=10,
        document_text_sha256="a" * 64,
        outline_sha256="b" * 64,
        is_truncated=False,
        truncation_reasons_json=[],
    )
    db_session.add(v1)
    db_session.flush()
    v1_section = HtmlStructuredContentSection(
        artifact_id=v1.id,
        position=0,
        kind="heading",
        heading_level=1,
        heading_text="Historical",
        region_key="body",
        direct_text="V1",
        direct_text_sha256="c" * 64,
        section_sha256="d" * 64,
        subtree_sha256="e" * 64,
    )
    db_session.add(v1_section)
    db_session.commit()

    first, reused = get_or_create_structured_artifact(db_session, blob, content=source)
    first_payload = _artifact_payload(first)
    rebuilt = rebuild_structured_artifact(db_session, blob, store)

    assert reused is False
    assert _artifact_payload(rebuilt) == first_payload
    assert (
        db_session.get(HtmlStructuredContentArtifact, v1.id).extractor_version
        == "structured-content-v1"
    )
    assert db_session.get(HtmlStructuredContentSection, v1_section.id).heading_text == "Historical"
    assert (
        db_session.scalar(
            select(func.count(HtmlStructuredContentArtifact.id)).where(
                HtmlStructuredContentArtifact.content_blob_id == blob.id
            )
        )
        == 2
    )


def test_shared_blob_v2_survives_one_observation_delete_and_cascades_with_blob(
    db_session, tmp_path: Path
) -> None:
    store = LocalContentStore(tmp_path / "shared")
    blob = store.put_html(db_session, b"<h1>Shared</h1><p>Body</p>", "text/html", "utf-8")
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.test/",
        scheme="https",
        host="example.test",
        path="/",
        query="",
    )
    scans = [
        Scan(starting_url=f"https://example.test/{index}", status="completed", scope_config={})
        for index in range(2)
    ]
    db_session.add_all([resource, *scans])
    db_session.flush()
    snapshots = [
        ResourceSnapshot(
            scan_id=scan.id,
            resource_id=resource.id,
            requested_url=scan.starting_url,
            final_url=scan.starting_url,
            http_status=200,
            content_type="text/html",
            crawl_depth=0,
            response_headers={},
            redirect_chain=[],
            html_blob_id=blob.id,
            raw_html_sha256=blob.sha256,
            fetch_state="fetched",
        )
        for scan in scans
    ]
    db_session.add_all(snapshots)
    artifact, _ = get_or_create_structured_artifact(db_session, blob, store=store)
    db_session.commit()
    artifact_id = artifact.id
    db_session.delete(snapshots[0])
    db_session.commit()
    assert db_session.get(HtmlStructuredContentArtifact, artifact_id) is not None
    db_session.delete(snapshots[1])
    db_session.delete(blob)
    db_session.commit()
    assert db_session.get(HtmlStructuredContentArtifact, artifact_id) is None
    assert (
        db_session.scalar(
            select(func.count(HtmlStructuredContentNode.id)).where(
                HtmlStructuredContentNode.artifact_id == artifact_id
            )
        )
        == 0
    )


def test_document_query_is_paginated_and_markdown_api_is_bounded_with_provenance(
    db_session, tmp_path: Path
) -> None:
    source = b"<main><h1>Guide</h1><p>One <a href='../two'>two</a> three.</p></main>"
    store = LocalContentStore(tmp_path / "api")
    blob = store.put_html(db_session, source, "text/html", "utf-8")
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.test/guide",
        scheme="https",
        host="example.test",
        path="/guide",
        query="",
    )
    scan = Scan(starting_url="https://example.test/", status="completed", scope_config={})
    db_session.add_all([resource, scan])
    db_session.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=200,
        content_type="text/html",
        crawl_depth=0,
        response_headers={},
        redirect_chain=[],
        html_blob_id=blob.id,
        raw_html_sha256=blob.sha256,
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    artifact, _ = get_or_create_structured_artifact(db_session, blob, content=source)
    db_session.commit()

    page = structured_document_for_snapshot(db_session, snapshot, limit=2, offset=1)
    assert page.total == artifact.node_count
    assert [node.position for node in page.items] == [1, 2]

    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    application = FastAPI()
    application.include_router(router)

    def override_db():
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        document = client.get(
            f"/api/snapshots/{snapshot.id}/structured-content/document?limit=2&offset=1"
        )
        markdown = client.get(
            f"/api/snapshots/{snapshot.id}/structured-content/markdown?max_characters=12"
        )

    assert document.status_code == 200
    assert document.json()["total"] == artifact.node_count
    assert [item["position"] for item in document.json()["items"]] == [1, 2]
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.headers["x-structured-content-extractor"] == "structured-content-v2"
    assert markdown.headers["x-structured-content-config"] == "canonical-document-v1"
    assert markdown.headers["x-structured-markdown-renderer"] == "structured-markdown-v1"
    assert markdown.headers["x-structured-markdown-sha256"] == artifact.markdown_sha256
    assert markdown.headers["x-structured-markdown-partial"] == "true"
    assert len(markdown.text) == 12


def _artifact_payload(artifact: HtmlStructuredContentArtifact) -> dict[str, object]:
    return {
        "document": artifact.canonical_document_sha256,
        "outline": artifact.outline_sha256,
        "markdown": render_markdown(artifact.nodes),
        "markdown_sha": artifact.markdown_sha256,
        "nodes": [
            (
                node.position,
                node.kind,
                node.depth,
                node.source_tag,
                node.source_dom_path,
                node.region_key,
                node.region_dom_path,
                node.text,
                node.inline_json,
                node.source_attributes_json,
                node.semantic_json,
                node.semantic_sha256,
                node.subtree_sha256,
                node.child_count,
                node.descendant_count,
            )
            for node in artifact.nodes
        ],
    }
