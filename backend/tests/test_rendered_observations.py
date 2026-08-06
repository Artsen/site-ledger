from datetime import UTC, datetime, timedelta

import pytest

from app.browser.config import DEFAULTS, capabilities, validate_render_config
from app.browser.privacy import redact_url, sanitize_headers
from app.crawler.scope import ScopeConfig
from app.models import (
    ArtifactBlob,
    ContentBlob,
    RenderedArtifact,
    ResourceSnapshot,
    Scan,
    WebResource,
)
from app.services.rendered_capture import create_observation, select_render_candidates
from app.services.scan_deletion import delete_scan
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore


def test_legacy_scope_defaults_to_static_only() -> None:
    config = ScopeConfig.from_dict({"max_pages": 25})
    assert config.render_mode == "none"
    assert config.render_max_pages == DEFAULTS.render_max_pages


def test_capabilities_are_authoritative_and_bounded() -> None:
    contract = capabilities()
    assert contract["defaults"]["render_mode"] == "none"
    assert contract["browser_engine"] == "chromium"
    with pytest.raises(ValueError, match="cannot exceed max_pages"):
        validate_render_config(
            {"max_pages": 2, "render_max_pages": 3, "render_mode": "all_eligible"}
        )


def test_url_and_headers_remove_credentials() -> None:
    redacted, digest = redact_url(
        "https://user:password@example.com/a?token=secret&view=wide#fragment"
    )
    assert redacted == "https://example.com/a?token=%5BREDACTED%5D&view=wide"
    assert len(digest) == 64
    headers = sanitize_headers(
        {"Authorization": "Bearer secret", "Cookie": "id=secret", "Accept": "text/html"}
    )
    assert headers == {"accept": "text/html"}


def test_artifact_store_deduplicates_and_uses_hash_paths(db_session, tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    first = store.put(db_session, b"<html></html>", "text/plain", gzip_content=True)
    second = store.put(db_session, b"<html></html>", "text/plain", gzip_content=True)
    assert first.id == second.id
    assert "html" not in first.storage_key.removesuffix(".html.gz")
    assert store.read(first) == b"<html></html>"
    with pytest.raises(ValueError, match="Unsafe"):
        store._path("../outside")


def test_render_selection_is_deterministic_and_html_only(db_session) -> None:
    scan = Scan(starting_url="https://example.com/", status="running", scope_config={})
    db_session.add(scan)
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/",
        scheme="https",
        host="example.com",
        path="/",
        query="",
    )
    second_resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/b",
        scheme="https",
        host="example.com",
        path="/b",
        query="",
    )
    db_session.add_all([resource, second_resource])
    db_session.flush()
    blob = ContentBlob(
        sha256="a" * 64,
        storage_key="aa/a",
        compression_type="gzip",
        content_type="text/html",
        encoding="utf-8",
        raw_byte_size=10,
        stored_byte_size=8,
    )
    db_session.add(blob)
    db_session.flush()
    later = datetime.now(UTC)
    child = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=second_resource.id,
        requested_url="https://example.com/b",
        final_url="https://example.com/b",
        http_status=200,
        content_type="text/html",
        crawl_depth=1,
        fetched_at=later,
        html_blob_id=blob.id,
        fetch_state="fetched",
    )
    start = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=scan.starting_url,
        final_url=scan.starting_url,
        http_status=404,
        content_type="text/html",
        crawl_depth=0,
        fetched_at=later + timedelta(seconds=1),
        html_blob_id=blob.id,
        fetch_state="fetched",
    )
    db_session.add_all([child, start])
    db_session.commit()
    config = ScopeConfig(render_mode="all_eligible", render_max_pages=2)
    selected = select_render_candidates(db_session, scan, config)
    assert [item.id for item in selected] == [start.id, child.id]


def test_scan_deletion_removes_unreferenced_rendered_files(db_session, tmp_path) -> None:
    content_store = LocalContentStore(tmp_path / "html")
    artifact_store = LocalArtifactStore(tmp_path / "rendered")
    scan = Scan(starting_url="https://example.com/", status="completed", scope_config={})
    resource = WebResource(
        resource_type="page",
        normalized_url=scan.starting_url,
        scheme="https",
        host="example.com",
        path="/",
        query="",
    )
    db_session.add_all([scan, resource])
    db_session.flush()
    html_blob = content_store.put_html(db_session, b"<html></html>", "text/html", "utf-8")
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=scan.starting_url,
        final_url=scan.starting_url,
        http_status=200,
        content_type="text/html",
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        html_blob_id=html_blob.id,
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.commit()
    observation = create_observation(db_session, snapshot, ScopeConfig())
    artifact_blob = artifact_store.put(db_session, b"png", "image/png")
    artifact_path = artifact_store.path_for(artifact_blob)
    db_session.add(
        RenderedArtifact(
            rendered_observation_id=observation.id,
            artifact_blob_id=artifact_blob.id,
            artifact_type="viewport_screenshot",
            metadata_json={},
        )
    )
    db_session.commit()

    assert delete_scan(db_session, scan.id, content_store, artifact_store) is not None
    assert db_session.get(ArtifactBlob, artifact_blob.id) is None
    assert not artifact_path.exists()
