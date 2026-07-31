"""saved sites

Revision ID: 202607300004
Revises: 202607290001
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607300004"
down_revision: str | None = "202607290001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "website_properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("normalized_base_url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("group_key", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=32), nullable=True),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("ownership_key", sa.String(length=64), nullable=False),
        sa.Column("scope_config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("normalized_base_url", name="uq_website_properties_base_url"),
    )
    op.create_index("ix_website_properties_group_key", "website_properties", ["group_key"])
    op.create_index("ix_website_properties_locale", "website_properties", ["locale"])
    op.create_index("ix_website_properties_platform_key", "website_properties", ["platform_key"])
    op.create_index("ix_website_properties_ownership_key", "website_properties", ["ownership_key"])
    op.create_index("ix_website_properties_is_active", "website_properties", ["is_active"])
    with op.batch_alter_table("scans") as batch_op:
        batch_op.add_column(sa.Column("website_property_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_scans_website_property_id",
            "website_properties",
            ["website_property_id"],
            ["id"],
        )
        batch_op.create_index("ix_scans_website_property_id", ["website_property_id"])


def downgrade() -> None:
    with op.batch_alter_table("scans") as batch_op:
        batch_op.drop_index("ix_scans_website_property_id")
        batch_op.drop_constraint("fk_scans_website_property_id", type_="foreignkey")
        batch_op.drop_column("website_property_id")
    op.drop_index("ix_website_properties_is_active", table_name="website_properties")
    op.drop_index("ix_website_properties_ownership_key", table_name="website_properties")
    op.drop_index("ix_website_properties_platform_key", table_name="website_properties")
    op.drop_index("ix_website_properties_locale", table_name="website_properties")
    op.drop_index("ix_website_properties_group_key", table_name="website_properties")
    op.drop_table("website_properties")
