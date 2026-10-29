"""배송 상태 준비(preparing) — FMS가 Pinky를 약제실로 부른 뒤 정밀 주차 끝(출발)까지

사용자 결정(2026-10-29): "OMX 적재 준비 단계 추가 — 준비 두 글자, 호출부터 준비, 정밀 주차 출발".
reserved → preparing(FMS robot_called) → dispatched(약제실 정밀 주차 끝) → arrived → received (services/fms_events.py).
배송 상태·배송 기록 종류 CHECK와 병상 진행 중 유일 인덱스에 preparing을 더한다. 열은 늘지 않는다.
제약 SQL은 app/models/delivery.py·delivery_event.py와 같은 값(테스트는 모델로 스키마를 만든다). 계약 docs/api_contract_delivery_2026-10-20.md 10장

Revision ID: 0017_delivery_preparing
Revises: 0016_fms_batches
Create Date: 2026-10-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0017_delivery_preparing"
down_revision = "0016_fms_batches"
branch_labels = None
depends_on = None

STATUS_SQL = "status IN ('reserved', 'preparing', 'cancelled', 'dispatched', 'arrived', 'received', 'failed')"
EVENT_TYPE_SQL = "event_type IN ('reserved', 'updated', 'cancelled', 'preparing', 'dispatched', 'arrived', 'received', 'failed')"
BEDSIDE_ACTIVE_SQL = "status IN ('reserved', 'preparing', 'dispatched', 'arrived')"

OLD_STATUS_SQL = "status IN ('reserved', 'cancelled', 'dispatched', 'arrived', 'received', 'failed')"
OLD_EVENT_TYPE_SQL = "event_type IN ('reserved', 'updated', 'cancelled', 'dispatched', 'arrived', 'received', 'failed')"
OLD_BEDSIDE_ACTIVE_SQL = "status IN ('reserved', 'dispatched', 'arrived')"


def _replace(status_sql: str, event_type_sql: str, bedside_active_sql: str) -> None:
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint("ck_deliveries_status", "deliveries", status_sql)
    op.drop_constraint("ck_delivery_events_event_type", "delivery_events", type_="check")
    op.create_check_constraint("ck_delivery_events_event_type", "delivery_events", event_type_sql)
    op.drop_index("uq_deliveries_bedside_active", table_name="deliveries")
    op.create_index(
        "uq_deliveries_bedside_active", "deliveries", ["bedside_device_id"], unique=True,
        postgresql_where=sa.text(bedside_active_sql),
    )


def upgrade() -> None:
    _replace(STATUS_SQL, EVENT_TYPE_SQL, BEDSIDE_ACTIVE_SQL)


def downgrade() -> None:
    # 준비 중인 배송·준비 기록을 다른 값으로 바꿀 수 없다 — 있으면 멈춘다
    bind = op.get_bind()
    deliveries = bind.scalar(sa.text("SELECT count(*) FROM deliveries WHERE status = 'preparing'"))
    events = bind.scalar(sa.text("SELECT count(*) FROM delivery_events WHERE event_type = 'preparing'"))
    if deliveries or events:
        raise RuntimeError(f"{deliveries} preparing deliveries / {events} preparing events exist; downgrade would lose them")
    _replace(OLD_STATUS_SQL, OLD_EVENT_TYPE_SQL, OLD_BEDSIDE_ACTIVE_SQL)
