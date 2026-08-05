from dataclasses import dataclass

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    ContentBlob,
    HtmlParseArtifact,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    ScanSeed,
    ScanSeedOrigin,
    SitePage,
    UrlSourceEntry,
    WebResource,
)
from app.schemas.scans import ScanDeletePreview, ScanDeleteResult
from app.storage.content_store import LocalContentStore

TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}
ACTIVE_JOB_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class DeletionImpact:
    scan: Scan
    snapshots: int
    link_occurrences: int
    resource_ids: list[int]
    referenced_blobs: list[ContentBlob]
    deletable_blobs: list[ContentBlob]
    shared_blob_count: int

    @property
    def raw_bytes(self) -> int:
        return sum(blob.raw_byte_size for blob in self.deletable_blobs)

    @property
    def stored_bytes(self) -> int:
        return sum(blob.stored_byte_size for blob in self.deletable_blobs)


def preview_scan_deletion(db: Session, scan_id: int) -> ScanDeletePreview | None:
    scan = db.get(Scan, scan_id)
    if scan is None:
        return None
    if scan.status not in TERMINAL_STATUSES:
        return ScanDeletePreview(
            scan_id=scan.id,
            starting_url=scan.starting_url,
            can_delete=False,
            status=scan.status,
            snapshots=0,
            link_occurrences=0,
            unique_resources=0,
            html_blobs_referenced=0,
            exclusive_html_blobs=0,
            shared_html_blobs=0,
            html_blobs_deleted=0,
            raw_html_bytes_reclaimable=0,
            stored_html_bytes_reclaimable=0,
            reason="The scan must finish or be cancelled before it can be deleted.",
        )
    if _has_active_scan_job(db, scan.id):
        return ScanDeletePreview(
            scan_id=scan.id,
            starting_url=scan.starting_url,
            can_delete=False,
            status=scan.status,
            snapshots=0,
            link_occurrences=0,
            unique_resources=0,
            html_blobs_referenced=0,
            exclusive_html_blobs=0,
            shared_html_blobs=0,
            html_blobs_deleted=0,
            raw_html_bytes_reclaimable=0,
            stored_html_bytes_reclaimable=0,
            reason="The scan still has an active background job.",
        )
    impact = _deletion_impact(db, scan)
    return ScanDeletePreview(
        scan_id=scan.id,
        starting_url=scan.starting_url,
        can_delete=True,
        status=scan.status,
        snapshots=impact.snapshots,
        link_occurrences=impact.link_occurrences,
        unique_resources=len(impact.resource_ids),
        html_blobs_referenced=len(impact.referenced_blobs),
        exclusive_html_blobs=len(impact.deletable_blobs),
        shared_html_blobs=impact.shared_blob_count,
        html_blobs_deleted=len(impact.deletable_blobs),
        raw_html_bytes_reclaimable=impact.raw_bytes,
        stored_html_bytes_reclaimable=impact.stored_bytes,
    )


def delete_scan(db: Session, scan_id: int, store: LocalContentStore) -> ScanDeleteResult | None:
    scan = db.get(Scan, scan_id)
    if scan is None:
        return None
    if scan.status not in TERMINAL_STATUSES:
        raise ValueError("The scan must finish or be cancelled before it can be deleted.")
    if _has_active_scan_job(db, scan.id):
        raise ValueError("The scan still has an active background job.")
    impact = _deletion_impact(db, scan)
    deleted_blob_ids = [blob.id for blob in impact.deletable_blobs]
    candidate_resource_ids = impact.resource_ids
    snapshot_ids = select(ResourceSnapshot.id).where(ResourceSnapshot.scan_id == scan.id)
    db.execute(
        delete(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id.in_(snapshot_ids))
    )
    db.execute(delete(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan.id))
    _delete_unreferenced_artifacts(db)
    seed_ids = select(ScanSeed.id).where(ScanSeed.scan_id == scan.id)
    db.execute(delete(ScanSeedOrigin).where(ScanSeedOrigin.scan_seed_id.in_(seed_ids)))
    db.execute(delete(ScanSeed).where(ScanSeed.scan_id == scan.id))
    db.execute(delete(Scan).where(Scan.id == scan.id))
    if deleted_blob_ids:
        db.execute(delete(ContentBlob).where(ContentBlob.id.in_(deleted_blob_ids)))
    deleted_resource_ids = _delete_unreferenced_resources(db, candidate_resource_ids)
    db.commit()
    warnings: list[str] = []
    files_deleted = 0
    for blob in impact.deletable_blobs:
        try:
            if store.delete(blob):
                files_deleted += 1
            else:
                warnings.append(f"HTML blob file was already missing: {blob.storage_key}")
        except OSError as exc:
            warnings.append(f"Could not delete HTML blob file {blob.storage_key}: {exc}")
    return ScanDeleteResult(
        deleted_scan_id=scan_id,
        snapshots_deleted=impact.snapshots,
        link_occurrences_deleted=impact.link_occurrences,
        resources_deleted=len(deleted_resource_ids),
        html_blob_records_deleted=len(impact.deletable_blobs),
        html_blob_files_deleted=files_deleted,
        html_blobs_deleted=len(impact.deletable_blobs),
        raw_html_bytes_reclaimed=impact.raw_bytes,
        stored_html_bytes_reclaimed=impact.stored_bytes,
        warnings=warnings,
    )


def _deletion_impact(db: Session, scan: Scan) -> DeletionImpact:
    snapshot_ids = select(ResourceSnapshot.id).where(ResourceSnapshot.scan_id == scan.id)
    snapshots = (
        db.scalar(
            select(func.count(ResourceSnapshot.id)).where(ResourceSnapshot.scan_id == scan.id)
        )
        or 0
    )
    link_occurrences = (
        db.scalar(
            select(func.count(ResourceOccurrence.id)).where(
                ResourceOccurrence.source_snapshot_id.in_(snapshot_ids)
            )
        )
        or 0
    )
    referenced_blob_ids = list(
        db.scalars(
            select(distinct(ResourceSnapshot.html_blob_id)).where(
                ResourceSnapshot.scan_id == scan.id,
                ResourceSnapshot.html_blob_id.is_not(None),
            )
        )
    )
    snapshot_resource_ids = [
        resource_id
        for resource_id in db.scalars(
            select(distinct(ResourceSnapshot.resource_id)).where(
                ResourceSnapshot.scan_id == scan.id
            )
        )
        if resource_id is not None
    ]
    seed_resource_ids = [
        resource_id
        for resource_id in db.scalars(
            select(distinct(ScanSeed.resource_id)).where(
                ScanSeed.scan_id == scan.id,
                ScanSeed.resource_id.is_not(None),
            )
        )
        if resource_id is not None
    ]
    resource_ids = sorted(set(snapshot_resource_ids + seed_resource_ids))
    referenced_blobs = (
        list(db.scalars(select(ContentBlob).where(ContentBlob.id.in_(referenced_blob_ids))))
        if referenced_blob_ids
        else []
    )
    outside_blob_references = (
        {
            blob_id: count
            for blob_id, count in db.execute(
                select(ResourceSnapshot.html_blob_id, func.count(ResourceSnapshot.id))
                .where(
                    ResourceSnapshot.html_blob_id.in_(referenced_blob_ids),
                    ResourceSnapshot.scan_id != scan.id,
                )
                .group_by(ResourceSnapshot.html_blob_id)
            )
            if blob_id is not None
        }
        if referenced_blob_ids
        else {}
    )
    deletable_blobs = [
        blob for blob in referenced_blobs if outside_blob_references.get(blob.id, 0) == 0
    ]
    return DeletionImpact(
        scan=scan,
        snapshots=snapshots,
        link_occurrences=link_occurrences,
        resource_ids=resource_ids,
        referenced_blobs=referenced_blobs,
        deletable_blobs=deletable_blobs,
        shared_blob_count=len(referenced_blobs) - len(deletable_blobs),
    )


def _has_active_scan_job(db: Session, scan_id: int) -> bool:
    return (
        db.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.scan_id == scan_id,
                BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    ) > 0


def _delete_unreferenced_resources(db: Session, candidate_resource_ids: list[int]) -> list[int]:
    if not candidate_resource_ids:
        return []
    still_snapshotted = set(
        db.scalars(
            select(distinct(ResourceSnapshot.resource_id)).where(
                ResourceSnapshot.resource_id.in_(candidate_resource_ids)
            )
        )
    )
    still_targeted = set(
        db.scalars(
            select(distinct(ResourceOccurrence.target_resource_id)).where(
                ResourceOccurrence.target_resource_id.in_(candidate_resource_ids)
            )
        )
    )
    still_source_entry = set(
        db.scalars(
            select(distinct(UrlSourceEntry.resource_id)).where(
                UrlSourceEntry.resource_id.in_(candidate_resource_ids)
            )
        )
    )
    still_seeded = set(
        db.scalars(
            select(distinct(ScanSeed.resource_id)).where(
                ScanSeed.resource_id.in_(candidate_resource_ids)
            )
        )
    )
    still_site_pages = set(
        db.scalars(
            select(distinct(SitePage.resource_id)).where(
                SitePage.resource_id.in_(candidate_resource_ids)
            )
        )
    )
    deletable = sorted(
        set(candidate_resource_ids)
        - still_snapshotted
        - still_targeted
        - still_source_entry
        - still_seeded
        - still_site_pages
    )
    if deletable:
        db.execute(delete(WebResource).where(WebResource.id.in_(deletable)))
    return deletable


def _delete_unreferenced_artifacts(db: Session) -> None:
    referenced_artifacts = select(distinct(ResourceSnapshot.parse_artifact_id)).where(
        ResourceSnapshot.parse_artifact_id.is_not(None)
    )
    db.execute(delete(HtmlParseArtifact).where(HtmlParseArtifact.id.not_in(referenced_artifacts)))
