from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import BackgroundJob, Scan, SourceRefresh
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.schemas.sources import UrlSourceCreate
from app.services.background_jobs import (
    StaleLeaseError,
    claim_next_job,
    enqueue_scan_job,
    enqueue_source_refresh_job,
    heartbeat_job,
    recover_expired_jobs,
    register_worker,
    request_cancellation,
    worker_health,
)
from app.services.site_management import create_site
from app.services.source_management import create_source
from app.services.source_refresh import create_source_refresh


def test_scan_enqueue_dedupes_and_claims_deterministically(db_session: Session) -> None:
    low_priority = _scan(db_session, "https://example.com/low")
    high_priority = _scan(db_session, "https://example.com/high")
    first_job = enqueue_scan_job(db_session, low_priority, priority=100)
    duplicate = enqueue_scan_job(db_session, low_priority, priority=100)
    second_job = enqueue_scan_job(db_session, high_priority, priority=10)
    db_session.commit()

    assert duplicate.id == first_job.id

    claimed = claim_next_job(db_session, worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    assert claimed.job.id == second_job.id
    assert claimed.job.attempt_count == 1
    assert claimed.lease_token


def test_two_sessions_cannot_claim_same_job(db_session: Session) -> None:
    scan = _scan(db_session, "https://example.com/")
    enqueue_scan_job(db_session, scan)
    db_session.commit()
    SessionLocal = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)

    with SessionLocal() as first, SessionLocal() as second:
        first_claim = claim_next_job(first, worker_id="worker-a", lease_seconds=30)
        second_claim = claim_next_job(second, worker_id="worker-b", lease_seconds=30)

    assert first_claim is not None
    assert second_claim is None


def test_stale_lease_cannot_heartbeat(db_session: Session) -> None:
    scan = _scan(db_session, "https://example.com/")
    enqueue_scan_job(db_session, scan)
    db_session.commit()
    claimed = claim_next_job(db_session, worker_id="worker-a", lease_seconds=30)
    assert claimed is not None

    with pytest.raises(StaleLeaseError):
        heartbeat_job(
            db_session,
            job_id=claimed.job.id,
            lease_token="stale-token",
            lease_seconds=30,
        )


def test_worker_health_and_expired_scan_recovery(db_session: Session) -> None:
    scan = _scan(db_session, "https://example.com/")
    enqueue_scan_job(db_session, scan)
    register_worker(db_session, worker_id="worker-a", concurrency=2)
    health = worker_health(db_session, offline_threshold_seconds=60)
    assert health.online_workers == 1
    assert health.total_concurrency == 2

    claimed = claim_next_job(db_session, worker_id="worker-a", lease_seconds=1)
    assert claimed is not None
    job = db_session.get(BackgroundJob, claimed.job.id)
    assert job is not None
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    scan.status = "running"
    db_session.commit()

    assert recover_expired_jobs(db_session) == 1
    db_session.refresh(job)
    db_session.refresh(scan)
    assert job.status == "interrupted"
    assert scan.status == "interrupted"


def test_queued_cancellation_is_durable(db_session: Session) -> None:
    scan = _scan(db_session, "https://example.com/")
    job = enqueue_scan_job(db_session, scan)
    db_session.commit()

    request_cancellation(db_session, job)
    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.cancellation_requested_at is not None
    assert job.cancelled_at is not None


def test_source_refresh_enqueue(db_session: Session) -> None:
    site = create_site(
        db_session,
        WebsitePropertyCreate(
            name="Example",
            base_url="https://example.com/",
            scope_config=ScopeConfigPayload(),
        ),
    )
    source = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Sitemap", source_url="https://example.com/sitemap.xml"),
    )
    assert source is not None
    refresh = create_source_refresh(db_session, site.id, source.id)
    assert refresh is not None
    job = enqueue_source_refresh_job(db_session, refresh)
    db_session.commit()

    assert job.source_refresh_id == refresh.id
    assert db_session.get(SourceRefresh, refresh.id).status == "queued"


def _scan(db: Session, starting_url: str) -> Scan:
    scan = Scan(
        starting_url=starting_url,
        status="queued",
        scope_config=ScopeConfigPayload().model_dump(),
    )
    db.add(scan)
    db.flush()
    return scan
