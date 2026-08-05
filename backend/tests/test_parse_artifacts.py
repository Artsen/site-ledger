from app.models import HtmlParseAnchor, HtmlParseArtifact
from app.services.parse_artifacts import get_or_create_artifact
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
    assert first.artifact.id == second.artifact.id
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
