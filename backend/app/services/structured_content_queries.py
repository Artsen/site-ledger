from __future__ import annotations

import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    HtmlStructuredContentArtifact,
    HtmlStructuredContentNode,
    ResourceSnapshot,
    Scan,
    SitePage,
)
from app.schemas.structured_content import (
    StructuredContentArtifactRead,
    StructuredContentDocumentRead,
    StructuredContentNodeRead,
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
    sections = _outline_sections(artifact)
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
        items=sections[offset : offset + limit],
        total=artifact.section_count,
        limit=limit,
        offset=offset,
    )


def structured_document_for_snapshot(
    db: Session, snapshot: ResourceSnapshot, *, limit: int, offset: int
) -> StructuredContentDocumentRead:
    outline = structured_content_for_snapshot(db, snapshot, limit=1, offset=0)
    if outline.artifact is None:
        return StructuredContentDocumentRead(
            status=outline.status,
            reason=outline.reason,
            provenance=outline.provenance,
            artifact=None,
            items=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    rows = list(
        db.scalars(
            select(HtmlStructuredContentNode)
            .where(HtmlStructuredContentNode.artifact_id == outline.artifact.id)
            .order_by(HtmlStructuredContentNode.position)
            .limit(limit)
            .offset(offset)
        )
    )
    return StructuredContentDocumentRead(
        status=outline.status,
        reason=outline.reason,
        provenance=outline.provenance,
        artifact=outline.artifact,
        items=[_node_read(row) for row in rows],
        total=outline.artifact.node_count,
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
        node_count=artifact.node_count,
        canonical_document_sha256=artifact.canonical_document_sha256,
        markdown_renderer_version=artifact.markdown_renderer_version,
        markdown_sha256=artifact.markdown_sha256,
        markdown_character_count=artifact.markdown_character_count,
        created_at=artifact.created_at,
    )


def _outline_sections(
    artifact: HtmlStructuredContentArtifact,
) -> list[StructuredContentSectionRead]:
    nodes = artifact.nodes
    by_id = {node.id: node for node in nodes}
    sections = [node for node in nodes if node.kind == "section"]
    result: list[StructuredContentSectionRead] = []
    for section in sections:
        children = [node for node in nodes if node.parent_node_id == section.id]
        heading = next((node for node in children if node.kind == "heading"), None)
        parent = by_id.get(section.parent_node_id or -1)
        direct = "\n".join(
            node.text or "" for node in children if node.kind != "heading" and node.text
        )
        subtree_text = "\n".join(
            node.text or ""
            for node in nodes
            if node.position >= section.position
            and node.position <= section.position + section.descendant_count
            and node.text
        )
        result.append(
            StructuredContentSectionRead(
                id=section.id,
                position=section.position,
                parent_section_id=parent.id if parent and parent.kind == "section" else None,
                kind=str(section.semantic_json.get("section_kind", "unheaded")),
                heading_level=_heading_level(heading.semantic_json.get("level"))
                if heading
                else None,
                heading_text=heading.text if heading else None,
                heading_dom_path=heading.source_dom_path if heading else None,
                region_key=section.region_key,
                region_dom_path=section.region_dom_path,
                direct_text=direct,
                direct_text_sha256=_sha(direct),
                section_sha256=section.semantic_sha256,
                subtree_sha256=section.subtree_sha256,
                direct_word_count=len(direct.split()),
                direct_character_count=len(direct),
                subtree_word_count=len(subtree_text.split()),
                subtree_character_count=len(subtree_text),
                child_count=sum(
                    node.kind == "section" and node.parent_node_id == section.id for node in nodes
                ),
                descendant_count=sum(
                    node.kind == "section"
                    and section.position
                    < node.position
                    <= section.position + section.descendant_count
                    for node in nodes
                ),
                block_count=sum(node.kind not in {"section", "heading"} for node in children),
                has_direct_content=bool(direct),
            )
        )
    return result


def _node_read(node: HtmlStructuredContentNode) -> StructuredContentNodeRead:
    return StructuredContentNodeRead(
        id=node.id,
        position=node.position,
        parent_node_id=node.parent_node_id,
        kind=node.kind,
        depth=node.depth,
        source_tag=node.source_tag,
        source_dom_path=node.source_dom_path,
        region_key=node.region_key,
        region_dom_path=node.region_dom_path,
        text=node.text,
        inline=node.inline_json,
        source_attributes=node.source_attributes_json,
        semantic=node.semantic_json,
        semantic_sha256=node.semantic_sha256,
        subtree_sha256=node.subtree_sha256,
        child_count=node.child_count,
        descendant_count=node.descendant_count,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _heading_level(value: object) -> int | None:
    if isinstance(value, int) and 1 <= value <= 6:
        return value
    return None
