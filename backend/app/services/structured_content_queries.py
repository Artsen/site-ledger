from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    HtmlStructuredContentArtifact,
    HtmlStructuredContentSection,
    ResourceSnapshot,
    Scan,
    SitePage,
)
from app.schemas.structured_content import (
    StructuredContentArtifactRead,
    StructuredContentProvenance,
    StructuredContentRead,
    StructuredContentSectionRead,
)
from app.services.structured_content import compatible_structured_artifact


def structured_content_for_snapshot(
    db: Session, snapshot: ResourceSnapshot, *, limit: int, offset: int
) -> StructuredContentRead:
    if snapshot.html_blob_id is None:
        return StructuredContentRead(
            status="not_applicable",
            reason="This observation has no retained HTML ContentBlob.",
            items=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    provenance = _provenance(db, snapshot)
    artifact = compatible_structured_artifact(db, snapshot.html_blob_id)
    if artifact is None:
        return StructuredContentRead(
            status="not_prepared",
            reason="Structured content has not been prepared for this retained HTML blob.",
            provenance=provenance,
            items=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    rows = list(
        db.scalars(
            select(HtmlStructuredContentSection)
            .where(HtmlStructuredContentSection.artifact_id == artifact.id)
            .order_by(HtmlStructuredContentSection.position)
            .limit(limit)
            .offset(offset)
        )
    )
    return StructuredContentRead(
        status=artifact.extraction_state,
        reason=(
            "Extraction completed with deterministic bounds."
            if artifact.extraction_state == "partial"
            else "The retained HTML could not be parsed."
            if artifact.extraction_state == "unavailable"
            else None
        ),
        provenance=provenance,
        artifact=_artifact_read(artifact),
        items=[_section_read(section) for section in rows],
        total=artifact.section_count,
        limit=limit,
        offset=offset,
    )


def latest_page_content_snapshot(
    db: Session, site_id: int, resource_id: int
) -> ResourceSnapshot | None:
    if (
        db.scalar(
            select(SitePage.id).where(
                SitePage.website_property_id == site_id,
                SitePage.resource_id == resource_id,
            )
        )
        is None
    ):
        return None
    return db.scalar(
        select(ResourceSnapshot)
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .where(
            Scan.website_property_id == site_id,
            ResourceSnapshot.resource_id == resource_id,
            ResourceSnapshot.fetch_state == "fetched",
            ResourceSnapshot.html_blob_id.is_not(None),
        )
        .order_by(
            func.coalesce(ResourceSnapshot.fetched_at, Scan.created_at).desc(),
            ResourceSnapshot.id.desc(),
        )
        .limit(1)
    )


def _provenance(db: Session, snapshot: ResourceSnapshot) -> StructuredContentProvenance:
    site_id = db.scalar(select(Scan.website_property_id).where(Scan.id == snapshot.scan_id))
    return StructuredContentProvenance(
        snapshot_id=snapshot.id,
        scan_id=snapshot.scan_id,
        site_id=site_id,
        content_blob_id=snapshot.html_blob_id or 0,
        raw_html_sha256=snapshot.raw_html_sha256,
        requested_url=snapshot.requested_url,
        final_url=snapshot.final_url,
        fetched_at=snapshot.fetched_at,
        retrieval_method=snapshot.retrieval_method,
        reused_from_snapshot_id=snapshot.reused_from_snapshot_id,
    )


def _artifact_read(artifact: HtmlStructuredContentArtifact) -> StructuredContentArtifactRead:
    return StructuredContentArtifactRead(
        id=artifact.id,
        extractor_version=artifact.extractor_version,
        extractor_config_version=artifact.extractor_config_version,
        extraction_state=artifact.extraction_state,
        document_profile=artifact.document_profile,
        section_count=artifact.section_count,
        heading_count=artifact.heading_count,
        heading_counts=artifact.heading_counts_json,
        document_word_count=artifact.document_word_count,
        document_character_count=artifact.document_character_count,
        document_text_sha256=artifact.document_text_sha256,
        outline_sha256=artifact.outline_sha256,
        is_truncated=artifact.is_truncated,
        truncation_reasons=artifact.truncation_reasons_json,
        created_at=artifact.created_at,
    )


def _section_read(section: HtmlStructuredContentSection) -> StructuredContentSectionRead:
    return StructuredContentSectionRead.model_validate(section, from_attributes=True)
