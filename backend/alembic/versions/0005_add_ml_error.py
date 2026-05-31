"""Add ml_error column to media_files for per-file ML failure tracking

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-31 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("media_files", sa.Column("ml_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("media_files", "ml_error")
