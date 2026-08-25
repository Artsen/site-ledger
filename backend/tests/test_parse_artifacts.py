from app.models import HtmlParseAnchor, HtmlParseArtifact
from app.services.parse_artifacts import (
    HTML_PARSER_CONFIG_VERSION,
    HTML_PARSER_VERSION,
    get_or_create_artifact,
)
from app.storage.content_store import LocalContentStore


def test_parse_artifact_reuses_same_blob_version_and_base(db_session, tmp_path) -> None:
    store = LocalContentStore(tmp_path)
    content = b"""
      <html><head><title>Example</title><link rel="canonical" href="/canonical"></head>
      <body><a href="/a">A</a><a href="b">B</a></body></html>
    """
    blob = store.put_html(db_session, content, "text/html", "utf-8")

    first = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/root/",
    )
    second = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/root/",
    )

    assert first.parsed is True
    assert second.parsed is False
    assert first.parse_method == "parsed"
    assert second.parse_method == "reused_exact_hash"
    assert first.artifact.id == second.artifact.id
    assert first.artifact.parser_version == "html-parser-v4-rel-token-semantics"
    assert first.artifact.parser_version == HTML_PARSER_VERSION
    assert first.artifact.parser_config_version == HTML_PARSER_CONFIG_VERSION == "default-v1"
    assert second.anchors[0].resolved_url == "https://example.com/a"
    assert second.anchors[1].resolved_url == "https://example.com/root/b"
    assert db_session.query(HtmlParseArtifact).count() == 1
    assert [
        anchor.raw_href
        for anchor in db_session.query(HtmlParseAnchor).order_by(HtmlParseAnchor.position)
    ] == ["/a", "b"]


def test_parse_artifact_resolution_base_is_part_of_identity(db_session, tmp_path) -> None:
    store = LocalContentStore(tmp_path)
    content = (
        b"<html><head><title>Example</title></head><body><a href='child'>Child</a></body></html>"
    )
    blob = store.put_html(db_session, content, "text/html", "utf-8")

    first = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/a/",
    )
    second = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/b/",
    )

    assert first.artifact.id != second.artifact.id
    assert first.anchors[0].resolved_url == "https://example.com/a/child"
    assert second.anchors[0].resolved_url == "https://example.com/b/child"
    assert db_session.query(HtmlParseArtifact).count() == 2


def test_v3_parser_artifact_remains_unchanged_and_is_not_reused_as_v4(db_session, tmp_path) -> None:
    store = LocalContentStore(tmp_path)
    content = b"""<html><head>
      <link rel="alternate canonical" href="/canonical">
      <link rel="preload stylesheet" href="/asset.css">
    </head><body><nav><a href="/a">A</a></nav></body></html>"""
    blob = store.put_html(db_session, content, "text/html", "utf-8")
    legacy = HtmlParseArtifact(
        content_blob_id=blob.id,
        parser_version="html-parser-v3-resource-references",
        parser_config_version="default-v1",
        resolution_base_url="https://example.com/",
        page_title=None,
        html_language=None,
        meta_description=None,
        meta_robots=None,
        canonical_url=None,
        document_encoding="utf-8",
        viewport=None,
        head_sha256="0" * 64,
        parsed_head_json={"historical": "v3"},
        anchor_count=1,
        resource_reference_count=0,
    )
    db_session.add(legacy)
    db_session.flush()
    legacy_anchor = HtmlParseAnchor(
        parse_artifact_id=legacy.id,
        position=0,
        raw_href="/historical-v3",
        resolved_url="https://example.com/historical-v3",
        anchor_text="Historical V3",
        title=None,
        aria_label=None,
        rel="nofollow",
        target=None,
        dom_path="html > body > a",
        link_role="content",
        link_role_rule="historical-v3-rule",
        link_context_json={"historical": True},
    )
    db_session.add(legacy_anchor)
    db_session.flush()

    current = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/",
    )

    assert current.artifact.id != legacy.id
    assert current.artifact.parser_version == "html-parser-v4-rel-token-semantics"
    assert current.artifact.canonical_url == "https://example.com/canonical"
    assert [item.relation_type for item in current.resource_references] == [
        "alternate",
        "stylesheet",
    ]
    assert current.anchors[0].link_role == "navigation"
    db_session.refresh(legacy)
    db_session.refresh(legacy_anchor)
    assert legacy.parser_version == "html-parser-v3-resource-references"
    assert legacy.canonical_url is None
    assert legacy.parsed_head_json == {"historical": "v3"}
    assert legacy.resource_reference_count == 0
    assert legacy_anchor.raw_href == "/historical-v3"
    assert legacy_anchor.link_role_rule == "historical-v3-rule"
    assert db_session.query(HtmlParseArtifact).count() == 2
