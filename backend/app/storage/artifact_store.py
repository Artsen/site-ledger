from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ArtifactBlob


class ArtifactNotFoundError(FileNotFoundError):
    pass


class LocalArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self, db: Session, content: bytes, media_type: str, *, gzip_content: bool = False
    ) -> ArtifactBlob:
        sha = hashlib.sha256(content).hexdigest()
        existing = db.scalar(select(ArtifactBlob).where(ArtifactBlob.sha256 == sha))
        if existing:
            return existing
        stored = gzip.compress(content) if gzip_content else content
        suffix = ".html.gz" if gzip_content else ".png"
        key = f"{sha[:2]}/{sha[2:4]}/{sha}{suffix}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".artifact-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(stored)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        blob = ArtifactBlob(
            sha256=sha,
            storage_key=key,
            media_type=media_type,
            compression_type="gzip" if gzip_content else "none",
            raw_byte_size=len(content),
            stored_byte_size=len(stored),
        )
        db.add(blob)
        db.flush()
        return blob

    def path_for(self, blob: ArtifactBlob) -> Path:
        path = self._path(blob.storage_key)
        if not path.is_file():
            raise ArtifactNotFoundError(blob.storage_key)
        return path

    def read(self, blob: ArtifactBlob) -> bytes:
        content = self.path_for(blob).read_bytes()
        return gzip.decompress(content) if blob.compression_type == "gzip" else content

    def delete(self, blob: ArtifactBlob) -> bool:
        try:
            path = self.path_for(blob)
        except ArtifactNotFoundError:
            return False
        path.unlink()
        return True

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Unsafe artifact storage key")
        return path
