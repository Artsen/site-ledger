from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.api.findings_routes import router as findings_router
from app.database import get_db
from app.models import (
    BackgroundJob,
    Finding,
    FindingAssessment,
    FindingEvaluation,
    FindingEvidenceReference,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services import background_jobs
from app.services.finding_evaluations import (
    FindingEvaluationChronologyError,
    create_evaluation,
    execute_evaluation,
)
from app.services.findings import get_finding, list_findings, set_acknowledged
from app.services.job_handlers import FindingEvaluationJobHandler, JobExecutionContext


def _site_page(db):
    site = WebsiteProperty(
        name="Finding fixture",
        base_url="https://example.test/",
        normalized_base_url="https://example.test/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.test/page",
        scheme="https",
        host="example.test",
        path="/page",
        query="",
    )
    db.add_all([site, resource])
    db.flush()
    page = SitePage(website_property_id=site.id, resource_id=resource.id)
    db.add(page)
    db.flush()
    return site, resource, page


def _scan(db, site, resource, moment, status, fetch_state="fetched"):
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
        execute_evaluation(db_session, evaluation_id)
        db_session.commit()

        listing = client.get(f"/api/sites/{site.id}/findings").json()
        assert listing["total"] == 1
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


def test_job_completion_and_finding_lifecycle_share_one_transaction(
    db_session, monkeypatch
) -> None:
    site, resource, _page = _site_page(db_session)
    _scan(db_session, site, resource, datetime(2026, 8, 24, tzinfo=UTC), 404)
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
    assert db_session.get(BackgroundJob, job.id).status == "running"

    monkeypatch.setattr(background_jobs, "complete_job", real_complete)
    handler._execute_blocking(job, evaluation.id, context)
    db_session.expire_all()
    assert db_session.get(FindingEvaluation, evaluation.id).status == "completed"
    assert db_session.get(BackgroundJob, job.id).status == "completed"
    assert db_session.query(Finding).count() == 1
    assert db_session.query(FindingAssessment).count() == 1


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
