"""Add video_preview_path to media_files

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_files",
        sa.Column("video_preview_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("media_files", "video_preview_path")
