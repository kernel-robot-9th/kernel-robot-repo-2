"""다른 부서 전송 걷어냄: delivery_executions 제거, 배송 상태는 reserved·cancelled만

Revision ID: 0014_remove_dispatch
Revises: 0013_shrink_delivery_status
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_remove_dispatch"
down_revision = "0013_shrink_delivery_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 전송됐거나 전송에 실패한 배송은 예약 상태로 되돌린다 (간호사가 보고 취소할 수 있게)
    op.execute("UPDATE deliveries SET status = 'reserved' WHERE status IN ('dispatched', 'dispatch_failed')")
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled')")
    op.drop_table('delivery_executions')


def downgrade() -> None:
    op.create_table('delivery_executions',
    sa.Column('delivery_id', sa.Integer(), nullable=False),
    sa.Column('dispatch_attempts', sa.Integer(), nullable=False),
    sa.Column('last_dispatch_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_dispatch_error', sa.Text(), nullable=True),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['delivery_id'], ['deliveries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('delivery_id')
    )
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled', 'dispatched', 'dispatch_failed')")
