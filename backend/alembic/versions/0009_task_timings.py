"""Add task_timings table for latency analysis

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_timings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_files.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "file_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_raw", sa.Boolean(), nullable=True),
    )
    op.create_index("idx_task_timings_task_name", "task_timings", ["task_name"])
    op.create_index("idx_task_timings_started_at", "task_timings", ["started_at"])
    op.create_index("idx_task_timings_file_id", "task_timings", ["file_id"])


def downgrade() -> None:
    op.drop_index("idx_task_timings_file_id", "task_timings")
    op.drop_index("idx_task_timings_started_at", "task_timings")
    op.drop_index("idx_task_timings_task_name", "task_timings")
    op.drop_table("task_timings")
