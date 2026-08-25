from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    AccessibilityObservation,
    AccessibilityPayloadBlob,
    BackgroundJob,
    PerformanceObservation,
    PerformancePayloadBlob,
)
from app.services.job_types import (
    ACTIVE_JOB_STATUSES,
    JOB_TYPE_ACCESSIBILITY_RUN,
    JOB_TYPE_PERFORMANCE_RUN,
)
from app.storage.accessibility_store import LocalAccessibilityPayloadStore
from app.storage.observability_payloads import (
    delete_payload,
    inventory_payload_files,
    payload_storage_key,
)
from app.storage.performance_store import LocalPerformancePayloadStore

PayloadDomain = Literal["performance", "accessibility"]


@dataclass
class PayloadGcReport:
    domain: PayloadDomain
    apply: bool
    db_blob_records: int
    referenced_blob_records: int
    unreferenced_blob_records: int
    referenced_files_missing: list[str]
    orphan_physical_files: list[str]
    unexpected_files: list[str]
    raw_bytes: int
    stored_bytes: int
    reclaimable_raw_bytes: int
    reclaimable_stored_bytes: int
    deleted_blob_records: int = 0
    deleted_physical_files: int = 0
    warnings: list[str] = field(default_factory=list)


def collect_performance_payload_gc(
    db: Session, store: LocalPerformancePayloadStore, *, apply: bool = False
) -> PayloadGcReport:
    _guard_active_jobs(db, JOB_TYPE_PERFORMANCE_RUN, "Performance")
    blobs = list(db.scalars(select(PerformancePayloadBlob)))
    referenced_ids = set(
        db.scalars(
            select(distinct(PerformanceObservation.payload_blob_id)).where(
                PerformanceObservation.payload_blob_id.is_not(None)
            )
        )
    )
    return _collect(
        db,
        "performance",
        store,
        blobs,
        referenced_ids,
        PerformancePayloadBlob,
        apply=apply,
    )


def collect_accessibility_payload_gc(
    db: Session, store: LocalAccessibilityPayloadStore, *, apply: bool = False
) -> PayloadGcReport:
    _guard_active_jobs(db, JOB_TYPE_ACCESSIBILITY_RUN, "Accessibility")
    blobs = list(db.scalars(select(AccessibilityPayloadBlob)))
    referenced_ids = set(
        db.scalars(
            select(distinct(AccessibilityObservation.payload_blob_id)).where(
                AccessibilityObservation.payload_blob_id.is_not(None)
            )
        )
    )
    return _collect(
        db,
        "accessibility",
        store,
        blobs,
        referenced_ids,
        AccessibilityPayloadBlob,
        apply=apply,
    )


def _collect(
    db: Session,
    domain: PayloadDomain,
    store: LocalPerformancePayloadStore | LocalAccessibilityPayloadStore,
    blobs: list[PerformancePayloadBlob] | list[AccessibilityPayloadBlob],
    referenced_ids: set[int | None],
    blob_model: type[PerformancePayloadBlob] | type[AccessibilityPayloadBlob],
    *,
    apply: bool,
) -> PayloadGcReport:
    inventory = inventory_payload_files(store.root)
    by_sha = {blob.sha256: blob for blob in blobs}
    referenced = [blob for blob in blobs if blob.id in referenced_ids]
    unreferenced = [blob for blob in blobs if blob.id not in referenced_ids]
    missing = [
        blob.storage_key for blob in referenced if not store._path(blob.storage_key).is_file()
    ]
    orphan_shas = sorted(set(inventory.payloads) - set(by_sha))
    orphan_files = [
        inventory.payloads[sha].relative_to(store.root).as_posix() for sha in orphan_shas
    ]
    report = PayloadGcReport(
        domain=domain,
        apply=apply,
        db_blob_records=len(blobs),
        referenced_blob_records=len(referenced),
        unreferenced_blob_records=len(unreferenced),
        referenced_files_missing=sorted(missing),
        orphan_physical_files=orphan_files,
        unexpected_files=inventory.unexpected,
        raw_bytes=sum(blob.raw_byte_size for blob in blobs),
        stored_bytes=sum(blob.stored_byte_size for blob in blobs),
        reclaimable_raw_bytes=sum(blob.raw_byte_size for blob in unreferenced),
        reclaimable_stored_bytes=sum(blob.stored_byte_size for blob in unreferenced),
    )
    if not apply:
        return report
    if unreferenced:
        db.execute(delete(blob_model).where(blob_model.id.in_([blob.id for blob in unreferenced])))
    db.commit()
    report.deleted_blob_records = len(unreferenced)
    for blob in unreferenced:
        if blob.storage_key != payload_storage_key(blob.sha256):
            report.warnings.append(
                f"Unexpected {domain} payload storage key was not removed: {blob.storage_key}"
            )
            continue
        try:
            if delete_payload(store.root, blob.storage_key):
                report.deleted_physical_files += 1
        except OSError as exc:
            report.warnings.append(f"Could not delete {domain} payload {blob.storage_key}: {exc}")
    for sha in orphan_shas:
        try:
            inventory.payloads[sha].unlink()
            report.deleted_physical_files += 1
        except OSError as exc:
            relative = inventory.payloads[sha].relative_to(store.root).as_posix()
            report.warnings.append(f"Could not delete orphan {domain} payload {relative}: {exc}")
    return report


def _guard_active_jobs(db: Session, job_type: str, label: str) -> None:
    count = (
        db.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.job_type == job_type,
                BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    if count:
        raise RuntimeError(f"{label} payload GC is blocked while collection jobs are active.")
