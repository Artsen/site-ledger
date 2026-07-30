"""initial scanner schema

Revision ID: 202607290001
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607290001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("starting_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scope_config", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("queued_count", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(length=128), nullable=True),
        sa.Column("fatal_error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_scans_status", "scans", ["status"])

    op.create_table(
        "web_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("scheme", sa.String(length=16), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("resource_type", "normalized_url", name="uq_resource_type_url"),
    )
    op.create_index("ix_web_resources_host", "web_resources", ["host"])
    op.create_index("ix_web_resources_scheme", "web_resources", ["scheme"])

    op.create_table(
        "content_blobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("compression_type", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("encoding", sa.String(length=64), nullable=True),
        sa.Column("raw_byte_size", sa.Integer(), nullable=False),
        sa.Column("stored_byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("sha256"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_table(
        "resource_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id", sa.Integer(), sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("web_resources.id"), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("encoding", sa.String(length=64), nullable=True),
        sa.Column("crawl_depth", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.Column("redirect_chain", sa.JSON(), nullable=True),
        sa.Column("html_blob_id", sa.Integer(), sa.ForeignKey("content_blobs.id"), nullable=True),
        sa.Column("raw_html_sha256", sa.String(length=64), nullable=True),
        sa.Column("head_sha256", sa.String(length=64), nullable=True),
        sa.Column("page_title", sa.Text(), nullable=True),
        sa.Column("html_language", sa.String(length=64), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_robots", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("parsed_head_json", sa.JSON(), nullable=True),
        sa.Column("fetch_state", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_resource_snapshots_scan_id", "resource_snapshots", ["scan_id"])
    op.create_index("ix_resource_snapshots_resource_id", "resource_snapshots", ["resource_id"])
    op.create_index("ix_resource_snapshots_http_status", "resource_snapshots", ["http_status"])
    op.create_index("ix_resource_snapshots_crawl_depth", "resource_snapshots", ["crawl_depth"])
    op.create_index(
        "ix_resource_snapshots_raw_html_sha256", "resource_snapshots", ["raw_html_sha256"]
    )
    op.create_index("ix_resource_snapshots_fetch_state", "resource_snapshots", ["fetch_state"])
    op.create_index("ix_resource_snapshots_error_type", "resource_snapshots", ["error_type"])
    op.create_index("ix_snapshot_scan_resource", "resource_snapshots", ["scan_id", "resource_id"])

    op.create_table(
        "resource_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("resource_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("raw_href", sa.Text(), nullable=True),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("normalized_target_url", sa.Text(), nullable=True),
        sa.Column(
            "target_resource_id", sa.Integer(), sa.ForeignKey("web_resources.id"), nullable=True
        ),
        sa.Column("anchor_text", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("aria_label", sa.Text(), nullable=True),
        sa.Column("rel", sa.Text(), nullable=True),
        sa.Column("target", sa.String(length=128), nullable=True),
        sa.Column("dom_path", sa.Text(), nullable=True),
        sa.Column("in_scope", sa.Boolean(), nullable=False),
        sa.Column("scope_decision", sa.String(length=64), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_resource_occurrences_source_snapshot_id", "resource_occurrences", ["source_snapshot_id"]
    )
    op.create_index(
        "ix_resource_occurrences_relation_type", "resource_occurrences", ["relation_type"]
    )
    op.create_index(
        "ix_resource_occurrences_normalized_target_url",
        "resource_occurrences",
        ["normalized_target_url"],
    )
    op.create_index(
        "ix_resource_occurrences_target_resource_id", "resource_occurrences", ["target_resource_id"]
    )
    op.create_index(
        "ix_resource_occurrences_scope_decision", "resource_occurrences", ["scope_decision"]
    )
    op.create_index(
        "ix_occurrence_source_target",
        "resource_occurrences",
        ["source_snapshot_id", "target_resource_id"],
    )


def downgrade() -> None:
    op.drop_table("resource_occurrences")
    op.drop_table("resource_snapshots")
    op.drop_table("content_blobs")
    op.drop_table("web_resources")
    op.drop_table("scans")
