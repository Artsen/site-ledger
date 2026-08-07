import gzip
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiDocumentBlob


class AiDocumentBlobNotFoundError(FileNotFoundError):
    pass


class LocalAiDocumentStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self, db: Session, content: bytes, media_type: str | None, encoding: str | None
    ) -> AiDocumentBlob:
        sha = hashlib.sha256(content).hexdigest()
        existing = db.scalar(select(AiDocumentBlob).where(AiDocumentBlob.sha256 == sha))
        if existing:
            return existing
        compressed = gzip.compress(content)
        storage_key = f"{sha[:2]}/{sha[2:4]}/{sha}.txt.gz"
        path = self.root / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        created_file = not path.exists()
        path.write_bytes(compressed)
        blob = AiDocumentBlob(
            sha256=sha,
            storage_key=storage_key,
            media_type=media_type,
            encoding=encoding,
            compression_type="gzip",
            raw_byte_size=len(content),
            stored_byte_size=len(compressed),
        )
        db.add(blob)
        try:
            db.flush()
        except Exception:
            if created_file:
                path.unlink(missing_ok=True)
            raise
        return blob

    def get(self, blob: AiDocumentBlob) -> bytes:
        path = self.root / blob.storage_key
        if not path.exists():
            raise AiDocumentBlobNotFoundError(blob.storage_key)
        return gzip.decompress(path.read_bytes())

    def delete(self, blob: AiDocumentBlob) -> bool:
        path = self.root / blob.storage_key
        if not path.exists():
            return False
        path.unlink()
        return True
