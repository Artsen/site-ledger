"""Add Page category rules and Site display timezone.

Revision ID: 202608060017
Revises: 202608060016
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608060017"
down_revision: str | None = "202608060016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("website_properties", sa.Column("display_timezone", sa.String(255)))
    _create_rules()
    _create_supports_and_exclusions()
    _create_history()
    op.execute(
        sa.text(
            """
            INSERT INTO page_category_assignment_supports
                (page_category_assignment_id, support_type, rule_id, support_key,
                 created_at, updated_at)
            SELECT id, 'manual', NULL, 'manual', assigned_at, assigned_at
            FROM page_category_assignments
            """
        )
    )
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL AND website_property_id IS NOT NULL "
            "AND job_type = 'category_rule_evaluation')",
        )


def _create_rules() -> None:
    op.create_table(
        "page_category_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("match_mode", sa.String(8), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("current_match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("match_mode IN ('all', 'any')", name="ck_category_rule_match_mode"),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["category_id"], ["page_categories.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_page_category_rules_website_property_id", "page_category_rules", ["website_property_id"]
    )
    op.create_index("ix_page_category_rules_category_id", "page_category_rules", ["category_id"])
    op.create_index("ix_page_category_rules_is_active", "page_category_rules", ["is_active"])
    op.create_index(
        "ix_category_rule_site_active", "page_category_rules", ["website_property_id", "is_active"]
    )
    op.create_index(
        "ix_category_rule_site_category",
        "page_category_rules",
        ["website_property_id", "category_id"],
    )
    op.create_table(
        "page_category_rule_conditions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("negate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "target IN ('normalized_url','host','path','query','filename')",
            name="ck_category_rule_condition_target",
        ),
        sa.CheckConstraint(
            "operator IN ('equals','starts_with','ends_with','contains','glob','regex')",
            name="ck_category_rule_condition_operator",
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["page_category_rules.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_page_category_rule_conditions_rule_id", "page_category_rule_conditions", ["rule_id"]
    )
    op.create_index(
        "ix_category_rule_condition_order",
        "page_category_rule_conditions",
        ["rule_id", "sort_order", "id"],
    )


def _create_supports_and_exclusions() -> None:
    op.create_table(
        "page_category_assignment_supports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_category_assignment_id", sa.Integer(), nullable=False),
        sa.Column("support_type", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.Integer()),
        sa.Column("support_key", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(support_type = 'manual' AND rule_id IS NULL AND support_key = 'manual') OR "
            "(support_type = 'rule' AND rule_id IS NOT NULL)",
            name="ck_category_assignment_support_source",
        ),
        sa.ForeignKeyConstraint(
            ["page_category_assignment_id"], ["page_category_assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["page_category_rules.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "page_category_assignment_id", "support_key", name="uq_assignment_support_key"
        ),
    )
    op.create_index(
        "ix_page_category_assignment_supports_page_category_assignment_id",
        "page_category_assignment_supports",
        ["page_category_assignment_id"],
    )
    op.create_index(
        "ix_page_category_assignment_supports_rule_id",
        "page_category_assignment_supports",
        ["rule_id"],
    )
    op.create_index(
        "ix_category_assignment_support_rule_assignment",
        "page_category_assignment_supports",
        ["rule_id", "page_category_assignment_id"],
    )
    op.create_table(
        "page_category_automatic_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_page_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["site_page_id"], ["site_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["page_categories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("site_page_id", "category_id", name="uq_page_category_auto_exclusion"),
    )
    op.create_index(
        "ix_page_category_automatic_exclusions_site_page_id",
        "page_category_automatic_exclusions",
        ["site_page_id"],
    )
    op.create_index(
        "ix_page_category_automatic_exclusions_category_id",
        "page_category_automatic_exclusions",
        ["category_id"],
    )


def _create_history() -> None:
    op.create_table(
        "page_category_rule_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("trigger_rule_id", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *[
            sa.Column(name, sa.Integer(), nullable=False, server_default="0")
            for name in (
                "page_count",
                "rule_count",
                "condition_count",
                "match_count",
                "rule_supports_added",
                "rule_supports_removed",
                "effective_assignments_added",
                "effective_assignments_removed",
                "exclusions_suppressing_matches",
                "unchanged_count",
            )
        ],
        sa.Column("error_type", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("evaluator_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_rule_id"], ["page_category_rules.id"], ondelete="SET NULL"
        ),
    )
    for column in ("website_property_id", "trigger_rule_id", "trigger_type", "status"):
        op.create_index(f"ix_page_category_rule_runs_{column}", "page_category_rule_runs", [column])
    op.create_index(
        "ix_category_rule_run_site_created",
        "page_category_rule_runs",
        ["website_property_id", "created_at"],
    )
    op.create_table(
        "page_category_rule_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer()),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('created','updated','enabled','disabled','deleted')",
            name="ck_category_rule_revision_action",
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["page_category_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["category_id"], ["page_categories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("rule_id", "revision_number", name="uq_category_rule_revision"),
    )
    for column in ("rule_id", "website_property_id", "category_id"):
        op.create_index(
            f"ix_page_category_rule_revisions_{column}", "page_category_rule_revisions", [column]
        )


def downgrade() -> None:
    op.execute("DELETE FROM background_jobs WHERE job_type = 'category_rule_evaluation'")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL)",
        )
    for table in (
        "page_category_rule_revisions",
        "page_category_rule_runs",
        "page_category_automatic_exclusions",
        "page_category_assignment_supports",
        "page_category_rule_conditions",
        "page_category_rules",
    ):
        op.drop_table(table)
    op.drop_column("website_properties", "display_timezone")
