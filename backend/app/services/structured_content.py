from __future__ import annotations

import hashlib
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Subquery

from app.crawler.canonical_document import (
    STRUCTURED_CONTENT_CONFIG_VERSION,
    STRUCTURED_CONTENT_EXTRACTOR_VERSION,
    STRUCTURED_MARKDOWN_RENDERER_VERSION,
    CanonicalDocument,
    canonical_semantic_sha256,
    canonical_subtree_sha256,
    extract_canonical_document,
    render_markdown,
    validate_canonical_document,
)
from app.models import (
    ContentBlob,
    HtmlStructuredContentArtifact,
    HtmlStructuredContentNode,
    ResourceSnapshot,
    Scan,
    SitePage,
)
from app.services.job_types import ExecutionOwnershipLost
from app.storage.content_store import LocalContentStore


def compatible_structured_artifact(
    db: Session, content_blob_id: int
) -> HtmlStructuredContentArtifact | None:
    return db.scalar(
        select(HtmlStructuredContentArtifact)
        .options(selectinload(HtmlStructuredContentArtifact.nodes))
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
    result = extract_canonical_document(content)
    validate_canonical_document(result)
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
    nodes = list(
        db.scalars(
            select(HtmlStructuredContentNode)
            .where(HtmlStructuredContentNode.artifact_id == artifact.id)
            .order_by(HtmlStructuredContentNode.position)
        )
    )
    if [node.position for node in nodes] != list(range(len(nodes))):
        raise ValueError("Persisted canonical node positions are not contiguous.")
    if artifact.node_count != len(nodes):
        raise ValueError("Persisted canonical node count does not match its rows.")
    ids = {node.id for node in nodes}
    children: dict[int, list[HtmlStructuredContentNode]] = {}
    for node in nodes:
        if node.parent_node_id is not None and node.parent_node_id not in ids:
            raise ValueError("Persisted canonical node parent is outside its artifact.")
        if node.parent_node_id is not None:
            children.setdefault(node.parent_node_id, []).append(node)
        if node.semantic_sha256 != canonical_semantic_sha256(node):
            raise ValueError("Persisted canonical node semantic hash is invalid.")
    for node in reversed(nodes):
        child_hashes = [child.subtree_sha256 for child in children.get(node.id, [])]
        if node.subtree_sha256 != canonical_subtree_sha256(node.semantic_sha256, child_hashes):
            raise ValueError("Persisted canonical node subtree hash is invalid.")
    if not nodes or artifact.canonical_document_sha256 != nodes[0].subtree_sha256:
        raise ValueError("Persisted canonical document hash is invalid.")
    markdown = render_markdown(nodes)
    if artifact.markdown_sha256 != hashlib.sha256(markdown.encode()).hexdigest():
        raise ValueError("Persisted Structured Markdown hash is invalid.")


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


def latest_page_content_snapshot_subquery(site_id: int) -> Subquery:
    ranked = (
        select(
            ResourceSnapshot.id.label("source_snapshot_id"),
            ResourceSnapshot.resource_id,
            ResourceSnapshot.html_blob_id.label("content_blob_id"),
            func.coalesce(ResourceSnapshot.fetched_at, Scan.created_at).label("observed_at"),
            func.row_number()
            .over(
                partition_by=ResourceSnapshot.resource_id,
                order_by=(
                    func.coalesce(ResourceSnapshot.fetched_at, Scan.created_at).desc(),
                    ResourceSnapshot.id.desc(),
                ),
            )
            .label("position"),
        )
        .join(Scan, Scan.id == ResourceSnapshot.scan_id)
        .join(
            SitePage,
            (SitePage.website_property_id == site_id)
            & (SitePage.resource_id == ResourceSnapshot.resource_id),
        )
        .where(
            Scan.website_property_id == site_id,
            SitePage.workspace_state == "active",
            ResourceSnapshot.fetch_state == "fetched",
            ResourceSnapshot.html_blob_id.is_not(None),
        )
        .subquery()
    )
    return select(ranked).where(ranked.c.position == 1).subquery()


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
    content_blob_ids: list[int] | None = None,
    fence_domain_mutation: Callable[[Session], None] | None = None,
) -> dict[str, int]:
    blob_ids = (
        list(dict.fromkeys(content_blob_ids))
        if content_blob_ids is not None
        else missing_structured_blob_ids(db, site_id=site_id, scan_id=scan_id, limit=limit)
    )
    counters = {"prepared": 0, "ready": 0, "partial": 0, "unavailable": 0, "failed": 0}
    for index, blob_id in enumerate(blob_ids, 1):
        if should_cancel and should_cancel():
            break
        try:
            blob = db.get(ContentBlob, blob_id)
            if blob is None:
                raise ValueError(f"ContentBlob {blob_id} no longer exists.")
            artifact = compatible_structured_artifact(db, blob.id)
            if artifact is None:
                content = store.get(blob)
                result = extract_canonical_document(content)
                validate_canonical_document(result)
                if fence_domain_mutation is not None:
                    fence_domain_mutation(db)
                artifact = compatible_structured_artifact(db, blob.id)
                if artifact is None:
                    try:
                        with db.begin_nested():
                            artifact = _persist_result(db, blob, result)
                    except IntegrityError:
                        artifact = compatible_structured_artifact(db, blob.id)
                        if artifact is None:
                            raise
            counters["prepared"] += 1
            counters[artifact.extraction_state] += 1
            db.commit()
        except ExecutionOwnershipLost:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            counters["failed"] += 1
            if stop_on_error:
                raise
        if progress:
            progress(index, len(blob_ids), counters.copy())
    return {**counters, "total": len(blob_ids)}


def _persist_result(
    db: Session, blob: ContentBlob, result: CanonicalDocument
) -> HtmlStructuredContentArtifact:
    artifact = HtmlStructuredContentArtifact(
        content_blob_id=blob.id,
        extractor_version=STRUCTURED_CONTENT_EXTRACTOR_VERSION,
        extractor_config_version=STRUCTURED_CONTENT_CONFIG_VERSION,
        extraction_state=result.extraction_state,
        document_profile=result.document_profile,
        section_count=sum(node.kind == "section" for node in result.nodes),
        heading_count=result.heading_count,
        heading_counts_json=result.heading_counts,
        document_word_count=result.document_word_count,
        document_character_count=result.document_character_count,
        document_text_sha256=result.document_text_sha256,
        outline_sha256=result.outline_sha256,
        is_truncated=result.is_truncated,
        truncation_reasons_json=list(result.truncation_reasons),
        node_count=len(result.nodes),
        canonical_document_sha256=result.canonical_document_sha256,
        markdown_renderer_version=STRUCTURED_MARKDOWN_RENDERER_VERSION,
        markdown_sha256=result.markdown_sha256,
        markdown_character_count=len(result.markdown),
    )
    db.add(artifact)
    db.flush()
    persisted: dict[int, HtmlStructuredContentNode] = {}
    rows: list[HtmlStructuredContentNode] = []
    for node in result.nodes:
        parent = persisted.get(node.parent_position) if node.parent_position is not None else None
        row = HtmlStructuredContentNode(
            artifact_id=artifact.id,
            parent=parent,
            position=node.position,
            kind=node.kind,
            depth=node.depth,
            source_tag=node.source_tag,
            source_dom_path=node.source_dom_path,
            region_key=node.region_key,
            region_dom_path=node.region_dom_path,
            text=node.text,
            inline_json=node.inline,
            source_attributes_json=node.source_attributes,
            semantic_json=node.semantic,
            semantic_sha256=node.semantic_sha256,
            subtree_sha256=node.subtree_sha256,
            child_count=node.child_count,
            descendant_count=node.descendant_count,
        )
        rows.append(row)
        persisted[node.position] = row
    db.add_all(rows)
    db.flush()
    verify_structured_artifact(db, artifact)
    return artifact
