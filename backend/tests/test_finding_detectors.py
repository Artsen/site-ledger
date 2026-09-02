from __future__ import annotations

import hashlib
import json

import pytest

from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
)
from app.models import ResourceSnapshot, Scan
from app.services.finding_detectors import (
    CURRENT_FINDING_DETECTORS,
    PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE,
    PAGE_HTTP_ERROR_TYPE,
    PAGE_INDEXABILITY_CONFLICT_TYPE,
    PAGE_NOINDEX_TYPE,
    DetectorContext,
    build_snapshot_url_index,
)
from app.services.finding_evaluations import finding_fingerprint


def _detector(finding_type: str):
    return next(item for item in CURRENT_FINDING_DETECTORS if item.finding_type == finding_type)


def _snapshot(
    *,
    snapshot_id: int = 1,
    resource_id: int = 1,
    requested_url: str = "https://example.test/page",
    status: int | None = 200,
    fetch_state: str = "fetched",
    meta_robots: str | None = None,
    response_headers: dict[str, object] | None = None,
    canonical_url: str | None = None,
    page_title: str | None = "Example page",
    parsed_head_json: dict[str, object] | None = None,
    representation_kind: str | None = "html_page",
    error_type: str | None = None,
    error_message: str | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        id=snapshot_id,
        scan_id=1,
        resource_id=resource_id,
        requested_url=requested_url,
        final_url=requested_url,
        http_status=status,
        crawl_depth=0,
        fetch_state=fetch_state,
        meta_robots=meta_robots,
        response_headers=response_headers,
        canonical_url=canonical_url,
        page_title=page_title,
        parsed_head_json={"links": []} if parsed_head_json is None else parsed_head_json,
        representation_kind=representation_kind,
        error_type=error_type,
        error_message=error_message,
    )


def _context(
    snapshots: list[ResourceSnapshot],
    *,
    version: str = URL_NORMALIZATION_V2_VERSION,
    drop_query_parameters: list[str] | None = None,
) -> DetectorContext:
    scan = Scan(
        id=1,
        starting_url="https://example.test/",
        status="completed",
        scope_config={"drop_query_parameters": drop_query_parameters or []},
        url_normalization_version=version,
    )
    by_resource = {item.resource_id: item for item in snapshots}
    return DetectorContext(scan, by_resource, build_snapshot_url_index(scan, by_resource))


@pytest.mark.parametrize(
    ("status", "fetch_state", "outcome", "severity"),
    [
        (200, "fetched", "clear", None),
        (301, "fetched", "clear", None),
        (404, "fetched", "detected", "medium"),
        (500, "fetched", "detected", "high"),
        (None, "fetched", "unknown", None),
        (None, "failed", "unknown", None),
    ],
)
def test_http_detector_preserves_v1_semantics(
    status: int | None, fetch_state: str, outcome: str, severity: str | None
) -> None:
    snapshot = _snapshot(status=status, fetch_state=fetch_state)
    result = _detector(PAGE_HTTP_ERROR_TYPE).evaluate(snapshot, _context([snapshot]))
    assert (result.outcome, result.severity) == (outcome, severity)


@pytest.mark.parametrize(
    ("meta", "headers", "outcome", "matched"),
    [
        ("noindex", None, "detected", ["meta_robots"]),
        ("NOINDEX, FOLLOW", None, "detected", ["meta_robots"]),
        ("notnoindex, follow", None, "clear", []),
        (None, {"X-Robots-Tag": "noindex, follow"}, "detected", ["x_robots_tag"]),
        (
            "noindex",
            {"x-robots-tag": "NOINDEX"},
            "detected",
            ["meta_robots", "x_robots_tag"],
        ),
        ("index", None, "clear", []),
        (None, None, "clear", []),
        (None, {"X-Robots-Tag": "otherbot: noindex"}, "unknown", []),
        (None, {"X-Robots-Tag": "otherbot: follow, noindex"}, "unknown", []),
    ],
)
def test_noindex_detector_parses_exact_applicable_directives(
    meta: str | None,
    headers: dict[str, object] | None,
    outcome: str,
    matched: list[str],
) -> None:
    snapshot = _snapshot(meta_robots=meta, response_headers=headers)
    result = _detector(PAGE_NOINDEX_TYPE).evaluate(snapshot, _context([snapshot]))
    assert result.outcome == outcome
    assert result.details.get("matched_sources", []) == matched
    assert result.details.get("meta_robots_raw") == meta


@pytest.mark.parametrize("snapshot", [None, _snapshot(status=None, fetch_state="failed")])
def test_noindex_detector_keeps_missing_or_failed_evidence_unknown(
    snapshot: ResourceSnapshot | None,
) -> None:
    result = _detector(PAGE_NOINDEX_TYPE).evaluate(snapshot, _context([]))
    assert (result.outcome, result.severity) == ("unknown", None)


@pytest.mark.parametrize(
    ("meta", "header", "outcome"),
    [
        ("index", "noindex", "detected"),
        ("noindex", "index", "detected"),
        ("noindex, noindex", "noindex", "clear"),
        (None, "noindex", "clear"),
        ("index", None, "clear"),
        (None, "otherbot: noindex", "unknown"),
    ],
)
def test_indexability_conflict_requires_explicit_applicable_opposites(
    meta: str | None, header: str | None, outcome: str
) -> None:
    snapshot = _snapshot(
        meta_robots=meta,
        response_headers={"x-robots-tag": header} if header is not None else None,
    )
    result = _detector(PAGE_INDEXABILITY_CONFLICT_TYPE).evaluate(snapshot, _context([snapshot]))
    assert result.outcome == outcome


def test_canonical_detector_uses_ordered_same_scan_evidence() -> None:
    subject = _snapshot(canonical_url="/target")
    target = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/target",
        status=404,
    )
    result = _detector(PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE).evaluate(
        subject, _context([subject, target])
    )
    assert (result.outcome, result.severity) == ("detected", "high")
    assert [item.role for item in result.evidence] == ["primary", "canonical_target"]
    assert result.details["resolved_canonical_resource_id"] == 2
    assert result.details["target_snapshot_id"] == 2
    assert result.details["target_http_status"] == 404


@pytest.mark.parametrize(
    ("canonical", "target_status", "target_state", "include_target", "outcome"),
    [
        (None, 200, "fetched", False, "clear"),
        ("https://example.test/page", 200, "fetched", False, "clear"),
        ("/target", 200, "fetched", True, "clear"),
        ("/target", 500, "fetched", True, "detected"),
        ("/target", 200, "fetched", False, "unknown"),
        ("/target", None, "failed", True, "unknown"),
    ],
)
def test_canonical_detector_outcomes(
    canonical: str | None,
    target_status: int | None,
    target_state: str,
    include_target: bool,
    outcome: str,
) -> None:
    subject = _snapshot(canonical_url=canonical)
    snapshots = [subject]
    if include_target:
        snapshots.append(
            _snapshot(
                snapshot_id=2,
                resource_id=2,
                requested_url="https://example.test/target",
                status=target_status,
                fetch_state=target_state,
            )
        )
    result = _detector(PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE).evaluate(subject, _context(snapshots))
    assert result.outcome == outcome


def test_canonical_resolution_uses_the_source_scan_normalization_contract() -> None:
    subject = _snapshot(canonical_url="/target?utm_source=campaign")
    target = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/target",
        status=404,
    )
    detector = _detector(PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE)
    v1 = detector.evaluate(
        subject,
        _context(
            [subject, target],
            version=URL_NORMALIZATION_V1_VERSION,
            drop_query_parameters=["utm_*"],
        ),
    )
    v2 = detector.evaluate(
        subject,
        _context(
            [subject, target],
            version=URL_NORMALIZATION_V2_VERSION,
            drop_query_parameters=["utm_*"],
        ),
    )
    assert v1.outcome == "detected"
    assert v2.outcome == "unknown"


def test_canonical_target_observed_only_outside_source_scan_is_unknown() -> None:
    subject = _snapshot(canonical_url="/target")
    other_scan_target = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/target",
        status=404,
    )
    result = _detector(PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE).evaluate(subject, _context([subject]))
    assert other_scan_target.http_status == 404
    assert result.outcome == "unknown"
    assert result.details["resolution_error"] == "same_scan_target_not_observed"


def test_general_fingerprint_preserves_exact_v1_http_identity() -> None:
    legacy_payload = {
        "finding_type": "page_http_error",
        "logical_key_version": "page-http-error-key-v1",
        "site_id": 17,
        "subject_kind": "web_resource",
        "web_resource_id": 29,
    }
    encoded = json.dumps(
        legacy_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    assert finding_fingerprint(17, 29) == hashlib.sha256(encoded).hexdigest()
    assert finding_fingerprint(
        17,
        29,
        finding_type="page_noindex",
        logical_key_version="page-noindex-key-v1",
    ) != finding_fingerprint(17, 29)
    assert finding_fingerprint(17, 30) != finding_fingerprint(17, 29)
    assert finding_fingerprint(18, 29) != finding_fingerprint(17, 29)


@pytest.mark.parametrize(
    ("error_type", "outcome"),
    [
        ("connection_timeout", "detected"),
        ("dns_error", "detected"),
        ("response_too_large", "detected"),
        ("redirect_loop", "detected"),
        ("unclassified_failure", "unknown"),
        (None, "unknown"),
    ],
)
def test_static_fetch_failure_uses_retained_crawler_outcomes(
    error_type: str | None, outcome: str
) -> None:
    snapshot = _snapshot(status=None, fetch_state="failed", error_type=error_type)
    result = _detector("page_static_fetch_failure").evaluate(snapshot, _context([snapshot]))
    assert result.outcome == outcome
    assert result.details["error_type"] == error_type
    assert result.severity == ("high" if outcome == "detected" else None)


@pytest.mark.parametrize(
    ("title", "representation", "outcome"),
    [
        (None, "html_page", "detected"),
        ("  ", "html_page", "detected"),
        ("Title", "html_page", "clear"),
        (None, "document", "unknown"),
    ],
)
def test_missing_title_requires_usable_html(
    title: str | None, representation: str, outcome: str
) -> None:
    snapshot = _snapshot(page_title=title, representation_kind=representation)
    result = _detector("page_missing_title").evaluate(snapshot, _context([snapshot]))
    assert result.outcome == outcome
    assert result.details["page_title"] == title


@pytest.mark.parametrize(
    ("canonical", "outcome"),
    [(None, "clear"), ("/valid", "clear"), ("http://[invalid", "detected")],
)
def test_invalid_canonical_is_distinct_from_target_observation(
    canonical: str | None, outcome: str
) -> None:
    snapshot = _snapshot(canonical_url=canonical)
    context = _context([snapshot])
    result = _detector("page_invalid_canonical").evaluate(snapshot, context)
    assert result.outcome == outcome
    if outcome == "detected":
        target_result = _detector(PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE).evaluate(snapshot, context)
        assert target_result.outcome == "unknown"


def test_multiple_canonicals_uses_exact_rel_tokens_and_retains_hrefs() -> None:
    snapshot = _snapshot(
        parsed_head_json={
            "links": [
                {"rel": "Canonical alternate", "href": "/one"},
                {"rel": "canonical", "href": "/two"},
                {"rel": "notcanonical", "href": "/ignored"},
            ]
        }
    )
    result = _detector("page_multiple_canonicals").evaluate(snapshot, _context([snapshot]))
    assert (result.outcome, result.severity) == ("detected", "medium")
    assert result.details == {
        "canonical_count": 2,
        "declared_href_values": ["/one", "/two"],
    }


def test_non_html_representation_uses_current_successful_snapshot() -> None:
    snapshot = _snapshot(
        representation_kind="document",
        response_headers={"content-type": "application/pdf"},
    )
    snapshot.content_type = "application/pdf"
    snapshot.normalized_mime_type = "application/pdf"
    result = _detector("page_non_html_representation").evaluate(snapshot, _context([snapshot]))
    assert (result.outcome, result.severity) == ("detected", "medium")
    assert result.details["normalized_mime_type"] == "application/pdf"
