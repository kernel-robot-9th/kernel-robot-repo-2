"""간호사 마커 nurses.aruco_marker_id (ArUco DICT_4X4_50, 0~49, 중복 불가). 기존 간호사는 NULL(미배정)

Revision ID: 0003_nurse_aruco_marker
Revises: 0002_nurse_role
Create Date: 2026-10-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_nurse_aruco_marker"
down_revision = "0002_nurse_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL 허용 — 기존 간호사는 미배정으로 두고 관리자가 화면에서 번호를 넣는다
    op.add_column('nurses', sa.Column('aruco_marker_id', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_nurses_aruco_marker_id', 'nurses', 'aruco_marker_id BETWEEN 0 AND 49')
    op.create_unique_constraint('uq_nurses_aruco_marker_id', 'nurses', ['aruco_marker_id'])


def downgrade() -> None:
    op.drop_constraint('uq_nurses_aruco_marker_id', 'nurses', type_='unique')
    op.drop_constraint('ck_nurses_aruco_marker_id', 'nurses', type_='check')
    op.drop_column('nurses', 'aruco_marker_id')
