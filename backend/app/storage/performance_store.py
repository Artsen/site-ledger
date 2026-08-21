from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PerformancePayloadBlob
from app.storage.observability_payloads import delete_payload, read_payload, store_payload


class PerformancePayloadNotFoundError(FileNotFoundError):
    pass


class LocalPerformancePayloadStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self, db: Session, content: bytes, content_type: str = "application/json"
    ) -> PerformancePayloadBlob:
        sha = hashlib.sha256(content).hexdigest()
        existing = db.scalar(
            select(PerformancePayloadBlob).where(PerformancePayloadBlob.sha256 == sha)
        )
        if existing is not None:
            return existing
        stored = store_payload(self.root, content, temporary_prefix=".performance-")
        blob = PerformancePayloadBlob(
            sha256=sha,
            storage_key=stored.storage_key,
            content_type=content_type,
            compression_type="gzip",
            raw_byte_size=stored.raw_byte_size,
            stored_byte_size=stored.stored_byte_size,
        )
        try:
            with db.begin_nested():
                db.add(blob)
                db.flush()
            return blob
        except IntegrityError:
            winner = db.scalar(
                select(PerformancePayloadBlob).where(PerformancePayloadBlob.sha256 == sha)
            )
            if winner is None or winner.storage_key != stored.storage_key:
                raise
            return winner

    def read(self, blob: PerformancePayloadBlob) -> bytes:
        path = self._path(blob.storage_key)
        if not path.is_file():
            raise PerformancePayloadNotFoundError(blob.storage_key)
        return read_payload(self.root, blob.storage_key)

    def delete(self, blob: PerformancePayloadBlob) -> bool:
        return delete_payload(self.root, blob.storage_key)

    def _path(self, key: str) -> Path:
        from app.storage.observability_payloads import safe_payload_path

        return safe_payload_path(self.root, key)
