from datetime import UTC, datetime

import pytest

from app.models import (
    ArtifactBlob,
    BackgroundJob,
    JobEvent,
    RenderedArtifact,
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.services.rendered_deletion import (
    ACTIVE_RENDER_DELETE_REASON,
    delete_render_run,
    delete_rendered_observations,
    delete_run_target_evidence,
    preview_render_run_deletion,
    preview_run_target_deletion,
    purge_scan_rendered_evidence,
    purge_site_rendered_evidence,
)
from app.services.rendered_queries import list_render_run_targets
from app.storage.artifact_store import LocalArtifactStore


def _resource(db_session, suffix: str) -> tuple[WebsiteProperty, WebResource]:
    site = WebsiteProperty(
        name="Deletion fixture",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={"allowed_host_patterns": ["example.com"]},
    )
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://example.com/{suffix}",
        scheme="https",
        host="example.com",
        path=f"/{suffix}",
        query="",
    )
    db_session.add_all([site, resource])
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
    db_session.flush()
    return site, resource


def _target(db_session, site, resource, position: int = 1, run=None):
    if run is None:
        run = RenderRun(
            website_property_id=site.id,
            status="completed",
            trigger="site_workspace",
            configuration_json={},
            target_count=1,
            attempted_count=1,
            completed_count=1,
            artifact_count=1,
        )
        db_session.add(run)
        db_session.flush()
    target = RenderRunTarget(
        render_run_id=run.id,
        web_resource_id=resource.id,
        requested_url=resource.normalized_url,
        position=position,
    )
    db_session.add(target)
    db_session.flush()
    return run, target


def _observation(target, *, status=200):
    return RenderedObservation(
        render_run_id=target.render_run_id,
        render_run_target_id=target.id,
        web_resource_id=target.web_resource_id,
        capture_state="completed" if status == 200 else "failed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        requested_url=target.requested_url,
        navigation_http_status=status,
        browser_engine="chromium",
        renderer_version="2",
        browser_policy_version="2",
        capture_schema_version="2",
        viewport_width=1440,
        viewport_height=900,
        device_scale_factor=1.0,
        locale="en-US",
        timezone_id="UTC",
        color_scheme="light",
        reduced_motion="reduce",
        configuration_fingerprint="a" * 64,
    )


def test_shared_artifact_blob_survives_until_last_observation_is_deleted(
    db_session, tmp_path
) -> None:
    site, first_resource = _resource(db_session, "first")
    second_resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/second",
        scheme="https",
        host="example.com",
        path="/second",
        query="",
    )
    db_session.add(second_resource)
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=second_resource.id))
    first_run, first_target = _target(db_session, site, first_resource)
    second_run, second_target = _target(db_session, site, second_resource)
    first = _observation(first_target)
    second = _observation(second_target)
    db_session.add_all([first, second])
    db_session.flush()
    store = LocalArtifactStore(tmp_path / "artifacts")
    blob = store.put(db_session, b"shared screenshot", "image/png")
    db_session.add_all(
        [
            RenderedArtifact(
                rendered_observation_id=first.id,
                artifact_blob_id=blob.id,
                artifact_type="viewport_screenshot",
                metadata_json={},
            ),
            RenderedArtifact(
                rendered_observation_id=second.id,
                artifact_blob_id=blob.id,
                artifact_type="viewport_screenshot",
                metadata_json={},
            ),
        ]
    )
    db_session.commit()
    blob_id, path = blob.id, store.path_for(blob)

    first_result = delete_rendered_observations(db_session, [first.id], artifact_store=store)
    assert first_result.artifact_blob_records_deleted == 0
    assert first_result.shared_artifact_blobs_retained == 1
    assert db_session.get(ArtifactBlob, blob_id) is not None
    assert path.exists()

    second_result = delete_rendered_observations(db_session, [second.id], artifact_store=store)
    assert second_result.artifact_blob_records_deleted == 1
    assert second_result.artifact_blob_files_deleted == 1
    assert db_session.get(ArtifactBlob, blob_id) is None
    assert not path.exists()
    assert db_session.get(RenderRun, first_run.id) is not None
    assert db_session.get(RenderRun, second_run.id) is not None


def test_deleted_evidence_and_never_attempted_targets_remain_distinct(db_session, tmp_path) -> None:
    site, first_resource = _resource(db_session, "observed")
    second_resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/unattempted",
        scheme="https",
        host="example.com",
        path="/unattempted",
        query="",
    )
    db_session.add(second_resource)
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=second_resource.id))
    run, observed = _target(db_session, site, first_resource)
    run.target_count = 2
    _run, unattempted = _target(db_session, site, second_resource, position=2, run=run)
    observation = _observation(observed)
    db_session.add(observation)
    db_session.commit()

    delete_rendered_observations(
        db_session, [observation.id], artifact_store=LocalArtifactStore(tmp_path / "artifacts")
    )
    result = list_render_run_targets(db_session, run.id)
    states = {item.target_id: item.presentation_state for item in result.items}
    assert states[observed.id] == "evidence_deleted"
    assert states[unattempted.id] == "not_attempted"
    assert db_session.get(RenderRunTarget, observed.id).evidence_deleted_at is not None
    assert db_session.get(RenderRunTarget, unattempted.id).evidence_deleted_at is None
    retained_run = db_session.get(RenderRun, run.id)
    assert retained_run is not None
    assert (
        retained_run.attempted_count,
        retained_run.completed_count,
        retained_run.artifact_count,
    ) == (
        1,
        1,
        1,
    )


def test_legacy_429_observation_deletion_preserves_static_evidence(db_session, tmp_path) -> None:
    _site, resource = _resource(db_session, "legacy")
    scan = Scan(starting_url=resource.normalized_url, status="completed", scope_config={})
    db_session.add(scan)
    db_session.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.flush()
    legacy = _observation(
        RenderRunTarget(
            id=0,
            render_run_id=0,
            web_resource_id=resource.id,
            requested_url=resource.normalized_url,
            position=1,
        ),
        status=429,
    )
    legacy.render_run_id = None
    legacy.render_run_target_id = None
    legacy.web_resource_id = None
    legacy.snapshot_id = snapshot.id
    db_session.add(legacy)
    db_session.flush()
    store = LocalArtifactStore(tmp_path / "artifacts")
    blobs = [store.put(db_session, value, "image/png") for value in (b"a", b"b", b"c")]
    for artifact_type, blob in zip(
        ("viewport_screenshot", "full_page_screenshot", "rendered_dom"), blobs, strict=True
    ):
        db_session.add(
            RenderedArtifact(
                rendered_observation_id=legacy.id,
                artifact_blob_id=blob.id,
                artifact_type=artifact_type,
                metadata_json={},
            )
        )
    db_session.commit()
    scan_id, snapshot_id, resource_id, observation_id = (
        scan.id,
        snapshot.id,
        resource.id,
        legacy.id,
    )

    result = delete_rendered_observations(db_session, [observation_id], artifact_store=store)

    assert result.observations_deleted == 1
    assert result.artifact_rows_deleted == 3
    assert result.artifact_blob_records_deleted == 3
    assert db_session.get(RenderedObservation, observation_id) is None
    assert db_session.get(Scan, scan_id) is not None
    assert db_session.get(ResourceSnapshot, snapshot_id) is not None
    assert db_session.get(WebResource, resource_id) is not None
    assert db_session.query(RenderRunTarget).count() == 0


def test_active_render_run_blocks_observation_and_run_deletion(db_session, tmp_path) -> None:
    site, resource = _resource(db_session, "active")
    run, target = _target(db_session, site, resource)
    run.status = "running"
    observation = _observation(target)
    db_session.add(observation)
    db_session.add(
        BackgroundJob(
            job_type="render_run",
            status="running",
            render_run_id=run.id,
            dedupe_key=f"render_run:{run.id}",
            payload_json={},
        )
    )
    db_session.commit()
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(RuntimeError, match="Finish or cancel"):
        delete_rendered_observations(db_session, [observation.id], artifact_store=store)
    preview = preview_render_run_deletion(db_session, site.id, run.id)
    assert preview is not None and not preview.can_delete
    with pytest.raises(RuntimeError, match="Finish or cancel"):
        delete_render_run(
            db_session,
            site.id,
            run.id,
            f"DELETE RENDER RUN {run.id}",
            store,
        )


def test_active_run_blocks_no_evidence_target_deletion_until_terminal(db_session, tmp_path) -> None:
    site, first_resource = _resource(db_session, "active-unattempted")
    second_resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/active-deleted",
        scheme="https",
        host="example.com",
        path="/active-deleted",
        query="",
    )
    db_session.add(second_resource)
    db_session.flush()
    db_session.add(SitePage(website_property_id=site.id, resource_id=second_resource.id))
    run, unattempted = _target(db_session, site, first_resource)
    run.status = "running"
    run.target_count = 2
    _run, deleted = _target(db_session, site, second_resource, position=2, run=run)
    deleted.evidence_deleted_at = datetime.now(UTC)
    job = BackgroundJob(
        job_type="render_run",
        status="running",
        render_run_id=run.id,
        dedupe_key=f"render_run:{run.id}",
        payload_json={},
    )
    db_session.add(job)
    db_session.commit()
    store = LocalArtifactStore(tmp_path / "artifacts")

    for target_ids in ([unattempted.id], [deleted.id], [unattempted.id, deleted.id]):
        preview = preview_run_target_deletion(db_session, site.id, run.id, target_ids)
        assert preview is not None
        assert not preview.can_delete
        assert preview.reason == ACTIVE_RENDER_DELETE_REASON

    for target_id in (unattempted.id, deleted.id):
        with pytest.raises(RuntimeError, match="Finish or cancel"):
            delete_run_target_evidence(db_session, site.id, run.id, [target_id], store)
    assert db_session.get(RenderRunTarget, unattempted.id).evidence_deleted_at is None
    assert db_session.get(RenderRunTarget, deleted.id).evidence_deleted_at is not None

    run.status = "completed"
    job.status = "completed"
    db_session.commit()
    preview = preview_run_target_deletion(db_session, site.id, run.id, [unattempted.id, deleted.id])
    assert preview is not None and preview.can_delete
    result = delete_run_target_evidence(
        db_session, site.id, run.id, [unattempted.id, deleted.id], store
    )
    assert result is not None
    assert result.observations_deleted == 0
    assert result.targets_already_without_evidence == 2


def test_run_deletion_removes_job_history_and_detaches_rerender_child(db_session, tmp_path) -> None:
    site, resource = _resource(db_session, "parent")
    parent, target = _target(db_session, site, resource)
    observation = _observation(target)
    db_session.add(observation)
    db_session.flush()
    child = RenderRun(
        website_property_id=site.id,
        source_render_run_id=parent.id,
        status="completed",
        trigger="rerender",
        configuration_json={},
        target_count=1,
    )
    db_session.add(child)
    db_session.flush()
    job = BackgroundJob(
        job_type="render_run",
        status="completed",
        render_run_id=parent.id,
        dedupe_key=f"render_run:{parent.id}",
        payload_json={},
    )
    db_session.add(job)
    db_session.flush()
    event = JobEvent(job_id=job.id, event_type="completed", message="Done", data_json={})
    db_session.add(event)
    db_session.commit()
    parent_id, target_id, observation_id, job_id, event_id, child_id = (
        parent.id,
        target.id,
        observation.id,
        job.id,
        event.id,
        child.id,
    )

    result = delete_render_run(
        db_session,
        site.id,
        parent_id,
        f"DELETE RENDER RUN {parent_id}",
        LocalArtifactStore(tmp_path / "artifacts"),
    )
    db_session.expire_all()

    assert result is not None
    assert result.background_jobs_deleted == 1
    assert result.job_events_deleted == 1
    assert result.child_rerender_links_detached == 1
    assert db_session.get(RenderRun, parent_id) is None
    assert db_session.get(RenderRunTarget, target_id) is None
    assert db_session.get(RenderedObservation, observation_id) is None
    assert db_session.get(BackgroundJob, job_id) is None
    assert db_session.get(JobEvent, event_id) is None
    assert db_session.get(RenderRun, child_id).source_render_run_id is None
    assert db_session.get(WebResource, resource.id) is not None


def test_run_deletion_succeeds_after_its_last_observation_was_deleted(db_session, tmp_path) -> None:
    site, resource = _resource(db_session, "empty-run")
    run, target = _target(db_session, site, resource)
    observation = _observation(target)
    db_session.add(observation)
    db_session.commit()
    store = LocalArtifactStore(tmp_path / "artifacts")
    run_id = run.id

    delete_rendered_observations(db_session, [observation.id], artifact_store=store)
    preview = preview_render_run_deletion(db_session, site.id, run_id)

    assert preview is not None
    assert preview.observations == 0
    assert preview.deleted_targets == 1
    assert preview.can_delete
    result = delete_render_run(
        db_session,
        site.id,
        run_id,
        f"DELETE RENDER RUN {run_id}",
        store,
    )

    assert result is not None
    assert result.runs_deleted == 1
    assert db_session.get(RenderRun, run_id) is None


def test_site_purge_includes_legacy_evidence_and_preserves_static_site_data(
    db_session, tmp_path
) -> None:
    site, resource = _resource(db_session, "site-purge")
    run, target = _target(db_session, site, resource)
    run_observation = _observation(target)
    db_session.add(run_observation)
    scan = Scan(
        website_property_id=site.id,
        starting_url=resource.normalized_url,
        status="completed",
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        fetch_state="fetched",
    )
    db_session.add(snapshot)
    db_session.flush()
    legacy = _observation(target)
    legacy.render_run_id = None
    legacy.render_run_target_id = None
    legacy.web_resource_id = None
    legacy.snapshot_id = snapshot.id
    db_session.add(legacy)
    db_session.commit()
    ids = site.id, resource.id, scan.id, snapshot.id, run.id

    result = purge_site_rendered_evidence(
        db_session,
        site.id,
        "DELETE RENDERED EVIDENCE",
        LocalArtifactStore(tmp_path / "artifacts"),
    )
    db_session.expire_all()

    assert result is not None
    assert result.runs_deleted == 1
    assert result.observations_deleted == 2
    assert db_session.get(WebsiteProperty, ids[0]) is not None
    assert db_session.get(WebResource, ids[1]) is not None
    assert db_session.get(Scan, ids[2]) is not None
    assert db_session.get(ResourceSnapshot, ids[3]) is not None
    assert db_session.get(RenderRun, ids[4]) is None


def test_scan_purge_deletes_site_less_run_but_preserves_site_owned_run(
    db_session, tmp_path
) -> None:
    site, resource = _resource(db_session, "scan-ownership")
    scan = Scan(
        website_property_id=site.id,
        starting_url=resource.normalized_url,
        status="completed",
        scope_config={},
    )
    db_session.add(scan)
    db_session.flush()
    site_run, site_target = _target(db_session, site, resource)
    site_run.source_scan_id = scan.id
    db_session.add(_observation(site_target))
    ad_hoc_run = RenderRun(
        website_property_id=None,
        source_scan_id=scan.id,
        status="completed",
        trigger="scan",
        configuration_json={},
        target_count=1,
    )
    db_session.add(ad_hoc_run)
    db_session.flush()
    ad_hoc_target = RenderRunTarget(
        render_run_id=ad_hoc_run.id,
        web_resource_id=resource.id,
        requested_url=resource.normalized_url,
        position=1,
    )
    db_session.add(ad_hoc_target)
    db_session.flush()
    db_session.add(_observation(ad_hoc_target))
    db_session.commit()
    scan_id, site_run_id, ad_hoc_run_id = scan.id, site_run.id, ad_hoc_run.id

    result = purge_scan_rendered_evidence(
        db_session,
        scan.id,
        f"DELETE SCAN RENDERS {scan.id}",
        LocalArtifactStore(tmp_path / "artifacts"),
    )
    db_session.expire_all()

    assert result is not None and result.runs_deleted == 1
    assert db_session.get(Scan, scan_id) is not None
    assert db_session.get(RenderRun, ad_hoc_run_id) is None
    assert db_session.get(RenderRun, site_run_id) is not None


def test_missing_artifact_file_returns_warning_after_committed_deletion(
    db_session, tmp_path
) -> None:
    site, resource = _resource(db_session, "missing-file")
    _run, target = _target(db_session, site, resource)
    observation = _observation(target)
    db_session.add(observation)
    db_session.flush()
    store = LocalArtifactStore(tmp_path / "artifacts")
    blob = store.put(db_session, b"missing", "image/png")
    db_session.add(
        RenderedArtifact(
            rendered_observation_id=observation.id,
            artifact_blob_id=blob.id,
            artifact_type="viewport_screenshot",
            metadata_json={},
        )
    )
    db_session.commit()
    store.path_for(blob).unlink()

    result = delete_rendered_observations(db_session, [observation.id], artifact_store=store)

    assert result.observations_deleted == 1
    assert result.artifact_blob_records_deleted == 1
    assert result.artifact_blob_files_deleted == 0
    assert result.warnings == [f"Rendered artifact file was already missing: {blob.storage_key}"]


def test_database_failure_does_not_delete_artifact_file(db_session, tmp_path, monkeypatch) -> None:
    site, resource = _resource(db_session, "rollback")
    _run, target = _target(db_session, site, resource)
    observation = _observation(target)
    db_session.add(observation)
    db_session.flush()
    store = LocalArtifactStore(tmp_path / "artifacts")
    blob = store.put(db_session, b"rollback", "image/png")
    db_session.add(
        RenderedArtifact(
            rendered_observation_id=observation.id,
            artifact_blob_id=blob.id,
            artifact_type="viewport_screenshot",
            metadata_json={},
        )
    )
    db_session.commit()
    path = store.path_for(blob)

    def fail_commit() -> None:
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced database failure"):
        delete_rendered_observations(db_session, [observation.id], artifact_store=store)
    db_session.rollback()

    assert path.exists()
    assert db_session.get(ArtifactBlob, blob.id) is not None
    assert db_session.get(RenderedArtifact, 1) is not None
