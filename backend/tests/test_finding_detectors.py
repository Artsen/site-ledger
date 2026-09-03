from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
)
from app.models import ResourceOccurrence, ResourceSnapshot, Scan, SourceEntryObservation
from app.services.finding_detectors import (
    CURRENT_FINDING_DETECTOR_MANIFEST,
    CURRENT_FINDING_DETECTOR_MANIFEST_SHA256,
    CURRENT_FINDING_DETECTORS,
    PAGE_BROKEN_INTERNAL_LINKS_TYPE,
    PAGE_CANONICAL_TARGET_HTTP_ERROR_TYPE,
    PAGE_HTTP_ERROR_TYPE,
    PAGE_INDEXABILITY_CONFLICT_TYPE,
    PAGE_INTERNAL_LINKS_TO_REDIRECTS_TYPE,
    PAGE_NOINDEX_TYPE,
    SITEMAP_PAGE_HTTP_ERROR_TYPE,
    SITEMAP_PAGE_NOINDEX_TYPE,
    SITEMAP_PAGE_REDIRECT_TYPE,
    DetectorContext,
    SitemapMembershipEvidence,
    build_snapshot_url_index,
    finding_detector_manifest_sha256,
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
    final_url: str | None = None,
    redirect_chain: list[dict[str, object]] | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        id=snapshot_id,
        scan_id=1,
        resource_id=resource_id,
        requested_url=requested_url,
        final_url=final_url or requested_url,
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
        redirect_chain=redirect_chain,
    )


def _occurrence(
    occurrence_id: int,
    source: ResourceSnapshot,
    target: ResourceSnapshot,
    *,
    decision: str = "already_seen",
    role: str = "main_content",
) -> ResourceOccurrence:
    return ResourceOccurrence(
        id=occurrence_id,
        source_snapshot_id=source.id,
        relation_type="page_link",
        normalized_target_url=target.requested_url,
        target_resource_id=target.resource_id,
        scope_decision=decision,
        in_scope=decision == "crawlable",
        link_role=role,
    )


def _context(
    snapshots: list[ResourceSnapshot],
    *,
    version: str = URL_NORMALIZATION_V2_VERSION,
    drop_query_parameters: list[str] | None = None,
    occurrences: list[ResourceOccurrence] | None = None,
    memberships: list[SitemapMembershipEvidence] | None = None,
    active_sitemap_source_ids: tuple[int, ...] = (),
    usable_sitemap_refresh_ids_by_source_id: dict[int, int] | None = None,
    sitemap_membership_complete: bool | None = None,
    subject_resource_id: int | None = None,
) -> DetectorContext:
    scan = Scan(
        id=1,
        starting_url="https://example.test/",
        status="completed",
        scope_config={"drop_query_parameters": drop_query_parameters or []},
        url_normalization_version=version,
    )
    by_resource = {item.resource_id: item for item in snapshots}
    by_source: dict[int, list[ResourceOccurrence]] = {}
    resources_by_snapshot = {item.id: item.resource_id for item in snapshots}
    for occurrence in occurrences or []:
        source_resource_id = resources_by_snapshot[occurrence.source_snapshot_id]
        by_source.setdefault(source_resource_id, []).append(occurrence)
    membership_by_resource: dict[int, list[SitemapMembershipEvidence]] = {}
    for membership in memberships or []:
        assert membership.observation.resource_id is not None
        membership_by_resource.setdefault(membership.observation.resource_id, []).append(membership)
    usable = usable_sitemap_refresh_ids_by_source_id or {}
    return DetectorContext(
        scan=scan,
        snapshots_by_resource_id=by_resource,
        snapshots_by_normalized_url=build_snapshot_url_index(scan, by_resource),
        occurrences_by_source_resource_id={
            resource_id: tuple(items) for resource_id, items in by_source.items()
        },
        active_sitemap_source_ids=active_sitemap_source_ids,
        usable_sitemap_refresh_ids=tuple(usable.values()),
        sitemap_membership_complete=(
            len(usable) == len(active_sitemap_source_ids)
            if sitemap_membership_complete is None
            else sitemap_membership_complete
        ),
        sitemap_membership_by_resource_id={
            resource_id: tuple(items) for resource_id, items in membership_by_resource.items()
        },
        subject_resource_id=subject_resource_id,
    )


def _membership(
    observation_id: int,
    *,
    resource_id: int = 1,
    source_id: int = 10,
    refresh_id: int = 20,
    position: int = 0,
    raw_url: str = "https://example.test/page",
) -> SitemapMembershipEvidence:
    observation = SourceEntryObservation(
        id=observation_id,
        source_refresh_id=refresh_id,
        position=position,
        resource_id=resource_id,
        raw_url=raw_url,
        normalized_url=raw_url,
        normalization_version=URL_NORMALIZATION_V2_VERSION,
        source_metadata_json={"document_type": "urlset"},
        validation_state="valid",
        scope_decision="crawlable",
    )
    return SitemapMembershipEvidence(
        observation=observation,
        url_source_id=source_id,
        source_refresh_id=refresh_id,
        source_refresh_finished_at="2026-09-03T01:00:00+00:00",
    )


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


def test_broken_internal_links_preserve_duplicates_and_aggregate_target_severity() -> None:
    source = _snapshot()
    gone = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/gone",
        status=404,
    )
    server_error = _snapshot(
        snapshot_id=3,
        resource_id=3,
        requested_url="https://example.test/server-error",
        status=500,
    )
    ok = _snapshot(
        snapshot_id=4,
        resource_id=4,
        requested_url="https://example.test/ok",
    )
    occurrences = [
        _occurrence(2, source, gone),
        _occurrence(1, source, gone),
        _occurrence(3, source, server_error),
        _occurrence(4, source, ok),
    ]
    result = _detector(PAGE_BROKEN_INTERNAL_LINKS_TYPE).evaluate(
        source, _context([source, gone, server_error, ok], occurrences=occurrences)
    )
    assert (result.outcome, result.severity) == ("detected", "high")
    assert result.details["broken_target_count"] == 2
    assert result.details["broken_occurrence_count"] == 3
    assert result.details["broken_4xx_target_count"] == 1
    assert result.details["broken_5xx_target_count"] == 1
    assert [item.occurrence.id for item in result.evidence if item.occurrence] == [1, 2, 3]


def test_topology_uses_only_eligible_internal_page_link_occurrences() -> None:
    source = _snapshot()
    gone = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/gone",
        status=404,
    )
    occurrences = [
        _occurrence(1, source, gone, decision="external"),
        _occurrence(2, source, gone, role="download"),
    ]
    occurrences[0].in_scope = False
    occurrences[1].relation_type = "resource_reference"
    context = _context([source, gone], occurrences=occurrences)
    for finding_type in (
        PAGE_BROKEN_INTERNAL_LINKS_TYPE,
        PAGE_INTERNAL_LINKS_TO_REDIRECTS_TYPE,
    ):
        result = _detector(finding_type).evaluate(source, context)
        assert result.outcome == "clear"
        assert result.reason_code == "no_eligible_internal_occurrences"


def test_topology_never_substitutes_target_evidence_from_another_scan() -> None:
    source = _snapshot()
    historical_gone = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/gone",
        status=404,
    )
    occurrence = _occurrence(1, source, historical_gone)
    result = _detector(PAGE_BROKEN_INTERNAL_LINKS_TYPE).evaluate(
        source, _context([source], occurrences=[occurrence])
    )
    assert result.outcome == "unknown"
    assert result.reason_code == "target_not_observed"
    assert result.details["unknown_target_count"] == 1


def test_internal_redirect_requires_actual_redirect_to_distinct_normalized_url() -> None:
    source = _snapshot()
    redirected = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/old",
        final_url="https://example.test/new",
        redirect_chain=[{"status_code": 301, "url": "https://example.test/old"}],
    )
    result = _detector(PAGE_INTERNAL_LINKS_TO_REDIRECTS_TYPE).evaluate(
        source, _context([source, redirected], occurrences=[_occurrence(1, source, redirected)])
    )
    assert (result.outcome, result.severity) == ("detected", "medium")
    assert result.details["redirect_target_count"] == 1
    assert result.details["redirect_occurrence_count"] == 1
    assert result.details["target_samples"][0]["final_url"] == "https://example.test/new"

    spelling_only = _snapshot(
        snapshot_id=3,
        resource_id=3,
        requested_url="https://example.test/same",
        final_url="https://EXAMPLE.test:443/same",
        redirect_chain=[{"status_code": 301, "url": "https://example.test/same"}],
    )
    spelling_result = _detector(PAGE_INTERNAL_LINKS_TO_REDIRECTS_TYPE).evaluate(
        source,
        _context([source, spelling_only], occurrences=[_occurrence(2, source, spelling_only)]),
    )
    assert spelling_result.outcome == "clear"


def test_topology_evidence_sample_is_deterministically_bounded() -> None:
    source = _snapshot()
    gone = _snapshot(
        snapshot_id=2,
        resource_id=2,
        requested_url="https://example.test/gone",
        status=404,
    )
    occurrences = [_occurrence(index, source, gone) for index in range(25, 0, -1)]
    result = _detector(PAGE_BROKEN_INTERNAL_LINKS_TYPE).evaluate(
        source, _context([source, gone], occurrences=occurrences)
    )
    assert result.details["broken_occurrence_count"] == 25
    assert result.details["evidence_sample_count"] == 20
    assert result.details["evidence_truncated"] is True
    assert len(result.evidence) == 41
    assert [item.occurrence.id for item in result.evidence if item.occurrence] == list(range(1, 21))


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


def test_sitemap_http_error_uses_exact_duplicate_membership_evidence() -> None:
    snapshot = _snapshot(status=404)
    memberships = [
        _membership(100, position=0),
        _membership(101, position=1),
        _membership(102, source_id=11, refresh_id=21),
    ]
    context = _context(
        [snapshot],
        memberships=memberships,
        active_sitemap_source_ids=(10, 11),
        usable_sitemap_refresh_ids_by_source_id={10: 20, 11: 21},
    )
    result = _detector(SITEMAP_PAGE_HTTP_ERROR_TYPE).evaluate(snapshot, context)
    assert (result.outcome, result.severity) == ("detected", "medium")
    assert result.details["sitemap_source_count"] == 2
    assert result.details["membership_observation_count"] == 3
    assert result.details["membership_sample_count"] == 3
    assert result.details["membership_evidence_truncated"] is False
    assert [item.source_entry_observation.id for item in result.evidence[1:]] == [100, 101, 102]


def test_sitemap_noindex_reuses_static_directive_semantics() -> None:
    snapshot = _snapshot(meta_robots="noindex")
    context = _context(
        [snapshot],
        memberships=[_membership(100)],
        active_sitemap_source_ids=(10,),
        usable_sitemap_refresh_ids_by_source_id={10: 20},
    )
    result = _detector(SITEMAP_PAGE_NOINDEX_TYPE).evaluate(snapshot, context)
    assert (result.outcome, result.severity) == ("detected", "medium")
    assert result.details["matched_sources"] == ["meta_robots"]


def test_sitemap_redirect_requires_retained_chain_and_distinct_final_identity() -> None:
    membership = _membership(100)
    direct = _snapshot(final_url="https://example.test/new", redirect_chain=[])
    redirected = _snapshot(
        final_url="https://example.test/new",
        redirect_chain=[{"status": 301, "url": "https://example.test/page"}],
    )
    context = _context(
        [redirected],
        memberships=[membership],
        active_sitemap_source_ids=(10,),
        usable_sitemap_refresh_ids_by_source_id={10: 20},
    )
    assert _detector(SITEMAP_PAGE_REDIRECT_TYPE).evaluate(direct, context).outcome == "clear"
    result = _detector(SITEMAP_PAGE_REDIRECT_TYPE).evaluate(redirected, context)
    assert (result.outcome, result.severity) == ("detected", "medium")
    assert result.details["declared_sitemap_url"] == "https://example.test/page"
    assert result.details["normalized_final_url"] == "https://example.test/new"
    assert result.details["redirect_hop_count"] == 1


@pytest.mark.parametrize(
    ("active", "usable", "expected", "reason"),
    [
        ((), {}, "clear", "no_active_sitemap_sources"),
        ((10,), {}, "unknown", "sitemap_source_evidence_unavailable"),
        ((10,), {10: 20}, "clear", "sitemap_membership_not_present"),
        ((10, 11), {10: 20}, "unknown", "sitemap_source_evidence_unavailable"),
    ],
)
def test_sitemap_membership_three_state_absence_contract(
    active: tuple[int, ...], usable: dict[int, int], expected: str, reason: str
) -> None:
    snapshot = _snapshot(status=404)
    result = _detector(SITEMAP_PAGE_HTTP_ERROR_TYPE).evaluate(
        snapshot,
        _context(
            [snapshot],
            active_sitemap_source_ids=active,
            usable_sitemap_refresh_ids_by_source_id=usable,
        ),
    )
    assert result.outcome == expected
    assert result.reason_code == reason


def test_sitemap_membership_remains_known_when_static_snapshot_is_missing() -> None:
    membership = _membership(100, resource_id=1, source_id=10, refresh_id=20)
    context = _context(
        [],
        subject_resource_id=1,
        active_sitemap_source_ids=(10,),
        usable_sitemap_refresh_ids_by_source_id={10: 20},
        memberships=[membership],
    )

    result = _detector(SITEMAP_PAGE_HTTP_ERROR_TYPE).evaluate(None, context)

    assert result.outcome == "unknown"
    assert result.reason_code == "missing_subject_evidence"
    assert result.details["sitemap_source_count"] == 1
    assert [item.source_entry_observation.id for item in result.evidence] == [100]


def test_detector_manifest_is_deterministic_and_covers_registry_contract() -> None:
    assert len(CURRENT_FINDING_DETECTOR_MANIFEST) == len(CURRENT_FINDING_DETECTORS) == 14
    assert CURRENT_FINDING_DETECTOR_MANIFEST[0] == {
        "finding_type": "page_http_error",
        "detector_identity": "page-http-error-v1",
        "logical_key_version": "page-http-error-key-v1",
        "subject_kind": "web_resource",
    }
    payload = json.dumps(
        CURRENT_FINDING_DETECTOR_MANIFEST,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    assert (
        CURRENT_FINDING_DETECTOR_MANIFEST_SHA256
        == "c0c8f3db2532677fb6650a248cefe4eb610df632b8241da88b996e18d6332c96"
    )
    assert hashlib.sha256(payload).hexdigest() == CURRENT_FINDING_DETECTOR_MANIFEST_SHA256
    assert (
        finding_detector_manifest_sha256(CURRENT_FINDING_DETECTORS)
        == CURRENT_FINDING_DETECTOR_MANIFEST_SHA256
    )
    v4_manifest_sha256 = finding_detector_manifest_sha256(CURRENT_FINDING_DETECTORS[:-3])
    assert v4_manifest_sha256 == (
        "bc8459b5780ae48740a13e9b2b3a153143518a13e20edd9d31b545d325993948"
    )
    v3_manifest_sha256 = finding_detector_manifest_sha256(CURRENT_FINDING_DETECTORS[:-5])
    assert v3_manifest_sha256 == (
        "8d413eb1d494beb84be11c682d058c9a6ee474beabd4e77fa78be084414b99db"
    )
    assert v3_manifest_sha256 != CURRENT_FINDING_DETECTOR_MANIFEST_SHA256


def test_detector_manifest_changes_with_membership_order_or_semantic_identity() -> None:
    assert (
        finding_detector_manifest_sha256(CURRENT_FINDING_DETECTORS[:-1])
        != CURRENT_FINDING_DETECTOR_MANIFEST_SHA256
    )
    assert (
        finding_detector_manifest_sha256(tuple(reversed(CURRENT_FINDING_DETECTORS)))
        != CURRENT_FINDING_DETECTOR_MANIFEST_SHA256
    )
    changed = (
        replace(CURRENT_FINDING_DETECTORS[0], detector_identity="page-http-error-v2"),
        *CURRENT_FINDING_DETECTORS[1:],
    )
    assert finding_detector_manifest_sha256(changed) != CURRENT_FINDING_DETECTOR_MANIFEST_SHA256


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
