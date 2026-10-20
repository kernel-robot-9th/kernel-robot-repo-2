"""deliveries.status 길이 32 → 16 (작업 시퀀스 상태를 걷어낸 뒤 원래대로)

Revision ID: 0013_shrink_delivery_status
Revises: 0012_remove_work_sequence
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_shrink_delivery_status"
down_revision = "0012_remove_work_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 남은 상태값은 최대 15자(dispatch_failed)라 줄여도 잘리지 않는다
    op.alter_column('deliveries', 'status', type_=sa.String(length=16), existing_type=sa.String(length=32),
                    existing_nullable=False)


def downgrade() -> None:
    op.alter_column('deliveries', 'status', type_=sa.String(length=32), existing_type=sa.String(length=16),
                    existing_nullable=False)
