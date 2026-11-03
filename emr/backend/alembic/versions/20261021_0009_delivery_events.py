"""배송 기록 — delivery_events 테이블 (간호사 예약·변경·취소, 로봇 출발·도착·수령·실패). 기존 배송은 채우지 않는다

로드맵 4단계(2026-10-21 사용자 결정 범위). 제약 SQL은 app/models/delivery_event.py와 같은 문자열(테스트는 모델로 스키마를 만든다).

Revision ID: 0009_delivery_events
Revises: 0008_delivery_dispatch
Create Date: 2026-10-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_delivery_events"
down_revision = "0008_delivery_dispatch"
branch_labels = None
depends_on = None

EVENT_TYPE_SQL = (
    "event_type IN ('reserved', 'updated', 'cancelled', 'dispatched', 'arrived', 'received', 'failed')"
)
ACTOR_TYPE_SQL = "actor_type IN ('nurse', 'robot')"
ACTOR_CONSISTENCY_SQL = (
    "(actor_type = 'nurse' AND actor_nurse_id IS NOT NULL AND actor_robot_id IS NULL AND actor_robot_name IS NULL)"
    " OR (actor_type = 'robot' AND actor_nurse_id IS NULL AND actor_robot_name IS NOT NULL)"
)


def upgrade() -> None:
    op.create_table(
        'delivery_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('delivery_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=16), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor_type', sa.String(length=8), nullable=False),
        sa.Column('actor_nurse_id', sa.Integer(), nullable=True),
        sa.Column('actor_robot_id', sa.Integer(), nullable=True),
        sa.Column('actor_robot_name', sa.String(length=64), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(EVENT_TYPE_SQL, name='ck_delivery_events_event_type'),
        sa.CheckConstraint(ACTOR_TYPE_SQL, name='ck_delivery_events_actor_type'),
        sa.CheckConstraint(ACTOR_CONSISTENCY_SQL, name='ck_delivery_events_actor'),
        sa.ForeignKeyConstraint(
            ['delivery_id'], ['deliveries.id'], name='fk_delivery_events_delivery_id', ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['actor_nurse_id'], ['nurses.id'], name='fk_delivery_events_actor_nurse_id'),
        sa.ForeignKeyConstraint(
            ['actor_robot_id'], ['robots.id'], name='fk_delivery_events_actor_robot_id', ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name='delivery_events_pkey'),
    )
    op.create_index(op.f('ix_delivery_events_delivery_id'), 'delivery_events', ['delivery_id'], unique=False)
    op.create_index(op.f('ix_delivery_events_actor_robot_id'), 'delivery_events', ['actor_robot_id'], unique=False)
    op.create_index('ix_delivery_events_occurred_at', 'delivery_events', ['occurred_at', 'id'], unique=False)


def downgrade() -> None:
    # 기록은 지우지 않기로 했다(2026-10-21) — 행이 있으면 멈춘다
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM delivery_events"))
    if count:
        raise RuntimeError(f"{count} delivery events exist; downgrade would delete the delivery history")
    op.drop_index('ix_delivery_events_occurred_at', table_name='delivery_events')
    op.drop_index(op.f('ix_delivery_events_actor_robot_id'), table_name='delivery_events')
    op.drop_index(op.f('ix_delivery_events_delivery_id'), table_name='delivery_events')
    op.drop_table('delivery_events')
