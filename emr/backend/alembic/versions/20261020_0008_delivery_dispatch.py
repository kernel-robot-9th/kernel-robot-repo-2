"""배송 배정·진행 — deliveries 상태 dispatched·arrived·failed, 맡은 로봇·단계 시각·실패 사유·일회용 수령 마커, robots 복귀 장소. 기존 행은 모두 NULL

docs/api_contract_delivery_2026-10-20.md. 제약 SQL은 app/models/delivery.py와 같은 문자열(테스트는 모델로 스키마를 만든다).

Revision ID: 0008_delivery_dispatch
Revises: 0007_supply_auto_expiry
Create Date: 2026-10-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_delivery_dispatch"
down_revision = "0007_supply_auto_expiry"
branch_labels = None
depends_on = None

DISPATCH_CONSISTENCY_SQL = (
    "status NOT IN ('dispatched', 'arrived') OR (dispatched_at IS NOT NULL AND assigned_robot_id IS NOT NULL)"
)
ARRIVAL_CONSISTENCY_SQL = "status <> 'arrived' OR (arrived_at IS NOT NULL AND receipt_marker_id IS NOT NULL)"
FAILURE_CONSISTENCY_SQL = (
    "(status = 'failed' AND failed_at IS NOT NULL AND failure_reason IS NOT NULL)"
    " OR (status <> 'failed' AND failed_at IS NULL AND failure_reason IS NULL)"
)
FAILURE_REASON_SQL = (
    "failure_reason IS NULL OR failure_reason IN "
    "('navigation_failed', 'not_received', 'destination_blocked', 'robot_error')"
)
RECEIPT_MARKER_RANGE_SQL = "receipt_marker_id IS NULL OR receipt_marker_id BETWEEN 50 AND 249"
NEW_STATUSES = ('dispatched', 'arrived', 'failed')


def upgrade() -> None:
    # 복귀 장소 — 기존 로봇은 미지정(NULL). 관리자가 로봇 탭에서 고른다
    op.add_column('robots', sa.Column('home_location_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_robots_home_location_id', 'robots', 'locations', ['home_location_id'], ['id'], ondelete='RESTRICT',
    )

    # 배정·진행 — 기존 예약(reserved·cancelled·received)은 모두 NULL
    op.add_column('deliveries', sa.Column('assigned_robot_id', sa.Integer(), nullable=True))
    op.add_column('deliveries', sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('failure_reason', sa.String(length=32), nullable=True))
    op.add_column('deliveries', sa.Column('receipt_marker_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_deliveries_assigned_robot_id', 'deliveries', 'robots', ['assigned_robot_id'], ['id'], ondelete='SET NULL',
    )
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint(
        'ck_deliveries_status', 'deliveries',
        "status IN ('reserved', 'cancelled', 'dispatched', 'arrived', 'received', 'failed')",
    )
    op.create_check_constraint('ck_deliveries_dispatch', 'deliveries', DISPATCH_CONSISTENCY_SQL)
    op.create_check_constraint('ck_deliveries_arrival', 'deliveries', ARRIVAL_CONSISTENCY_SQL)
    op.create_check_constraint('ck_deliveries_failure', 'deliveries', FAILURE_CONSISTENCY_SQL)
    op.create_check_constraint('ck_deliveries_failure_reason', 'deliveries', FAILURE_REASON_SQL)
    op.create_check_constraint('ck_deliveries_receipt_marker_range', 'deliveries', RECEIPT_MARKER_RANGE_SQL)
    op.create_index(
        'uq_deliveries_receipt_marker_arrived', 'deliveries', ['receipt_marker_id'], unique=True,
        postgresql_where=sa.text("status = 'arrived'"),
    )
    op.create_index(
        'uq_deliveries_assigned_robot_active', 'deliveries', ['assigned_robot_id'], unique=True,
        postgresql_where=sa.text("status IN ('dispatched', 'arrived')"),
    )
    op.create_index('ix_deliveries_status_scheduled_at', 'deliveries', ['status', 'scheduled_at'])


def downgrade() -> None:
    # 진행·실패 기록을 reserved·cancelled·received 중 무엇으로 되돌릴지 정할 수 없다 — 있으면 멈춘다
    count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM deliveries WHERE status IN ('dispatched', 'arrived', 'failed')")
    )
    if count:
        raise RuntimeError(f"{count} dispatched/arrived/failed deliveries exist; downgrade would lose dispatch records")
    op.drop_index('ix_deliveries_status_scheduled_at', table_name='deliveries')
    op.drop_index('uq_deliveries_assigned_robot_active', table_name='deliveries')
    op.drop_index('uq_deliveries_receipt_marker_arrived', table_name='deliveries')
    for name in ('ck_deliveries_receipt_marker_range', 'ck_deliveries_failure_reason', 'ck_deliveries_failure',
                 'ck_deliveries_arrival', 'ck_deliveries_dispatch', 'ck_deliveries_status'):
        op.drop_constraint(name, 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled', 'received')")
    op.drop_constraint('fk_deliveries_assigned_robot_id', 'deliveries', type_='foreignkey')
    for column in ('receipt_marker_id', 'failure_reason', 'failed_at', 'arrived_at', 'dispatched_at', 'assigned_robot_id'):
        op.drop_column('deliveries', column)
    op.drop_constraint('fk_robots_home_location_id', 'robots', type_='foreignkey')
    op.drop_column('robots', 'home_location_id')
