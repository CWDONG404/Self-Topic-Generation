"""持久化模型默认角色并修复文档证据约束。

Revision ID: 0002_contract_consistency
Revises: 0001_initial_schema
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_contract_consistency"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    model_profile_columns = {
        column["name"] for column in inspector.get_columns("model_profiles")
    }
    if "default_roles" not in model_profile_columns:
        op.add_column(
            "model_profiles",
            sa.Column(
                "default_roles",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )

    op.execute(
        sa.text(
            "UPDATE documents "
            "SET allow_as_evidence = true "
            "WHERE role = 'source' AND allow_as_evidence = false"
        )
    )
    check_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("documents")
        if constraint.get("name")
    }
    if "ck_documents_source_evidence" not in check_names:
        with op.batch_alter_table("documents") as batch_op:
            batch_op.create_check_constraint(
                "ck_documents_source_evidence",
                "role <> 'source' OR allow_as_evidence",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    check_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("documents")
        if constraint.get("name")
    }
    if "ck_documents_source_evidence" in check_names:
        with op.batch_alter_table("documents") as batch_op:
            batch_op.drop_constraint(
                "ck_documents_source_evidence",
                type_="check",
            )

    model_profile_columns = {
        column["name"] for column in inspector.get_columns("model_profiles")
    }
    if "default_roles" in model_profile_columns:
        op.drop_column("model_profiles", "default_roles")
