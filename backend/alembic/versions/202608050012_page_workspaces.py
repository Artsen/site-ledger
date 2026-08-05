"""Add Site-scoped Page workspaces and link roles.

Revision ID: 202608050012
Revises: 5a2ba8ad44fd
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608050012"
down_revision: str | None = "5a2ba8ad44fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("owner_label", sa.String(length=128), nullable=True),
        sa.Column(
            "workflow_status", sa.String(length=32), server_default="unreviewed", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["resource_id"], ["web_resources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("website_property_id", "resource_id", name="uq_site_page_resource"),
    )
    op.create_index("ix_site_pages_website_property_id", "site_pages", ["website_property_id"])
    op.create_index("ix_site_pages_resource_id", "site_pages", ["resource_id"])
    op.create_index("ix_site_pages_workflow_status", "site_pages", ["workflow_status"])
    op.create_index(
        "ix_site_page_site_workflow",
        "site_pages",
        ["website_property_id", "workflow_status"],
    )

    # A Page becomes Site-associated only after an actual saved-site observation.
    op.execute(
        sa.text(
            """
            INSERT INTO site_pages (
                website_property_id, resource_id, owner_label, workflow_status,
                created_at, updated_at
            )
            SELECT
                scans.website_property_id,
                resource_snapshots.resource_id,
                NULL,
                'unreviewed',
                COALESCE(
                    MIN(resource_snapshots.fetched_at), MIN(scans.created_at), CURRENT_TIMESTAMP
                ),
                COALESCE(
                    MIN(resource_snapshots.fetched_at), MIN(scans.created_at), CURRENT_TIMESTAMP
                )
            FROM resource_snapshots
            JOIN scans ON scans.id = resource_snapshots.scan_id
            WHERE scans.website_property_id IS NOT NULL
            GROUP BY scans.website_property_id, resource_snapshots.resource_id
            """
        )
    )

    op.create_table(
        "page_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color_key", sa.String(length=16), server_default="stone", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_property_id", "normalized_name", name="uq_site_category_normalized_name"
        ),
    )
    op.create_index(
        "ix_page_categories_website_property_id", "page_categories", ["website_property_id"]
    )
    op.create_index(
        "ix_page_category_site_active",
        "page_categories",
        ["website_property_id", "is_active"],
    )
    op.create_table(
        "page_category_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_page_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["category_id"], ["page_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_page_id"], ["site_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_page_id", "category_id", name="uq_site_page_category"),
    )
    op.create_index(
        "ix_page_category_assignments_category_id", "page_category_assignments", ["category_id"]
    )
    op.create_index(
        "ix_page_category_assignments_site_page_id",
        "page_category_assignments",
        ["site_page_id"],
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_property_id", sa.Integer(), nullable=True),
        sa.Column("scan_id", sa.Integer(), nullable=True),
        sa.Column("site_page_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(website_property_id IS NOT NULL AND scan_id IS NULL AND site_page_id IS NULL) OR "
            "(website_property_id IS NULL AND scan_id IS NOT NULL AND site_page_id IS NULL) OR "
            "(website_property_id IS NULL AND scan_id IS NULL AND site_page_id IS NOT NULL)",
            name="ck_note_exactly_one_target",
        ),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_page_id"], ["site_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_note_site_updated", "notes", ["website_property_id", "updated_at"])
    op.create_index("ix_note_scan_updated", "notes", ["scan_id", "updated_at"])
    op.create_index("ix_note_site_page_updated", "notes", ["site_page_id", "updated_at"])

    with op.batch_alter_table("html_parse_anchors") as batch_op:
        batch_op.add_column(sa.Column("link_role", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("link_role_rule", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("link_context_json", sa.JSON(), nullable=True))
    with op.batch_alter_table("resource_occurrences") as batch_op:
        batch_op.add_column(sa.Column("link_role", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("link_role_rule", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("link_context_json", sa.JSON(), nullable=True))
    op.create_index(
        "ix_occurrence_source_role", "resource_occurrences", ["source_snapshot_id", "link_role"]
    )
    op.create_index(
        "ix_occurrence_target_role", "resource_occurrences", ["target_resource_id", "link_role"]
    )


def downgrade() -> None:
    op.drop_index("ix_occurrence_target_role", table_name="resource_occurrences")
    op.drop_index("ix_occurrence_source_role", table_name="resource_occurrences")
    with op.batch_alter_table("resource_occurrences") as batch_op:
        batch_op.drop_column("link_context_json")
        batch_op.drop_column("link_role_rule")
        batch_op.drop_column("link_role")
    with op.batch_alter_table("html_parse_anchors") as batch_op:
        batch_op.drop_column("link_context_json")
        batch_op.drop_column("link_role_rule")
        batch_op.drop_column("link_role")

    op.drop_index("ix_note_site_page_updated", table_name="notes")
    op.drop_index("ix_note_scan_updated", table_name="notes")
    op.drop_index("ix_note_site_updated", table_name="notes")
    op.drop_table("notes")
    op.drop_index(
        "ix_page_category_assignments_site_page_id", table_name="page_category_assignments"
    )
    op.drop_index(
        "ix_page_category_assignments_category_id", table_name="page_category_assignments"
    )
    op.drop_table("page_category_assignments")
    op.drop_index("ix_page_category_site_active", table_name="page_categories")
    op.drop_index("ix_page_categories_website_property_id", table_name="page_categories")
    op.drop_table("page_categories")
    op.drop_index("ix_site_page_site_workflow", table_name="site_pages")
    op.drop_index("ix_site_pages_workflow_status", table_name="site_pages")
    op.drop_index("ix_site_pages_resource_id", table_name="site_pages")
    op.drop_index("ix_site_pages_website_property_id", table_name="site_pages")
    op.drop_table("site_pages")
