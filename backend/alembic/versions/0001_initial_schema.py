"""初始化完整数据模型。

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-30
"""
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op
from app import models  # noqa: F401
from app.db import Base

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
