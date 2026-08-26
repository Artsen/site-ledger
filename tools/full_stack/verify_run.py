from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from app.database import SessionLocal
from app.models import (
    BackgroundJob,
    ContentBlob,
    HtmlStructuredContentArtifact,
    ResourceSnapshot,
    Scan,
    ScanComparison,
    ScanComparisonBuild,
    ScanComparisonPageResult,
    ScanProjectionBuild,
    ScanSeedOrigin,
    SiteInventorySuppression,
    SitePage,
    UrlSourceEntry,
    WebResource,
    WebsiteProperty,
)
from app.schemas.scans import ScopeConfigPayload
from app.services.scan_projections import CURRENT_SCAN_PROJECTION_ALGORITHM


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify persisted Golden Path invariants.")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--request-log", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    manifest = verify(result, args.request_log)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, sort_keys=True), flush=True)


def verify(result: dict[str, Any], request_log: Path) -> dict[str, Any]:
    assert ScopeConfigPayload().allow_private_networks is False
    scan_ids = [int(result["scan_1_id"]), int(result["scan_2_id"])]
    comparison_id = int(result["comparison_id"])
    with SessionLocal() as db:
        scans = [db.get(Scan, scan_id) for scan_id in scan_ids]
        assert all(scan is not None and scan.status == "completed" for scan in scans)
        assert all(
            scan is not None and scan.scope_config["allow_private_networks"] for scan in scans
        )
        site = db.get(WebsiteProperty, int(result["site_id"]))
        assert site is not None and site.scope_config["allow_private_networks"] is True
        scan_jobs = list(
            db.scalars(
                select(BackgroundJob).where(
                    BackgroundJob.scan_id.in_(scan_ids),
                    BackgroundJob.job_type == "scan",
                )
            )
        )
        assert len(scan_jobs) == 2
        assert all(job.status == "completed" and job.worker_id for job in scan_jobs)
        projections = list(
            db.scalars(
                select(ScanProjectionBuild).where(
                    ScanProjectionBuild.scan_id.in_(scan_ids),
                    ScanProjectionBuild.status == "ready",
                )
            )
        )
        assert len(projections) == 2
        assert all(build.projection_version == "scan-projection-v1" for build in projections)
        assert all(
            build.algorithm_identity == CURRENT_SCAN_PROJECTION_ALGORITHM for build in projections
        )
        comparison = db.get(ScanComparison, comparison_id)
        assert comparison is not None and comparison.current_build_id is not None
        build = db.get(ScanComparisonBuild, comparison.current_build_id)
        assert (
            build is not None and build.status == "ready" and build.coverage_state == "comparable"
        )
        page_rows = list(
            db.scalars(
                select(ScanComparisonPageResult).where(
                    ScanComparisonPageResult.comparison_build_id == build.id
                )
            )
        )
        classes = Counter(row.primary_change_class for row in page_rows)
        expected_classes = {
            "substantive_change": 1,
            "metadata_change": 1,
            "technical_change": 1,
            "no_tracked_change": 1,
            "not_applicable": 1,
        }
        assert dict(classes) == expected_classes
        by_path = {row.path: row for row in page_rows}
        assert by_path["/"].document_content_state == "changed"
        assert by_path["/pricing/"].document_content_state == "same"
        assert by_path["/pricing/"].metadata_state == "changed"
        assert by_path["/technical/"].document_content_state == "same"
        assert by_path["/technical/"].technical_state == "changed"
        assert by_path["/unchanged/"].primary_change_class == "no_tracked_change"
        assert by_path["/new/"].presence_state == "newly_observed"

        observations = _observations_by_path(db, scan_ids)
        unchanged = observations["/unchanged/"]
        technical = observations["/technical/"]
        root = observations["/"]
        pricing = observations["/pricing/"]
        assert unchanged[0].html_blob_id == unchanged[1].html_blob_id
        assert unchanged[0].raw_html_sha256 == unchanged[1].raw_html_sha256
        assert technical[0].raw_html_sha256 != technical[1].raw_html_sha256
        assert root[0].raw_html_sha256 != root[1].raw_html_sha256
        assert pricing[0].raw_html_sha256 != pricing[1].raw_html_sha256
        artifact_ids = {
            path: [_artifact_id(db, snapshot) for snapshot in snapshots]
            for path, snapshots in observations.items()
            if len(snapshots) == 2
        }
        assert artifact_ids["/unchanged/"][0] == artifact_ids["/unchanged/"][1]
        assert _artifact_hashes(db, technical[0]) == _artifact_hashes(db, technical[1])
        root_hashes = [_artifact_hashes(db, item) for item in root]
        assert root_hashes[0][0] != root_hashes[1][0]
        assert root_hashes[0][1] == root_hashes[1][1]
        assert _artifact_hashes(db, pricing[0]) == _artifact_hashes(db, pricing[1])
        active_site_pages = db.scalar(
            select(func.count(SitePage.id)).where(
                SitePage.website_property_id == site.id,
                SitePage.workspace_state == "active",
            )
        )
        inventory_suppressions = db.scalar(
            select(func.count(SiteInventorySuppression.id)).where(
                SiteInventorySuppression.website_property_id == site.id
            )
        )
        current_source_entries = db.scalar(
            select(func.count(UrlSourceEntry.id))
            .join(UrlSourceEntry.url_source)
            .where(
                UrlSourceEntry.is_current.is_(True),
                UrlSourceEntry.url_source.has(website_property_id=site.id),
            )
        )
        snapshot_count = db.scalar(
            select(func.count(ResourceSnapshot.id)).where(ResourceSnapshot.scan_id.in_(scan_ids))
        )
        assert active_site_pages == 5
        assert inventory_suppressions == 0
        assert current_source_entries == 1
        assert snapshot_count == 9

        lifecycle_scan_id = int(result["lifecycle_scan_id"])
        lifecycle_scan = db.get(Scan, lifecycle_scan_id)
        assert lifecycle_scan is not None and lifecycle_scan.status in {
            "completed",
            "completed_with_errors",
        }
        lifecycle_projection = db.scalar(
            select(ScanProjectionBuild).where(
                ScanProjectionBuild.scan_id == lifecycle_scan_id,
                ScanProjectionBuild.status == "ready",
            )
        )
        assert lifecycle_projection is not None
        assert lifecycle_projection.algorithm_identity == CURRENT_SCAN_PROJECTION_ALGORITHM
        resource_id = int(result["lifecycle_page_resource_id"])
        assert db.get(SitePage, int(result["lifecycle_deleted_site_page_id"])) is None
        recreated_page = db.scalar(
            select(SitePage).where(
                SitePage.website_property_id == site.id,
                SitePage.resource_id == resource_id,
            )
        )
        assert recreated_page is not None
        assert recreated_page.owner_label is None
        assert recreated_page.workflow_status == "unreviewed"
        inventory_entry_id = int(result["lifecycle_inventory_entry_id"])
        inventory_entry = db.get(UrlSourceEntry, inventory_entry_id)
        assert inventory_entry is not None and inventory_entry.is_current
        seed_origins = list(
            db.scalars(
                select(ScanSeedOrigin).where(
                    ScanSeedOrigin.scan_seed.has(scan_id=lifecycle_scan_id),
                    ScanSeedOrigin.url_source_entry_id == inventory_entry_id,
                )
            )
        )
        assert seed_origins

        active_jobs = db.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.status.in_({"queued", "running"})
            )
        )
        assert active_jobs == 0
        all_jobs = list(db.scalars(select(BackgroundJob)))
        assert all_jobs
        assert all(job.status == "completed" for job in all_jobs)
        duplicate_artifacts = db.execute(
            select(
                HtmlStructuredContentArtifact.content_blob_id,
                HtmlStructuredContentArtifact.extractor_version,
                HtmlStructuredContentArtifact.extractor_config_version,
                func.count(HtmlStructuredContentArtifact.id),
            )
            .group_by(
                HtmlStructuredContentArtifact.content_blob_id,
                HtmlStructuredContentArtifact.extractor_version,
                HtmlStructuredContentArtifact.extractor_config_version,
            )
            .having(func.count(HtmlStructuredContentArtifact.id) > 1)
        ).all()
        assert duplicate_artifacts == []
        duplicate_site_pages = db.execute(
            select(SitePage.website_property_id, SitePage.resource_id, func.count(SitePage.id))
            .group_by(SitePage.website_property_id, SitePage.resource_id)
            .having(func.count(SitePage.id) > 1)
        ).all()
        assert duplicate_site_pages == []
        duplicate_current_source_entries = db.execute(
            select(
                UrlSourceEntry.url_source_id,
                func.coalesce(UrlSourceEntry.normalized_url, UrlSourceEntry.raw_url),
                func.count(UrlSourceEntry.id),
            )
            .where(UrlSourceEntry.is_current.is_(True))
            .group_by(
                UrlSourceEntry.url_source_id,
                func.coalesce(UrlSourceEntry.normalized_url, UrlSourceEntry.raw_url),
            )
            .having(func.count(UrlSourceEntry.id) > 1)
        ).all()
        assert duplicate_current_source_entries == []
        foreign_key_violations = db.execute(text("PRAGMA foreign_key_check")).all()
        assert foreign_key_violations == []
        blob_count = db.scalar(select(func.count(ContentBlob.id))) or 0

    requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
    crawler_requests = [
        entry for entry in requests if entry["user_agent"] == "SiteLedgerGoldenPath/1.0"
    ]
    allowed_paths = {
        "/",
        "/pricing/",
        "/technical/",
        "/unchanged/",
        "/new/",
        "/inventory-only/",
        "/sitemap.xml",
    }
    assert crawler_requests
    assert {entry["path"] for entry in crawler_requests} <= allowed_paths
    assert {entry["version"] for entry in crawler_requests} == {1, 2}
    return {
        **result,
        "active_job_count": active_jobs,
        "background_job_types": dict(Counter(job.job_type for job in all_jobs)),
        "background_job_statuses": dict(Counter(job.status for job in all_jobs)),
        "comparison_classes": expected_classes,
        "content_blob_count": blob_count,
        "crawler_request_count": len(crawler_requests),
        "crawler_request_paths": sorted({entry["path"] for entry in crawler_requests}),
        "duplicate_artifact_identity_count": 0,
        "duplicate_current_source_identity_count": 0,
        "duplicate_site_page_identity_count": 0,
        "foreign_key_violation_count": 0,
        "lifecycle_active_site_page_count": active_site_pages,
        "lifecycle_current_source_entry_count": current_source_entries,
        "lifecycle_inventory_suppression_count": inventory_suppressions,
        "lifecycle_preserved_snapshot_count": snapshot_count,
        "lifecycle_inventory_entry_id": inventory_entry_id,
        "lifecycle_seed_origin_count": len(seed_origins),
        "lifecycle_scan_id": lifecycle_scan_id,
        "projection_algorithm_identities": [build.algorithm_identity for build in projections],
        "projection_versions": [build.projection_version for build in projections],
        "structured_artifact_ids": artifact_ids,
        "structured_artifact_hashes": {
            path: [_artifact_hashes(db, snapshot) for snapshot in snapshots]
            for path, snapshots in observations.items()
            if len(snapshots) == 2
        },
        "scan_job_statuses": [job.status for job in scan_jobs],
    }


def _observations_by_path(db: Any, scan_ids: list[int]) -> dict[str, list[ResourceSnapshot]]:
    rows = db.execute(
        select(ResourceSnapshot, WebResource.path)
        .join(WebResource, WebResource.id == ResourceSnapshot.resource_id)
        .where(ResourceSnapshot.scan_id.in_(scan_ids))
        .order_by(WebResource.path, ResourceSnapshot.scan_id)
    ).all()
    result: dict[str, list[ResourceSnapshot]] = {}
    for snapshot, path in rows:
        result.setdefault(path, []).append(snapshot)
    return result


def _artifact_id(db: Any, snapshot: ResourceSnapshot) -> int:
    artifact = db.scalar(
        select(HtmlStructuredContentArtifact).where(
            HtmlStructuredContentArtifact.content_blob_id == snapshot.html_blob_id,
            HtmlStructuredContentArtifact.extractor_version == "structured-content-v1",
            HtmlStructuredContentArtifact.extractor_config_version == "default-v1",
        )
    )
    assert artifact is not None and artifact.extraction_state == "ready"
    return artifact.id


def _artifact_hashes(db: Any, snapshot: ResourceSnapshot) -> tuple[str, str]:
    artifact = db.get(HtmlStructuredContentArtifact, _artifact_id(db, snapshot))
    assert artifact is not None
    return artifact.document_text_sha256, artifact.outline_sha256


if __name__ == "__main__":
    main()
