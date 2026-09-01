from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.html_parser import AnchorData, ParsedHtml, ResourceReferenceData, parse_html
from app.database import materialize_outer_transaction
from app.models import (
    ContentBlob,
    HtmlParseAnchor,
    HtmlParseArtifact,
    HtmlParseResourceReference,
    ResourceSnapshot,
)
from app.storage.content_store import BlobNotFoundError, LocalContentStore

HTML_PARSER_VERSION = "html-parser-v4-rel-token-semantics"
HTML_PARSER_CONFIG_VERSION = "default-v1"


@dataclass(frozen=True)
class ArtifactResult:
    artifact: HtmlParseArtifact
    anchors: list[AnchorData]
    resource_references: list[ResourceReferenceData]
    parsed: bool

    @property
    def parse_method(self) -> str:
        return "parsed" if self.parsed else "reused_exact_hash"


def find_compatible_artifact(
    db: Session,
    *,
    content_blob_id: int,
    resolution_base_url: str,
    parser_version: str = HTML_PARSER_VERSION,
    parser_config_version: str = HTML_PARSER_CONFIG_VERSION,
) -> HtmlParseArtifact | None:
    return db.scalar(
        select(HtmlParseArtifact).where(
            HtmlParseArtifact.content_blob_id == content_blob_id,
            HtmlParseArtifact.parser_version == parser_version,
            HtmlParseArtifact.parser_config_version == parser_config_version,
            HtmlParseArtifact.resolution_base_url == resolution_base_url,
        )
    )


def get_or_create_artifact(
    db: Session,
    *,
    blob: ContentBlob,
    content: bytes | None = None,
    store: LocalContentStore | None = None,
    resolution_base_url: str,
    force_parse: bool = False,
) -> ArtifactResult:
    existing = find_compatible_artifact(
        db,
        content_blob_id=blob.id,
        resolution_base_url=resolution_base_url,
    )
    if existing is not None and not force_parse:
        return ArtifactResult(
            artifact=existing,
            anchors=load_artifact_anchors(db, existing),
            resource_references=load_artifact_resource_references(db, existing),
            parsed=False,
        )

    if content is None:
        if store is None:
            raise ValueError("Content or a content store is required to parse HTML.")
        content = store.get(blob)
    parsed = parse_html(content, resolution_base_url)
    if existing is not None:
        return ArtifactResult(
            artifact=existing,
            anchors=parsed.anchors,
            resource_references=parsed.resource_references,
            parsed=True,
        )

    materialize_outer_transaction(db)
    try:
        with db.begin_nested():
            artifact = _create_artifact(db, blob, resolution_base_url, parsed)
    except IntegrityError:
        winner = find_compatible_artifact(
            db,
            content_blob_id=blob.id,
            resolution_base_url=resolution_base_url,
        )
        if winner is None:
            raise
        return ArtifactResult(
            artifact=winner,
            anchors=load_artifact_anchors(db, winner),
            resource_references=load_artifact_resource_references(db, winner),
            parsed=True,
        )
    return ArtifactResult(
        artifact=artifact,
        anchors=parsed.anchors,
        resource_references=parsed.resource_references,
        parsed=True,
    )


def ensure_artifact_for_snapshot(
    db: Session,
    store: LocalContentStore,
    snapshot: ResourceSnapshot,
    *,
    force_parse: bool = False,
) -> ArtifactResult | None:
    if snapshot.blob is None or snapshot.final_url is None:
        return None
    try:
        content = store.get(snapshot.blob)
    except BlobNotFoundError:
        return None
    return get_or_create_artifact(
        db,
        blob=snapshot.blob,
        content=content,
        resolution_base_url=snapshot.final_url,
        force_parse=force_parse,
    )


def load_artifact_anchors(db: Session, artifact: HtmlParseArtifact) -> list[AnchorData]:
    rows = db.scalars(
        select(HtmlParseAnchor)
        .where(HtmlParseAnchor.parse_artifact_id == artifact.id)
        .order_by(HtmlParseAnchor.position)
    )
    return [
        AnchorData(
            raw_href=row.raw_href,
            resolved_url=row.resolved_url,
            anchor_text=row.anchor_text,
            title=row.title,
            aria_label=row.aria_label,
            rel=row.rel,
            target=row.target,
            dom_path=row.dom_path or "",
            link_role=row.link_role or "unknown",
            link_role_rule=row.link_role_rule or "fallback_unknown",
            link_context_json=row.link_context_json or {},
        )
        for row in rows
    ]


def load_artifact_resource_references(
    db: Session, artifact: HtmlParseArtifact
) -> list[ResourceReferenceData]:
    rows = db.scalars(
        select(HtmlParseResourceReference)
        .where(HtmlParseResourceReference.parse_artifact_id == artifact.id)
        .order_by(HtmlParseResourceReference.position)
    )
    return [
        ResourceReferenceData(
            position=row.position,
            relation_type=row.relation_type,
            element_tag=row.element_tag,
            attribute_name=row.attribute_name,
            raw_url=row.raw_url or "",
            resolved_url=row.resolved_url or "",
            inferred_kind=row.inferred_kind,
            classification_rule=row.classification_rule,
            dom_path=row.dom_path or "",
            rel=row.rel,
            media=row.media,
            type_hint=row.type_hint,
            as_hint=row.as_hint,
            srcset_descriptor=row.srcset_descriptor,
            alt_text=row.alt_text,
            title=row.title,
            width_attribute=row.width_attribute,
            height_attribute=row.height_attribute,
            crossorigin=row.crossorigin,
            loading=row.loading,
            context_json=row.context_json or {},
        )
        for row in rows
    ]


def _create_artifact(
    db: Session,
    blob: ContentBlob,
    resolution_base_url: str,
    parsed: ParsedHtml,
) -> HtmlParseArtifact:
    artifact = HtmlParseArtifact(
        content_blob_id=blob.id,
        parser_version=HTML_PARSER_VERSION,
        parser_config_version=HTML_PARSER_CONFIG_VERSION,
        resolution_base_url=resolution_base_url,
        page_title=parsed.title,
        html_language=parsed.html_language,
        meta_description=parsed.meta_description,
        meta_robots=parsed.meta_robots,
        canonical_url=parsed.canonical_url,
        document_encoding=parsed.encoding,
        viewport=parsed.viewport,
        head_sha256=parsed.head_sha256,
        parsed_head_json=parsed.head_json,
        anchor_count=len(parsed.anchors),
        resource_reference_count=len(parsed.resource_references),
    )
    db.add(artifact)
    db.flush()
    db.add_all(
        HtmlParseAnchor(
            parse_artifact_id=artifact.id,
            position=index,
            raw_href=anchor.raw_href,
            resolved_url=anchor.resolved_url,
            anchor_text=anchor.anchor_text,
            title=anchor.title,
            aria_label=anchor.aria_label,
            rel=anchor.rel,
            target=anchor.target,
            dom_path=anchor.dom_path,
            link_role=anchor.link_role,
            link_role_rule=anchor.link_role_rule,
            link_context_json=anchor.link_context_json,
        )
        for index, anchor in enumerate(parsed.anchors)
    )
    db.add_all(
        HtmlParseResourceReference(
            parse_artifact_id=artifact.id,
            position=reference.position,
            relation_type=reference.relation_type,
            element_tag=reference.element_tag,
            attribute_name=reference.attribute_name,
            raw_url=reference.raw_url,
            resolved_url=reference.resolved_url,
            inferred_kind=reference.inferred_kind,
            classification_rule=reference.classification_rule,
            dom_path=reference.dom_path,
            rel=reference.rel,
            media=reference.media,
            type_hint=reference.type_hint,
            as_hint=reference.as_hint,
            srcset_descriptor=reference.srcset_descriptor,
            alt_text=reference.alt_text,
            title=reference.title,
            width_attribute=reference.width_attribute,
            height_attribute=reference.height_attribute,
            crossorigin=reference.crossorigin,
            loading=reference.loading,
            context_json=reference.context_json,
        )
        for reference in parsed.resource_references
    )
    db.flush()
    return artifact
