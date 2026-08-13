from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessibilityPayloadBlob


class AccessibilityPayloadNotFoundError(FileNotFoundError):
    pass


class LocalAccessibilityPayloadStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, db: Session, content: bytes) -> AccessibilityPayloadBlob:
        sha = hashlib.sha256(content).hexdigest()
        existing = db.scalar(
            select(AccessibilityPayloadBlob).where(AccessibilityPayloadBlob.sha256 == sha)
        )
        if existing is not None:
            return existing
        stored = gzip.compress(content, mtime=0)
        key = f"{sha[:2]}/{sha[2:4]}/{sha}.json.gz"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".accessibility-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(stored)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        blob = AccessibilityPayloadBlob(
            sha256=sha,
            storage_key=key,
            raw_byte_size=len(content),
            stored_byte_size=len(stored),
        )
        db.add(blob)
        db.flush()
        return blob

    def read(self, blob: AccessibilityPayloadBlob) -> bytes:
        path = self._path(blob.storage_key)
        if not path.is_file():
            raise AccessibilityPayloadNotFoundError(blob.storage_key)
        return gzip.decompress(path.read_bytes())

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Unsafe Accessibility payload storage key")
        return path
