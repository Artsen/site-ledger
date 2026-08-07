"""Add immutable AI document source evidence.

Revision ID: 202608060015
Revises: 202608060014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608060015"
down_revision: str | None = "202608060014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_document_blobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("media_type", sa.String(255)),
        sa.Column("encoding", sa.String(64)),
        sa.Column("compression_type", sa.String(32), nullable=False, server_default="gzip"),
        sa.Column("raw_byte_size", sa.Integer(), nullable=False),
        sa.Column("stored_byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "ai_document_refreshes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_refresh_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False, server_default="0")
            for name in (
                "root_candidate_count", "document_discovered_count", "document_fetched_count",
                "document_saved_count", "document_unchanged_count", "document_changed_count",
                "document_failed_count", "document_skipped_count", "reference_count", "cycle_count",
                "total_network_bytes", "total_retained_bytes",
            )
        ],
        sa.Column("stop_reason", sa.String(128)),
        sa.Column("fatal_error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_refresh_id"], ["source_refreshes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_refresh_id"),
    )
    op.create_index("ix_ai_document_refreshes_source_refresh_id", "ai_document_refreshes", ["source_refresh_id"], unique=True)
    op.create_index("ix_ai_document_refreshes_status", "ai_document_refreshes", ["status"])
    op.create_table(
        "ai_document_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("refresh_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("parent_depth_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_role", sa.String(32), nullable=False),
        sa.Column("document_kind", sa.String(32), nullable=False),
        sa.Column("classification_rule", sa.String(64), nullable=False),
        sa.Column("fetch_state", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("normalized_mime_type", sa.String(255)),
        sa.Column("encoding", sa.String(64)),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column("redirect_chain", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("response_time_ms", sa.Integer()),
        sa.Column("declared_content_length", sa.Integer()),
        sa.Column("network_bytes_transferred", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retained_blob_id", sa.Integer()),
        sa.Column("raw_sha256", sa.String(64)),
        sa.Column("parsed_title", sa.Text()),
        sa.Column("parsed_summary", sa.Text()),
        sa.Column("parsed_intro", sa.Text()),
        sa.Column("parse_state", sa.String(32), nullable=False),
        sa.Column("parse_version", sa.String(64)),
        sa.Column("parse_warnings_json", sa.JSON(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("change_state", sa.String(32), nullable=False, server_default="new"),
        sa.Column("error_type", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["refresh_id"], ["ai_document_refreshes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["retained_blob_id"], ["ai_document_blobs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("refresh_id", "resource_id", name="uq_ai_snapshot_refresh_resource"),
    )
    for column in ("refresh_id", "resource_id", "parent_depth_min", "document_role", "document_kind", "fetch_state", "http_status", "normalized_mime_type", "fetched_at", "retained_blob_id", "raw_sha256", "parse_state", "warning_count", "change_state", "error_type"):
        op.create_index(f"ix_ai_document_snapshots_{column}", "ai_document_snapshots", [column])
    op.create_index("ix_ai_snapshot_refresh_kind_id", "ai_document_snapshots", ["refresh_id", "document_kind", "id"])
    op.create_table(
        "ai_document_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("target_resource_id", sa.Integer()),
        sa.Column("child_snapshot_id", sa.Integer()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.Text()), sa.Column("label", sa.Text()),
        sa.Column("description", sa.Text()), sa.Column("raw_url", sa.Text(), nullable=False),
        sa.Column("resolved_url", sa.Text()), sa.Column("normalized_target_url", sa.Text()),
        sa.Column("optional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("inferred_role", sa.String(32), nullable=False),
        sa.Column("inferred_kind", sa.String(32), nullable=False),
        sa.Column("classification_rule", sa.String(64), nullable=False),
        sa.Column("in_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope_decision", sa.String(64), nullable=False),
        sa.Column("exclusion_reason", sa.Text()),
        sa.Column("discovery_depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("forms_cycle", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("inventory_entry_id", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["parent_snapshot_id"], ["ai_document_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["child_snapshot_id"], ["ai_document_snapshots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inventory_entry_id"], ["url_source_entries.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("parent_snapshot_id", "position", name="uq_ai_reference_position"),
    )
    for column in ("parent_snapshot_id", "target_resource_id", "child_snapshot_id", "normalized_target_url", "optional", "inferred_role", "inferred_kind", "in_scope", "scope_decision", "discovery_depth", "forms_cycle", "inventory_entry_id"):
        op.create_index(f"ix_ai_document_references_{column}", "ai_document_references", [column])
    op.create_index("ix_ai_reference_parent_scope_id", "ai_document_references", ["parent_snapshot_id", "in_scope", "id"])
    op.create_table(
        "ai_document_validations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("refresh_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer()), sa.Column("reference_id", sa.Integer()),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["refresh_id"], ["ai_document_refreshes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["ai_document_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_id"], ["ai_document_references.id"], ondelete="CASCADE"),
    )
    for column in ("refresh_id", "snapshot_id", "reference_id", "severity", "code"):
        op.create_index(f"ix_ai_document_validations_{column}", "ai_document_validations", [column])


def downgrade() -> None:
    op.drop_table("ai_document_validations")
    op.drop_table("ai_document_references")
    op.drop_table("ai_document_snapshots")
    op.drop_table("ai_document_refreshes")
    op.drop_table("ai_document_blobs")
