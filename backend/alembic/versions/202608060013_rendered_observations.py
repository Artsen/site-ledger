"""Add bounded browser-rendered observations.

Revision ID: 202608060013
Revises: 202608050012
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608060013"
down_revision: str | None = "202608050012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("selected", "attempted", "completed", "failed", "skipped", "blocked_request", "artifact"):
        op.add_column("scans", sa.Column(f"rendered_{name}_count", sa.Integer(), server_default="0", nullable=False))
    op.create_table("artifact_blobs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True), sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("compression_type", sa.String(32), nullable=False), sa.Column("raw_byte_size", sa.Integer(), nullable=False),
        sa.Column("stored_byte_size", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("rendered_observations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("capture_state", sa.String(32), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("requested_url", sa.Text(), nullable=False), sa.Column("final_url", sa.Text()), sa.Column("navigation_http_status", sa.Integer()), sa.Column("document_title", sa.Text()),
        sa.Column("browser_engine", sa.String(32), nullable=False), sa.Column("browser_version", sa.String(128)), sa.Column("playwright_version", sa.String(64)),
        sa.Column("renderer_version", sa.String(32), nullable=False), sa.Column("browser_policy_version", sa.String(32), nullable=False), sa.Column("capture_schema_version", sa.String(32), nullable=False),
        sa.Column("user_agent", sa.Text()), sa.Column("viewport_width", sa.Integer(), nullable=False), sa.Column("viewport_height", sa.Integer(), nullable=False), sa.Column("device_scale_factor", sa.Float(), nullable=False),
        sa.Column("locale", sa.String(64), nullable=False), sa.Column("timezone_id", sa.String(128), nullable=False), sa.Column("color_scheme", sa.String(32), nullable=False), sa.Column("reduced_motion", sa.String(32), nullable=False),
        sa.Column("readiness_state", sa.String(64)), sa.Column("load_event_reached", sa.Boolean(), server_default=sa.false(), nullable=False), sa.Column("fonts_ready_reached", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("duration_ms", sa.Integer()), sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("network_entry_count", sa.Integer(), server_default="0", nullable=False), sa.Column("blocked_request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("console_message_count", sa.Integer(), server_default="0", nullable=False), sa.Column("page_error_count", sa.Integer(), server_default="0", nullable=False), sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("network_truncated", sa.Boolean(), server_default=sa.false(), nullable=False), sa.Column("console_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("page_errors_truncated", sa.Boolean(), server_default=sa.false(), nullable=False), sa.Column("warnings_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("total_encoded_network_bytes", sa.Integer(), server_default="0", nullable=False), sa.Column("error_type", sa.String(64)), sa.Column("error_message", sa.Text()), sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["resource_snapshots.id"], ondelete="CASCADE"), sa.UniqueConstraint("snapshot_id"))
    op.create_index("ix_rendered_observations_snapshot_id", "rendered_observations", ["snapshot_id"], unique=True)
    op.create_index("ix_rendered_observations_capture_state", "rendered_observations", ["capture_state"])
    op.create_table("rendered_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rendered_observation_id", sa.Integer(), nullable=False), sa.Column("artifact_blob_id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False), sa.Column("width", sa.Integer()), sa.Column("height", sa.Integer()), sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rendered_observation_id"], ["rendered_observations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["artifact_blob_id"], ["artifact_blobs.id"]),
        sa.UniqueConstraint("rendered_observation_id", "artifact_type", name="uq_rendered_artifact_type"))
    op.create_index("ix_rendered_artifacts_rendered_observation_id", "rendered_artifacts", ["rendered_observation_id"])
    op.create_index("ix_rendered_artifacts_artifact_blob_id", "rendered_artifacts", ["artifact_blob_id"])
    op.create_index("ix_rendered_artifacts_artifact_type", "rendered_artifacts", ["artifact_type"])
    _event_tables()


def _event_tables() -> None:
    op.create_table("rendered_network_entries",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rendered_observation_id", sa.Integer(), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False), sa.Column("redacted_url", sa.Text(), nullable=False), sa.Column("url_sha256", sa.String(64), nullable=False),
        sa.Column("method", sa.String(16), nullable=False), sa.Column("resource_type", sa.String(32)), sa.Column("is_main_navigation", sa.Boolean(), nullable=False), sa.Column("is_navigation_request", sa.Boolean(), nullable=False),
        sa.Column("request_started_offset_ms", sa.Integer()), sa.Column("duration_ms", sa.Integer()), sa.Column("response_status", sa.Integer()), sa.Column("response_status_text", sa.String(128)),
        sa.Column("response_mime_type", sa.String(255)), sa.Column("encoded_data_length", sa.Integer()), sa.Column("request_headers_json", sa.JSON(), nullable=False), sa.Column("response_headers_json", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text()), sa.Column("blocked_by_policy", sa.Boolean(), nullable=False), sa.Column("policy_reason", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rendered_observation_id"], ["rendered_observations.id"], ondelete="CASCADE"), sa.UniqueConstraint("rendered_observation_id", "sequence", name="uq_rendered_network_sequence"))
    op.create_index("ix_rendered_network_entries_rendered_observation_id", "rendered_network_entries", ["rendered_observation_id"])
    op.create_index("ix_rendered_network_entries_url_sha256", "rendered_network_entries", ["url_sha256"])
    op.create_index("ix_rendered_network_observation_resource", "rendered_network_entries", ["rendered_observation_id", "resource_type"])
    op.create_index("ix_rendered_network_observation_status", "rendered_network_entries", ["rendered_observation_id", "response_status"])
    op.create_index("ix_rendered_network_observation_blocked", "rendered_network_entries", ["rendered_observation_id", "blocked_by_policy"])
    for table, columns, unique in (
        ("rendered_console_messages", [sa.Column("message_type", sa.String(32), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("source_url", sa.Text()), sa.Column("line_number", sa.Integer()), sa.Column("column_number", sa.Integer())], "uq_rendered_console_sequence"),
        ("rendered_page_errors", [sa.Column("error_name", sa.String(128)), sa.Column("message", sa.Text(), nullable=False), sa.Column("stack", sa.Text()), sa.Column("source_url", sa.Text())], "uq_rendered_error_sequence")):
        op.create_table(table, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rendered_observation_id", sa.Integer(), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), *columns,
            sa.Column("timestamp_offset_ms", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["rendered_observation_id"], ["rendered_observations.id"], ondelete="CASCADE"), sa.UniqueConstraint("rendered_observation_id", "sequence", name=unique))
        op.create_index(f"ix_{table}_rendered_observation_id", table, ["rendered_observation_id"])
    op.create_index("ix_rendered_console_messages_message_type", "rendered_console_messages", ["message_type"])


def downgrade() -> None:
    for table in ("rendered_page_errors", "rendered_console_messages", "rendered_network_entries", "rendered_artifacts", "rendered_observations", "artifact_blobs"):
        op.drop_table(table)
    for name in ("artifact", "blocked_request", "skipped", "failed", "completed", "attempted", "selected"):
        op.drop_column("scans", f"rendered_{name}_count")
