"""전송·로봇 배정 데이터를 deliveries에서 delivery_executions로 분리

Revision ID: 0011_delivery_executions
Revises: 0010_delivery_work_sequence
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_delivery_executions"
down_revision = "0010_delivery_work_sequence"
branch_labels = None
depends_on = None

MOVED = "dispatch_attempts, last_dispatch_attempt_at, last_dispatch_error, dispatched_at, amr_robot_id, manipulator_robot_id"


def upgrade() -> None:
    op.create_table('delivery_executions',
    sa.Column('delivery_id', sa.Integer(), nullable=False),
    sa.Column('dispatch_attempts', sa.Integer(), nullable=False),
    sa.Column('last_dispatch_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_dispatch_error', sa.Text(), nullable=True),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('amr_robot_id', sa.Integer(), nullable=True),
    sa.Column('manipulator_robot_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['amr_robot_id'], ['robots.id'], name='fk_delivery_executions_amr_robot_id'),
    sa.ForeignKeyConstraint(['delivery_id'], ['deliveries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['manipulator_robot_id'], ['robots.id'], name='fk_delivery_executions_manipulator_robot_id'),
    sa.PrimaryKeyConstraint('delivery_id')
    )
    # 한 번이라도 전송을 시도한 배송만 옮긴다
    op.execute(f"INSERT INTO delivery_executions (delivery_id, {MOVED}) SELECT id, {MOVED} FROM deliveries "
               "WHERE dispatch_attempts > 0 OR amr_robot_id IS NOT NULL OR manipulator_robot_id IS NOT NULL")
    op.drop_constraint('fk_deliveries_manipulator_robot_id', 'deliveries', type_='foreignkey')
    op.drop_constraint('fk_deliveries_amr_robot_id', 'deliveries', type_='foreignkey')
    for column in MOVED.split(", "):
        op.drop_column('deliveries', column)


def downgrade() -> None:
    op.add_column('deliveries', sa.Column('dispatch_attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('deliveries', sa.Column('last_dispatch_attempt_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('last_dispatch_error', sa.Text(), nullable=True))
    op.add_column('deliveries', sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('amr_robot_id', sa.Integer(), nullable=True))
    op.add_column('deliveries', sa.Column('manipulator_robot_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_deliveries_amr_robot_id', 'deliveries', 'robots', ['amr_robot_id'], ['id'])
    op.create_foreign_key('fk_deliveries_manipulator_robot_id', 'deliveries', 'robots', ['manipulator_robot_id'], ['id'])
    op.execute(
        "UPDATE deliveries d SET dispatch_attempts = e.dispatch_attempts, last_dispatch_attempt_at = e.last_dispatch_attempt_at, "
        "last_dispatch_error = e.last_dispatch_error, dispatched_at = e.dispatched_at, "
        "amr_robot_id = e.amr_robot_id, manipulator_robot_id = e.manipulator_robot_id "
        "FROM delivery_executions e WHERE e.delivery_id = d.id"
    )
    op.drop_table('delivery_executions')
