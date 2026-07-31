"""Add URL source inventory and scan seeds.

Revision ID: 202607310006
Revises: 202607300004
Create Date: 2026-07-31 01:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607310006"
down_revision: str | None = "202607300004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "url_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("parent_source_id", sa.Integer(), nullable=True),
        sa.Column("root_source_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("normalized_source_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("discovery_mode", sa.String(length=64), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("last_refresh_status", sa.String(length=32), nullable=True),
        sa.Column("last_refresh_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_type", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_source_id"], ["url_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["root_source_id"], ["url_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_property_id"], ["website_properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_property_id",
            "source_type",
            "normalized_source_url",
            name="uq_site_source_type_url",
        ),
    )
    op.create_index("ix_url_sources_website_property_id", "url_sources", ["website_property_id"])
    op.create_index("ix_url_sources_parent_source_id", "url_sources", ["parent_source_id"])
    op.create_index("ix_url_sources_root_source_id", "url_sources", ["root_source_id"])
    op.create_index("ix_url_sources_source_type", "url_sources", ["source_type"])
    op.create_index("ix_url_sources_is_active", "url_sources", ["is_active"])
    op.create_index("ix_url_sources_discovery_mode", "url_sources", ["discovery_mode"])
    op.create_index("ix_url_sources_last_refresh_status", "url_sources", ["last_refresh_status"])
    op.create_index("ix_url_sources_last_error_type", "url_sources", ["last_error_type"])

    op.create_table(
        "source_refreshes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url_source_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("discovered_entry_count", sa.Integer(), nullable=False),
        sa.Column("accepted_entry_count", sa.Integer(), nullable=False),
        sa.Column("rejected_entry_count", sa.Integer(), nullable=False),
        sa.Column("child_source_count", sa.Integer(), nullable=False),
        sa.Column("entries_added", sa.Integer(), nullable=False),
        sa.Column("entries_updated", sa.Integer(), nullable=False),
        sa.Column("entries_no_longer_current", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["url_source_id"], ["url_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_refreshes_url_source_id", "source_refreshes", ["url_source_id"])
    op.create_index("ix_source_refreshes_status", "source_refreshes", ["status"])
    op.create_index("ix_source_refreshes_error_type", "source_refreshes", ["error_type"])

    op.create_table(
        "url_source_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url_source_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("normalized_url", sa.Text(), nullable=True),
        sa.Column("raw_url", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_refresh_id", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("sitemap_lastmod", sa.Text(), nullable=True),
        sa.Column("sitemap_changefreq", sa.String(length=32), nullable=True),
        sa.Column("sitemap_priority", sa.String(length=32), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=False),
        sa.Column("validation_state", sa.String(length=32), nullable=False),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("scope_decision", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["last_refresh_id"], ["source_refreshes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["url_source_id"], ["url_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_source_id", "normalized_url", name="uq_source_normalized_entry"),
    )
    op.create_index("ix_url_source_entries_url_source_id", "url_source_entries", ["url_source_id"])
    op.create_index("ix_url_source_entries_resource_id", "url_source_entries", ["resource_id"])
    op.create_index("ix_url_source_entries_normalized_url", "url_source_entries", ["normalized_url"])
    op.create_index("ix_url_source_entries_last_refresh_id", "url_source_entries", ["last_refresh_id"])
    op.create_index("ix_url_source_entries_is_current", "url_source_entries", ["is_current"])
    op.create_index("ix_url_source_entries_validation_state", "url_source_entries", ["validation_state"])
    op.create_index("ix_url_source_entries_scope_decision", "url_source_entries", ["scope_decision"])
    op.create_index("ix_source_entry_source_current", "url_source_entries", ["url_source_id", "is_current"])

    op.create_table(
        "scan_seeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("normalized_url", sa.Text(), nullable=True),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("queue_state", sa.String(length=32), nullable=False),
        sa.Column("scope_decision", sa.String(length=64), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "normalized_url", name="uq_scan_seed_url"),
    )
    op.create_index("ix_scan_seeds_scan_id", "scan_seeds", ["scan_id"])
    op.create_index("ix_scan_seeds_resource_id", "scan_seeds", ["resource_id"])
    op.create_index("ix_scan_seeds_normalized_url", "scan_seeds", ["normalized_url"])
    op.create_index("ix_scan_seeds_queue_state", "scan_seeds", ["queue_state"])
    op.create_index("ix_scan_seeds_scope_decision", "scan_seeds", ["scope_decision"])

    op.create_table(
        "scan_seed_origins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_seed_id", sa.Integer(), nullable=False),
        sa.Column("origin_type", sa.String(length=32), nullable=False),
        sa.Column("url_source_id", sa.Integer(), nullable=True),
        sa.Column("url_source_entry_id", sa.Integer(), nullable=True),
        sa.Column("source_refresh_id", sa.Integer(), nullable=True),
        sa.Column("raw_url", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["scan_seed_id"], ["scan_seeds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_refresh_id"], ["source_refreshes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["url_source_entry_id"], ["url_source_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["url_source_id"], ["url_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_seed_origins_scan_seed_id", "scan_seed_origins", ["scan_seed_id"])
    op.create_index("ix_scan_seed_origins_origin_type", "scan_seed_origins", ["origin_type"])


def downgrade() -> None:
    op.drop_index("ix_scan_seed_origins_origin_type", table_name="scan_seed_origins")
    op.drop_index("ix_scan_seed_origins_scan_seed_id", table_name="scan_seed_origins")
    op.drop_table("scan_seed_origins")
    op.drop_index("ix_scan_seeds_scope_decision", table_name="scan_seeds")
    op.drop_index("ix_scan_seeds_queue_state", table_name="scan_seeds")
    op.drop_index("ix_scan_seeds_normalized_url", table_name="scan_seeds")
    op.drop_index("ix_scan_seeds_resource_id", table_name="scan_seeds")
    op.drop_index("ix_scan_seeds_scan_id", table_name="scan_seeds")
    op.drop_table("scan_seeds")
    op.drop_index("ix_source_entry_source_current", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_scope_decision", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_validation_state", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_is_current", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_last_refresh_id", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_normalized_url", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_resource_id", table_name="url_source_entries")
    op.drop_index("ix_url_source_entries_url_source_id", table_name="url_source_entries")
    op.drop_table("url_source_entries")
    op.drop_index("ix_source_refreshes_error_type", table_name="source_refreshes")
    op.drop_index("ix_source_refreshes_status", table_name="source_refreshes")
    op.drop_index("ix_source_refreshes_url_source_id", table_name="source_refreshes")
    op.drop_table("source_refreshes")
    op.drop_index("ix_url_sources_last_error_type", table_name="url_sources")
    op.drop_index("ix_url_sources_last_refresh_status", table_name="url_sources")
    op.drop_index("ix_url_sources_discovery_mode", table_name="url_sources")
    op.drop_index("ix_url_sources_is_active", table_name="url_sources")
    op.drop_index("ix_url_sources_source_type", table_name="url_sources")
    op.drop_index("ix_url_sources_root_source_id", table_name="url_sources")
    op.drop_index("ix_url_sources_parent_source_id", table_name="url_sources")
    op.drop_index("ix_url_sources_website_property_id", table_name="url_sources")
    op.drop_table("url_sources")
