"""작업 시퀀스 걷어냄: 단계 상태·delivery_status_events·로봇 배정 컬럼 제거 (나중에 다시 설계)

Revision ID: 0012_remove_work_sequence
Revises: 0011_delivery_executions
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_remove_work_sequence"
down_revision = "0011_delivery_executions"
branch_labels = None
depends_on = None

STATUSES = "'reserved', 'cancelled', 'dispatched', 'dispatch_failed'"
SEQUENCE_STATUSES = ("'loading_started', 'arrived_at_loading', 'loading', 'loaded', "
                     "'delivering', 'receipt_requested', 'returning'")


def upgrade() -> None:
    # 시퀀스 단계에 있던 배송은 '작업 등록됨'으로 되돌린다
    op.execute(f"UPDATE deliveries SET status = 'dispatched' WHERE status IN ({SEQUENCE_STATUSES})")
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', f"status IN ({STATUSES})")
    op.drop_index(op.f('ix_delivery_status_events_delivery_id'), table_name='delivery_status_events')
    op.drop_table('delivery_status_events')
    op.drop_constraint('fk_delivery_executions_manipulator_robot_id', 'delivery_executions', type_='foreignkey')
    op.drop_constraint('fk_delivery_executions_amr_robot_id', 'delivery_executions', type_='foreignkey')
    op.drop_column('delivery_executions', 'manipulator_robot_id')
    op.drop_column('delivery_executions', 'amr_robot_id')


def downgrade() -> None:
    op.add_column('delivery_executions', sa.Column('amr_robot_id', sa.Integer(), nullable=True))
    op.add_column('delivery_executions', sa.Column('manipulator_robot_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_delivery_executions_amr_robot_id', 'delivery_executions', 'robots', ['amr_robot_id'], ['id'])
    op.create_foreign_key('fk_delivery_executions_manipulator_robot_id', 'delivery_executions', 'robots', ['manipulator_robot_id'], ['id'])
    op.create_table('delivery_status_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('delivery_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('robot_id', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['delivery_id'], ['deliveries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['robot_id'], ['robots.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_delivery_status_events_delivery_id'), 'delivery_status_events', ['delivery_id'], unique=False)
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', f"status IN ({STATUSES}, {SEQUENCE_STATUSES})")
