"""병상 단말 환자 요청 — bedside_devices 테이블, 배송의 예약한 쪽(간호사·병상), 버튼 수령, 배송 기록 행위자 bedside

사용자 결정(2026-10-22): 환자 비품 요청(SR-02) + "받았습니다" 버튼 수령(SR-06), 간호사 승인 없음, 병상 단말 키, 병상당 진행 중 1건.
docs/api_contract_delivery_2026-10-20.md 8장. 제약 SQL은 app/models/delivery.py·delivery_event.py와 같은 문자열(테스트는 모델로 스키마를 만든다).
기존 배송은 모두 간호사 예약(requester_type='nurse')으로 채운다.

Revision ID: 0010_bedside_requests
Revises: 0009_delivery_events
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_bedside_requests"
down_revision = "0009_delivery_events"
branch_labels = None
depends_on = None

RECEIPT_CONSISTENCY_SQL = (
    "(status = 'received' AND received_at IS NOT NULL"
    " AND (received_by_nurse_id IS NOT NULL OR requester_type = 'bedside'))"
    " OR (status <> 'received' AND received_at IS NULL AND received_by_nurse_id IS NULL AND received_by_robot_id IS NULL)"
)
OLD_RECEIPT_CONSISTENCY_SQL = (
    "(status = 'received' AND received_at IS NOT NULL AND received_by_nurse_id IS NOT NULL)"
    " OR (status <> 'received' AND received_at IS NULL AND received_by_nurse_id IS NULL AND received_by_robot_id IS NULL)"
)
REQUESTER_CONSISTENCY_SQL = (
    "(requester_type = 'nurse' AND nurse_id IS NOT NULL AND bedside_device_id IS NULL AND bedside_name IS NULL)"
    " OR (requester_type = 'bedside' AND nurse_id IS NULL AND bedside_name IS NOT NULL)"
)
BEDSIDE_ACTIVE_SQL = "status IN ('reserved', 'dispatched', 'arrived')"
ACTOR_TYPE_SQL = "actor_type IN ('nurse', 'robot', 'bedside')"
OLD_ACTOR_TYPE_SQL = "actor_type IN ('nurse', 'robot')"
ACTOR_CONSISTENCY_SQL = (
    "(actor_type = 'nurse' AND actor_nurse_id IS NOT NULL AND actor_robot_id IS NULL AND actor_robot_name IS NULL"
    " AND actor_bedside_name IS NULL)"
    " OR (actor_type = 'robot' AND actor_nurse_id IS NULL AND actor_robot_name IS NOT NULL AND actor_bedside_name IS NULL)"
    " OR (actor_type = 'bedside' AND actor_nurse_id IS NULL AND actor_robot_id IS NULL AND actor_robot_name IS NULL"
    " AND actor_bedside_name IS NOT NULL)"
)
OLD_ACTOR_CONSISTENCY_SQL = (
    "(actor_type = 'nurse' AND actor_nurse_id IS NOT NULL AND actor_robot_id IS NULL AND actor_robot_name IS NULL)"
    " OR (actor_type = 'robot' AND actor_nurse_id IS NULL AND actor_robot_name IS NOT NULL)"
)


def upgrade() -> None:
    # 병상 단말 — 관리자가 등록하고 키를 발급한다
    op.create_table(
        'bedside_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('api_key_hash', sa.String(length=64), nullable=True),
        sa.Column('api_key_issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name='fk_bedside_devices_location_id', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('api_key_hash', name='uq_bedside_devices_api_key_hash'),
    )

    # 배송: 예약한 쪽 — 기존 행은 모두 간호사 예약
    op.add_column('deliveries', sa.Column('requester_type', sa.String(length=8), server_default='nurse', nullable=False))
    op.add_column('deliveries', sa.Column('bedside_device_id', sa.Integer(), nullable=True))
    op.add_column('deliveries', sa.Column('bedside_name', sa.String(length=64), nullable=True))
    op.alter_column('deliveries', 'nurse_id', existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        'fk_deliveries_bedside_device_id', 'deliveries', 'bedside_devices', ['bedside_device_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(op.f('ix_deliveries_bedside_device_id'), 'deliveries', ['bedside_device_id'], unique=False)
    op.create_check_constraint('ck_deliveries_requester_type', 'deliveries', "requester_type IN ('nurse', 'bedside')")
    op.create_check_constraint('ck_deliveries_requester', 'deliveries', REQUESTER_CONSISTENCY_SQL)
    op.drop_constraint('ck_deliveries_receipt', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_receipt', 'deliveries', RECEIPT_CONSISTENCY_SQL)
    op.create_index(
        'uq_deliveries_bedside_active', 'deliveries', ['bedside_device_id'], unique=True,
        postgresql_where=sa.text(BEDSIDE_ACTIVE_SQL),
    )

    # 배송 기록: 행위자 bedside
    op.add_column('delivery_events', sa.Column('actor_bedside_name', sa.String(length=64), nullable=True))
    op.drop_constraint('ck_delivery_events_actor', 'delivery_events', type_='check')
    op.drop_constraint('ck_delivery_events_actor_type', 'delivery_events', type_='check')
    op.create_check_constraint('ck_delivery_events_actor_type', 'delivery_events', ACTOR_TYPE_SQL)
    op.create_check_constraint('ck_delivery_events_actor', 'delivery_events', ACTOR_CONSISTENCY_SQL)


def downgrade() -> None:
    # 병상 배송·기록을 간호사 예약으로 바꿀 수 없다 — 있으면 멈춘다
    bind = op.get_bind()
    deliveries = bind.scalar(sa.text("SELECT count(*) FROM deliveries WHERE requester_type = 'bedside'"))
    events = bind.scalar(sa.text("SELECT count(*) FROM delivery_events WHERE actor_type = 'bedside'"))
    if deliveries or events:
        raise RuntimeError(f"{deliveries} bedside deliveries / {events} bedside events exist; downgrade would lose them")
    op.drop_constraint('ck_delivery_events_actor', 'delivery_events', type_='check')
    op.drop_constraint('ck_delivery_events_actor_type', 'delivery_events', type_='check')
    op.create_check_constraint('ck_delivery_events_actor_type', 'delivery_events', OLD_ACTOR_TYPE_SQL)
    op.create_check_constraint('ck_delivery_events_actor', 'delivery_events', OLD_ACTOR_CONSISTENCY_SQL)
    op.drop_column('delivery_events', 'actor_bedside_name')

    op.drop_index('uq_deliveries_bedside_active', table_name='deliveries')
    op.drop_constraint('ck_deliveries_receipt', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_receipt', 'deliveries', OLD_RECEIPT_CONSISTENCY_SQL)
    op.drop_constraint('ck_deliveries_requester', 'deliveries', type_='check')
    op.drop_constraint('ck_deliveries_requester_type', 'deliveries', type_='check')
    op.drop_index(op.f('ix_deliveries_bedside_device_id'), table_name='deliveries')
    op.drop_constraint('fk_deliveries_bedside_device_id', 'deliveries', type_='foreignkey')
    op.alter_column('deliveries', 'nurse_id', existing_type=sa.Integer(), nullable=False)
    for column in ('bedside_name', 'bedside_device_id', 'requester_type'):
        op.drop_column('deliveries', column)
    op.drop_table('bedside_devices')
