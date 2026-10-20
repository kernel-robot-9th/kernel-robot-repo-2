"""간호사 역할 nurses.role (admin·nurse). 기존 간호사는 nurse, N001은 admin

Revision ID: 0002_nurse_role
Revises: 0001_baseline
Create Date: 2026-10-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_nurse_role"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 행은 일반 간호사로 채운 뒤 기본값을 걷어낸다 (모델은 파이썬 쪽 default만 둔다)
    op.add_column('nurses', sa.Column('role', sa.String(length=16), server_default='nurse', nullable=False))
    op.alter_column('nurses', 'role', server_default=None)
    op.create_check_constraint('ck_nurses_role', 'nurses', "role IN ('admin', 'nurse')")
    # 첫 관리자 (2026-10-15 결정). N001이 없는 DB(빈 DB 등)에서는 아무것도 하지 않는다 — 개발 DB는 seed가 지정
    op.execute("UPDATE nurses SET role = 'admin' WHERE employee_no = 'N001'")


def downgrade() -> None:
    op.drop_constraint('ck_nurses_role', 'nurses', type_='check')
    op.drop_column('nurses', 'role')
