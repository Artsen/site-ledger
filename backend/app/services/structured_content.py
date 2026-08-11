from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.crawler.structured_content import (
    STRUCTURED_CONTENT_CONFIG_VERSION,
    STRUCTURED_CONTENT_EXTRACTOR_VERSION,
    ExtractedStructuredContent,
    extract_structured_content,
    validate_extracted_content,
)
from app.models import (
    ContentBlob,
    HtmlStructuredContentArtifact,
    HtmlStructuredContentSection,
    ResourceSnapshot,
    Scan,
)
from app.storage.content_store import LocalContentStore


def compatible_structured_artifact(
    db: Session, content_blob_id: int
) -> HtmlStructuredContentArtifact | None:
    return db.scalar(
        select(HtmlStructuredContentArtifact)
        .options(selectinload(HtmlStructuredContentArtifact.sections))
        .where(
            HtmlStructuredContentArtifact.content_blob_id == content_blob_id,
            HtmlStructuredContentArtifact.extractor_version == STRUCTURED_CONTENT_EXTRACTOR_VERSION,
            HtmlStructuredContentArtifact.extractor_config_version
            == STRUCTURED_CONTENT_CONFIG_VERSION,
        )
    )


def get_or_create_structured_artifact(
    db: Session,
    blob: ContentBlob,
    *,
    content: bytes | None = None,
    store: LocalContentStore | None = None,
) -> tuple[HtmlStructuredContentArtifact, bool]:
    existing = compatible_structured_artifact(db, blob.id)
    if existing is not None:
        return existing, True
    if content is None:
        if store is None:
            raise ValueError("Content or a content store is required to build structured content.")
        content = store.get(blob)
    result = extract_structured_content(content)
    validate_extracted_content(result)
    try:
        with db.begin_nested():
            artifact = _persist_result(db, blob, result)
    except IntegrityError:
        raced = compatible_structured_artifact(db, blob.id)
        if raced is None:
            raise
        return raced, True
    return artifact, False


def rebuild_structured_artifact(
    db: Session, blob: ContentBlob, store: LocalContentStore
) -> HtmlStructuredContentArtifact:
    existing = compatible_structured_artifact(db, blob.id)
    if existing is not None:
        db.delete(existing)
        db.flush()
    artifact, _ = get_or_create_structured_artifact(db, blob, store=store)
    return artifact


def verify_structured_artifact(db: Session, artifact: HtmlStructuredContentArtifact) -> None:
    sections = list(
        db.scalars(
            select(HtmlStructuredContentSection)
            .where(HtmlStructuredContentSection.artifact_id == artifact.id)
            .order_by(HtmlStructuredContentSection.position)
        )
    )
    if [section.position for section in sections] != list(range(len(sections))):
        raise ValueError("Persisted structured section positions are not contiguous.")
    if artifact.section_count != len(sections):
        raise ValueError("Persisted structured section count does not match its rows.")
    ids = {section.id for section in sections}
    for section in sections:
        if section.parent_section_id is not None and section.parent_section_id not in ids:
            raise ValueError("Persisted structured section parent is outside its artifact.")


def missing_structured_blob_ids(
    db: Session,
    *,
    site_id: int | None = None,
    scan_id: int | None = None,
    limit: int | None = None,
) -> list[int]:
    compatible = (
        select(HtmlStructuredContentArtifact.id)
        .where(
            HtmlStructuredContentArtifact.content_blob_id == ContentBlob.id,
            HtmlStructuredContentArtifact.extractor_version == STRUCTURED_CONTENT_EXTRACTOR_VERSION,
            HtmlStructuredContentArtifact.extractor_config_version
            == STRUCTURED_CONTENT_CONFIG_VERSION,
        )
        .exists()
    )
    statement = (
        select(ContentBlob.id)
        .join(ResourceSnapshot, ResourceSnapshot.html_blob_id == ContentBlob.id)
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .where(~compatible)
        .distinct()
        .order_by(ContentBlob.id)
    )
    if site_id is not None:
        statement = statement.where(Scan.website_property_id == site_id)
    if scan_id is not None:
        statement = statement.where(Scan.id == scan_id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement))


def build_missing_structured_content(
    db: Session,
    store: LocalContentStore,
    *,
    site_id: int | None = None,
    scan_id: int | None = None,
    limit: int | None = None,
    stop_on_error: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[int, int, dict[str, int]], None] | None = None,
) -> dict[str, int]:
    blob_ids = missing_structured_blob_ids(db, site_id=site_id, scan_id=scan_id, limit=limit)
    counters = {"prepared": 0, "ready": 0, "partial": 0, "unavailable": 0, "failed": 0}
    for index, blob_id in enumerate(blob_ids, 1):
        if should_cancel and should_cancel():
            break
        try:
            blob = db.get(ContentBlob, blob_id)
            if blob is None:
                raise ValueError(f"ContentBlob {blob_id} no longer exists.")
            artifact, _ = get_or_create_structured_artifact(db, blob, store=store)
            counters["prepared"] += 1
            counters[artifact.extraction_state] += 1
            db.commit()
        except Exception:
            db.rollback()
            counters["failed"] += 1
            if stop_on_error:
                raise
        if progress:
            progress(index, len(blob_ids), counters.copy())
    return {**counters, "total": len(blob_ids)}


def _persist_result(
    db: Session, blob: ContentBlob, result: ExtractedStructuredContent
) -> HtmlStructuredContentArtifact:
    artifact = HtmlStructuredContentArtifact(
        content_blob_id=blob.id,
        extractor_version=STRUCTURED_CONTENT_EXTRACTOR_VERSION,
        extractor_config_version=STRUCTURED_CONTENT_CONFIG_VERSION,
        extraction_state=result.extraction_state,
        document_profile=result.document_profile,
        section_count=len(result.sections),
        heading_count=result.heading_count,
        heading_counts_json=result.heading_counts,
        document_word_count=result.document_word_count,
        document_character_count=result.document_character_count,
        document_text_sha256=result.document_text_sha256,
        outline_sha256=result.outline_sha256,
        is_truncated=result.is_truncated,
        truncation_reasons_json=list(result.truncation_reasons),
    )
    db.add(artifact)
    db.flush()
    persisted: dict[int, HtmlStructuredContentSection] = {}
    rows: list[HtmlStructuredContentSection] = []
    for section in result.sections:
        parent = (
            persisted.get(section.parent_position) if section.parent_position is not None else None
        )
        row = HtmlStructuredContentSection(
            artifact_id=artifact.id,
            parent=parent,
            position=section.position,
            kind=section.kind,
            heading_level=section.heading_level,
            heading_text=section.heading_text,
            heading_dom_path=section.heading_dom_path,
            region_key=section.region_key,
            region_dom_path=section.region_dom_path,
            direct_text=section.direct_text,
            direct_text_sha256=section.direct_text_sha256,
            section_sha256=section.section_sha256,
            subtree_sha256=section.subtree_sha256,
            direct_word_count=section.direct_word_count,
            direct_character_count=section.direct_character_count,
            subtree_word_count=section.subtree_word_count,
            subtree_character_count=section.subtree_character_count,
            child_count=section.child_count,
            descendant_count=section.descendant_count,
            block_count=section.block_count,
            has_direct_content=section.has_direct_content,
        )
        rows.append(row)
        persisted[section.position] = row
    db.add_all(rows)
    db.flush()
    verify_structured_artifact(db, artifact)
    return artifact
