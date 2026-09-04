from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes import router
from app.database import get_db
from app.models import (
    ArtifactBlob,
    RenderedArtifact,
    RenderedConsoleMessage,
    RenderedNetworkEntry,
    RenderedObservation,
    RenderedPageError,
    RenderRun,
    RenderRunTarget,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.rendered_deletion import delete_render_run
from app.services.rendered_queries import list_scan_rendered_observations
from app.services.scan_render_authority import resolve_scan_render_authority, scan_reads
from app.storage.artifact_store import LocalArtifactStore


def test_no_render_has_explicit_none_authority(db_session) -> None:
    scan = _scan_snapshot(db_session)[0]
    db_session.commit()

    summary = resolve_scan_render_authority(db_session, scan)

    assert summary.authority == "none"
    assert summary.render_run_id is None
    assert summary.status is None
    assert summary.model_dump(include=_OUTCOME_FIELDS) == _zero_outcomes()


def test_legacy_scan_counters_and_observation_remain_authoritative(db_session) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session)
    scan.rendered_selected_count = 2
    scan.rendered_attempted_count = 2
    scan.rendered_completed_count = 1
    scan.rendered_failed_count = 1
    scan.rendered_blocked_request_count = 4
    scan.rendered_artifact_count = 3
    observation = _observation(resource, snapshot=snapshot)
    db_session.add(observation)
    db_session.flush()
    blob = ArtifactBlob(
        sha256="b" * 64,
        storage_key="bb/legacy.png",
        media_type="image/png",
        compression_type="none",
        raw_byte_size=6,
        stored_byte_size=6,
    )
    db_session.add(blob)
    db_session.flush()
    db_session.add_all(
        [
            RenderedArtifact(
                rendered_observation_id=observation.id,
                artifact_blob_id=blob.id,
                artifact_type="viewport_screenshot",
                metadata_json={},
            ),
            RenderedNetworkEntry(
                rendered_observation_id=observation.id,
                sequence=1,
                request_key="c" * 64,
                redacted_url=resource.normalized_url,
                url_sha256="d" * 64,
                method="GET",
            ),
            RenderedConsoleMessage(
                rendered_observation_id=observation.id,
                sequence=1,
                message_type="log",
                text="legacy console evidence",
            ),
            RenderedPageError(
                rendered_observation_id=observation.id,
                sequence=1,
                message="legacy page error evidence",
            ),
        ]
    )
    db_session.commit()

    summary = resolve_scan_render_authority(db_session, scan)
    rendered = list_scan_rendered_observations(db_session, scan.id)

    assert summary.authority == "legacy_scan"
    assert summary.legacy
    assert summary.render_run_id is None
    assert summary.attempted_count == 2
    assert summary.completed_count == 1
    assert summary.failed_count == 1
    assert summary.blocked_request_count == 4
    assert summary.artifact_count == 3
    assert summary.retained_observation_count == 1
    assert summary.retained_artifact_count == 1
    assert [item.id for item in rendered.items] == [observation.id]
    assert len(observation.artifacts) == 1
    assert len(observation.network_entries) == 1
    assert len(observation.console_messages) == 1
    assert len(observation.page_errors) == 1
    assert db_session.query(RenderRun).count() == 0


def test_modern_queued_run_reports_selected_targets_before_attempts(db_session) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session)
    scan.rendered_selected_count = 2
    run, _target = _scan_run(db_session, scan, snapshot, resource, target_count=2)
    second_resource = WebResource(
        resource_type="page",
        normalized_url="https://authority.example/queued-second",
        scheme="https",
        host="authority.example",
        path="/queued-second",
        query="",
    )
    db_session.add(second_resource)
    db_session.flush()
    db_session.add(
        RenderRunTarget(
            render_run_id=run.id,
            web_resource_id=second_resource.id,
            requested_url=second_resource.normalized_url,
            position=2,
        )
    )
    db_session.commit()

    summary = resolve_scan_render_authority(db_session, scan)

    assert summary.authority == "render_run"
    assert summary.render_run_id == run.id
    assert summary.status == "queued"
    assert summary.selected_count == summary.target_count == 2
    assert summary.attempted_count == 0
    assert summary.unattempted_target_count == 2


def test_deleted_modern_run_does_not_resurrect_scan_outcome_authority(db_session, tmp_path) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session, "deleted-run")
    site = WebsiteProperty(
        name="Deleted run",
        base_url="https://authority.example/",
        normalized_base_url="https://authority.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    scan.website_property_id = site.id
    scan.rendered_selected_count = 1
    run, _target = _scan_run(db_session, scan, snapshot, resource)
    run.website_property_id = site.id
    run.status = "completed"
    db_session.commit()

    result = delete_render_run(
        db_session,
        site.id,
        run.id,
        f"DELETE RENDER RUN {run.id}",
        LocalArtifactStore(tmp_path / "artifacts"),
    )
    db_session.refresh(scan)
    summary = resolve_scan_render_authority(db_session, scan)

    assert result is not None
    assert summary.authority == "none"
    assert summary.render_run_id is None
    assert summary.selected_count == 1
    assert summary.model_dump(include=_OUTCOME_FIELDS) == _zero_outcomes()


def test_modern_run_counters_win_over_conflicting_legacy_columns(db_session) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session)
    scan.rendered_selected_count = 10
    scan.rendered_attempted_count = 99
    scan.rendered_completed_count = 99
    scan.rendered_failed_count = 99
    scan.rendered_skipped_count = 99
    scan.rendered_blocked_request_count = 99
    scan.rendered_artifact_count = 99
    run, _target = _scan_run(db_session, scan, snapshot, resource, target_count=10)
    run.status = "completed_with_errors"
    run.attempted_count = 4
    run.completed_count = 3
    run.failed_count = 1
    run.skipped_count = 6
    run.blocked_request_count = 7
    run.artifact_count = 8
    run.started_at = datetime.now(UTC)
    run.finished_at = datetime.now(UTC)
    db_session.commit()

    summary = resolve_scan_render_authority(db_session, scan)

    assert summary.authority == "render_run"
    assert summary.status == "completed_with_errors"
    assert (
        summary.attempted_count,
        summary.completed_count,
        summary.failed_count,
        summary.skipped_count,
        summary.blocked_request_count,
        summary.artifact_count,
    ) == (4, 3, 1, 6, 7, 8)


@pytest.mark.parametrize(
    "run_status",
    ["running", "completed", "completed_with_errors", "failed", "cancelled", "interrupted"],
)
def test_modern_run_lifecycle_does_not_replace_scan_status(db_session, run_status: str) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session, run_status)
    run, _target = _scan_run(db_session, scan, snapshot, resource)
    run.status = run_status
    if run_status == "running":
        run.started_at = datetime.now(UTC)
    elif run_status != "queued":
        run.finished_at = datetime.now(UTC)
    db_session.commit()

    summary = resolve_scan_render_authority(db_session, scan)

    assert scan.status == "completed"
    assert summary.authority == "render_run"
    assert summary.status == run_status


def test_original_scan_run_is_deterministic_and_rerender_evidence_is_isolated(db_session) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session)
    site = WebsiteProperty(
        name="Authority",
        base_url="https://authority.example/",
        normalized_base_url="https://authority.example/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
    )
    db_session.add(site)
    db_session.flush()
    scan.website_property_id = site.id
    original, original_target = _scan_run(db_session, scan, snapshot, resource)
    original_observation = _observation(resource, snapshot=snapshot, target=original_target)
    db_session.add(original_observation)
    db_session.flush()
    duplicate, duplicate_target = _scan_run(db_session, scan, snapshot, resource)
    duplicate.status = "completed"
    duplicate_observation = _observation(resource, snapshot=snapshot, target=duplicate_target)
    db_session.add(duplicate_observation)
    db_session.flush()
    rerender = RenderRun(
        website_property_id=site.id,
        source_render_run_id=original.id,
        status="completed",
        trigger="rerender",
        configuration_json={},
        target_count=1,
        attempted_count=1,
        completed_count=1,
    )
    db_session.add(rerender)
    db_session.flush()
    rerender_target = RenderRunTarget(
        render_run_id=rerender.id,
        web_resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        requested_url=resource.normalized_url,
        position=1,
    )
    db_session.add(rerender_target)
    db_session.flush()
    rerender_observation = _observation(resource, snapshot=snapshot, target=rerender_target)
    db_session.add(rerender_observation)
    db_session.commit()

    summary = resolve_scan_render_authority(db_session, scan)
    rendered = list_scan_rendered_observations(db_session, scan.id)

    assert summary.render_run_id == original.id
    assert [item.id for item in rendered.items] == [original_observation.id]
    assert duplicate_observation.id not in {item.id for item in rendered.items}
    assert rerender_observation.id not in {item.id for item in rendered.items}


def test_scan_read_batch_uses_same_authority_for_history_and_lists(db_session) -> None:
    modern, snapshot, resource = _scan_snapshot(db_session, "modern")
    modern.rendered_selected_count = 1
    run, _target = _scan_run(db_session, modern, snapshot, resource)
    legacy, legacy_snapshot, legacy_resource = _scan_snapshot(db_session, "legacy")
    legacy.rendered_attempted_count = 1
    db_session.add(_observation(legacy_resource, snapshot=legacy_snapshot))
    db_session.commit()

    reads = {item.id: item for item in scan_reads(db_session, [modern, legacy])}

    assert reads[modern.id].render.authority == "render_run"
    assert reads[modern.id].render_run_id == run.id
    assert reads[legacy.id].render.authority == "legacy_scan"
    assert reads[legacy.id].render_run_id is None


def test_scan_detail_list_and_history_share_render_authority(db_session) -> None:
    scan, snapshot, resource = _scan_snapshot(db_session)
    scan.rendered_selected_count = 1
    run, _target = _scan_run(db_session, scan, snapshot, resource)
    run.status = "running"
    run.attempted_count = 1
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        detail = client.get(f"/api/scans/{scan.id}")
        scans = client.get("/api/scans")
        history = client.get("/api/scans/history")

    assert detail.status_code == scans.status_code == history.status_code == 200
    summaries = [
        detail.json()["render"],
        scans.json()[0]["render"],
        history.json()["items"][0]["render"],
    ]
    assert all(item["authority"] == "render_run" for item in summaries)
    assert all(item["render_run_id"] == run.id for item in summaries)
    assert all(item["attempted_count"] == 1 for item in summaries)


_OUTCOME_FIELDS = {
    "target_count",
    "attempted_count",
    "completed_count",
    "failed_count",
    "skipped_count",
    "blocked_request_count",
    "artifact_count",
}


def _zero_outcomes() -> dict[str, int]:
    return {field: 0 for field in _OUTCOME_FIELDS}


def _scan_snapshot(db, suffix: str = "page") -> tuple[Scan, ResourceSnapshot, WebResource]:
    resource = WebResource(
        resource_type="page",
        normalized_url=f"https://authority.example/{suffix}",
        scheme="https",
        host="authority.example",
        path=f"/{suffix}",
        query="",
    )
    scan = Scan(
        starting_url=resource.normalized_url,
        status="completed",
        scope_config={"render_mode": "all_eligible"},
    )
    db.add_all([resource, scan])
    db.flush()
    snapshot = ResourceSnapshot(
        scan_id=scan.id,
        resource_id=resource.id,
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        http_status=200,
        content_type="text/html",
        crawl_depth=0,
        fetched_at=datetime.now(UTC),
        fetch_state="fetched",
    )
    db.add(snapshot)
    db.flush()
    return scan, snapshot, resource


def _scan_run(
    db,
    scan: Scan,
    snapshot: ResourceSnapshot,
    resource: WebResource,
    *,
    target_count: int = 1,
) -> tuple[RenderRun, RenderRunTarget]:
    run = RenderRun(
        source_scan_id=scan.id,
        status="queued",
        trigger="scan",
        configuration_json={},
        target_count=target_count,
    )
    db.add(run)
    db.flush()
    target = RenderRunTarget(
        render_run_id=run.id,
        web_resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        requested_url=resource.normalized_url,
        position=1,
    )
    db.add(target)
    db.flush()
    return run, target


def _observation(
    resource: WebResource,
    *,
    snapshot: ResourceSnapshot,
    target: RenderRunTarget | None = None,
) -> RenderedObservation:
    return RenderedObservation(
        render_run_id=target.render_run_id if target else None,
        render_run_target_id=target.id if target else None,
        web_resource_id=resource.id if target else None,
        snapshot_id=snapshot.id,
        capture_state="completed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        requested_url=resource.normalized_url,
        final_url=resource.normalized_url,
        navigation_http_status=200,
        browser_engine="chromium",
        renderer_version="2" if target else "1",
        browser_policy_version="2" if target else "1",
        capture_schema_version="2" if target else "1",
        viewport_width=1440,
        viewport_height=900,
        device_scale_factor=1.0,
        locale="en-US",
        timezone_id="UTC",
        color_scheme="light",
        reduced_motion="reduce",
        configuration_fingerprint="a" * 64,
    )
