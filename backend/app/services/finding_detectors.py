from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.crawler.url_normalizer import (
    NormalizedUrl,
    UrlNormalizationError,
    normalize_url_for_version,
)
from app.models import ResourceSnapshot, Scan

FindingOutcome = Literal["detected", "clear", "unknown"]
FindingSeverity = Literal["medium", "high"]

PAGE_HTTP_ERROR_TYPE = "page_http_error"
PAGE_HTTP_ERROR_KEY_VERSION = "page-http-error-key-v1"
PAGE_HTTP_ERROR_DETECTOR_IDENTITY = "page-http-error-v1"
PAGE_STATIC_FETCH_FAILURE_TYPE = "page_static_fetch_failure"
PAGE_STATIC_FETCH_FAILURE_KEY_VERSION = "page-static-fetch-failure-key-v1"
PAGE_STATIC_FETCH_FAILURE_DETECTOR_IDENTITY = "page-static-fetch-failure-v1"
PAGE_NOINDEX_TYPE = "page_noindex"
PAGE_NOINDEX_KEY_VERSION = "page-noindex-key-v1"
PAGE_NOINDEX_DETECTOR_IDENTITY = "page-noindex-v1"
PAGE_INDEXABILITY_CONFLICT_TYPE = "page_indexability_conflict"
PAGE_INDEXABILITY_CONFLICT_KEY_VERSION = "page-indexability-conflict-key-v1"
PAGE_INDEXABILITY_CONFLICT_DETECTOR_IDENTITY = "page-indexability-conflict-v1"
PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE = "page_canonical_target_http_error"
PAGE_CANONICAL_TARGET_HTTP_ERROR_KEY_VERSION = "page-canonical-target-http-error-key-v1"
PAGE_CANONICAL_TARGET_HTTP_ERROR_DETECTOR_IDENTITY = "page-canonical-target-http-error-v1"
PAGE_MISSING_TITLE_TYPE = "page_missing_title"
PAGE_MISSING_TITLE_KEY_VERSION = "page-missing-title-key-v1"
PAGE_MISSING_TITLE_DETECTOR_IDENTITY = "page-missing-title-v1"
PAGE_INVALID_CANONICAL_TYPE = "page_invalid_canonical"
PAGE_INVALID_CANONICAL_KEY_VERSION = "page-invalid-canonical-key-v1"
PAGE_INVALID_CANONICAL_DETECTOR_IDENTITY = "page-invalid-canonical-v1"
PAGE_MULTIPLE_CANONICALS_TYPE = "page_multiple_canonicals"
PAGE_MULTIPLE_CANONICALS_KEY_VERSION = "page-multiple-canonicals-key-v1"
PAGE_MULTIPLE_CANONICALS_DETECTOR_IDENTITY = "page-multiple-canonicals-v1"
PAGE_NON_HTML_REPRESENTATION_TYPE = "page_non_html_representation"
PAGE_NON_HTML_REPRESENTATION_KEY_VERSION = "page-non-html-representation-key-v1"
PAGE_NON_HTML_REPRESENTATION_DETECTOR_IDENTITY = "page-non-html-representation-v1"

FINDING_TYPE_LABELS = {
    PAGE_HTTP_ERROR_TYPE: "Page HTTP error",
    PAGE_STATIC_FETCH_FAILURE_TYPE: "Static fetch failure",
    PAGE_NOINDEX_TYPE: "Page is noindex",
    PAGE_INDEXABILITY_CONFLICT_TYPE: "Conflicting indexability directives",
    PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE: "Canonical target HTTP error",
    PAGE_MISSING_TITLE_TYPE: "Page is missing a title",
    PAGE_INVALID_CANONICAL_TYPE: "Invalid canonical URL",
    PAGE_MULTIPLE_CANONICALS_TYPE: "Multiple canonical declarations",
    PAGE_NON_HTML_REPRESENTATION_TYPE: "Page returns a non-HTML representation",
}

STATIC_FETCH_FAILURE_ERROR_TYPES = frozenset(
    {
        "request_timeout",
        "connection_timeout",
        "read_timeout",
        "connection_error",
        "connection_reset",
        "dns_error",
        "certificate_validation_error",
        "tls_configuration_error",
        "transient_tls_disconnect",
        "too_many_redirects",
        "redirect_loop",
        "response_too_large",
        "unsafe_destination",
        "invalid_url",
    }
)


@dataclass(frozen=True)
class DetectorEvidence:
    role: str
    snapshot: ResourceSnapshot


@dataclass(frozen=True)
class DetectorResult:
    outcome: FindingOutcome
    severity: FindingSeverity | None
    details: dict[str, Any]
    evidence: tuple[DetectorEvidence, ...]
    reason_code: str | None = None


@dataclass(frozen=True)
class DetectorContext:
    scan: Scan
    snapshots_by_resource_id: Mapping[int, ResourceSnapshot]
    snapshots_by_normalized_url: Mapping[str, ResourceSnapshot]


@dataclass(frozen=True)
class FindingDetector:
    detector_identity: str
    finding_type: str
    logical_key_version: str
    label: str
    subject_kind: str
    evaluate: Callable[[ResourceSnapshot | None, DetectorContext], DetectorResult]


@dataclass(frozen=True)
class RobotsDirectiveEvidence:
    meta_robots_raw: str | None
    x_robots_tag_raw: tuple[str, ...]
    meta_directives: tuple[str, ...]
    x_robots_tag_directives: tuple[str, ...]
    ambiguous_agent_scopes: tuple[str, ...]

    @property
    def applicable_directives(self) -> frozenset[str]:
        return frozenset((*self.meta_directives, *self.x_robots_tag_directives))

    @property
    def ambiguous(self) -> bool:
        return bool(self.ambiguous_agent_scopes)

    def details(self) -> dict[str, Any]:
        return {
            "meta_robots_raw": self.meta_robots_raw,
            "x_robots_tag_raw": list(self.x_robots_tag_raw),
            "parsed_directives": {
                "meta_robots": list(self.meta_directives),
                "x_robots_tag": list(self.x_robots_tag_directives),
            },
            "ambiguous_agent_scopes": list(self.ambiguous_agent_scopes),
        }


_DIRECTIVE_TOKEN = re.compile(r"^[a-z][a-z0-9_-]*(?::[^,\s]+)?$")
_KNOWN_COLON_DIRECTIVES = {
    "max-image-preview",
    "max-snippet",
    "max-video-preview",
    "unavailable_after",
}


def parse_robots_directives(snapshot: ResourceSnapshot) -> RobotsDirectiveEvidence:
    meta_raw = snapshot.meta_robots
    meta_directives = _parse_generic_directives(meta_raw)
    header_values = _header_values(snapshot.response_headers or {}, "x-robots-tag")
    header_directives: list[str] = []
    ambiguous_scopes: list[str] = []
    for value in header_values:
        current_agent: str | None = None
        for raw_segment in value.split(","):
            segment = raw_segment.strip().lower()
            if not segment:
                continue
            prefix, separator, remainder = segment.partition(":")
            if separator and prefix not in _KNOWN_COLON_DIRECTIVES:
                current_agent = prefix.strip()
                segment = remainder.strip()
            tokens = _tokens(segment)
            scoped_indexability = {token for token in tokens if token in {"index", "noindex"}}
            if current_agent is not None:
                if scoped_indexability:
                    ambiguous_scopes.append(
                        f"{current_agent}: {' '.join(sorted(scoped_indexability))}"
                    )
                continue
            header_directives.extend(tokens)
    return RobotsDirectiveEvidence(
        meta_robots_raw=meta_raw,
        x_robots_tag_raw=tuple(header_values),
        meta_directives=tuple(sorted(set(meta_directives))),
        x_robots_tag_directives=tuple(sorted(set(header_directives))),
        ambiguous_agent_scopes=tuple(ambiguous_scopes),
    )


def _http_error(snapshot: ResourceSnapshot | None, _context: DetectorContext) -> DetectorResult:
    details = {
        "fetch_state": snapshot.fetch_state if snapshot else None,
        "http_status": snapshot.http_status if snapshot else None,
    }
    evidence = _primary(snapshot)
    if not _usable_static(snapshot):
        return DetectorResult("unknown", None, details, evidence, _unusable_reason(snapshot))
    assert snapshot is not None and snapshot.http_status is not None
    if 500 <= snapshot.http_status <= 599:
        return DetectorResult("detected", "high", details, evidence)
    if 400 <= snapshot.http_status <= 499:
        return DetectorResult("detected", "medium", details, evidence)
    return DetectorResult("clear", None, details, evidence)


def _static_fetch_failure(
    snapshot: ResourceSnapshot | None, _context: DetectorContext
) -> DetectorResult:
    details = {
        "fetch_state": snapshot.fetch_state if snapshot else None,
        "error_type": snapshot.error_type if snapshot else None,
        "error_message": snapshot.error_message if snapshot else None,
        "retrieval_http_status": snapshot.retrieval_http_status if snapshot else None,
        "redirect_chain_summary": _redirect_chain_summary(snapshot),
    }
    evidence = _primary(snapshot)
    if snapshot is None:
        return DetectorResult("unknown", None, details, evidence, "missing_subject_evidence")
    if snapshot.fetch_state == "failed" and snapshot.error_type in STATIC_FETCH_FAILURE_ERROR_TYPES:
        return DetectorResult("detected", "high", details, evidence)
    if _usable_static(snapshot):
        return DetectorResult("clear", None, details, evidence)
    reason = (
        "failed_without_classified_error"
        if snapshot.fetch_state == "failed"
        else "fetch_state_unusable"
    )
    return DetectorResult("unknown", None, details, evidence, reason)


def _noindex(snapshot: ResourceSnapshot | None, _context: DetectorContext) -> DetectorResult:
    if not _usable_html(snapshot):
        return DetectorResult(
            "unknown",
            None,
            {"fetch_state": snapshot.fetch_state if snapshot else None},
            _primary(snapshot),
            _html_unusable_reason(snapshot),
        )
    assert snapshot is not None
    directives = parse_robots_directives(snapshot)
    applicable = directives.applicable_directives
    details = directives.details()
    matched_sources = []
    if "noindex" in directives.meta_directives:
        matched_sources.append("meta_robots")
    if "noindex" in directives.x_robots_tag_directives:
        matched_sources.append("x_robots_tag")
    details["matched_sources"] = matched_sources
    if "noindex" in applicable:
        return DetectorResult("detected", "medium", details, _primary(snapshot))
    if directives.ambiguous:
        return DetectorResult("unknown", None, details, _primary(snapshot), "ambiguous_agent_scope")
    return DetectorResult("clear", None, details, _primary(snapshot))


def _indexability_conflict(
    snapshot: ResourceSnapshot | None, _context: DetectorContext
) -> DetectorResult:
    if not _usable_html(snapshot):
        return DetectorResult(
            "unknown",
            None,
            {"fetch_state": snapshot.fetch_state if snapshot else None},
            _primary(snapshot),
            _html_unusable_reason(snapshot),
        )
    assert snapshot is not None
    directives = parse_robots_directives(snapshot)
    applicable = directives.applicable_directives
    details = directives.details()
    details["matched_sources"] = {
        directive: [
            source
            for source, values in (
                ("meta_robots", directives.meta_directives),
                ("x_robots_tag", directives.x_robots_tag_directives),
            )
            if directive in values
        ]
        for directive in ("index", "noindex")
    }
    if {"index", "noindex"}.issubset(applicable):
        return DetectorResult("detected", "medium", details, _primary(snapshot))
    if directives.ambiguous:
        return DetectorResult("unknown", None, details, _primary(snapshot), "ambiguous_agent_scope")
    return DetectorResult("clear", None, details, _primary(snapshot))


def _canonical_target_http_error(
    snapshot: ResourceSnapshot | None, context: DetectorContext
) -> DetectorResult:
    details: dict[str, Any] = {
        "canonical_url": snapshot.canonical_url if snapshot else None,
        "source_scan_id": context.scan.id,
        "normalization_version": context.scan.url_normalization_version,
    }
    if not _usable_html(snapshot):
        details["fetch_state"] = snapshot.fetch_state if snapshot else None
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), _html_unusable_reason(snapshot)
        )
    assert snapshot is not None
    if not snapshot.canonical_url:
        return DetectorResult("clear", None, details, _primary(snapshot))
    try:
        normalized = _normalize_canonical(snapshot, context)
    except (UrlNormalizationError, ValueError) as exc:
        details["resolution_error"] = str(exc)
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), "canonical_unresolvable"
        )
    details["normalized_canonical_url"] = normalized.normalized_url
    target = context.snapshots_by_normalized_url.get(normalized.normalized_url)
    if target is None:
        details["resolution_error"] = "same_scan_target_not_observed"
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), "same_scan_target_not_observed"
        )
    details.update(
        {
            "resolved_canonical_resource_id": target.resource_id,
            "target_http_status": target.http_status,
            "target_snapshot_id": target.id,
            "target_fetch_state": target.fetch_state,
        }
    )
    evidence = (
        DetectorEvidence("primary", snapshot),
        DetectorEvidence("canonical_target", target),
    )
    if not _usable_static(target):
        return DetectorResult("unknown", None, details, evidence, "target_unusable")
    assert target.http_status is not None
    if 400 <= target.http_status <= 599:
        return DetectorResult("detected", "high", details, evidence)
    return DetectorResult("clear", None, details, evidence)


def _missing_title(snapshot: ResourceSnapshot | None, _context: DetectorContext) -> DetectorResult:
    details = {
        "page_title": snapshot.page_title if snapshot else None,
        "representation_kind": snapshot.representation_kind if snapshot else None,
    }
    if not _usable_html(snapshot):
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), _html_unusable_reason(snapshot)
        )
    assert snapshot is not None
    if snapshot.page_title is None or not snapshot.page_title.strip():
        return DetectorResult("detected", "medium", details, _primary(snapshot))
    return DetectorResult("clear", None, details, _primary(snapshot))


def _invalid_canonical(
    snapshot: ResourceSnapshot | None, context: DetectorContext
) -> DetectorResult:
    details: dict[str, Any] = {
        "canonical_url": snapshot.canonical_url if snapshot else None,
        "normalization_version": context.scan.url_normalization_version,
    }
    if not _usable_html(snapshot):
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), _html_unusable_reason(snapshot)
        )
    assert snapshot is not None
    if not snapshot.canonical_url:
        return DetectorResult("clear", None, details, _primary(snapshot))
    try:
        normalized = _normalize_canonical(snapshot, context)
    except (UrlNormalizationError, ValueError) as exc:
        details["resolution_error"] = str(exc)
        return DetectorResult("detected", "medium", details, _primary(snapshot))
    details["normalized_canonical_url"] = normalized.normalized_url
    return DetectorResult("clear", None, details, _primary(snapshot))


def _multiple_canonicals(
    snapshot: ResourceSnapshot | None, _context: DetectorContext
) -> DetectorResult:
    details: dict[str, Any] = {"canonical_count": None, "declared_href_values": []}
    if not _usable_html(snapshot):
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), _html_unusable_reason(snapshot)
        )
    assert snapshot is not None
    if not isinstance(snapshot.parsed_head_json, dict):
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), "parsed_head_unavailable"
        )
    links = snapshot.parsed_head_json.get("links")
    if not isinstance(links, list):
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), "parsed_head_links_unavailable"
        )
    hrefs = [
        item.get("href")
        for item in links
        if isinstance(item, dict) and "canonical" in _rel_tokens(item.get("rel"))
    ]
    details.update({"canonical_count": len(hrefs), "declared_href_values": hrefs})
    if len(hrefs) > 1:
        return DetectorResult("detected", "medium", details, _primary(snapshot))
    return DetectorResult("clear", None, details, _primary(snapshot))


def _non_html_representation(
    snapshot: ResourceSnapshot | None, _context: DetectorContext
) -> DetectorResult:
    details = {
        "representation_kind": snapshot.representation_kind if snapshot else None,
        "content_type": snapshot.content_type if snapshot else None,
        "normalized_mime_type": snapshot.normalized_mime_type if snapshot else None,
        "final_url": snapshot.final_url if snapshot else None,
    }
    if not _usable_static(snapshot):
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), _unusable_reason(snapshot)
        )
    assert snapshot is not None
    if snapshot.representation_kind in {None, "unknown"}:
        return DetectorResult(
            "unknown", None, details, _primary(snapshot), "representation_unclassified"
        )
    if snapshot.representation_kind != "html_page":
        return DetectorResult("detected", "medium", details, _primary(snapshot))
    return DetectorResult("clear", None, details, _primary(snapshot))


def build_snapshot_url_index(
    scan: Scan, snapshots: Mapping[int, ResourceSnapshot]
) -> dict[str, ResourceSnapshot]:
    result: dict[str, ResourceSnapshot] = {}
    drop_query_params = scan.scope_config.get("drop_query_parameters", [])
    for snapshot in snapshots.values():
        for raw_url in (snapshot.requested_url, snapshot.final_url):
            if not raw_url:
                continue
            try:
                normalized = normalize_url_for_version(
                    raw_url,
                    normalization_version=scan.url_normalization_version,
                    drop_query_params=drop_query_params,
                )
            except UrlNormalizationError:
                continue
            result.setdefault(normalized.normalized_url, snapshot)
    return result


CURRENT_FINDING_DETECTORS = (
    FindingDetector(
        PAGE_HTTP_ERROR_DETECTOR_IDENTITY,
        PAGE_HTTP_ERROR_TYPE,
        PAGE_HTTP_ERROR_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_HTTP_ERROR_TYPE],
        "web_resource",
        _http_error,
    ),
    FindingDetector(
        PAGE_STATIC_FETCH_FAILURE_DETECTOR_IDENTITY,
        PAGE_STATIC_FETCH_FAILURE_TYPE,
        PAGE_STATIC_FETCH_FAILURE_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_STATIC_FETCH_FAILURE_TYPE],
        "web_resource",
        _static_fetch_failure,
    ),
    FindingDetector(
        PAGE_NOINDEX_DETECTOR_IDENTITY,
        PAGE_NOINDEX_TYPE,
        PAGE_NOINDEX_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_NOINDEX_TYPE],
        "web_resource",
        _noindex,
    ),
    FindingDetector(
        PAGE_INDEXABILITY_CONFLICT_DETECTOR_IDENTITY,
        PAGE_INDEXABILITY_CONFLICT_TYPE,
        PAGE_INDEXABILITY_CONFLICT_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_INDEXABILITY_CONFLICT_TYPE],
        "web_resource",
        _indexability_conflict,
    ),
    FindingDetector(
        PAGE_MISSING_TITLE_DETECTOR_IDENTITY,
        PAGE_MISSING_TITLE_TYPE,
        PAGE_MISSING_TITLE_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_MISSING_TITLE_TYPE],
        "web_resource",
        _missing_title,
    ),
    FindingDetector(
        PAGE_INVALID_CANONICAL_DETECTOR_IDENTITY,
        PAGE_INVALID_CANONICAL_TYPE,
        PAGE_INVALID_CANONICAL_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_INVALID_CANONICAL_TYPE],
        "web_resource",
        _invalid_canonical,
    ),
    FindingDetector(
        PAGE_MULTIPLE_CANONICALS_DETECTOR_IDENTITY,
        PAGE_MULTIPLE_CANONICALS_TYPE,
        PAGE_MULTIPLE_CANONICALS_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_MULTIPLE_CANONICALS_TYPE],
        "web_resource",
        _multiple_canonicals,
    ),
    FindingDetector(
        PAGE_CANONICAL_TARGET_HTTP_ERROR_DETECTOR_IDENTITY,
        PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE,
        PAGE_CANONICAL_TARGET_HTTP_ERROR_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE],
        "web_resource",
        _canonical_target_http_error,
    ),
    FindingDetector(
        PAGE_NON_HTML_REPRESENTATION_DETECTOR_IDENTITY,
        PAGE_NON_HTML_REPRESENTATION_TYPE,
        PAGE_NON_HTML_REPRESENTATION_KEY_VERSION,
        FINDING_TYPE_LABELS[PAGE_NON_HTML_REPRESENTATION_TYPE],
        "web_resource",
        _non_html_representation,
    ),
)


def finding_detector_manifest(
    detectors: Sequence[FindingDetector],
) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "finding_type": detector.finding_type,
            "detector_identity": detector.detector_identity,
            "logical_key_version": detector.logical_key_version,
            "subject_kind": detector.subject_kind,
        }
        for detector in detectors
    )


def finding_detector_manifest_sha256(detectors: Sequence[FindingDetector]) -> str:
    payload = json.dumps(
        finding_detector_manifest(detectors),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


CURRENT_FINDING_DETECTOR_MANIFEST = finding_detector_manifest(CURRENT_FINDING_DETECTORS)
CURRENT_FINDING_DETECTOR_MANIFEST_SHA256 = finding_detector_manifest_sha256(
    CURRENT_FINDING_DETECTORS
)


def _usable_static(snapshot: ResourceSnapshot | None) -> bool:
    return bool(snapshot and snapshot.fetch_state == "fetched" and snapshot.http_status is not None)


def _usable_html(snapshot: ResourceSnapshot | None) -> bool:
    return bool(
        _usable_static(snapshot) and snapshot and snapshot.representation_kind == "html_page"
    )


def _unusable_reason(snapshot: ResourceSnapshot | None) -> str:
    if snapshot is None:
        return "missing_subject_evidence"
    if snapshot.fetch_state != "fetched":
        return "subject_fetch_unusable"
    return "subject_http_status_unavailable"


def _html_unusable_reason(snapshot: ResourceSnapshot | None) -> str:
    if not _usable_static(snapshot):
        return _unusable_reason(snapshot)
    return "subject_non_html"


def _normalize_canonical(snapshot: ResourceSnapshot, context: DetectorContext) -> NormalizedUrl:
    assert snapshot.canonical_url is not None
    return normalize_url_for_version(
        snapshot.canonical_url,
        normalization_version=context.scan.url_normalization_version,
        base_url=snapshot.final_url or snapshot.requested_url,
        drop_query_params=context.scan.scope_config.get("drop_query_parameters", []),
    )


def _redirect_chain_summary(snapshot: ResourceSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None or snapshot.redirect_chain is None:
        return None
    chain = snapshot.redirect_chain
    return {
        "count": len(chain),
        "final_url": snapshot.final_url,
        "statuses": [item.get("status") for item in chain if isinstance(item, dict)],
    }


def _rel_tokens(value: Any) -> frozenset[str]:
    return (
        frozenset(token.casefold() for token in value.split())
        if isinstance(value, str)
        else frozenset()
    )


def _primary(snapshot: ResourceSnapshot | None) -> tuple[DetectorEvidence, ...]:
    return (DetectorEvidence("primary", snapshot),) if snapshot is not None else ()


def _parse_generic_directives(value: str | None) -> list[str]:
    if not value:
        return []
    directives: list[str] = []
    for segment in value.lower().split(","):
        directives.extend(_tokens(segment))
    return directives


def _tokens(value: str) -> list[str]:
    return [token for token in value.strip().split() if _DIRECTIVE_TOKEN.fullmatch(token)]


def _header_values(headers: Mapping[str, Any], name: str) -> list[str]:
    values: list[str] = []
    for key, raw_value in headers.items():
        if key.lower() != name:
            continue
        if isinstance(raw_value, list):
            values.extend(str(item) for item in raw_value)
        elif raw_value is not None:
            values.append(str(raw_value))
    return values
