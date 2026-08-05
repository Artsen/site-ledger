from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ResourceSnapshot, Scan
from app.storage.content_store import LocalContentStore

SUPPORTED_VARY_HEADERS = {"user-agent", "accept", "accept-language"}
REPRESENTATION_REQUEST_HEADERS = {"user-agent", "accept", "accept-language"}


@dataclass(frozen=True)
class RevalidationCandidate:
    snapshot: ResourceSnapshot
    request_headers: dict[str, str]
    fingerprint: str


def representation_headers(user_agent: str) -> dict[str, str]:
    return {
        "user-agent": user_agent,
        "accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }


def request_variant_fingerprint(headers: dict[str, str]) -> str:
    relevant = {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in REPRESENTATION_REQUEST_HEADERS
    }
    payload = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def conditional_headers(snapshot: ResourceSnapshot) -> dict[str, str]:
    headers: dict[str, str] = {}
    if snapshot.etag:
        headers["If-None-Match"] = snapshot.etag
    if snapshot.last_modified:
        headers["If-Modified-Since"] = snapshot.last_modified
    return headers


def find_revalidation_candidate(
    db: Session,
    *,
    scan: Scan,
    resource_id: int,
    request_headers: dict[str, str],
    store: LocalContentStore,
) -> RevalidationCandidate | None:
    fingerprint = request_variant_fingerprint(request_headers)
    query = (
        select(ResourceSnapshot)
        .join(Scan, ResourceSnapshot.scan_id == Scan.id)
        .where(
            ResourceSnapshot.resource_id == resource_id,
            ResourceSnapshot.fetch_state == "fetched",
            ResourceSnapshot.http_status == 200,
            ResourceSnapshot.html_blob_id.is_not(None),
            ResourceSnapshot.raw_html_sha256.is_not(None),
        )
        .order_by(
            (Scan.website_property_id == scan.website_property_id).desc()
            if scan.website_property_id is not None
            else ResourceSnapshot.fetched_at.desc(),
            ResourceSnapshot.fetched_at.desc(),
            ResourceSnapshot.id.desc(),
        )
        .limit(20)
    )
    for snapshot in db.scalars(query):
        if _snapshot_reusable(snapshot, request_headers, fingerprint, store):
            headers = conditional_headers(snapshot)
            if headers:
                return RevalidationCandidate(
                    snapshot=snapshot,
                    request_headers=headers,
                    fingerprint=fingerprint,
                )
    return None


def _snapshot_reusable(
    snapshot: ResourceSnapshot,
    request_headers: dict[str, str],
    fingerprint: str,
    store: LocalContentStore,
) -> bool:
    if snapshot.blob is None or not store.exists(snapshot.blob):
        return False
    if not snapshot.etag and not snapshot.last_modified:
        return False
    if snapshot.request_variant_fingerprint and snapshot.request_variant_fingerprint != fingerprint:
        return False
    if _has_no_store(snapshot.cache_control):
        return False
    if not _vary_allows_reuse(snapshot.vary_header, request_headers):
        return False
    content_type = (snapshot.content_type or "").lower()
    return "text/html" in content_type or not content_type


def _has_no_store(cache_control: str | None) -> bool:
    if not cache_control:
        return False
    return any(part.strip().lower() == "no-store" for part in cache_control.split(","))


def _vary_allows_reuse(vary_header: str | None, request_headers: dict[str, str]) -> bool:
    if not vary_header:
        return True
    names: list[str] = []
    for value in vary_header.split(","):
        name = value.strip().lower()
        if not name:
            continue
        if name == "*":
            return False
        names.append(name)
    if any(name not in SUPPORTED_VARY_HEADERS for name in names):
        return False
    normalized = {key.lower(): value for key, value in request_headers.items()}
    return all(name in normalized for name in names)


def response_header_value(headers: dict[str, Any], name: str) -> str | None:
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower and value is not None:
            return str(value)
    return None
