"""Add canonical Structured Content V2 nodes.

Revision ID: 202608270027
Revises: 202608260026
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608270027"
down_revision: str | None = "202608260026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("html_structured_content_artifacts") as batch:
        batch.add_column(sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("canonical_document_sha256", sa.String(64)))
        batch.add_column(sa.Column("markdown_renderer_version", sa.String(64)))
        batch.add_column(sa.Column("markdown_sha256", sa.String(64)))
        batch.add_column(sa.Column("markdown_character_count", sa.Integer()))
        batch.create_index(
            "ix_html_structured_content_artifacts_canonical_document_sha256",
            ["canonical_document_sha256"],
        )
        batch.create_index(
            "ix_html_structured_content_artifacts_markdown_renderer_version",
            ["markdown_renderer_version"],
        )
        batch.create_index(
            "ix_html_structured_content_artifacts_markdown_sha256", ["markdown_sha256"]
        )

    op.create_table(
        "html_structured_content_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("html_structured_content_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "parent_node_id",
            sa.Integer(),
            sa.ForeignKey("html_structured_content_nodes.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("source_tag", sa.String(128)),
        sa.Column("source_dom_path", sa.Text()),
        sa.Column("region_key", sa.String(32), nullable=False),
        sa.Column("region_dom_path", sa.Text()),
        sa.Column("text", sa.Text()),
        sa.Column("inline_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_attributes_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("semantic_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("semantic_sha256", sa.String(64), nullable=False),
        sa.Column("subtree_sha256", sa.String(64), nullable=False),
        sa.Column("child_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("descendant_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("artifact_id", "position", name="uq_structured_node_position"),
    )
    for column in (
        "artifact_id",
        "parent_node_id",
        "kind",
        "region_key",
        "semantic_sha256",
        "subtree_sha256",
    ):
        op.create_index(
            f"ix_html_structured_content_nodes_{column}", "html_structured_content_nodes", [column]
        )
    op.create_index(
        "ix_html_structured_content_nodes_artifact_position",
        "html_structured_content_nodes",
        ["artifact_id", "position"],
    )
    op.create_index(
        "ix_html_structured_content_nodes_artifact_parent_position",
        "html_structured_content_nodes",
        ["artifact_id", "parent_node_id", "position"],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM html_structured_content_nodes WHERE artifact_id IN ("
            "SELECT id FROM html_structured_content_artifacts "
            "WHERE extractor_version = 'structured-content-v2' "
            "AND extractor_config_version = 'canonical-document-v1')"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM html_structured_content_artifacts "
            "WHERE extractor_version = 'structured-content-v2' "
            "AND extractor_config_version = 'canonical-document-v1'"
        )
    )
    op.drop_table("html_structured_content_nodes")
    with op.batch_alter_table("html_structured_content_artifacts") as batch:
        batch.drop_index("ix_html_structured_content_artifacts_markdown_sha256")
        batch.drop_index("ix_html_structured_content_artifacts_markdown_renderer_version")
        batch.drop_index("ix_html_structured_content_artifacts_canonical_document_sha256")
        batch.drop_column("markdown_character_count")
        batch.drop_column("markdown_sha256")
        batch.drop_column("markdown_renderer_version")
        batch.drop_column("canonical_document_sha256")
        batch.drop_column("node_count")
