from datetime import UTC, datetime

import pytest

from app.models import (
    AccessibilityRun,
    PerformanceRun,
    RenderRun,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    SourceRefresh,
    UrlSource,
    WebsiteProperty,
)
from app.services import background_jobs
from app.services.native_cancellation import request_native_cancellation

NATIVE_KINDS = (
    "scan",
    "source_refresh",
    "performance",
    "accessibility",
    "render",
    "comparison",
)


@pytest.mark.parametrize("kind", NATIVE_KINDS)
def test_queued_native_cancellation_commits_job_and_domain_together(db_session, kind) -> None:
    job, domain = _queued_native_fixture(db_session, kind)

    request_native_cancellation(db_session, job, "Test cancellation requested.")

    assert job.status == "cancelled"
    assert domain.status == "cancelled"
    if kind == "comparison":
        assert domain.failed_at is not None
    else:
        assert domain.finished_at == job.finished_at
    if kind == "scan":
        assert domain.stop_reason == "cancelled_by_user"
    if kind == "source_refresh":
        assert domain.error_type == "cancelled"
        assert domain.url_source.last_refresh_status == "cancelled"
        assert domain.url_source.last_refresh_finished_at == job.finished_at
        assert domain.url_source.last_error_type == "cancelled"
    if kind == "comparison":
        assert domain.active_key is None
        assert domain.error_type == "cancelled"


@pytest.mark.parametrize("kind", NATIVE_KINDS)
def test_queued_native_cancellation_rolls_back_both_sides_before_commit(
    db_session, monkeypatch, kind
) -> None:
    job, domain = _queued_native_fixture(db_session, kind)
    job_id, domain_type, domain_id = job.id, type(domain), domain.id

    def fail_commit() -> None:
        assert job.status == "cancelled"
        assert domain.status == "cancelled"
        raise RuntimeError("simulated crash before cancellation commit")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated crash"):
        request_native_cancellation(db_session, job)
    db_session.rollback()

    persisted_job = db_session.get(type(job), job_id)
    persisted_domain = db_session.get(domain_type, domain_id)
    assert persisted_job is not None and persisted_job.status == "queued"
    assert persisted_domain is not None and persisted_domain.status == "queued"


@pytest.mark.parametrize("kind", NATIVE_KINDS)
def test_running_native_cancellation_remains_cooperative(db_session, kind) -> None:
    job, domain = _queued_native_fixture(db_session, kind)
    job.status = "running"
    domain.status = "running" if kind != "comparison" else "building"
    db_session.commit()

    request_native_cancellation(db_session, job)

    assert job.status == "running"
    assert job.cancellation_requested_at is not None
    assert domain.status == ("building" if kind == "comparison" else "running")
    assert domain.finished_at is None


def _queued_native_fixture(db, kind: str):
    site = WebsiteProperty(
        name=f"Cancellation {kind}",
        base_url=f"https://{kind.replace('_', '-')}.example/",
        normalized_base_url=f"https://{kind.replace('_', '-')}.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db.add(site)
    db.flush()
    if kind == "scan":
        domain = Scan(
            website_property_id=site.id,
            starting_url=site.base_url,
            status="queued",
            scope_config={},
        )
        db.add(domain)
        db.flush()
        job = background_jobs.enqueue_scan_job(db, domain)
    elif kind == "source_refresh":
        source = UrlSource(
            website_property_id=site.id,
            source_type="sitemap",
            name="Sitemap",
            source_url=f"{site.base_url}sitemap.xml",
            normalized_source_url=f"{site.base_url}sitemap.xml",
            discovery_mode="include",
            settings_json={},
            last_refresh_status="queued",
        )
        db.add(source)
        db.flush()
        domain = SourceRefresh(
            url_source_id=source.id,
            status="queued",
            started_at=datetime.now(UTC),
            warnings_json=[],
        )
        db.add(domain)
        db.flush()
        job = background_jobs.enqueue_source_refresh_job(db, domain)
    elif kind == "performance":
        domain = PerformanceRun(
            website_property_id=site.id,
            status="queued",
            trigger="site_workspace",
            configuration_json={},
            target_count=0,
            request_count=0,
        )
        db.add(domain)
        db.flush()
        job = background_jobs.enqueue_performance_run_job(db, domain.id, site.id)
    elif kind == "accessibility":
        domain = AccessibilityRun(
            website_property_id=site.id,
            status="queued",
            trigger="site_workspace",
            configuration_json={},
            target_count=0,
            observation_count=0,
            axe_core_version="test",
            detector_bundle_sha256="0" * 64,
            integration_version="test",
            normalization_version="test",
            ruleset_profile="test",
            ruleset_rule_count=0,
            ruleset_sha256="1" * 64,
        )
        db.add(domain)
        db.flush()
        job = background_jobs.enqueue_accessibility_run_job(db, domain.id, site.id)
    elif kind == "render":
        domain = RenderRun(
            website_property_id=site.id,
            status="queued",
            trigger="site_workspace",
            configuration_json={},
            target_count=0,
        )
        db.add(domain)
        db.flush()
        job = background_jobs.enqueue_render_run_job(db, domain)
    else:
        baseline = Scan(starting_url=site.base_url, status="completed", scope_config={})
        target = Scan(starting_url=f"{site.base_url}target", status="completed", scope_config={})
        db.add_all([baseline, target])
        db.flush()
        comparison = ScanComparison(
            website_property_id=site.id,
            baseline_scan_id=baseline.id,
            target_scan_id=target.id,
        )
        db.add(comparison)
        db.flush()
        domain = ScanComparisonBuild(
            scan_comparison_id=comparison.id,
            comparison_version="test",
            algorithm_identity="test",
            status="queued",
            active_key=f"test:{comparison.id}",
            warnings_json=[],
            validation_json={},
        )
        db.add(domain)
        db.flush()
        job = background_jobs.enqueue_scan_comparison_job(db, domain.id, comparison.id, site.id)
    db.commit()
    return job, domain
