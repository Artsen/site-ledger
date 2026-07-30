from dataclasses import dataclass

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.models import ContentBlob, ResourceOccurrence, ResourceSnapshot, Scan
from app.schemas.scans import ScanDeletePreview, ScanDeleteResult
from app.storage.content_store import LocalContentStore

TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}


@dataclass(frozen=True)
class DeletionImpact:
    scan: Scan
    snapshots: int
    link_occurrences: int
    referenced_blobs: list[ContentBlob]
    deletable_blobs: list[ContentBlob]

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
            can_delete=False,
            status=scan.status,
            snapshots=0,
            link_occurrences=0,
            html_blobs_referenced=0,
            html_blobs_deleted=0,
            raw_html_bytes_reclaimable=0,
            stored_html_bytes_reclaimable=0,
            reason="Only terminal scans can be deleted.",
        )
    impact = _deletion_impact(db, scan)
    return ScanDeletePreview(
        scan_id=scan.id,
        can_delete=True,
        status=scan.status,
        snapshots=impact.snapshots,
        link_occurrences=impact.link_occurrences,
        html_blobs_referenced=len(impact.referenced_blobs),
        html_blobs_deleted=len(impact.deletable_blobs),
        raw_html_bytes_reclaimable=impact.raw_bytes,
        stored_html_bytes_reclaimable=impact.stored_bytes,
    )


def delete_scan(db: Session, scan_id: int, store: LocalContentStore) -> ScanDeleteResult | None:
    scan = db.get(Scan, scan_id)
    if scan is None:
        return None
    if scan.status not in TERMINAL_STATUSES:
        raise ValueError("Only terminal scans can be deleted.")
    impact = _deletion_impact(db, scan)
    deleted_blob_ids = [blob.id for blob in impact.deletable_blobs]
    snapshot_ids = select(ResourceSnapshot.id).where(ResourceSnapshot.scan_id == scan.id)
    db.execute(
        delete(ResourceOccurrence).where(ResourceOccurrence.source_snapshot_id.in_(snapshot_ids))
    )
    db.execute(delete(ResourceSnapshot).where(ResourceSnapshot.scan_id == scan.id))
    db.execute(delete(Scan).where(Scan.id == scan.id))
    if deleted_blob_ids:
        db.execute(delete(ContentBlob).where(ContentBlob.id.in_(deleted_blob_ids)))
    db.commit()
    for blob in impact.deletable_blobs:
        store.delete(blob)
    return ScanDeleteResult(
        deleted_scan_id=scan_id,
        snapshots_deleted=impact.snapshots,
        link_occurrences_deleted=impact.link_occurrences,
        html_blobs_deleted=len(impact.deletable_blobs),
        raw_html_bytes_reclaimed=impact.raw_bytes,
        stored_html_bytes_reclaimed=impact.stored_bytes,
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
    referenced_blobs = (
        list(db.scalars(select(ContentBlob).where(ContentBlob.id.in_(referenced_blob_ids))))
        if referenced_blob_ids
        else []
    )
    deletable_blobs: list[ContentBlob] = []
    for blob in referenced_blobs:
        references_outside_scan = (
            db.scalar(
                select(func.count(ResourceSnapshot.id)).where(
                    ResourceSnapshot.html_blob_id == blob.id,
                    ResourceSnapshot.scan_id != scan.id,
                )
            )
            or 0
        )
        if references_outside_scan == 0:
            deletable_blobs.append(blob)
    return DeletionImpact(
        scan=scan,
        snapshots=snapshots,
        link_occurrences=link_occurrences,
        referenced_blobs=referenced_blobs,
        deletable_blobs=deletable_blobs,
    )
