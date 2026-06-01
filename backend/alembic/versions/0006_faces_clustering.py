"""Add face clustering support: centroid on people, min cluster size pref on users

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-31 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # centroid vector for stable cluster identity across re-runs
    op.add_column("people", sa.Column("centroid", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE people ALTER COLUMN centroid TYPE vector(512) "
        "USING centroid::vector(512)"
    )

    # per-user threshold: hide persons with fewer than N face appearances
    op.add_column(
        "users",
        sa.Column(
            "face_cluster_min_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("20"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "face_cluster_min_size")
    op.drop_column("people", "centroid")
