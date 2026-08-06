"""Add Resource Inventory representation and occurrence evidence.

Revision ID: 202608060014
Revises: 202608060013
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import sqlalchemy as sa

from alembic import op

revision: str = "202608060014"
down_revision: str | None = "202608060013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "html_page_observed",
        "resource_observed",
        "resource_discovered",
        "resource_reference_occurrence",
    ):
        op.add_column(
            "scans",
            sa.Column(f"{name}_count", sa.Integer(), server_default="0", nullable=False),
        )
    op.add_column(
        "html_parse_artifacts",
        sa.Column("resource_reference_count", sa.Integer(), server_default="0", nullable=False),
    )
    for column in (
        sa.Column("representation_kind", sa.String(32)),
        sa.Column("representation_rule", sa.String(64)),
        sa.Column("normalized_mime_type", sa.String(255)),
        sa.Column("file_extension", sa.String(32)),
        sa.Column("content_disposition_filename", sa.String(255)),
        sa.Column("declared_content_length", sa.Integer()),
        sa.Column("response_body_state", sa.String(32)),
        sa.Column("inspected_prefix_byte_count", sa.Integer(), server_default="0", nullable=False),
    ):
        op.add_column("resource_snapshots", column)
    op.create_index(
        "ux_web_resources_normalized_url", "web_resources", ["normalized_url"], unique=True
    )
    op.create_index(
        "ix_resource_snapshots_representation_kind",
        "resource_snapshots",
        ["representation_kind"],
    )
    op.create_index(
        "ix_resource_snapshots_normalized_mime_type",
        "resource_snapshots",
        ["normalized_mime_type"],
    )
    op.create_index(
        "ix_resource_snapshots_file_extension", "resource_snapshots", ["file_extension"]
    )
    op.create_index(
        "ix_snapshot_scan_representation",
        "resource_snapshots",
        ["scan_id", "representation_kind"],
    )
    op.create_index(
        "ix_snapshot_resource_representation",
        "resource_snapshots",
        ["resource_id", "representation_kind"],
    )
    _create_parse_reference_table()
    _create_occurrence_table()
    _backfill_snapshots()
    _recalculate_scans()


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE resource_snapshots SET fetch_state='skipped', "
            "error_type='unsupported_content_type', error_message='Response was not HTML' "
            "WHERE representation_kind NOT IN ('html_page', 'unknown') "
            "AND retrieval_method='non_html' AND error_type IS NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE scans SET failed_count=(SELECT COUNT(*) FROM resource_snapshots rs "
            "WHERE rs.scan_id=scans.id AND rs.error_type IS NOT NULL)"
        )
    )
    op.drop_table("resource_reference_occurrences")
    op.drop_table("html_parse_resource_references")
    op.drop_index("ix_snapshot_resource_representation", table_name="resource_snapshots")
    op.drop_index("ix_snapshot_scan_representation", table_name="resource_snapshots")
    op.drop_index("ix_resource_snapshots_file_extension", table_name="resource_snapshots")
    op.drop_index("ix_resource_snapshots_normalized_mime_type", table_name="resource_snapshots")
    op.drop_index("ix_resource_snapshots_representation_kind", table_name="resource_snapshots")
    op.drop_index("ux_web_resources_normalized_url", table_name="web_resources")
    for name in (
        "inspected_prefix_byte_count",
        "response_body_state",
        "declared_content_length",
        "content_disposition_filename",
        "file_extension",
        "normalized_mime_type",
        "representation_rule",
        "representation_kind",
    ):
        op.drop_column("resource_snapshots", name)
    op.drop_column("html_parse_artifacts", "resource_reference_count")
    for name in (
        "resource_reference_occurrence",
        "resource_discovered",
        "resource_observed",
        "html_page_observed",
    ):
        op.drop_column("scans", f"{name}_count")


def _create_parse_reference_table() -> None:
    op.create_table(
        "html_parse_resource_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parse_artifact_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("element_tag", sa.String(32), nullable=False),
        sa.Column("attribute_name", sa.String(32), nullable=False),
        sa.Column("raw_url", sa.Text()),
        sa.Column("resolved_url", sa.Text()),
        sa.Column("inferred_kind", sa.String(32), nullable=False),
        sa.Column("classification_rule", sa.String(64), nullable=False),
        sa.Column("dom_path", sa.Text()),
        sa.Column("rel", sa.Text()),
        sa.Column("media", sa.Text()),
        sa.Column("type_hint", sa.String(255)),
        sa.Column("as_hint", sa.String(64)),
        sa.Column("srcset_descriptor", sa.String(64)),
        sa.Column("alt_text", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("width_attribute", sa.String(32)),
        sa.Column("height_attribute", sa.String(32)),
        sa.Column("crossorigin", sa.String(64)),
        sa.Column("loading", sa.String(64)),
        sa.Column("context_json", sa.JSON()),
        sa.ForeignKeyConstraint(
            ["parse_artifact_id"], ["html_parse_artifacts.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "parse_artifact_id", "position", name="uq_parse_resource_reference_position"
        ),
    )
    op.create_index(
        "ix_html_parse_resource_references_parse_artifact_id",
        "html_parse_resource_references",
        ["parse_artifact_id"],
    )
    op.create_index(
        "ix_html_parse_resource_references_relation_type",
        "html_parse_resource_references",
        ["relation_type"],
    )
    op.create_index(
        "ix_html_parse_resource_references_inferred_kind",
        "html_parse_resource_references",
        ["inferred_kind"],
    )
    op.create_index(
        "ix_parse_resource_reference_artifact_position",
        "html_parse_resource_references",
        ["parse_artifact_id", "position"],
    )


def _create_occurrence_table() -> None:
    op.create_table(
        "resource_reference_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("target_resource_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("element_tag", sa.String(32), nullable=False),
        sa.Column("attribute_name", sa.String(32), nullable=False),
        sa.Column("raw_url", sa.Text()),
        sa.Column("resolved_url", sa.Text()),
        sa.Column("normalized_target_url", sa.Text(), nullable=False),
        sa.Column("inferred_kind", sa.String(32), nullable=False),
        sa.Column("classification_rule", sa.String(64), nullable=False),
        sa.Column("dom_path", sa.Text()),
        sa.Column("rel", sa.Text()),
        sa.Column("media", sa.Text()),
        sa.Column("type_hint", sa.String(255)),
        sa.Column("as_hint", sa.String(64)),
        sa.Column("srcset_descriptor", sa.String(64)),
        sa.Column("alt_text", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("width_attribute", sa.String(32)),
        sa.Column("height_attribute", sa.String(32)),
        sa.Column("in_scope", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("scope_decision", sa.String(64), nullable=False),
        sa.Column("exclusion_reason", sa.Text()),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"], ["resource_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["target_resource_id"], ["web_resources.id"]),
    )
    for name in (
        "source_snapshot_id",
        "target_resource_id",
        "relation_type",
        "normalized_target_url",
        "inferred_kind",
        "scope_decision",
    ):
        op.create_index(
            f"ix_resource_reference_occurrences_{name}",
            "resource_reference_occurrences",
            [name],
        )
    op.create_index(
        "ix_resource_reference_source_kind",
        "resource_reference_occurrences",
        ["source_snapshot_id", "inferred_kind"],
    )
    op.create_index(
        "ix_resource_reference_target_source",
        "resource_reference_occurrences",
        ["target_resource_id", "source_snapshot_id"],
    )


def _backfill_snapshots() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, requested_url, final_url, content_type, response_headers, http_status, "
            "html_blob_id, fetch_state, parse_method, error_type, error_message "
            "FROM resource_snapshots"
        )
    ).mappings()
    update = sa.text(
        "UPDATE resource_snapshots SET representation_kind=:kind, representation_rule=:rule, "
        "normalized_mime_type=:mime, file_extension=:extension, "
        "content_disposition_filename=:filename, declared_content_length=:declared, "
        "response_body_state=:body_state, fetch_state=:fetch_state, parse_method=:parse_method, "
        "error_type=:error_type, error_message=:error_message WHERE id=:id"
    )
    for row in rows:
        headers = _headers(row["response_headers"])
        mime = _mime(row["content_type"])
        extension = _extension(row["final_url"] or row["requested_url"])
        filename = _filename(headers.get("content-disposition"))
        kind, rule = _classify(mime, extension, _extension(filename))
        corrected = (
            row["http_status"] is not None
            and kind != "html_page"
            and row["error_type"] == "unsupported_content_type"
        )
        declared = _integer(headers.get("content-length"))
        bind.execute(
            update,
            {
                "id": row["id"],
                "kind": kind,
                "rule": rule,
                "mime": mime,
                "extension": extension,
                "filename": filename,
                "declared": declared,
                "body_state": "full_html"
                if row["html_blob_id"] is not None
                else "metadata_only"
                if row["http_status"] is not None
                else "not_available",
                "fetch_state": "fetched" if corrected else row["fetch_state"],
                "parse_method": "not_applicable" if corrected else row["parse_method"],
                "error_type": None if corrected else row["error_type"],
                "error_message": None if corrected else row["error_message"],
            },
        )


def _recalculate_scans() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE scans SET
              html_page_observed_count=(
                SELECT COUNT(*) FROM resource_snapshots rs
                WHERE rs.scan_id=scans.id AND rs.representation_kind='html_page'
              ),
              resource_observed_count=(
                SELECT COUNT(*) FROM resource_snapshots rs
                WHERE rs.scan_id=scans.id
                  AND rs.representation_kind NOT IN ('html_page','unknown')
              ),
              resource_discovered_count=(
                SELECT COUNT(DISTINCT rs.resource_id) FROM resource_snapshots rs
                WHERE rs.scan_id=scans.id
                  AND rs.representation_kind NOT IN ('html_page','unknown')
              ),
              failed_count=(
                SELECT COUNT(*) FROM resource_snapshots rs
                WHERE rs.scan_id=scans.id AND rs.error_type IS NOT NULL
              )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE scans SET status='completed'
            WHERE status='completed_with_errors'
              AND failed_count=0
              AND rendered_failed_count=0
              AND NOT EXISTS (
                SELECT 1 FROM rendered_observations ro
                JOIN resource_snapshots rs ON rs.id=ro.snapshot_id
                WHERE rs.scan_id=scans.id
                  AND ro.capture_state IN ('failed','interrupted')
              )
            """
        )
    )


def _classify(
    mime: str | None, extension: str | None, filename_extension: str | None
) -> tuple[str, str]:
    if mime in {"text/html", "application/xhtml+xml"}:
        return "html_page", "mime_text_html"
    if mime and mime.startswith("image/"):
        return "image", "mime_image"
    if mime == "application/pdf":
        return "document", "mime_pdf"
    if mime == "text/css":
        return "stylesheet", "mime_stylesheet"
    if mime and ("javascript" in mime or "ecmascript" in mime):
        return "script", "mime_javascript"
    if mime and (mime.startswith("font/") or "font" in mime):
        return "font", "mime_font"
    if mime and mime.startswith("video/"):
        return "video", "mime_video"
    if mime and mime.startswith("audio/"):
        return "audio", "mime_audio"
    if mime in {"application/rss+xml", "application/atom+xml"}:
        return "feed", "mime_feed"
    if mime and "manifest" in mime:
        return "manifest", "mime_manifest"
    if mime and (
        mime.endswith("+json") or mime in {"application/json", "application/xml", "text/xml"}
    ):
        return "structured_data", "mime_structured_data"
    if mime and any(
        token in mime
        for token in (
            "word",
            "excel",
            "spreadsheet",
            "presentation",
            "powerpoint",
            "opendocument",
            "msword",
        )
    ):
        return "document", "mime_document"
    if mime and any(token in mime for token in ("zip", "gzip", "rar", "7z", "tar", "archive")):
        return "archive", "mime_archive"
    for candidate, rule in (
        (filename_extension, "content_disposition_filename"),
        (extension, "extension"),
    ):
        kind = _extension_kind(candidate)
        if kind:
            return kind, rule
    return ("other", "fallback_unknown") if mime else ("unknown", "fallback_unknown")


def _extension_kind(extension: str | None) -> str | None:
    groups = {
        "image": {"avif", "gif", "ico", "jpeg", "jpg", "png", "svg", "webp"},
        "document": {
            "csv",
            "doc",
            "docx",
            "ods",
            "odt",
            "pdf",
            "ppt",
            "pptx",
            "rtf",
            "txt",
            "xls",
            "xlsx",
        },
        "stylesheet": {"css"},
        "script": {"cjs", "js", "mjs"},
        "font": {"eot", "otf", "ttf", "woff", "woff2"},
        "video": {"avi", "mkv", "mov", "mp4", "webm"},
        "audio": {"flac", "m4a", "mp3", "ogg", "wav"},
        "archive": {"7z", "gz", "jar", "rar", "tar", "zip"},
        "feed": {"atom", "rss"},
        "manifest": {"webmanifest"},
        "structured_data": {"json", "jsonld", "xml"},
        "html_page": {"htm", "html", "xhtml"},
    }
    return next((kind for kind, values in groups.items() if extension in values), None)


def _headers(value: object) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    return {str(key).casefold(): str(item) for key, item in value.items()}


def _mime(value: object) -> str | None:
    return str(value).split(";", 1)[0].strip().casefold() if value else None


def _extension(value: object) -> str | None:
    if not value:
        return None
    name = PurePosixPath(unquote(urlsplit(str(value)).path)).name
    return (
        name.rsplit(".", 1)[-1].casefold()[:32] if "." in name and not name.endswith(".") else None
    )


def _filename(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r'filename\*?\s*=\s*(?:[^\']*\'\')?"?([^";\r\n]+)', value, re.I)
    return unquote(match.group(1)).strip()[:255] if match else None


def _integer(value: object) -> int | None:
    try:
        result = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and result >= 0 else None
