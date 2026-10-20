"""배송 작업 시퀀스: 상태 확장, 배정 로봇, delivery_status_events

Revision ID: 0010_delivery_work_sequence
Revises: 0009_robot_type
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_delivery_work_sequence"
down_revision = "0009_robot_type"
branch_labels = None
depends_on = None

OLD_STATUSES = "'reserved', 'cancelled', 'dispatched', 'dispatch_failed'"
NEW_STATUSES = (OLD_STATUSES + ", 'loading_started', 'arrived_at_loading', 'loading', 'loaded', "
                "'delivering', 'receipt_requested', 'returning'")


def upgrade() -> None:
    op.alter_column('deliveries', 'status', type_=sa.String(length=32), existing_nullable=False)
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', f"status IN ({NEW_STATUSES})")
    op.add_column('deliveries', sa.Column('amr_robot_id', sa.Integer(), nullable=True))
    op.add_column('deliveries', sa.Column('manipulator_robot_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_deliveries_amr_robot_id', 'deliveries', 'robots', ['amr_robot_id'], ['id'])
    op.create_foreign_key('fk_deliveries_manipulator_robot_id', 'deliveries', 'robots', ['manipulator_robot_id'], ['id'])
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
    # 이미 전송된 배송은 전송 시각으로 기록 한 줄을 남긴다
    op.execute(
        "INSERT INTO delivery_status_events (delivery_id, status, occurred_at) "
        "SELECT id, 'dispatched', dispatched_at FROM deliveries WHERE dispatched_at IS NOT NULL"
    )


def downgrade() -> None:
    # 작업 시퀀스 상태인 배송이 있으면 실패한다 — 되돌리기 전에 정리 필요
    op.drop_index(op.f('ix_delivery_status_events_delivery_id'), table_name='delivery_status_events')
    op.drop_table('delivery_status_events')
    op.drop_constraint('fk_deliveries_manipulator_robot_id', 'deliveries', type_='foreignkey')
    op.drop_constraint('fk_deliveries_amr_robot_id', 'deliveries', type_='foreignkey')
    op.drop_column('deliveries', 'manipulator_robot_id')
    op.drop_column('deliveries', 'amr_robot_id')
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', f"status IN ({OLD_STATUSES})")
    op.alter_column('deliveries', 'status', type_=sa.String(length=16), existing_nullable=False)
