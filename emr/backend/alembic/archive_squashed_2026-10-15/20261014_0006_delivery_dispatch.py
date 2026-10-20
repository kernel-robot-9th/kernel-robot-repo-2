"""deliveries 전송 상태 (dispatched·dispatch_failed) + 전송 기록 컬럼

Revision ID: 0006_delivery_dispatch
Revises: 0005_rename_to_deliveries
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_delivery_dispatch"
down_revision = "0005_rename_to_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deliveries', sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('dispatch_attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('deliveries', sa.Column('last_dispatch_attempt_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('last_dispatch_error', sa.Text(), nullable=True))
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint(
        'ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled', 'dispatched', 'dispatch_failed')"
    )


def downgrade() -> None:
    # dispatched·dispatch_failed 행이 있으면 실패한다 — 되돌리기 전에 정리 필요
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled')")
    op.drop_column('deliveries', 'last_dispatch_error')
    op.drop_column('deliveries', 'last_dispatch_attempt_at')
    op.drop_column('deliveries', 'dispatch_attempts')
    op.drop_column('deliveries', 'dispatched_at')
