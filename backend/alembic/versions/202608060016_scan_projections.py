"""Add versioned terminal Scan projections.

Revision ID: 202608060016
Revises: 202608060015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608060016"
down_revision: str | None = "202608060015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_projection_builds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("projection_version", sa.String(64), nullable=False),
        sa.Column("algorithm_identity", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active_key", sa.String(255), unique=True),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resource_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("link_edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("graph_node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("graph_edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rendered_page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_snapshot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_link_occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "source_resource_reference_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("build_duration_ms", sa.Integer()),
        sa.Column("checksum_sha256", sa.String(64)),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scan_projection_builds_scan_id", "scan_projection_builds", ["scan_id"])
    op.create_index(
        "ix_scan_projection_builds_projection_version",
        "scan_projection_builds",
        ["projection_version"],
    )
    op.create_index("ix_scan_projection_builds_status", "scan_projection_builds", ["status"])
    op.create_index(
        "ix_projection_build_scan_version_status",
        "scan_projection_builds",
        ["scan_id", "projection_version", "status"],
    )
    op.create_index(
        "ix_scan_projection_builds_checksum_sha256",
        "scan_projection_builds",
        ["checksum_sha256"],
    )
    op.create_table(
        "scan_projection_states",
        sa.Column("scan_id", sa.Integer(), primary_key=True),
        sa.Column("current_build_id", sa.Integer(), unique=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_build_id"], ["scan_projection_builds.id"], ondelete="SET NULL"
        ),
    )
    _create_page_table()
    _create_resource_table()
    _create_link_table()
    _create_summary_table()


def _create_page_table() -> None:
    op.create_table(
        "scan_page_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("projection_build_id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("page_title", sa.Text()),
        sa.Column("crawl_depth", sa.Integer(), nullable=False),
        sa.Column("fetch_state", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_type", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("content_type", sa.Text()),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("head_hash", sa.String(64)),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("robots_directives", sa.Text()),
        sa.Column("language", sa.String(64)),
        sa.Column("redirects", sa.Boolean(), nullable=False),
        sa.Column("response_time_ms", sa.Integer()),
        sa.Column("network_bytes_transferred", sa.Integer()),
        sa.Column("raw_html_size", sa.Integer()),
        sa.Column("stored_html_size", sa.Integer()),
        sa.Column("inbound_source_page_count", sa.Integer(), nullable=False),
        sa.Column("inbound_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("outbound_target_count", sa.Integer(), nullable=False),
        sa.Column("outbound_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("embedded_resource_count", sa.Integer(), nullable=False),
        sa.Column("discovery_source", sa.Text()),
        sa.Column("is_seed", sa.Boolean(), nullable=False),
        sa.Column("seed_origin_count", sa.Integer(), nullable=False),
        sa.Column("is_starting_page", sa.Boolean(), nullable=False),
        sa.Column("rendered_capture_state", sa.String(32)),
        sa.Column("rendered_network_count", sa.Integer(), nullable=False),
        sa.Column("rendered_console_count", sa.Integer(), nullable=False),
        sa.Column("rendered_page_error_count", sa.Integer(), nullable=False),
        sa.Column("rendered_artifact_count", sa.Integer(), nullable=False),
        sa.Column("rendered_captured_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["projection_build_id"], ["scan_projection_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["resource_snapshots.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["web_resources.id"]),
        sa.UniqueConstraint(
            "projection_build_id", "snapshot_id", name="uq_projection_page_snapshot"
        ),
    )
    _indexes(
        "scan_page_projections",
        "projection_page",
        {
            "url": ["projection_build_id", "normalized_url"],
            "status": ["projection_build_id", "http_status"],
            "fetch": ["projection_build_id", "fetch_state"],
            "depth": ["projection_build_id", "crawl_depth"],
            "resource": ["projection_build_id", "resource_id"],
            "snapshot": ["projection_build_id", "snapshot_id"],
            "fetched": ["projection_build_id", "fetched_at"],
        },
    )
    op.create_index("ix_scan_page_projections_scan_id", "scan_page_projections", ["scan_id"])
    op.create_index(
        "ix_scan_page_projections_projection_build_id",
        "scan_page_projections",
        ["projection_build_id"],
    )


def _create_resource_table() -> None:
    op.create_table(
        "scan_resource_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("projection_build_id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("file_extension", sa.String(32)),
        sa.Column("effective_kind", sa.String(32), nullable=False),
        sa.Column("classification_source", sa.String(64), nullable=False),
        sa.Column("observed", sa.Boolean(), nullable=False),
        sa.Column("discovered_only", sa.Boolean(), nullable=False),
        sa.Column("latest_snapshot_id", sa.Integer()),
        sa.Column("final_url", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("normalized_mime_type", sa.String(255)),
        sa.Column("content_disposition_filename", sa.String(255)),
        sa.Column("declared_content_length", sa.Integer()),
        sa.Column("network_bytes_transferred", sa.Integer()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("response_time_ms", sa.Integer()),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("source_page_count", sa.Integer(), nullable=False),
        sa.Column("anchor_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("embedded_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("in_scope_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("out_of_scope_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True)),
        sa.Column("latest_discovered_at", sa.DateTime(timezone=True)),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["projection_build_id"], ["scan_projection_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["latest_snapshot_id"], ["resource_snapshots.id"]),
        sa.UniqueConstraint("projection_build_id", "resource_id", name="uq_projection_resource"),
    )
    _indexes(
        "scan_resource_projections",
        "projection_resource",
        {
            "url": ["projection_build_id", "normalized_url"],
            "kind": ["projection_build_id", "effective_kind"],
            "observed": ["projection_build_id", "observed"],
            "mime": ["projection_build_id", "normalized_mime_type"],
            "extension": ["projection_build_id", "file_extension"],
            "host": ["projection_build_id", "host"],
            "status": ["projection_build_id", "http_status"],
            "occurrences": ["projection_build_id", "occurrence_count"],
            "sources": ["projection_build_id", "source_page_count"],
            "latest": ["projection_build_id", "latest_discovered_at"],
        },
    )
    op.create_index(
        "ix_scan_resource_projections_scan_id", "scan_resource_projections", ["scan_id"]
    )
    op.create_index(
        "ix_scan_resource_projections_projection_build_id",
        "scan_resource_projections",
        ["projection_build_id"],
    )


def _create_link_table() -> None:
    op.create_table(
        "scan_link_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("projection_build_id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("source_resource_id", sa.Integer(), nullable=False),
        sa.Column("target_resource_id", sa.Integer(), nullable=False),
        sa.Column("target_snapshot_id", sa.Integer()),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("unique_anchor_count", sa.Integer(), nullable=False),
        sa.Column("empty_anchor_count", sa.Integer(), nullable=False),
        sa.Column("follow_count", sa.Integer(), nullable=False),
        sa.Column("nofollow_count", sa.Integer(), nullable=False),
        sa.Column("self_link", sa.Boolean(), nullable=False),
        sa.Column("in_scope_count", sa.Integer(), nullable=False),
        sa.Column("out_of_scope_count", sa.Integer(), nullable=False),
        sa.Column("role_counts_json", sa.JSON(), nullable=False),
        sa.Column("scope_counts_json", sa.JSON(), nullable=False),
        sa.Column("dom_regions_json", sa.JSON(), nullable=False),
        sa.Column("sample_anchors_json", sa.JSON(), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True)),
        sa.Column("latest_discovered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["projection_build_id"], ["scan_projection_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_snapshot_id"], ["resource_snapshots.id"]),
        sa.ForeignKeyConstraint(["source_resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["target_resource_id"], ["web_resources.id"]),
        sa.ForeignKeyConstraint(["target_snapshot_id"], ["resource_snapshots.id"]),
        sa.UniqueConstraint(
            "projection_build_id",
            "source_snapshot_id",
            "target_resource_id",
            name="uq_projection_link_edge",
        ),
    )
    _indexes(
        "scan_link_projections",
        "projection_link",
        {
            "source": ["projection_build_id", "source_snapshot_id"],
            "target": ["projection_build_id", "target_resource_id"],
            "target_snapshot": ["projection_build_id", "target_snapshot_id"],
            "occurrences": ["projection_build_id", "occurrence_count"],
        },
    )
    op.create_index("ix_scan_link_projections_scan_id", "scan_link_projections", ["scan_id"])
    op.create_index(
        "ix_scan_link_projections_projection_build_id",
        "scan_link_projections",
        ["projection_build_id"],
    )


def _create_summary_table() -> None:
    op.create_table(
        "scan_summary_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("projection_build_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("page_total", sa.Integer(), nullable=False),
        sa.Column("successful_page_total", sa.Integer(), nullable=False),
        sa.Column("failed_page_total", sa.Integer(), nullable=False),
        sa.Column("resource_total", sa.Integer(), nullable=False),
        sa.Column("observed_resource_total", sa.Integer(), nullable=False),
        sa.Column("discovered_only_resource_total", sa.Integer(), nullable=False),
        sa.Column("resource_occurrence_total", sa.Integer(), nullable=False),
        sa.Column("link_occurrence_total", sa.Integer(), nullable=False),
        sa.Column("link_edge_total", sa.Integer(), nullable=False),
        sa.Column("rendered_page_total", sa.Integer(), nullable=False),
        sa.Column("rendered_artifact_total", sa.Integer(), nullable=False),
        sa.Column("retry_total", sa.Integer(), nullable=False),
        sa.Column("recovered_page_total", sa.Integer(), nullable=False),
        sa.Column("error_counts_json", sa.JSON(), nullable=False),
        sa.Column("status_counts_json", sa.JSON(), nullable=False),
        sa.Column("resource_kind_counts_json", sa.JSON(), nullable=False),
        sa.Column("http_status_counts_json", sa.JSON(), nullable=False),
        sa.Column("depth_counts_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["projection_build_id"], ["scan_projection_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scan_summary_projections_scan_id", "scan_summary_projections", ["scan_id"])


def _indexes(table: str, prefix: str, definitions: dict[str, list[str]]) -> None:
    for suffix, columns in definitions.items():
        op.create_index(f"ix_{prefix}_build_{suffix}", table, columns)


def downgrade() -> None:
    op.drop_table("scan_summary_projections")
    op.drop_table("scan_link_projections")
    op.drop_table("scan_resource_projections")
    op.drop_table("scan_page_projections")
    op.drop_table("scan_projection_states")
    op.drop_table("scan_projection_builds")
