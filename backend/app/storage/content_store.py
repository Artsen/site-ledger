import gzip
import hashlib
import io
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import materialize_outer_transaction
from app.models import ContentBlob


class BlobNotFoundError(FileNotFoundError):
    pass


class LocalContentStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_html(
        self, db: Session, content: bytes, content_type: str | None, encoding: str | None
    ) -> ContentBlob:
        sha = hashlib.sha256(content).hexdigest()
        existing = db.scalar(select(ContentBlob).where(ContentBlob.sha256 == sha))
        if existing:
            return existing
        storage_key = f"{sha[:2]}/{sha[2:4]}/{sha}.html.gz"
        path = self.root / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        compressed = _deterministic_gzip(content)
        _atomic_publish(path, compressed)
        blob = ContentBlob(
            sha256=sha,
            storage_key=storage_key,
            compression_type="gzip",
            content_type=content_type,
            encoding=encoding,
            raw_byte_size=len(content),
            stored_byte_size=len(compressed),
        )
        materialize_outer_transaction(db)
        try:
            with db.begin_nested():
                db.add(blob)
                db.flush()
            return blob
        except IntegrityError:
            winner = db.scalar(select(ContentBlob).where(ContentBlob.sha256 == sha))
            if winner is None or winner.storage_key != storage_key:
                raise
            return winner

    def get(self, blob: ContentBlob) -> bytes:
        path = self.root / blob.storage_key
        if not path.exists():
            raise BlobNotFoundError(blob.storage_key)
        return gzip.decompress(path.read_bytes())

    def exists(self, blob: ContentBlob) -> bool:
        return (self.root / blob.storage_key).exists()

    def delete(self, blob: ContentBlob) -> bool:
        path = self.root / blob.storage_key
        if not path.exists():
            return False
        path.unlink()
        current = path.parent
        while current != self.root and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
        return True


def _deterministic_gzip(content: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as archive:
        archive.write(content)
    return output.getvalue()


def _atomic_publish(path: Path, content: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
