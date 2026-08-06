from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.html_parser import AnchorData, ParsedHtml, parse_html
from app.models import ContentBlob, HtmlParseAnchor, HtmlParseArtifact, ResourceSnapshot
from app.storage.content_store import BlobNotFoundError, LocalContentStore

HTML_PARSER_VERSION = "html-parser-v2-link-roles"
HTML_PARSER_CONFIG_VERSION = "default-v1"


@dataclass(frozen=True)
class ArtifactResult:
    artifact: HtmlParseArtifact
    anchors: list[AnchorData]
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
    content: bytes,
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
            parsed=False,
        )

    parsed = parse_html(content, resolution_base_url)
    if existing is not None:
        return ArtifactResult(artifact=existing, anchors=parsed.anchors, parsed=True)

    artifact = _create_artifact(db, blob, resolution_base_url, parsed)
    return ArtifactResult(artifact=artifact, anchors=parsed.anchors, parsed=True)


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
    db.flush()
    return artifact
