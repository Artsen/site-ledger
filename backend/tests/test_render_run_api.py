from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.render_routes import router
from app.database import get_db
from app.models import (
    RenderedObservation,
    RenderRun,
    RenderRunTarget,
    SitePage,
    WebResource,
    WebsiteProperty,
)


def _client(db_session):
    factory = sessionmaker(bind=db_session.bind, autoflush=False, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), factory


def _site_with_pages(db_session, count: int = 2):
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        group_key="Other",
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={"allowed_host_patterns": ["example.com"]},
    )
    db_session.add(site)
    db_session.flush()
    resources = []
    for index in range(count):
        resource = WebResource(
            resource_type="page",
            normalized_url=f"https://example.com/{index}",
            scheme="https",
            host="example.com",
            path=f"/{index}",
            query="",
        )
        db_session.add(resource)
        db_session.flush()
        db_session.add(SitePage(website_property_id=site.id, resource_id=resource.id))
        resources.append(resource)
    db_session.commit()
    return site, resources


def _completed_observation(target: RenderRunTarget) -> RenderedObservation:
    return RenderedObservation(
        render_run_id=target.render_run_id,
        render_run_target_id=target.id,
        web_resource_id=target.web_resource_id,
        capture_state="completed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        requested_url=target.requested_url,
        final_url=target.requested_url,
        navigation_http_status=200,
        browser_engine="chromium",
        renderer_version="2",
        browser_policy_version="2",
        capture_schema_version="2",
        viewport_width=1440,
        viewport_height=900,
        device_scale_factor=1,
        locale="en-US",
        timezone_id="UTC",
        color_scheme="light",
        reduced_motion="reduce",
        configuration_fingerprint="a" * 64,
    )


def test_manual_run_api_freezes_targets_and_queues_job(db_session) -> None:
    site, resources = _site_with_pages(db_session)
    client, factory = _client(db_session)
    with client:
        response = client.post(
            f"/api/sites/{site.id}/render-runs",
            json={"resource_ids": [item.id for item in resources]},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["presentation_status"] == "queued"
    assert body["target_count"] == 2
    assert body["source_scan_id"] is None
    with factory() as db:
        run = db.get(RenderRun, body["id"])
        assert run is not None
        assert [target.requested_url for target in run.targets] == [
            item.normalized_url for item in resources
        ]
        assert run.jobs[0].job_type == "render_run"


def test_manual_run_rejects_suppressed_page(db_session) -> None:
    site, resources = _site_with_pages(db_session, count=1)
    page = db_session.query(SitePage).filter_by(resource_id=resources[0].id).one()
    page.workspace_state = "suppressed"
    db_session.commit()
    client, _factory = _client(db_session)

    with client:
        response = client.post(
            f"/api/sites/{site.id}/render-runs",
            json={"resource_ids": [resources[0].id]},
        )

    assert response.status_code == 422
    assert "suppressed" in response.json()["detail"]


def test_run_detail_history_and_rerender_create_new_immutable_evidence(db_session) -> None:
    site, resources = _site_with_pages(db_session)
    client, factory = _client(db_session)
    with client:
        created = client.post(
            f"/api/sites/{site.id}/render-runs", json={"resource_ids": [resources[0].id]}
        ).json()
    with factory() as db:
        run = db.get(RenderRun, created["id"])
        assert run is not None
        target = run.targets[0]
        observation = _completed_observation(target)
        observation.warning_count = 2
        db.add(observation)
        run.status = "completed"
        run.completed_count = 1
        run.attempted_count = 1
        db.commit()
        observation_id = observation.id
        target_id = target.id

    with client:
        detail = client.get(f"/api/sites/{site.id}/render-runs/{created['id']}")
        history = client.get(f"/api/sites/{site.id}/pages/{resources[0].id}/rendered-observations")
        filtered = client.get(
            f"/api/sites/{site.id}/render-runs/{created['id']}/observations",
            params={
                "has_warnings": "true",
                "has_page_errors": "false",
                "has_viewport_screenshot": "false",
                "outcome": ["successful", "rate_limited"],
            },
        )
        excluded = client.get(
            f"/api/sites/{site.id}/pages/{resources[0].id}/rendered-observations",
            params={"has_warnings": "false", "outcome": "rate_limited"},
        )
        rerender = client.post(
            f"/api/sites/{site.id}/render-runs/{created['id']}/rerender",
            json={"target_ids": [target_id]},
        )
    assert detail.status_code == 200
    assert detail.json()["observations"]["items"][0]["id"] == observation_id
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == observation_id
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert excluded.status_code == 200
    assert excluded.json()["total"] == 0
    assert rerender.status_code == 202
    assert rerender.json()["id"] != created["id"]
    assert rerender.json()["source_render_run_id"] == created["id"]
    with factory() as db:
        assert db.get(RenderedObservation, observation_id).navigation_http_status == 200
