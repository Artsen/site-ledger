from __future__ import annotations

import gzip
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

PAYLOAD_PATH_PATTERN = re.compile(
    r"^(?P<first>[0-9a-f]{2})/(?P<second>[0-9a-f]{2})/"
    r"(?P<sha>[0-9a-f]{64})\.json\.gz$"
)


@dataclass(frozen=True)
class StoredPayload:
    sha256: str
    storage_key: str
    raw_byte_size: int
    stored_byte_size: int


@dataclass(frozen=True)
class PayloadFileInventory:
    payloads: dict[str, Path]
    unexpected: list[str]


def store_payload(root: Path, content: bytes, *, temporary_prefix: str) -> StoredPayload:
    sha = hashlib.sha256(content).hexdigest()
    stored = gzip.compress(content, mtime=0)
    key = payload_storage_key(sha)
    path = safe_payload_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=temporary_prefix)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(stored)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return StoredPayload(sha, key, len(content), len(stored))


def read_payload(root: Path, storage_key: str) -> bytes:
    return gzip.decompress(safe_payload_path(root, storage_key).read_bytes())


def delete_payload(root: Path, storage_key: str) -> bool:
    path = safe_payload_path(root, storage_key)
    if not path.is_file():
        return False
    path.unlink()
    return True


def inventory_payload_files(root: Path) -> PayloadFileInventory:
    payloads: dict[str, Path] = {}
    unexpected: list[str] = []
    if not root.exists():
        return PayloadFileInventory(payloads, unexpected)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        match = PAYLOAD_PATH_PATTERN.fullmatch(relative)
        if (
            match is None
            or match["first"] != match["sha"][:2]
            or match["second"] != match["sha"][2:4]
        ):
            unexpected.append(relative)
            continue
        payloads[match["sha"]] = path
    return PayloadFileInventory(payloads, sorted(unexpected))


def payload_storage_key(sha256: str) -> str:
    return f"{sha256[:2]}/{sha256[2:4]}/{sha256}.json.gz"


def safe_payload_path(root: Path, storage_key: str) -> Path:
    match = PAYLOAD_PATH_PATTERN.fullmatch(storage_key.replace("\\", "/"))
    if match is None or match["first"] != match["sha"][:2] or match["second"] != match["sha"][2:4]:
        raise ValueError("Unsafe or invalid observability payload storage key")
    resolved_root = root.resolve()
    path = (resolved_root / storage_key).resolve()
    if resolved_root not in path.parents:
        raise ValueError("Unsafe observability payload storage key")
    return path
