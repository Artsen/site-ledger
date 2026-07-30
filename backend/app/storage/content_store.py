import gzip
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        compressed = gzip.compress(content)
        path.write_bytes(compressed)
        blob = ContentBlob(
            sha256=sha,
            storage_key=storage_key,
            compression_type="gzip",
            content_type=content_type,
            encoding=encoding,
            raw_byte_size=len(content),
            stored_byte_size=len(compressed),
        )
        db.add(blob)
        db.flush()
        return blob

    def get(self, blob: ContentBlob) -> bytes:
        path = self.root / blob.storage_key
        if not path.exists():
            raise BlobNotFoundError(blob.storage_key)
        return gzip.decompress(path.read_bytes())

    def delete(self, blob: ContentBlob) -> None:
        path = self.root / blob.storage_key
        if path.exists():
            path.unlink()
        current = path.parent
        while current != self.root and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
