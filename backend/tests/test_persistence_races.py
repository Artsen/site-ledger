from __future__ import annotations

import gzip

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.crawler.url_normalizer import normalize_url_v2
from app.database import Base
from app.models import ContentBlob, HtmlParseAnchor, HtmlParseArtifact, WebResource
from app.services.parse_artifacts import get_or_create_artifact
from app.services.repositories import get_or_create_resource
from app.services.url_identity import ensure_url_identity_state
from app.storage.content_store import LocalContentStore


def _sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'races.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        ensure_url_identity_state(db)
        db.commit()
    return factory


def test_web_resource_unique_race_recovers_committed_winner(tmp_path) -> None:
    factory = _sessions(tmp_path)
    normalized = normalize_url_v2("https://example.com/race")

    with factory() as loser, factory() as winner:
        original_flush = loser.flush
        raced = False

        def flush_with_winner(objects=None) -> None:
            nonlocal raced
            if not raced and any(isinstance(item, WebResource) for item in loser.new):
                raced = True
                get_or_create_resource(winner, normalized)
                winner.commit()
            original_flush(objects)

        loser.flush = flush_with_winner  # type: ignore[method-assign]
        recovered = get_or_create_resource(loser, normalized)
        loser.commit()

        assert recovered.id == winner.scalar(select(WebResource.id))
        assert recovered.last_seen_at is not None

    with factory() as db:
        assert db.scalar(select(func.count(WebResource.id))) == 1


def test_content_blob_unique_race_recovers_winner_and_publishes_atomically(tmp_path) -> None:
    factory = _sessions(tmp_path)
    store = LocalContentStore(tmp_path / "html")
    content = b"<html><body>race</body></html>"

    with factory() as loser, factory() as winner:
        original_flush = loser.flush
        raced = False

        def flush_with_winner(objects=None) -> None:
            nonlocal raced
            if not raced and any(isinstance(item, ContentBlob) for item in loser.new):
                raced = True
                store.put_html(winner, content, "text/html", "utf-8")
                winner.commit()
            original_flush(objects)

        loser.flush = flush_with_winner  # type: ignore[method-assign]
        recovered = store.put_html(loser, content, "text/html", "utf-8")
        loser.commit()

        assert recovered.id == winner.scalar(select(ContentBlob.id))
        assert store.get(recovered) == content

    assert not list((tmp_path / "html").rglob("*.tmp"))
    with factory() as db:
        assert db.scalar(select(func.count(ContentBlob.id))) == 1


def test_parse_artifact_unique_race_returns_persisted_winner_children(tmp_path) -> None:
    factory = _sessions(tmp_path)
    store = LocalContentStore(tmp_path / "html")
    content = b"<html><body><a href='/loser'>Loser</a></body></html>"
    winner_content = b"<html><body><a href='/winner'>Winner</a></body></html>"
    with factory() as setup:
        blob_id = store.put_html(setup, content, "text/html", "utf-8").id
        setup.commit()

    with factory() as loser, factory() as winner:
        loser_blob = loser.get(ContentBlob, blob_id)
        winner_blob = winner.get(ContentBlob, blob_id)
        assert loser_blob is not None and winner_blob is not None
        original_flush = loser.flush
        raced = False

        def flush_with_winner(objects=None) -> None:
            nonlocal raced
            if not raced and any(isinstance(item, HtmlParseArtifact) for item in loser.new):
                raced = True
                get_or_create_artifact(
                    winner,
                    blob=winner_blob,
                    content=winner_content,
                    resolution_base_url="https://example.com/",
                )
                winner.commit()
            original_flush(objects)

        loser.flush = flush_with_winner  # type: ignore[method-assign]
        recovered = get_or_create_artifact(
            loser,
            blob=loser_blob,
            content=content,
            resolution_base_url="https://example.com/",
        )
        loser.commit()

        assert recovered.parsed is True
        assert recovered.anchors[0].raw_href == "/winner"
        assert recovered.artifact.id == winner.scalar(select(HtmlParseArtifact.id))

    with factory() as db:
        assert db.scalar(select(func.count(HtmlParseArtifact.id))) == 1
        assert db.scalar(select(func.count(HtmlParseAnchor.id))) == 1


def test_legacy_gzip_blob_remains_readable(tmp_path) -> None:
    store = LocalContentStore(tmp_path / "html")
    content = b"legacy gzip content"
    path = store.root / "legacy/content.html.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(content))
    blob = ContentBlob(
        sha256="a" * 64,
        storage_key="legacy/content.html.gz",
        compression_type="gzip",
        raw_byte_size=len(content),
        stored_byte_size=path.stat().st_size,
    )

    assert store.get(blob) == content
