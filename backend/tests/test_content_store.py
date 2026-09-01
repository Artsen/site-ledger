import pytest

from app.models import ContentBlob
from app.storage.content_store import BlobNotFoundError, LocalContentStore, _deterministic_gzip


def test_hash_compress_retrieve_and_reuse(tmp_path, db_session) -> None:
    store = LocalContentStore(tmp_path)
    first = store.put_html(db_session, b"<html>same</html>", "text/html", "utf-8")
    second = store.put_html(db_session, b"<html>same</html>", "text/html", "utf-8")
    db_session.commit()
    assert first.id == second.id
    assert first.raw_byte_size == len(b"<html>same</html>")
    assert first.stored_byte_size > 0
    assert store.get(first) == b"<html>same</html>"


def test_missing_blob_raises(tmp_path, db_session) -> None:
    store = LocalContentStore(tmp_path)
    blob = ContentBlob(
        sha256="a" * 64,
        storage_key="aa/aa/missing.html.gz",
        compression_type="gzip",
        raw_byte_size=1,
        stored_byte_size=1,
    )
    with pytest.raises(BlobNotFoundError):
        store.get(blob)


def test_gzip_encoding_is_deterministic() -> None:
    content = b"<html>deterministic</html>"

    assert _deterministic_gzip(content) == _deterministic_gzip(content)


def test_atomic_publish_failure_cleans_temporary_file(tmp_path, db_session, monkeypatch) -> None:
    store = LocalContentStore(tmp_path / "html")

    def fail_publish(*_args) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr("app.storage.content_store.os.replace", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        store.put_html(db_session, b"content", "text/html", "utf-8")

    assert not list(store.root.rglob("*.tmp"))
    assert db_session.query(ContentBlob).count() == 0
