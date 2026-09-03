import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select
from sqlalchemy.orm import sessionmaker

from app.api.findings_routes import router as findings_router
from app.database import get_db
from app.models import (
    BackgroundJob,
    Finding,
    FindingAssessment,
    FindingEvaluation,
    FindingEvidenceReference,
    JobEvent,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    SitePage,
    SourceEntryObservation,
    SourceRefresh,
    UrlSource,
    WebResource,
    WebsiteProperty,
)
from app.services import background_jobs
from app.services.finding_deletion import reset_site_findings
from app.services.finding_detectors import CURRENT_FINDING_DETECTOR_MANIFEST_SHA256
from app.services.finding_evaluations import (
    FINDING_DETECTOR_BUNDLE_IDENTITY,
    FindingEvaluationChronologyError,
    create_evaluation,
    execute_evaluation,
    finding_fingerprint,
)
from app.services.findings import get_finding, list_evaluations, list_findings, set_acknowledged
from app.services.job_handlers import (
    FindingEvaluationJobHandler,
    JobExecutionContext,
    JobHandlerRegistry,
    run_claimed_job,
)
from app.services.job_types import JOB_TYPE_FINDING_EVALUATION
from app.services.site_intelligence import get_site_intelligence


def _site_page(db, *, name: str = "Finding fixture", base_url: str = "https://example.test/"):
    host = base_url.removeprefix("https://").removeprefix("http://").rstrip("/")
    site = WebsiteProperty(
        name=name,
        base_url=base_url,
        normalized_base_url=base_url,
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url=f"{base_url.rstrip('/')}/page",
        scheme="https",
        host=host,
        path="/page",
        query="",
    )
    db.add_all([site, resource])
    db.flush()
    page = SitePage(website_property_id=site.id, resource_id=resource.id)
    db.add(page)
    db.flush()
    return site, resource, page


def _scan(
    db,
    site,
    resource,
    moment,
    status,
    fetch_state="fetched",
    *,
    meta_robots=None,
    response_headers=None,
    canonical_url=None,
    page_title="Example page",
    parsed_head_json=None,
    representation_kind="html_page",
    error_type=None,
    error_message=None,
    final_url=None,
    redirect_chain=None,
):
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=moment,
        finished_at=moment,
    )
    db.add(scan)
    db.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        http_status=status,
        crawl_depth=0,
        fetched_at=moment - timedelta(minutes=5),
        fetch_state=fetch_state,
        meta_robots=meta_robots,
        response_headers=response_headers,
        canonical_url=canonical_url,
        page_title=page_title,
        parsed_head_json={"links": []} if parsed_head_json is None else parsed_head_json,
        representation_kind=representation_kind,
        error_type=error_type,
        error_message=error_message,
        final_url=final_url or resource.normalized_url,
        redirect_chain=redirect_chain,
    )
    db.add(snapshot)
    db.flush()
    return scan, snapshot


def _evaluate(db, site):
    evaluation, created = create_evaluation(db, site.id)
    assert created
    result = execute_evaluation(db, evaluation.id)
    db.commit()
    return evaluation, result


def _sitemap_refresh(
    db,
    site,
    resource,
    moment,
    *,
    source=None,
    status="completed",
    materialized=True,
    present=True,
    duplicates=1,
):
    if source is None:
        source = UrlSource(
            website_property_id=site.id,
            source_type="sitemap",
            name="Sitemap",
            source_url="https://example.test/sitemap.xml",
            normalized_source_url="https://example.test/sitemap.xml",
            is_active=True,
            discovery_mode="configured",
            settings_json={},
        )
        db.add(source)
        db.flush()
    refresh = SourceRefresh(
        url_source_id=source.id,
        status=status,
        started_at=moment - timedelta(minutes=1),
        finished_at=moment,
        membership_materialized=materialized,
        sitemap_document_type="urlset" if materialized else None,
        child_refresh_ids_json=[],
    )
    db.add(refresh)
    db.flush()
    if present:
        for position in range(duplicates):
            db.add(
                SourceEntryObservation(
                    source_refresh_id=refresh.id,
                    position=position,
                    resource_id=resource.id,
                    raw_url=resource.normalized_url,
                    normalized_url=resource.normalized_url,
                    normalization_version="url-normalization-v1",
                    source_metadata_json={"document_type": "urlset"},
                    validation_state="valid",
                    scope_decision="crawlable",
                )
            )
    db.flush()
    return source, refresh


def _manifest_leaf(source, refresh):
    return {
        "url_source_id": source.id,
        "refresh_tree": {
            "url_source_id": source.id,
            "source_refresh_id": refresh.id,
            "sitemap_document_type": "urlset",
            "status": refresh.status,
            "membership_materialized": True,
            "children": [],
        },
    }


def _sitemap_source(db, site, name, path, *, discovery_mode="sitemap_index_discovered"):
    source = UrlSource(
        website_property_id=site.id,
        source_type="sitemap",
        name=name,
        source_url=f"https://example.test/{path}",
        normalized_source_url=f"https://example.test/{path}",
        is_active=True,
        discovery_mode=discovery_mode,
        settings_json={},
    )
    db.add(source)
    db.flush()
    return source


def _sitemap_index_refresh(db, source, moment, children, *, status="completed"):
    refresh = SourceRefresh(
        url_source_id=source.id,
        status=status,
        started_at=moment - timedelta(minutes=1),
        finished_at=moment,
        sitemap_document_type="sitemapindex",
        membership_materialized=False,
        child_refresh_ids_json=[child.id for child in children],
        child_source_count=len(children),
    )
    db.add(refresh)
    db.flush()
    return refresh


def _findings_client(db_session) -> TestClient:
    application = FastAPI()
    application.include_router(findings_router)

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    return TestClient(application)


def _job_context(factory, job, lease_token: str) -> JobExecutionContext:
    return JobExecutionContext(
        session_factory=factory,
        job_id=job.id,
        lease_token=lease_token,
        lease_seconds=30,
    )


def _universe_hash(resource_ids: list[int]) -> str:
    payload = json.dumps(resource_ids, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _resource(db, path: str) -> WebResource:
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://example.test{path}",
        scheme="https",
        host="example.test",
        path=path,
        query="",
    )
    db.add(resource)
    db.flush()
    return resource


def _target_snapshot(
    db,
    scan: Scan,
    resource: WebResource,
    moment: datetime,
    status: int | None,
    *,
    fetch_state: str = "fetched",
    final_url: str | None = None,
    redirect_chain: list[dict[str, object]] | None = None,
) -> ResourceSnapshot:
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=final_url or resource.normalized_url,
        http_status=status,
        crawl_depth=1,
        fetched_at=moment - timedelta(minutes=4),
        fetch_state=fetch_state,
        representation_kind="html_page",
        page_title="Target page",
        parsed_head_json={"links": []},
        redirect_chain=redirect_chain,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _link(
    db,
    source: ResourceSnapshot,
    target: WebResource,
    *,
    count: int = 1,
) -> list[ResourceOccurrence]:
    occurrences = [
        ResourceOccurrence(
            source_snapshot_id=source.id,
            relation_type="page_link",
            raw_href=target.path,
            resolved_url=target.normalized_url,
            normalized_target_url=target.normalized_url,
            target_resource_id=target.id,
            anchor_text=f"Link to {target.path}",
            in_scope=index == 0,
            scope_decision="crawlable" if index == 0 else "already_seen",
            link_role="main_content",
            link_role_rule="ancestor_main",
        )
        for index in range(count)
    ]
    db.add_all(occurrences)
    db.flush()
    return occurrences


def test_http_finding_lifecycle_uses_one_identity_and_evidence_time(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    start = datetime(2026, 8, 24, 9, tzinfo=UTC)
    _scan(db_session, site, resource, start, 404)
    first, _ = _evaluate(db_session, site)
    finding = db_session.scalar(select(Finding))
    assert finding is not None
    finding_id = finding.id
    fingerprint = finding.fingerprint_sha256
    assert finding.condition_state == "detected"
    assert finding.current_severity == "medium"
    assert finding.first_detected_at == start - timedelta(minutes=5)

    _scan(db_session, site, resource, start + timedelta(hours=1), None, "failed")
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert (finding.id, finding.fingerprint_sha256, finding.condition_state) == (
        finding_id,
        fingerprint,
        "unknown",
    )
    assert finding.resolved_at is None

    _scan(db_session, site, resource, start + timedelta(hours=2), 200)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "resolved"
    assert finding.resolved_at == start + timedelta(hours=2, minutes=-5)
    assert set_acknowledged(db_session, site.id, finding.id, True).acknowledged_at is not None

    _scan(db_session, site, resource, start + timedelta(hours=3), 500)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "detected"
    assert finding.current_severity == "high"
    assert finding.reopened_at == start + timedelta(hours=3, minutes=-5)
    assert finding.acknowledged_at is None
    assert db_session.scalar(select(Finding).where(Finding.id == finding_id)) is finding
    assert db_session.query(Finding).count() == 1
    assert db_session.query(FindingAssessment).count() == 4
    assert [
        row.outcome
        for row in db_session.scalars(select(FindingAssessment).order_by(FindingAssessment.id))
    ] == ["detected", "unknown", "clear", "detected"]
    assert first.started_at is not None and first.started_at > first.evidence_horizon_at


def test_clean_and_unknown_pages_without_history_create_no_rows_and_exact_input_dedupes(
    db_session,
) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 200)
    evaluation, _ = _evaluate(db_session, site)
    duplicate, created = create_evaluation(db_session, site.id)
    assert not created and duplicate.id == evaluation.id
    assert db_session.query(Finding).count() == 0
    assert db_session.query(FindingAssessment).count() == 0


def test_multi_detector_counts_identity_and_sparse_persistence(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(
        db_session,
        site,
        resource,
        datetime(2026, 8, 24, tzinfo=UTC),
        404,
        meta_robots="index",
        response_headers={"x-robots-tag": "noindex"},
    )
    evaluation, result = _evaluate(db_session, site)

    findings = list(db_session.scalars(select(Finding).order_by(Finding.finding_type)))
    assert [item.finding_type for item in findings] == [
        "page_http_error",
        "page_indexability_conflict",
        "page_noindex",
    ]
    assert len({item.fingerprint_sha256 for item in findings}) == 3
    assert (result.detected, result.clear, result.unknown) == (3, 11, 0)
    assert evaluation.active_page_count == 1
    assert evaluation.assessment_count == 3
    assert evaluation.detector_summary_json["page_http_error"] == {
        "detector_identity": "page-http-error-v1",
        "detected": 1,
        "clear": 0,
        "unknown": 0,
        "reason_counts": {},
    }
    assert len(evaluation.detector_summary_json) == 14
    assert db_session.query(FindingAssessment).count() == 3


def test_detector_summary_persists_sparse_unknown_diagnostics(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(
        db_session,
        site,
        resource,
        datetime(2026, 8, 24, tzinfo=UTC),
        None,
        "failed",
        error_type="connection_timeout",
        error_message="Timed out",
    )
    evaluation, result = _evaluate(db_session, site)
    assert result.detector_summary == evaluation.detector_summary_json
    assert evaluation.detector_summary_json["page_static_fetch_failure"]["detected"] == 1
    assert evaluation.detector_summary_json["page_missing_title"] == {
        "detector_identity": "page-missing-title-v1",
        "detected": 0,
        "clear": 0,
        "unknown": 1,
        "reason_counts": {"subject_fetch_unusable": 1},
    }
    assert evaluation.detected_count == 1
    assert db_session.query(Finding).count() == 1


def test_noindex_full_lifecycle_preserves_and_clears_acknowledgement(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    start = datetime(2026, 8, 24, 9, tzinfo=UTC)
    _scan(db_session, site, resource, start, 200, meta_robots="noindex")
    _evaluate(db_session, site)
    finding = db_session.scalar(select(Finding).where(Finding.finding_type == "page_noindex"))
    assert finding is not None and finding.condition_state == "detected"

    _scan(db_session, site, resource, start + timedelta(hours=1), None, "failed")
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "unknown" and finding.resolved_at is None

    _scan(db_session, site, resource, start + timedelta(hours=2), 200, meta_robots="index")
    _evaluate(db_session, site)
    assert set_acknowledged(db_session, site.id, finding.id, True).acknowledged_at is not None
    db_session.refresh(finding)
    assert finding.condition_state == "resolved" and finding.acknowledged_at is not None

    _scan(db_session, site, resource, start + timedelta(hours=3), 200, meta_robots="noindex")
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "detected"
    assert finding.reopened_at == start + timedelta(hours=3, minutes=-5)
    assert finding.acknowledged_at is None
    assessments = list(
        db_session.scalars(
            select(FindingAssessment)
            .where(FindingAssessment.finding_id == finding.id)
            .order_by(FindingAssessment.id)
        )
    )
    assert [item.outcome for item in assessments] == [
        "detected",
        "unknown",
        "clear",
        "detected",
    ]


def test_v3_continues_http_identity_but_will_not_execute_historical_v1(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _snapshot = _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    legacy = FindingEvaluation(
        website_property_id=site.id,
        source_scan_id=scan.id,
        evaluator_version="finding-evaluator-v1",
        detector_bundle_identity="finding-detectors-v1",
        input_fingerprint_sha256="1" * 64,
        evidence_horizon_at=scan.finished_at,
        active_page_count=1,
        active_page_universe_sha256="2" * 64,
        active_page_resource_ids_json=[resource.id],
        status="queued",
    )
    db_session.add(legacy)
    db_session.commit()

    current, created = create_evaluation(db_session, site.id)
    assert created
    execute_evaluation(db_session, current.id)
    db_session.commit()
    finding = db_session.scalar(select(Finding).where(Finding.finding_type == "page_http_error"))
    assert finding is not None
    fingerprint = finding.fingerprint_sha256

    with pytest.raises(ValueError, match="Historical Finding evaluations"):
        execute_evaluation(db_session, legacy.id)
    db_session.rollback()
    db_session.refresh(finding)
    assert finding.fingerprint_sha256 == fingerprint
    assert finding.condition_state == "detected"


def test_v4_reevaluates_same_retained_scan_and_preserves_v3_finding_continuity(
    db_session,
) -> None:
    site, resource, _page = _site_page(db_session)
    scan, snapshot = _scan(
        db_session,
        site,
        resource,
        datetime(2026, 9, 2, 1, tzinfo=UTC),
        404,
        page_title=None,
    )
    universe_hash = _universe_hash([resource.id])
    historical_v3 = FindingEvaluation(
        website_property_id=site.id,
        source_scan_id=scan.id,
        evaluator_version="finding-evaluator-v2",
        detector_bundle_identity="finding-detectors-v3",
        input_fingerprint_sha256="2" * 64,
        evidence_horizon_at=scan.finished_at,
        active_page_count=1,
        active_page_universe_sha256=universe_hash,
        active_page_resource_ids_json=[resource.id],
        status="completed",
        detected_count=1,
        clear_count=3,
    )
    observed_at = snapshot.fetched_at or scan.finished_at
    http_finding = Finding(
        website_property_id=site.id,
        web_resource_id=resource.id,
        finding_type="page_http_error",
        logical_key_version="page-http-error-key-v1",
        fingerprint_sha256=finding_fingerprint(site.id, resource.id),
        condition_state="detected",
        current_severity="medium",
        first_detected_at=observed_at,
        last_detected_at=observed_at,
        last_evaluated_evidence_at=observed_at,
    )
    db_session.add_all([historical_v3, http_finding])
    db_session.flush()
    historical_assessment = FindingAssessment(
        finding_id=http_finding.id,
        finding_evaluation_id=historical_v3.id,
        outcome="detected",
        severity="medium",
        evidence_observed_at=observed_at,
        details_json={"detector_identity": "page-http-error-v1", "http_status": 404},
        assessment_sha256="3" * 64,
    )
    db_session.add(historical_assessment)
    db_session.flush()
    http_finding.current_assessment_id = historical_assessment.id
    db_session.commit()

    current_v5, created = create_evaluation(db_session, site.id)
    assert created is True
    assert current_v5.source_scan_id == historical_v3.source_scan_id == scan.id
    assert current_v5.active_page_universe_sha256 == historical_v3.active_page_universe_sha256
    assert current_v5.evaluator_version == "finding-evaluator-v3"
    assert current_v5.detector_bundle_identity == "finding-detectors-v5"
    expected_fingerprint_payload = json.dumps(
        {
            "active_page_universe_sha256": universe_hash,
            "detector_bundle_identity": "finding-detectors-v5",
            "detector_bundle_manifest_sha256": CURRENT_FINDING_DETECTOR_MANIFEST_SHA256,
            "evaluator_version": "finding-evaluator-v3",
            "evidence_manifest": {
                "schema": "finding-evidence-manifest-v1",
                "static": {"scan_id": scan.id},
                "sitemap_roots": [],
            },
            "site_id": site.id,
            "source_scan_id": scan.id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    assert (
        current_v5.input_fingerprint_sha256
        == hashlib.sha256(expected_fingerprint_payload).hexdigest()
    )
    execute_evaluation(db_session, current_v5.id)
    db_session.commit()

    http_rows = list(
        db_session.scalars(select(Finding).where(Finding.finding_type == "page_http_error"))
    )
    assert len(http_rows) == 1
    assert http_rows[0].id == http_finding.id
    assert (
        db_session.query(FindingAssessment)
        .filter(FindingAssessment.finding_id == http_finding.id)
        .count()
        == 2
    )
    missing_title = db_session.scalar(
        select(Finding).where(Finding.finding_type == "page_missing_title")
    )
    assert missing_title is not None
    assert missing_title.id != http_finding.id

    repeated_v5, repeated_created = create_evaluation(db_session, site.id)
    assert repeated_created is False
    assert repeated_v5.id == current_v5.id
    history = list_evaluations(db_session, site.id, 10, 0)
    assert history is not None
    assert [item.detector_bundle_identity for item in history.items] == [
        "finding-detectors-v5",
        "finding-detectors-v3",
    ]


def test_v4_chronology_ignores_v3_but_blocks_older_pending_v4(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan_a, _snapshot = _scan(db_session, site, resource, datetime(2026, 9, 2, 1, tzinfo=UTC), 404)
    universe_hash = _universe_hash([resource.id])
    historical_v3 = FindingEvaluation(
        website_property_id=site.id,
        source_scan_id=scan_a.id,
        evaluator_version="finding-evaluator-v2",
        detector_bundle_identity="finding-detectors-v3",
        input_fingerprint_sha256="4" * 64,
        evidence_horizon_at=scan_a.finished_at,
        active_page_count=1,
        active_page_universe_sha256=universe_hash,
        active_page_resource_ids_json=[resource.id],
        status="completed",
    )
    db_session.add(historical_v3)
    db_session.flush()
    pending_v4_a, created = create_evaluation(db_session, site.id)
    assert created and pending_v4_a.source_scan_id == scan_a.id

    scan_b, _snapshot = _scan(db_session, site, resource, datetime(2026, 9, 2, 2, tzinfo=UTC), 200)
    v4_b, created = create_evaluation(db_session, site.id)
    assert created and v4_b.source_scan_id == scan_b.id
    execute_evaluation(db_session, v4_b.id)
    db_session.commit()

    with pytest.raises(FindingEvaluationChronologyError):
        execute_evaluation(db_session, pending_v4_a.id)
    db_session.rollback()
    assert historical_v3.status == "completed"
    assert historical_v3.detector_bundle_identity == "finding-detectors-v3"
    assert FINDING_DETECTOR_BUNDLE_IDENTITY == "finding-detectors-v5"


def test_v5_freezes_manifest_and_reevaluates_same_scan_for_new_source_refresh(
    db_session,
) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _snapshot = _scan(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC), 404)
    source, refresh_a = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC)
    )
    evaluation_a, created = create_evaluation(db_session, site.id)
    assert created
    assert evaluation_a.evidence_manifest_json == {
        "schema": "finding-evidence-manifest-v1",
        "static": {"scan_id": scan.id},
        "sitemap_roots": [_manifest_leaf(source, refresh_a)],
    }
    execute_evaluation(db_session, evaluation_a.id)
    db_session.commit()
    sitemap_finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert sitemap_finding is not None
    assessment = db_session.get(FindingAssessment, sitemap_finding.current_assessment_id)
    assert assessment is not None
    references = list(
        db_session.scalars(
            select(FindingEvidenceReference)
            .where(FindingEvidenceReference.finding_assessment_id == assessment.id)
            .order_by(FindingEvidenceReference.position)
        )
    )
    assert [item.evidence_kind for item in references] == [
        "resource_snapshot",
        "source_entry_observation",
        "scan",
    ]

    _source, refresh_b = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 3, 3, tzinfo=UTC),
        source=source,
        present=False,
    )
    evaluation_b, created = create_evaluation(db_session, site.id)
    assert created and evaluation_b.source_scan_id == scan.id
    assert evaluation_b.id != evaluation_a.id
    assert evaluation_b.input_fingerprint_sha256 != evaluation_a.input_fingerprint_sha256
    assert evaluation_b.evidence_manifest_json["sitemap_roots"] == [
        _manifest_leaf(source, refresh_b)
    ]
    execute_evaluation(db_session, evaluation_b.id)
    db_session.commit()
    resolved = db_session.get(Finding, sitemap_finding.id)
    assert resolved.condition_state == "resolved"
    assert resolved.resolved_at == refresh_b.finished_at
    resolved_assessment = db_session.get(FindingAssessment, resolved.current_assessment_id)
    assert resolved_assessment is not None
    assert resolved_assessment.evidence_observed_at == refresh_b.finished_at


def test_v5_new_scan_reuses_same_source_refresh_and_changes_fingerprint(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    source, refresh = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC)
    )
    scan_a, _ = _scan(db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC), 404)
    evaluation_a, _created = create_evaluation(db_session, site.id)
    execute_evaluation(db_session, evaluation_a.id)
    db_session.commit()
    scan_b, _ = _scan(db_session, site, resource, datetime(2026, 9, 3, 3, tzinfo=UTC), 200)
    evaluation_b, created = create_evaluation(db_session, site.id)
    assert created and evaluation_b.source_scan_id == scan_b.id
    assert evaluation_b.source_scan_id != scan_a.id
    assert evaluation_b.evidence_manifest_json["sitemap_roots"] == [_manifest_leaf(source, refresh)]
    assert evaluation_b.input_fingerprint_sha256 != evaluation_a.input_fingerprint_sha256


def test_v5_older_queued_manifest_cannot_overwrite_newer_completed_manifest(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _ = _scan(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC), 404)
    source, _refresh_a = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC)
    )
    older, _created = create_evaluation(db_session, site.id)
    _source, refresh_b = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 3, tzinfo=UTC), source=source
    )
    newer, created = create_evaluation(db_session, site.id)
    assert created and newer.source_scan_id == older.source_scan_id == scan.id
    assert (
        newer.evidence_manifest_json["sitemap_roots"][0]["refresh_tree"]["source_refresh_id"]
        == refresh_b.id
    )
    execute_evaluation(db_session, newer.id)
    db_session.commit()
    with pytest.raises(FindingEvaluationChronologyError, match="newer frozen evidence manifest"):
        execute_evaluation(db_session, older.id)
    db_session.rollback()


def test_v5_source_add_remove_and_failed_latest_refresh_are_manifest_aware(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC), 404)
    source_a, refresh_a = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC)
    )
    first, _ = create_evaluation(db_session, site.id)
    source_b = UrlSource(
        website_property_id=site.id,
        source_type="sitemap",
        name="Unrefreshed",
        source_url="https://example.test/second.xml",
        normalized_source_url="https://example.test/second.xml",
        is_active=True,
        discovery_mode="configured",
        settings_json={},
    )
    db_session.add(source_b)
    db_session.flush()
    added, created = create_evaluation(db_session, site.id)
    assert created
    assert added.evidence_manifest_json["sitemap_roots"] == [
        _manifest_leaf(source_a, refresh_a),
        {"url_source_id": source_b.id, "refresh_tree": None},
    ]
    execute_evaluation(db_session, added.id)
    db_session.commit()
    assert added.detector_summary_json["sitemap_page_http_error"]["detected"] == 1

    _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 3, 3, tzinfo=UTC),
        source=source_a,
        status="failed",
        materialized=False,
        present=False,
    )
    failed, created = create_evaluation(db_session, site.id)
    assert created
    assert failed.evidence_manifest_json["sitemap_roots"][0]["refresh_tree"] is None
    execute_evaluation(db_session, failed.id)
    db_session.commit()
    assert failed.detector_summary_json["sitemap_page_http_error"]["unknown"] == 1
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None and finding.condition_state == "unknown"

    source_b.is_active = False
    db_session.commit()
    removed, created = create_evaluation(db_session, site.id)
    assert created
    assert [item["url_source_id"] for item in removed.evidence_manifest_json["sitemap_roots"]] == [
        source_a.id
    ]
    assert first.input_fingerprint_sha256 != removed.input_fingerprint_sha256


def test_recursive_root_index_does_not_poison_known_absence(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    source_a = _sitemap_source(db_session, site, "A", "a.xml")
    source_b = _sitemap_source(db_session, site, "B", "b.xml")
    _unused, leaf_a = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 2, tzinfo=UTC),
        source=source_a,
        present=False,
    )
    _unused, leaf_b = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 2, tzinfo=UTC),
        source=source_b,
        present=False,
    )
    _sitemap_index_refresh(
        db_session, root, datetime(2026, 9, 4, 2, 1, tzinfo=UTC), [leaf_a, leaf_b]
    )

    evaluation = _evaluate(db_session, site)[0]

    assert evaluation.detector_summary_json["sitemap_page_http_error"]["clear"] == 1
    assert evaluation.detector_summary_json["sitemap_page_http_error"]["reason_counts"] == {
        "sitemap_membership_not_present": 1
    }


def test_recursive_sitemap_detects_then_resolves_on_same_scan(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _ = _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    child = _sitemap_source(db_session, site, "Child", "child.xml")
    _unused, child_r1 = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 4, 2, tzinfo=UTC), source=child
    )
    _sitemap_index_refresh(db_session, root, datetime(2026, 9, 4, 2, 1, tzinfo=UTC), [child_r1])
    first = _evaluate(db_session, site)[0]
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None and finding.condition_state == "detected"

    _unused, child_r2 = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 3, tzinfo=UTC),
        source=child,
        present=False,
    )
    root_r2 = _sitemap_index_refresh(
        db_session, root, datetime(2026, 9, 4, 3, 1, tzinfo=UTC), [child_r2]
    )
    second = _evaluate(db_session, site)[0]

    assert first.source_scan_id == second.source_scan_id == scan.id
    assert first.input_fingerprint_sha256 != second.input_fingerprint_sha256
    assert finding.condition_state == "resolved"
    assert finding.resolved_at == root_r2.finished_at


def test_removed_discovered_child_cannot_contribute_stale_membership(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    source_a = _sitemap_source(db_session, site, "A", "a.xml")
    source_b = _sitemap_source(db_session, site, "B", "b.xml")
    _unused, a_r1 = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 2, tzinfo=UTC),
        source=source_a,
        present=False,
    )
    _unused, b_r1 = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 4, 2, tzinfo=UTC), source=source_b
    )
    _sitemap_index_refresh(db_session, root, datetime(2026, 9, 4, 2, 1, tzinfo=UTC), [a_r1, b_r1])
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None and finding.condition_state == "detected"

    _unused, a_r2 = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 3, tzinfo=UTC),
        source=source_a,
        present=False,
    )
    _sitemap_index_refresh(db_session, root, datetime(2026, 9, 4, 3, 1, tzinfo=UTC), [a_r2])
    evaluation = _evaluate(db_session, site)[0]

    assert source_b.is_active is True
    assert finding.condition_state == "resolved"
    tree = evaluation.evidence_manifest_json["sitemap_roots"][0]["refresh_tree"]
    assert [item["url_source_id"] for item in tree["children"]] == [source_a.id]


def test_failed_child_keeps_absence_unknown_and_does_not_resolve(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    source_a = _sitemap_source(db_session, site, "A", "a.xml")
    source_b = _sitemap_source(db_session, site, "B", "b.xml")
    _unused, b_r1 = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 4, 2, tzinfo=UTC), source=source_b
    )
    _sitemap_index_refresh(db_session, root, datetime(2026, 9, 4, 2, 1, tzinfo=UTC), [b_r1])
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None and finding.condition_state == "detected"

    _unused, a_r2 = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 3, tzinfo=UTC),
        source=source_a,
        present=False,
    )
    _unused, b_failed = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 3, tzinfo=UTC),
        source=source_b,
        status="failed",
        materialized=False,
        present=False,
    )
    _sitemap_index_refresh(
        db_session,
        root,
        datetime(2026, 9, 4, 3, 1, tzinfo=UTC),
        [a_r2, b_failed],
        status="completed_with_errors",
    )
    evaluation = _evaluate(db_session, site)[0]

    assert evaluation.detector_summary_json["sitemap_page_http_error"]["unknown"] == 1
    assert finding.condition_state == "unknown"
    assert finding.resolved_at is None


def test_recursive_presence_dominates_failed_sibling(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    source_a = _sitemap_source(db_session, site, "A", "a.xml")
    source_b = _sitemap_source(db_session, site, "B", "b.xml")
    _unused, a_refresh = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 4, 2, tzinfo=UTC), source=source_a
    )
    _unused, b_failed = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 2, tzinfo=UTC),
        source=source_b,
        status="failed",
        materialized=False,
        present=False,
    )
    _sitemap_index_refresh(
        db_session,
        root,
        datetime(2026, 9, 4, 2, 1, tzinfo=UTC),
        [a_refresh, b_failed],
        status="completed_with_errors",
    )

    evaluation = _evaluate(db_session, site)[0]

    assert evaluation.detector_summary_json["sitemap_page_http_error"]["detected"] == 1


def test_created_evaluation_keeps_exact_recursive_refresh_tree(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    child = _sitemap_source(db_session, site, "Child", "child.xml")
    _unused, child_r1 = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 4, 2, tzinfo=UTC), source=child
    )
    root_r1 = _sitemap_index_refresh(
        db_session, root, datetime(2026, 9, 4, 2, 1, tzinfo=UTC), [child_r1]
    )
    frozen, created = create_evaluation(db_session, site.id)
    assert created
    _unused, child_r2 = _sitemap_refresh(
        db_session,
        site,
        resource,
        datetime(2026, 9, 4, 3, tzinfo=UTC),
        source=child,
        present=False,
    )
    root_r2 = _sitemap_index_refresh(
        db_session, root, datetime(2026, 9, 4, 3, 1, tzinfo=UTC), [child_r2]
    )
    newer, created = create_evaluation(db_session, site.id)
    assert created and frozen.input_fingerprint_sha256 != newer.input_fingerprint_sha256

    execute_evaluation(db_session, frozen.id)
    db_session.commit()

    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None and finding.condition_state == "detected"
    old_tree = frozen.evidence_manifest_json["sitemap_roots"][0]["refresh_tree"]
    new_tree = newer.evidence_manifest_json["sitemap_roots"][0]["refresh_tree"]
    assert old_tree["source_refresh_id"] == root_r1.id
    assert old_tree["children"][0]["source_refresh_id"] == child_r1.id
    assert new_tree["source_refresh_id"] == root_r2.id
    assert new_tree["children"][0]["source_refresh_id"] == child_r2.id


def test_nested_sitemap_index_retains_recursive_provenance(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 4, 1, tzinfo=UTC), 404)
    root = _sitemap_source(db_session, site, "Root", "root.xml", discovery_mode="configured")
    nested = _sitemap_source(db_session, site, "Nested", "nested.xml")
    leaf = _sitemap_source(db_session, site, "Leaf", "leaf.xml")
    _unused, leaf_refresh = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 4, 2, tzinfo=UTC), source=leaf
    )
    nested_refresh = _sitemap_index_refresh(
        db_session, nested, datetime(2026, 9, 4, 2, 1, tzinfo=UTC), [leaf_refresh]
    )
    root_refresh = _sitemap_index_refresh(
        db_session, root, datetime(2026, 9, 4, 2, 2, tzinfo=UTC), [nested_refresh]
    )

    evaluation = _evaluate(db_session, site)[0]

    assert evaluation.detector_summary_json["sitemap_page_http_error"]["detected"] == 1
    tree = evaluation.evidence_manifest_json["sitemap_roots"][0]["refresh_tree"]
    assert tree["source_refresh_id"] == root_refresh.id
    assert tree["children"][0]["source_refresh_id"] == nested_refresh.id
    assert tree["children"][0]["children"][0]["source_refresh_id"] == leaf_refresh.id


def test_sitemap_finding_streams_can_be_deleted_independently(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _ = _scan(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC), 404)
    source, _refresh = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC)
    )
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None

    db_session.delete(source)
    db_session.commit()
    source_deleted = get_finding(db_session, site.id, finding.id)
    assert source_deleted is not None
    source_refs = [
        item
        for item in source_deleted.assessments[0].evidence_references
        if item.evidence_kind == "source_entry_observation"
    ]
    assert source_refs and all(not item.retained for item in source_refs)
    assert any(
        item.evidence_kind == "resource_snapshot" and item.retained
        for item in source_deleted.assessments[0].evidence_references
    )

    db_session.execute(delete(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan.id))
    db_session.execute(delete(Scan).where(Scan.id == scan.id))
    db_session.commit()
    both_deleted = get_finding(db_session, site.id, finding.id)
    assert both_deleted is not None
    assert all(not item.retained for item in both_deleted.assessments[0].evidence_references)


def test_sitemap_evidence_remains_when_scan_is_deleted_first(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _ = _scan(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC), 404)
    _source, _refresh = _sitemap_refresh(
        db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC)
    )
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None
    db_session.execute(delete(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan.id))
    db_session.execute(delete(Scan).where(Scan.id == scan.id))
    db_session.commit()

    detail = get_finding(db_session, site.id, finding.id)
    assert detail is not None
    references = detail.assessments[0].evidence_references
    assert any(
        item.evidence_kind == "source_entry_observation" and item.retained for item in references
    )
    assert all(
        not item.retained
        for item in references
        if item.evidence_kind in {"resource_snapshot", "scan"}
    )


def test_sitemap_http_error_scan_lifecycle_detects_resolves_and_reopens(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _sitemap_refresh(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC))
    _scan(db_session, site, resource, datetime(2026, 9, 3, 2, tzinfo=UTC), 404)
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None and finding.current_severity == "medium"

    _scan(db_session, site, resource, datetime(2026, 9, 3, 3, tzinfo=UTC), 200)
    _evaluate(db_session, site)
    assert finding.condition_state == "resolved"

    _scan(db_session, site, resource, datetime(2026, 9, 3, 4, tzinfo=UTC), 500)
    _evaluate(db_session, site)
    assert finding.condition_state == "detected"
    assert finding.current_severity == "high"
    assert finding.reopened_at is not None
    assert (
        db_session.query(FindingAssessment)
        .filter(FindingAssessment.finding_id == finding.id)
        .count()
        == 3
    )


def test_sitemap_noindex_and_redirect_complete_lifecycles(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _sitemap_refresh(db_session, site, resource, datetime(2026, 9, 3, 1, tzinfo=UTC))
    _scan(
        db_session,
        site,
        resource,
        datetime(2026, 9, 3, 2, tzinfo=UTC),
        200,
        meta_robots="noindex",
        final_url="https://example.test/new",
        redirect_chain=[{"status": 301, "url": resource.normalized_url}],
    )
    _evaluate(db_session, site)
    noindex = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_noindex")
    )
    redirect = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_redirect")
    )
    assert noindex is not None and noindex.condition_state == "detected"
    assert redirect is not None and redirect.condition_state == "detected"

    _scan(
        db_session,
        site,
        resource,
        datetime(2026, 9, 3, 3, tzinfo=UTC),
        200,
        meta_robots="index",
    )
    _evaluate(db_session, site)
    assert noindex.condition_state == "resolved"
    assert redirect.condition_state == "resolved"


def test_suppression_and_evidence_deletion_do_not_resolve_or_delete_history(db_session) -> None:
    site, resource, page = _site_page(db_session)
    scan, _snapshot = _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    _evaluate(db_session, site)
    finding = db_session.scalar(select(Finding))
    page.workspace_state = "suppressed"
    db_session.commit()
    visible = list_findings(
        db_session,
        site.id,
        condition_state=None,
        severity=None,
        finding_type=None,
        acknowledged=None,
        search=None,
        include_suppressed=False,
        limit=50,
        offset=0,
    )
    assert visible is not None and visible.total == 0
    assert finding.condition_state == "detected"
    db_session.execute(delete(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan.id))
    db_session.execute(delete(Scan).where(Scan.id == scan.id))
    db_session.commit()
    assert db_session.get(Finding, finding.id) is not None
    detail = get_finding(db_session, site.id, finding.id)
    assert detail is not None
    assert all(
        not reference.retained
        for item in detail.assessments
        for reference in item.evidence_references
    )


def test_monotonic_chronology_fails_closed(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    old_scan, _ = _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    old_evaluation, _ = create_evaluation(db_session, site.id)
    _scan(db_session, site, resource, datetime(2026, 8, 25, tzinfo=UTC), 200)
    _evaluate(db_session, site)
    with pytest.raises(FindingEvaluationChronologyError):
        execute_evaluation(db_session, old_evaluation.id)
    db_session.rollback()
    assert db_session.get(Scan, old_scan.id) is not None


def test_invalid_typed_evidence_pointer_is_rejected_by_service_contract(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    _evaluate(db_session, site)
    assessment = db_session.scalar(select(FindingAssessment))
    assert assessment is not None
    references = list(db_session.scalars(select(FindingEvidenceReference)))
    assert {item.evidence_kind for item in references} == {"resource_snapshot", "scan"}


def test_canonical_finding_retains_ordered_subject_target_and_scan_evidence(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    target = WebResource(
        resource_type="page",
        normalized_url="https://example.test/canonical-target",
        scheme="https",
        host="example.test",
        path="/canonical-target",
        query="",
    )
    db_session.add(target)
    db_session.flush()
    moment = datetime(2026, 8, 24, tzinfo=UTC)
    scan, subject_snapshot = _scan(
        db_session,
        site,
        resource,
        moment,
        200,
        canonical_url=target.normalized_url,
    )
    target_snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=target.id,
        requested_url=target.normalized_url,
        final_url=target.normalized_url,
        http_status=404,
        crawl_depth=1,
        fetched_at=moment - timedelta(minutes=4),
        fetch_state="fetched",
    )
    db_session.add(target_snapshot)
    db_session.flush()

    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "page_canonical_target_http_error")
    )
    assert finding is not None and finding.web_resource_id == resource.id
    assessment = db_session.get(FindingAssessment, finding.current_assessment_id)
    assert assessment is not None
    references = list(
        db_session.scalars(
            select(FindingEvidenceReference)
            .where(FindingEvidenceReference.finding_assessment_id == assessment.id)
            .order_by(FindingEvidenceReference.position)
        )
    )
    assert [(item.role, item.evidence_kind, item.evidence_id) for item in references] == [
        ("primary", "resource_snapshot", subject_snapshot.id),
        ("canonical_target", "resource_snapshot", target_snapshot.id),
        ("evaluation_horizon", "scan", scan.id),
    ]
    detail = get_finding(db_session, site.id, finding.id)
    assert detail is not None
    assert detail.finding_label == "Canonical target HTTP error"
    assert [item.role for item in detail.assessments[0].evidence_references] == [
        "primary",
        "canonical_target",
        "evaluation_horizon",
    ]


def test_findings_api_queues_lists_details_and_keeps_acknowledgement_separate(
    db_session,
) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    application = FastAPI()
    application.include_router(findings_router)

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        queued = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert queued.status_code == 202
        evaluation_id = queued.json()["id"]
        job = db_session.scalar(
            select(BackgroundJob).where(BackgroundJob.job_type == "finding_evaluation")
        )
        assert job is not None
        queued_duplicate = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert queued_duplicate.json()["id"] == evaluation_id
        assert db_session.query(BackgroundJob).count() == 1

        claimed = background_jobs.claim_next_job(
            db_session, worker_id="finding-api-worker", lease_seconds=30
        )
        assert claimed is not None and claimed.job.id == job.id
        running_duplicate = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert running_duplicate.json()["id"] == evaluation_id
        assert db_session.query(BackgroundJob).count() == 1
        factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
        FindingEvaluationJobHandler(factory)._execute_blocking(
            claimed.job,
            evaluation_id,
            _job_context(factory, claimed.job, claimed.lease_token),
        )
        db_session.expire_all()
        completed_duplicate = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert completed_duplicate.json()["id"] == evaluation_id
        assert db_session.get(BackgroundJob, job.id).attempt_count == 1
        assert db_session.query(FindingAssessment).count() == 1

        listing = client.get(f"/api/sites/{site.id}/findings").json()
        assert listing["total"] == 1
        assert listing["items"][0]["finding_label"] == "Page HTTP error"
        finding_id = listing["items"][0]["id"]
        detail = client.get(f"/api/sites/{site.id}/findings/{finding_id}").json()
        assert detail["assessments"][0]["evidence_references"][0]["retained"] is True
        acknowledged = client.post(f"/api/sites/{site.id}/findings/{finding_id}/acknowledge").json()
        assert acknowledged["condition_state"] == "detected"
        assert acknowledged["acknowledged_at"] is not None
        unacknowledged = client.post(
            f"/api/sites/{site.id}/findings/{finding_id}/unacknowledge"
        ).json()
        assert unacknowledged["acknowledged_at"] is None


def test_topology_findings_run_through_api_worker_database_and_detail(db_session) -> None:
    site, source_a, _page = _site_page(db_session)
    source_b = _resource(db_session, "/source-b")
    db_session.add(SitePage(website_property_id=site.id, resource_id=source_b.id))
    gone = _resource(db_session, "/gone")
    server_error = _resource(db_session, "/server-error")
    ok = _resource(db_session, "/ok")
    old = _resource(db_session, "/old")
    moment = datetime(2026, 9, 2, 12, tzinfo=UTC)
    scan, source_a_snapshot = _scan(db_session, site, source_a, moment, 200)
    source_b_snapshot = _target_snapshot(db_session, scan, source_b, moment, 200)
    _target_snapshot(db_session, scan, gone, moment, 404)
    _target_snapshot(db_session, scan, server_error, moment, 500)
    _target_snapshot(db_session, scan, ok, moment, 200)
    _target_snapshot(
        db_session,
        scan,
        old,
        moment,
        200,
        final_url="https://example.test/new",
        redirect_chain=[{"status_code": 301, "url": old.normalized_url}],
    )
    _link(db_session, source_a_snapshot, gone, count=2)
    _link(db_session, source_a_snapshot, server_error)
    _link(db_session, source_a_snapshot, ok)
    _link(db_session, source_b_snapshot, old)
    db_session.commit()

    with _findings_client(db_session) as client:
        queued = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert queued.status_code == 202
        evaluation_id = queued.json()["id"]
        claimed = background_jobs.claim_next_job(
            db_session, worker_id="topology-worker", lease_seconds=30
        )
        assert claimed is not None
        factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
        FindingEvaluationJobHandler(factory)._execute_blocking(
            claimed.job,
            evaluation_id,
            _job_context(factory, claimed.job, claimed.lease_token),
        )
        db_session.expire_all()

        listing = client.get(f"/api/sites/{site.id}/findings?limit=50").json()
        topology = {
            item["finding_type"]: item
            for item in listing["items"]
            if item["finding_type"]
            in {"page_broken_internal_links", "page_internal_links_to_redirects"}
        }
        assert set(topology) == {
            "page_broken_internal_links",
            "page_internal_links_to_redirects",
        }
        broken = topology["page_broken_internal_links"]
        assert broken["current_severity"] == "high"
        assert broken["current_evidence_summary"]["broken_target_count"] == 2
        assert broken["current_evidence_summary"]["broken_occurrence_count"] == 3
        redirect = topology["page_internal_links_to_redirects"]
        assert redirect["current_evidence_summary"]["redirect_target_count"] == 1

        detail = client.get(f"/api/sites/{site.id}/findings/{broken['id']}").json()
        references = detail["assessments"][0]["evidence_references"]
        assert [item["evidence_kind"] for item in references] == [
            "resource_snapshot",
            "resource_occurrence",
            "resource_snapshot",
            "resource_occurrence",
            "resource_snapshot",
            "resource_occurrence",
            "resource_snapshot",
            "scan",
        ]
        assert all(item["retained"] for item in references)

    broken_finding_id = broken["id"]
    db_session.execute(delete(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan.id))
    db_session.execute(delete(Scan).where(Scan.id == scan.id))
    db_session.commit()
    surviving = get_finding(db_session, site.id, broken_finding_id)
    assert surviving is not None
    assert surviving.assessments
    assert all(not item.retained for item in surviving.assessments[0].evidence_references)


def test_api_runs_current_v5_bundle_against_same_scan_without_recrawl(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _snapshot = _scan(
        db_session,
        site,
        resource,
        datetime(2026, 9, 2, 1, tzinfo=UTC),
        200,
        page_title=None,
    )
    historical_v3 = FindingEvaluation(
        website_property_id=site.id,
        source_scan_id=scan.id,
        evaluator_version="finding-evaluator-v2",
        detector_bundle_identity="finding-detectors-v3",
        input_fingerprint_sha256="5" * 64,
        evidence_horizon_at=scan.finished_at,
        active_page_count=1,
        active_page_universe_sha256=_universe_hash([resource.id]),
        active_page_resource_ids_json=[resource.id],
        status="completed",
    )
    db_session.add(historical_v3)
    db_session.commit()

    with _findings_client(db_session) as client:
        queued = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert queued.status_code == 202
        payload = queued.json()
        assert payload["id"] != historical_v3.id
        assert payload["source_scan_id"] == historical_v3.source_scan_id == scan.id
        assert payload["active_page_universe_sha256"] == (historical_v3.active_page_universe_sha256)
        assert payload["evaluator_version"] == "finding-evaluator-v3"
        assert payload["detector_bundle_identity"] == "finding-detectors-v5"

        claimed = background_jobs.claim_next_job(
            db_session, worker_id="v4-same-scan-worker", lease_seconds=30
        )
        assert claimed is not None
        factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
        FindingEvaluationJobHandler(factory)._execute_blocking(
            claimed.job,
            payload["id"],
            _job_context(factory, claimed.job, claimed.lease_token),
        )
        db_session.expire_all()
        findings = client.get(f"/api/sites/{site.id}/findings").json()
        assert [item["finding_type"] for item in findings["items"]] == ["page_missing_title"]

        repeated = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert repeated.status_code == 202
        assert repeated.json()["id"] == payload["id"]
        assert db_session.query(FindingEvaluation).count() == 2
        assert db_session.query(Scan).count() == 1


def test_manual_product_fixture_exposes_distinct_static_pack_rows_through_worker_and_api(
    db_session,
) -> None:
    site, http_resource, _page = _site_page(db_session)
    fixture_specs = [
        ("fetch-failure", {}),
        ("noindex", {}),
        ("missing-title", {}),
        ("invalid-canonical", {}),
        ("multiple-canonicals", {}),
        ("broken-canonical", {}),
    ]
    resources = {"http-error": http_resource}
    for path, _config in fixture_specs:
        resource = WebResource(
            resource_type="page",
            normalized_url=f"https://example.test/{path}",
            scheme="https",
            host="example.test",
            path=f"/{path}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
        resources[path] = resource
    target = WebResource(
        resource_type="page",
        normalized_url="https://example.test/canonical-target",
        scheme="https",
        host="example.test",
        path="/canonical-target",
        query="",
    )
    db_session.add(target)
    db_session.flush()
    moment = datetime(2026, 9, 1, 12, tzinfo=UTC)
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
        created_at=moment,
        finished_at=moment,
    )
    db_session.add(scan)
    db_session.flush()

    def add_snapshot(path: str, **values) -> None:
        resource = resources[path]
        defaults = {
            "scan_id": scan.id,
            "resource_id": resource.id,
            "requested_url": resource.normalized_url,
            "final_url": resource.normalized_url,
            "http_status": 200,
            "crawl_depth": 0,
            "fetched_at": moment - timedelta(minutes=5),
            "fetch_state": "fetched",
            "page_title": "Fixture page",
            "representation_kind": "html_page",
            "parsed_head_json": {"links": []},
        }
        defaults.update(values)
        db_session.add(ResourceSnapshot(**defaults))

    add_snapshot("http-error", http_status=404)
    add_snapshot(
        "fetch-failure",
        final_url=None,
        http_status=None,
        fetch_state="failed",
        error_type="connection_timeout",
        error_message="Connection timed out",
        representation_kind=None,
        page_title=None,
        parsed_head_json=None,
    )
    add_snapshot("noindex", meta_robots="noindex")
    add_snapshot("missing-title", page_title="  ")
    add_snapshot("invalid-canonical", canonical_url="http://[invalid")
    add_snapshot(
        "multiple-canonicals",
        canonical_url="/two",
        parsed_head_json={
            "links": [
                {"rel": "canonical", "href": "/one"},
                {"rel": "alternate CANONICAL", "href": "/two"},
            ]
        },
    )
    add_snapshot("broken-canonical", canonical_url=target.normalized_url)
    db_session.add(
        ResourceSnapshot(
            scan_id=scan.id,
            resource_id=target.id,
            requested_url=target.normalized_url,
            final_url=target.normalized_url,
            http_status=500,
            crawl_depth=1,
            fetched_at=moment - timedelta(minutes=4),
            fetch_state="fetched",
            page_title="Broken target",
            representation_kind="html_page",
            parsed_head_json={"links": []},
        )
    )
    db_session.commit()

    with _findings_client(db_session) as client:
        queued = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert queued.status_code == 202
        evaluation_id = queued.json()["id"]
        claimed = background_jobs.claim_next_job(
            db_session, worker_id="manual-product-worker", lease_seconds=30
        )
        assert claimed is not None
        factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
        FindingEvaluationJobHandler(factory)._execute_blocking(
            claimed.job,
            evaluation_id,
            _job_context(factory, claimed.job, claimed.lease_token),
        )
        db_session.expire_all()
        response = client.get(f"/api/sites/{site.id}/findings?limit=100")
        assert response.status_code == 200
        visible_types = {item["finding_type"] for item in response.json()["items"]}
        assert visible_types == {
            "page_http_error",
            "page_static_fetch_failure",
            "page_noindex",
            "page_missing_title",
            "page_invalid_canonical",
            "page_multiple_canonicals",
            "page_canonical_target_http_error",
        }
        evaluation_payload = client.get(
            f"/api/sites/{site.id}/findings/evaluations/{evaluation_id}"
        ).json()
        assert (
            evaluation_payload["detected_count"],
            evaluation_payload["clear_count"],
            evaluation_payload["unknown_count"],
        ) == (7, 79, 12)
        assert len(evaluation_payload["detector_summary_json"]) == 14


def test_static_fetch_failure_clears_after_successful_fetch(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    start = datetime(2026, 9, 1, 9, tzinfo=UTC)
    _scan(
        db_session,
        site,
        resource,
        start,
        None,
        "failed",
        error_type="dns_error",
        error_message="Name resolution failed",
    )
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "page_static_fetch_failure")
    )
    assert finding is not None and finding.condition_state == "detected"
    _scan(db_session, site, resource, start + timedelta(hours=1), 200)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "resolved"


def test_head_evidence_detectors_share_snapshot_but_keep_distinct_lifecycles(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    start = datetime(2026, 9, 1, 9, tzinfo=UTC)
    _scan(
        db_session,
        site,
        resource,
        start,
        200,
        page_title=" ",
        canonical_url="http://[invalid",
        parsed_head_json={
            "links": [
                {"rel": "canonical", "href": "http://[invalid"},
                {"rel": "alternate canonical", "href": "/second"},
            ]
        },
    )
    _evaluate(db_session, site)
    finding_types = set(db_session.scalars(select(Finding.finding_type)))
    assert {
        "page_missing_title",
        "page_invalid_canonical",
        "page_multiple_canonicals",
    }.issubset(finding_types)

    _scan(
        db_session,
        site,
        resource,
        start + timedelta(hours=1),
        200,
        page_title="Restored title",
        canonical_url="/page",
        parsed_head_json={"links": [{"rel": "canonical", "href": "/page"}]},
    )
    _evaluate(db_session, site)
    states = dict(
        db_session.execute(
            select(Finding.finding_type, Finding.condition_state).where(
                Finding.finding_type.in_(
                    {
                        "page_missing_title",
                        "page_invalid_canonical",
                        "page_multiple_canonicals",
                    }
                )
            )
        ).all()
    )
    assert states == {
        "page_missing_title": "resolved",
        "page_invalid_canonical": "resolved",
        "page_multiple_canonicals": "resolved",
    }


def test_non_html_representation_clears_when_page_returns_html_again(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    start = datetime(2026, 9, 1, 9, tzinfo=UTC)
    _scan(
        db_session,
        site,
        resource,
        start,
        200,
        representation_kind="document",
    )
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "page_non_html_representation")
    )
    assert finding is not None and finding.condition_state == "detected"
    _scan(db_session, site, resource, start + timedelta(hours=1), 200)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "resolved"


def test_broken_internal_link_lifecycle_resolves_reopens_and_keeps_unknown(
    db_session,
) -> None:
    site, source, _page = _site_page(db_session)
    target = _resource(db_session, "/target")
    start = datetime(2026, 9, 2, 9, tzinfo=UTC)

    scan, source_snapshot = _scan(db_session, site, source, start, 200)
    _target_snapshot(db_session, scan, target, start, 404)
    _link(db_session, source_snapshot, target)
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "page_broken_internal_links")
    )
    assert finding is not None
    assert (finding.condition_state, finding.current_severity) == ("detected", "medium")

    scan, source_snapshot = _scan(db_session, site, source, start + timedelta(hours=1), 200)
    _target_snapshot(db_session, scan, target, start + timedelta(hours=1), 200)
    _link(db_session, source_snapshot, target)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "resolved"

    scan, source_snapshot = _scan(db_session, site, source, start + timedelta(hours=2), 200)
    _target_snapshot(db_session, scan, target, start + timedelta(hours=2), 500)
    _link(db_session, source_snapshot, target)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert (finding.condition_state, finding.current_severity) == ("detected", "high")
    assert finding.reopened_at is not None

    _scan_missing_target, missing_source = _scan(
        db_session, site, source, start + timedelta(hours=3), 200
    )
    _link(db_session, missing_source, target)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "unknown"
    assert finding.resolved_at < finding.reopened_at
    current = db_session.get(FindingAssessment, finding.current_assessment_id)
    assert current is not None and current.details_json["unknown_target_count"] == 1


def test_internal_redirect_link_resolves_when_target_becomes_direct(db_session) -> None:
    site, source, _page = _site_page(db_session)
    target = _resource(db_session, "/old")
    start = datetime(2026, 9, 2, 9, tzinfo=UTC)
    scan, source_snapshot = _scan(db_session, site, source, start, 200)
    _target_snapshot(
        db_session,
        scan,
        target,
        start,
        200,
        final_url="https://example.test/new",
        redirect_chain=[{"status_code": 301, "url": target.normalized_url}],
    )
    _link(db_session, source_snapshot, target)
    _evaluate(db_session, site)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "page_internal_links_to_redirects")
    )
    assert finding is not None and finding.condition_state == "detected"

    scan, source_snapshot = _scan(db_session, site, source, start + timedelta(hours=1), 200)
    _target_snapshot(db_session, scan, target, start + timedelta(hours=1), 200)
    _link(db_session, source_snapshot, target)
    _evaluate(db_session, site)
    db_session.refresh(finding)
    assert finding.condition_state == "resolved"


def test_job_completion_and_finding_lifecycle_share_one_transaction(
    db_session, monkeypatch
) -> None:
    site, resource, _page = _site_page(db_session)
    scan, source_snapshot = _scan(
        db_session,
        site,
        resource,
        datetime(2026, 8, 24, tzinfo=UTC),
        404,
        meta_robots="noindex",
    )
    target = _resource(db_session, "/broken")
    _target_snapshot(db_session, scan, target, datetime(2026, 8, 24, tzinfo=UTC), 404)
    _link(db_session, source_snapshot, target)
    evaluation, _ = create_evaluation(db_session, site.id)
    job = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    job.status = "running"
    job.lease_token = "owned-lease"
    job.lease_expires_at = datetime(2026, 8, 25, tzinfo=UTC)
    db_session.commit()

    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    context = JobExecutionContext(
        session_factory=factory,
        job_id=job.id,
        lease_token="owned-lease",
        lease_seconds=30,
    )
    handler = FindingEvaluationJobHandler(factory)
    real_complete = background_jobs.complete_job

    def fail_before_terminal_commit(*_args, **_kwargs):
        raise RuntimeError("forced terminal persistence failure")

    monkeypatch.setattr(background_jobs, "complete_job", fail_before_terminal_commit)
    with pytest.raises(RuntimeError, match="forced terminal"):
        handler._execute_blocking(job, evaluation.id, context)
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation.id).status == "queued"
    assert db_session.query(Finding).count() == 0
    assert db_session.query(FindingEvidenceReference).count() == 0
    assert db_session.get(BackgroundJob, job.id).status == "running"

    monkeypatch.setattr(background_jobs, "complete_job", real_complete)
    handler._execute_blocking(job, evaluation.id, context)
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation.id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert db_session.query(Finding).count() == 3
    assert db_session.query(FindingAssessment).count() == 3
    assert (
        db_session.query(FindingEvidenceReference)
        .filter(FindingEvidenceReference.evidence_kind == "resource_occurrence")
        .count()
        == 1
    )


def test_queued_job_cancellation_terminalizes_the_evaluation(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    evaluation, _ = create_evaluation(db_session, site.id)
    job = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    db_session.commit()
    background_jobs.request_cancellation(db_session, job)
    db_session.refresh(evaluation)
    assert job.status == "cancelled"
    assert evaluation.status == "cancelled"
    assert db_session.query(Finding).count() == 0


def test_expired_finding_job_rolls_back_then_recovers_and_explicitly_retries(
    db_session, monkeypatch
) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    evaluation, _ = create_evaluation(db_session, site.id)
    input_fingerprint = evaluation.input_fingerprint_sha256
    job = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    db_session.commit()
    claimed = background_jobs.claim_next_job(
        db_session, worker_id="finding-worker-dead", lease_seconds=30
    )
    assert claimed is not None and claimed.job.id == job.id

    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    handler = FindingEvaluationJobHandler(factory)
    real_complete = background_jobs.complete_job

    def fail_before_terminal_commit(*_args, **_kwargs):
        raise RuntimeError("simulated worker death before commit")

    monkeypatch.setattr(background_jobs, "complete_job", fail_before_terminal_commit)
    with pytest.raises(RuntimeError, match="simulated worker death"):
        handler._execute_blocking(
            claimed.job,
            evaluation.id,
            _job_context(factory, claimed.job, claimed.lease_token),
        )
    monkeypatch.setattr(background_jobs, "complete_job", real_complete)

    db_session.expire_all()
    persisted_job = db_session.get(BackgroundJob, job.id)
    persisted_evaluation = db_session.get(FindingEvaluation, evaluation.id)
    assert persisted_job is not None and persisted_job.status == "running"
    assert persisted_evaluation is not None and persisted_evaluation.status == "queued"
    assert db_session.query(Finding).count() == 0
    assert db_session.query(FindingAssessment).count() == 0
    assert db_session.query(FindingEvidenceReference).count() == 0

    persisted_job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert background_jobs.recover_expired_jobs(db_session) == 1
    db_session.refresh(persisted_job)
    db_session.refresh(persisted_evaluation)
    assert persisted_job.status == "interrupted"
    assert persisted_evaluation.status == "failed"
    assert persisted_evaluation.failed_at is not None
    assert persisted_evaluation.error_type == "lease_expired"
    assert persisted_evaluation.error_message == "Worker lease expired during Finding evaluation."
    assert db_session.query(Finding).count() == 0
    assert db_session.query(FindingAssessment).count() == 0
    assert db_session.query(FindingEvidenceReference).count() == 0

    with _findings_client(db_session) as client:
        retried = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert retried.status_code == 202
        assert retried.json()["id"] == evaluation.id
    db_session.expire_all()
    retried_job = db_session.get(BackgroundJob, job.id)
    retried_evaluation = db_session.get(FindingEvaluation, evaluation.id)
    assert retried_job is not None and retried_job.status == "queued"
    assert retried_evaluation is not None and retried_evaluation.status == "queued"
    assert retried_evaluation.input_fingerprint_sha256 == input_fingerprint
    assert (
        db_session.query(BackgroundJob)
        .filter(BackgroundJob.status.in_({"queued", "running"}))
        .count()
        == 1
    )

    retry_claim = background_jobs.claim_next_job(
        db_session, worker_id="finding-worker-retry", lease_seconds=30
    )
    assert retry_claim is not None and retry_claim.job.id == job.id
    handler._execute_blocking(
        retry_claim.job,
        evaluation.id,
        _job_context(factory, retry_claim.job, retry_claim.lease_token),
    )
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation.id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert db_session.query(Finding).count() == 1
    assert db_session.query(FindingAssessment).count() == 1
    finding_fingerprint = db_session.scalar(select(Finding.fingerprint_sha256))

    with _findings_client(db_session) as client:
        completed_duplicate = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert completed_duplicate.status_code == 202
        assert completed_duplicate.json()["id"] == evaluation.id
    db_session.expire_all()
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).attempt_count == 2
    assert db_session.query(Finding).count() == 1
    assert db_session.query(FindingAssessment).count() == 1
    assert db_session.scalar(select(Finding.fingerprint_sha256)) == finding_fingerprint
    event_types = list(
        db_session.scalars(
            select(background_jobs.JobEvent.event_type)
            .where(background_jobs.JobEvent.job_id == job.id)
            .order_by(background_jobs.JobEvent.id)
        )
    )
    assert event_types.count("claimed") == 2
    assert event_types.count("lease_expired") == 1
    assert event_types.count("manually_requeued") == 1


@pytest.mark.asyncio
async def test_failed_finding_job_can_be_explicitly_retried_and_completed(
    db_session, monkeypatch
) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    with _findings_client(db_session) as client:
        response = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert response.status_code == 202
        evaluation_id = response.json()["id"]
    job = db_session.scalar(
        select(BackgroundJob).where(BackgroundJob.job_type == JOB_TYPE_FINDING_EVALUATION)
    )
    assert job is not None
    claimed = background_jobs.claim_next_job(
        db_session, worker_id="finding-worker-failure", lease_seconds=30
    )
    assert claimed is not None
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    registry = JobHandlerRegistry(
        {JOB_TYPE_FINDING_EVALUATION: FindingEvaluationJobHandler(factory)}
    )

    def fail_evaluator(*_args, **_kwargs):
        raise RuntimeError("forced evaluator failure")

    monkeypatch.setattr("app.services.job_handlers.execute_evaluation", fail_evaluator)
    await run_claimed_job(
        session_factory=factory,
        registry=registry,
        claimed_job=claimed,
        lease_seconds=30,
    )
    monkeypatch.setattr("app.services.job_handlers.execute_evaluation", execute_evaluation)
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation_id).status == "failed"
    assert db_session.get(BackgroundJob, job.id).status == "failed"
    assert db_session.query(Finding).count() == 0
    assert db_session.query(FindingAssessment).count() == 0

    with _findings_client(db_session) as client:
        retried = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert retried.status_code == 202
        assert retried.json()["id"] == evaluation_id
    retry_claim = background_jobs.claim_next_job(
        db_session, worker_id="finding-worker-success", lease_seconds=30
    )
    assert retry_claim is not None and retry_claim.job.id == job.id
    await run_claimed_job(
        session_factory=factory,
        registry=registry,
        claimed_job=retry_claim,
        lease_seconds=30,
    )
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation_id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert db_session.query(Finding).count() == 1
    assert db_session.query(FindingAssessment).count() == 1

    with _findings_client(db_session) as client:
        duplicate = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert duplicate.status_code == 202
        assert duplicate.json()["id"] == evaluation_id
    db_session.expire_all()
    assert db_session.get(BackgroundJob, job.id).attempt_count == 2
    assert db_session.query(FindingAssessment).count() == 1


def test_cancelled_finding_evaluation_can_be_explicitly_retried(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
    with _findings_client(db_session) as client:
        response = client.post(f"/api/sites/{site.id}/findings/evaluations")
        evaluation_id = response.json()["id"]
    job = db_session.scalar(
        select(BackgroundJob).where(BackgroundJob.job_type == JOB_TYPE_FINDING_EVALUATION)
    )
    assert job is not None
    background_jobs.request_cancellation(db_session, job)
    assert job.status == "cancelled"
    assert db_session.get(FindingEvaluation, evaluation_id).status == "cancelled"

    with _findings_client(db_session) as client:
        retried = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert retried.status_code == 202
        assert retried.json()["id"] == evaluation_id
    db_session.expire_all()
    assert db_session.get(BackgroundJob, job.id).status == "queued"
    assert db_session.get(FindingEvaluation, evaluation_id).status == "queued"
    claimed = background_jobs.claim_next_job(
        db_session, worker_id="finding-worker-after-cancel", lease_seconds=30
    )
    assert claimed is not None and claimed.job.id == job.id
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    FindingEvaluationJobHandler(factory)._execute_blocking(
        claimed.job,
        evaluation_id,
        _job_context(factory, claimed.job, claimed.lease_token),
    )
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation_id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert db_session.query(Finding).count() == 1
    assert db_session.query(FindingAssessment).count() == 1


def test_evaluation_list_batches_background_job_lookup(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    scan, _snapshot = _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 200)
    evaluations = [
        FindingEvaluation(
            website_property_id=site.id,
            source_scan_id=scan.id,
            evaluator_version="finding-evaluator-v1",
            detector_bundle_identity="finding-detectors-v1",
            input_fingerprint_sha256=f"{index:064x}",
            evidence_horizon_at=scan.finished_at,
            active_page_count=1,
            active_page_universe_sha256=f"{index + 100:064x}",
            active_page_resource_ids_json=[resource.id],
            status="completed",
        )
        for index in range(100)
    ]
    db_session.add_all(evaluations)
    db_session.flush()
    for evaluation in evaluations:
        background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    db_session.commit()
    db_session.expire_all()

    selects = 0

    def count_selects(_connection, _cursor, statement, *_args) -> None:
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    event.listen(db_session.bind, "before_cursor_execute", count_selects)
    try:
        result = list_evaluations(db_session, site.id, 100, 0)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_selects)
    assert result is not None and len(result.items) == 100
    assert all(item.background_job_id is not None for item in result.items)
    assert selects <= 4
    print(f"finding evaluation list: evaluations=100 selects={selects}")


def test_finding_detail_batches_retained_evidence_resolution(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    start = datetime(2026, 8, 24, tzinfo=UTC)
    for index in range(25):
        _scan(
            db_session,
            site,
            resource,
            start + timedelta(hours=index),
            404 if index % 2 == 0 else 500,
        )
        _evaluate(db_session, site)
    finding = db_session.scalar(select(Finding))
    assert finding is not None
    site_id = site.id
    finding_id = finding.id
    db_session.expire_all()

    selects = 0

    def count_selects(_connection, _cursor, statement, *_args) -> None:
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    event.listen(db_session.bind, "before_cursor_execute", count_selects)
    try:
        detail = get_finding(db_session, site_id, finding_id)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_selects)
    assert detail is not None and len(detail.assessments) == 25
    assert sum(len(item.evidence_references) for item in detail.assessments) == 50
    assert all(
        reference.retained
        for assessment in detail.assessments
        for reference in assessment.evidence_references
    )
    assert selects <= 7
    print(f"finding detail: assessments=25 references=50 selects={selects}")


def test_individual_finding_delete_preserves_evaluation_job_siblings_and_evidence(
    db_session,
) -> None:
    site, resource, _page = _site_page(db_session)
    scan, snapshot = _scan(
        db_session,
        site,
        resource,
        datetime(2026, 9, 3, tzinfo=UTC),
        404,
        meta_robots="noindex",
    )
    evaluation, _result = _evaluate(db_session, site)
    job = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    job.status = "completed"
    job.finished_at = datetime.now(UTC)
    event_row = JobEvent(
        job_id=job.id,
        event_type="completed",
        level="info",
        message="Job completed.",
        data_json={},
    )
    db_session.add(event_row)
    db_session.commit()

    findings = list(db_session.scalars(select(Finding).order_by(Finding.id)))
    assert len(findings) >= 2
    selected, sibling = findings[:2]
    assert set_acknowledged(db_session, site.id, selected.id, True) is not None
    selected_assessment_ids = list(
        db_session.scalars(
            select(FindingAssessment.id).where(FindingAssessment.finding_id == selected.id)
        )
    )
    sibling_snapshot = (
        sibling.id,
        sibling.condition_state,
        sibling.current_assessment_id,
        sibling.fingerprint_sha256,
    )
    historical_counts = (
        evaluation.detected_count,
        evaluation.clear_count,
        evaluation.unknown_count,
        evaluation.assessment_count,
    )

    with _findings_client(db_session) as client:
        response = client.delete(f"/api/sites/{site.id}/findings/{selected.id}")
        assert response.status_code == 204
        duplicate = client.post(f"/api/sites/{site.id}/findings/evaluations")
        assert duplicate.status_code == 202
        assert duplicate.json()["id"] == evaluation.id

    db_session.expire_all()
    assert db_session.get(Finding, selected.id) is None
    assert not list(
        db_session.scalars(
            select(FindingAssessment).where(FindingAssessment.id.in_(selected_assessment_ids))
        )
    )
    assert not list(
        db_session.scalars(
            select(FindingEvidenceReference).where(
                FindingEvidenceReference.finding_assessment_id.in_(selected_assessment_ids)
            )
        )
    )
    retained_sibling = db_session.get(Finding, sibling.id)
    assert retained_sibling is not None
    assert (
        retained_sibling.id,
        retained_sibling.condition_state,
        retained_sibling.current_assessment_id,
        retained_sibling.fingerprint_sha256,
    ) == sibling_snapshot
    retained_evaluation = db_session.get(FindingEvaluation, evaluation.id)
    assert retained_evaluation is not None
    assert (
        retained_evaluation.detected_count,
        retained_evaluation.clear_count,
        retained_evaluation.unknown_count,
        retained_evaluation.assessment_count,
    ) == historical_counts
    assert db_session.get(BackgroundJob, job.id) is not None
    assert db_session.get(JobEvent, event_row.id) is not None
    assert db_session.get(Scan, scan.id) is not None
    assert db_session.get(ResourceSnapshot, snapshot.id) is not None


def test_site_reset_rebuilds_same_static_topology_and_recursive_sitemap_evidence(
    db_session,
) -> None:
    site, resource, _page = _site_page(db_session)
    moment = datetime(2026, 9, 3, 2, tzinfo=UTC)
    scan, source_snapshot = _scan(db_session, site, resource, moment, 404, meta_robots="noindex")
    target = _resource(db_session, "/broken")
    target_snapshot = _target_snapshot(db_session, scan, target, moment, 404)
    occurrence = _link(db_session, source_snapshot, target)[0]
    root = _sitemap_source(db_session, site, "Root", "index.xml", discovery_mode="configured")
    child = _sitemap_source(db_session, site, "Child", "child.xml")
    _child_source, leaf = _sitemap_refresh(
        db_session, site, resource, moment + timedelta(minutes=1), source=child
    )
    root_refresh = _sitemap_index_refresh(db_session, root, moment + timedelta(minutes=2), [leaf])
    evaluation, _result = _evaluate(db_session, site)
    job = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    job.status = "completed"
    job.finished_at = datetime.now(UTC)
    event_row = JobEvent(
        job_id=job.id,
        event_type="completed",
        level="info",
        message="Job completed.",
        data_json={},
    )
    db_session.add(event_row)
    scan_job = background_jobs.enqueue_scan_job(db_session, scan)
    scan_job.status = "completed"
    scan_job.finished_at = datetime.now(UTC)
    category_job = background_jobs.enqueue_category_rule_job(db_session, 999, site.id)
    category_job.status = "completed"
    category_job.finished_at = datetime.now(UTC)
    finding = db_session.scalar(
        select(Finding).where(Finding.finding_type == "sitemap_page_http_error")
    )
    assert finding is not None
    finding.acknowledged_at = datetime.now(UTC)
    db_session.commit()
    intelligence_before = get_site_intelligence(db_session, site.id)
    assert intelligence_before is not None
    assert intelligence_before.findings.detected > 0

    fingerprint = evaluation.input_fingerprint_sha256
    checksum = evaluation.evaluation_checksum_sha256
    finding_identities = set(
        db_session.execute(select(Finding.finding_type, Finding.fingerprint_sha256)).all()
    )
    detector_summary = evaluation.detector_summary_json
    manifest = evaluation.evidence_manifest_json
    evidence_ids = {
        "scan": scan.id,
        "source_snapshot": source_snapshot.id,
        "target_snapshot": target_snapshot.id,
        "occurrence": occurrence.id,
        "root_refresh": root_refresh.id,
        "leaf_refresh": leaf.id,
    }
    source_observation_ids = list(
        db_session.scalars(
            select(SourceEntryObservation.id).where(
                SourceEntryObservation.source_refresh_id == leaf.id
            )
        )
    )

    with _findings_client(db_session) as client:
        rejected = client.post(f"/api/sites/{site.id}/findings/reset", json={"confirm": False})
        assert rejected.status_code == 422
        response = client.post(f"/api/sites/{site.id}/findings/reset", json={"confirm": True})
        assert response.status_code == 200
        result = response.json()
        assert result["deleted_finding_count"] == len(finding_identities)
        assert result["deleted_assessment_count"] > 0
        assert result["deleted_evidence_reference_count"] > 0
        assert result["deleted_evaluation_count"] == 1
        assert result["deleted_job_count"] == 1
        assert result["deleted_job_event_count"] == 2

    db_session.expire_all()
    assert db_session.query(Finding).filter_by(website_property_id=site.id).count() == 0
    assert db_session.query(FindingEvaluation).filter_by(website_property_id=site.id).count() == 0
    assert db_session.get(BackgroundJob, job.id) is None
    assert db_session.get(JobEvent, event_row.id) is None
    assert db_session.get(BackgroundJob, scan_job.id) is not None
    assert db_session.get(BackgroundJob, category_job.id) is not None
    assert db_session.get(Scan, evidence_ids["scan"]) is not None
    assert db_session.get(ResourceSnapshot, evidence_ids["source_snapshot"]) is not None
    assert db_session.get(ResourceSnapshot, evidence_ids["target_snapshot"]) is not None
    assert db_session.get(ResourceOccurrence, evidence_ids["occurrence"]) is not None
    retained_root = db_session.get(SourceRefresh, evidence_ids["root_refresh"])
    assert retained_root is not None
    assert retained_root.child_refresh_ids_json == [evidence_ids["leaf_refresh"]]
    assert db_session.get(SourceRefresh, evidence_ids["leaf_refresh"]) is not None
    assert (
        list(
            db_session.scalars(
                select(SourceEntryObservation.id).where(
                    SourceEntryObservation.id.in_(source_observation_ids)
                )
            )
        )
        == source_observation_ids
    )
    intelligence_after = get_site_intelligence(db_session, site.id)
    assert intelligence_after is not None
    assert intelligence_after.findings.detected == 0
    assert intelligence_after.findings.unknown == 0
    assert intelligence_after.findings.latest_evaluation_id is None

    rebuilt, created = create_evaluation(db_session, site.id)
    assert created is True
    assert rebuilt.input_fingerprint_sha256 == fingerprint
    assert rebuilt.evidence_manifest_json == manifest
    assert rebuilt.evaluator_version == "finding-evaluator-v3"
    assert rebuilt.detector_bundle_identity == "finding-detectors-v5"
    execute_evaluation(db_session, rebuilt.id)
    db_session.commit()
    assert rebuilt.evaluation_checksum_sha256 == checksum
    assert rebuilt.detector_summary_json == detector_summary
    assert (
        set(db_session.execute(select(Finding.finding_type, Finding.fingerprint_sha256)).all())
        == finding_identities
    )


@pytest.mark.parametrize("evaluation_status", ["queued", "running"])
def test_finding_deletion_and_reset_block_active_evaluation_without_mutation(
    db_session, evaluation_status
) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 3, tzinfo=UTC), 404)
    evaluation, _result = _evaluate(db_session, site)
    finding = db_session.scalar(select(Finding))
    assert finding is not None
    evaluation.status = evaluation_status
    db_session.commit()
    counts = (
        db_session.query(Finding).count(),
        db_session.query(FindingAssessment).count(),
        db_session.query(FindingEvaluation).count(),
    )

    with _findings_client(db_session) as client:
        assert client.delete(f"/api/sites/{site.id}/findings/{finding.id}").status_code == 409
        assert (
            client.post(f"/api/sites/{site.id}/findings/reset", json={"confirm": True}).status_code
            == 409
        )
    assert (
        db_session.query(Finding).count(),
        db_session.query(FindingAssessment).count(),
        db_session.query(FindingEvaluation).count(),
    ) == counts


def test_site_reset_blocks_active_job_and_isolates_other_sites(db_session) -> None:
    site_a, resource_a, _page_a = _site_page(db_session)
    _scan(db_session, site_a, resource_a, datetime(2026, 9, 3, tzinfo=UTC), 404)
    evaluation_a, _result = _evaluate(db_session, site_a)
    finding_a = db_session.scalar(select(Finding).where(Finding.website_property_id == site_a.id))
    assert finding_a is not None

    site_b, resource_b, _page_b = _site_page(
        db_session, name="Finding fixture B", base_url="https://other.test/"
    )
    _scan(db_session, site_b, resource_b, datetime(2026, 9, 3, 1, tzinfo=UTC), 500)
    evaluation_b, _result = _evaluate(db_session, site_b)
    finding_b = db_session.scalar(select(Finding).where(Finding.website_property_id == site_b.id))
    assert finding_b is not None
    job_a = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation_a.id, site_a.id)
    db_session.commit()

    with _findings_client(db_session) as client:
        assert client.delete(f"/api/sites/{site_a.id}/findings/{finding_a.id}").status_code == 409
        assert (
            client.post(
                f"/api/sites/{site_a.id}/findings/reset", json={"confirm": True}
            ).status_code
            == 409
        )
        assert client.delete(f"/api/sites/{site_a.id}/findings/{finding_b.id}").status_code == 404
    assert db_session.get(Finding, finding_a.id) is not None

    job_a.status = "cancelled"
    evaluation_a.status = "cancelled"
    db_session.commit()
    with _findings_client(db_session) as client:
        assert (
            client.post(
                f"/api/sites/{site_a.id}/findings/reset", json={"confirm": True}
            ).status_code
            == 200
        )
        assert client.delete(f"/api/sites/999999/findings/{finding_b.id}").status_code == 404
    assert db_session.get(FindingEvaluation, evaluation_b.id) is not None
    assert db_session.get(Finding, finding_b.id) is not None
    assert db_session.get(Scan, evaluation_b.source_scan_id) is not None


def test_site_reset_is_atomic_when_the_caller_rolls_back(db_session) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 9, 3, tzinfo=UTC), 404)
    evaluation, _result = _evaluate(db_session, site)
    job = background_jobs.enqueue_finding_evaluation_job(db_session, evaluation.id, site.id)
    job.status = "completed"
    db_session.commit()
    finding_count = db_session.query(Finding).count()

    result = reset_site_findings(db_session, site.id)
    assert result is not None and result.deleted_finding_count == finding_count
    db_session.rollback()
    assert db_session.query(Finding).filter_by(website_property_id=site.id).count() == finding_count
    assert db_session.get(FindingEvaluation, evaluation.id) is not None
    assert db_session.get(BackgroundJob, job.id) is not None
