"""prepare versioned URL identity and guarded V2 migration

Revision ID: 202608140023
Revises: 202608130022
Create Date: 2026-08-14 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608140023"
down_revision: str | None = "202608130022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V1 = "url-normalization-v1"
V2 = "url-normalization-v2"


def upgrade() -> None:
    connection = op.get_bind()
    historical_resource_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM web_resources")
    ).scalar_one()

    with op.batch_alter_table("web_resources") as batch:
        batch.add_column(
            sa.Column(
                "normalization_version",
                sa.String(length=64),
                nullable=False,
                server_default=V1,
            )
        )
        batch.drop_index("ux_web_resources_normalized_url")
        batch.drop_constraint("uq_resource_type_url", type_="unique")
        batch.create_unique_constraint(
            "uq_web_resource_version_url",
            ["normalization_version", "normalized_url"],
        )
        batch.create_index("ix_web_resources_normalization_version", ["normalization_version"])
        batch.create_index("ix_web_resources_version_host", ["normalization_version", "host"])

    with op.batch_alter_table("scans") as batch:
        batch.add_column(
            sa.Column(
                "url_normalization_version",
                sa.String(length=64),
                nullable=False,
                server_default=V1,
            )
        )
        batch.create_index("ix_scans_url_normalization_version", ["url_normalization_version"])

    op.create_table(
        "url_identity_migrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("implementation_version", sa.String(length=64), nullable=False),
        sa.Column("reconciliation_schema_version", sa.String(length=64), nullable=False),
        sa.Column("source_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("target_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("reconciliation_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("reconciliation_source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("operation_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("backup_metadata_json", sa.JSON(), nullable=False),
        sa.Column("pre_migration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("post_migration_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("post_migration_write_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_url_identity_migrations_reconciliation_manifest_sha256",
        "url_identity_migrations",
        ["reconciliation_manifest_sha256"],
    )
    op.create_index("ix_url_identity_migrations_status", "url_identity_migrations", ["status"])

    op.create_table(
        "url_identity_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("reconciliation_required", sa.Boolean(), nullable=False),
        sa.Column("active_migration_id", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_url_identity_state_singleton"),
        sa.ForeignKeyConstraint(
            ["active_migration_id"], ["url_identity_migrations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "url_identity_migration_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("migration_id", sa.Integer(), nullable=False),
        sa.Column("old_resource_id", sa.Integer(), nullable=False),
        sa.Column("new_resource_id", sa.Integer(), nullable=False),
        sa.Column("mapping_kind", sa.String(length=32), nullable=False),
        sa.Column("candidate_identity_hash", sa.String(length=64), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("source_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("target_normalization_version", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["url_identity_migrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["new_resource_id"], ["web_resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "migration_id",
            "old_resource_id",
            "new_resource_id",
            name="uq_url_identity_migration_mapping",
        ),
    )
    op.create_index(
        "ix_url_identity_migration_mappings_migration_id",
        "url_identity_migration_mappings",
        ["migration_id"],
    )
    op.create_index(
        "ix_url_identity_migration_mappings_old_resource_id",
        "url_identity_migration_mappings",
        ["old_resource_id"],
    )
    op.create_index(
        "ix_url_identity_migration_mappings_new_resource_id",
        "url_identity_migration_mappings",
        ["new_resource_id"],
    )
    op.create_index(
        "ix_url_identity_migration_mappings_mapping_kind",
        "url_identity_migration_mappings",
        ["mapping_kind"],
    )

    op.create_table(
        "web_resource_aliases",
        sa.Column("legacy_resource_id", sa.Integer(), nullable=False),
        sa.Column("target_resource_id", sa.Integer(), nullable=False),
        sa.Column("migration_id", sa.Integer(), nullable=False),
        sa.Column("alias_reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["url_identity_migrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["target_resource_id"], ["web_resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("legacy_resource_id"),
    )
    op.create_index(
        "ix_web_resource_aliases_target_resource_id",
        "web_resource_aliases",
        ["target_resource_id"],
    )
    op.create_index(
        "ix_web_resource_aliases_migration_id", "web_resource_aliases", ["migration_id"]
    )

    active_version = V1 if historical_resource_count else V2
    connection.execute(
        sa.text(
            "INSERT INTO url_identity_state "
            "(id, active_normalization_version, reconciliation_required, activated_at) "
            "VALUES (1, :version, :required, CURRENT_TIMESTAMP)"
        ),
        {"version": active_version, "required": bool(historical_resource_count)},
    )


def downgrade() -> None:
    connection = op.get_bind()
    active_version = connection.execute(
        sa.text("SELECT active_normalization_version FROM url_identity_state WHERE id = 1")
    ).scalar_one_or_none()
    if active_version == V2:
        raise RuntimeError(
            "Cannot downgrade URL identity schema while url-normalization-v2 is active. "
            "Restore a verified pre-migration backup instead."
        )
    duplicate_count = connection.execute(
        sa.text("SELECT COUNT(*) - COUNT(DISTINCT normalized_url) FROM web_resources")
    ).scalar_one()
    if duplicate_count:
        raise RuntimeError("Cannot restore global normalized_url uniqueness with duplicate URLs.")

    op.drop_index("ix_web_resource_aliases_migration_id", table_name="web_resource_aliases")
    op.drop_index("ix_web_resource_aliases_target_resource_id", table_name="web_resource_aliases")
    op.drop_table("web_resource_aliases")
    op.drop_index(
        "ix_url_identity_migration_mappings_mapping_kind",
        table_name="url_identity_migration_mappings",
    )
    op.drop_index(
        "ix_url_identity_migration_mappings_new_resource_id",
        table_name="url_identity_migration_mappings",
    )
    op.drop_index(
        "ix_url_identity_migration_mappings_old_resource_id",
        table_name="url_identity_migration_mappings",
    )
    op.drop_index(
        "ix_url_identity_migration_mappings_migration_id",
        table_name="url_identity_migration_mappings",
    )
    op.drop_table("url_identity_migration_mappings")
    op.drop_table("url_identity_state")
    op.drop_index("ix_url_identity_migrations_status", table_name="url_identity_migrations")
    op.drop_index(
        "ix_url_identity_migrations_reconciliation_manifest_sha256",
        table_name="url_identity_migrations",
    )
    op.drop_table("url_identity_migrations")

    with op.batch_alter_table("scans") as batch:
        batch.drop_index("ix_scans_url_normalization_version")
        batch.drop_column("url_normalization_version")
    with op.batch_alter_table("web_resources") as batch:
        batch.drop_index("ix_web_resources_version_host")
        batch.drop_index("ix_web_resources_normalization_version")
        batch.drop_constraint("uq_web_resource_version_url", type_="unique")
        batch.drop_column("normalization_version")
        batch.create_unique_constraint("uq_resource_type_url", ["resource_type", "normalized_url"])
        batch.create_index("ux_web_resources_normalized_url", ["normalized_url"], unique=True)
