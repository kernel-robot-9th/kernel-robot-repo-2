"""FMS API v1 연동 1단계 — fms_orders 표, '로봇 한 대 = 진행 중 배송 하나' 유일 인덱스 없앰

사용자 결정(2026-10-27): "단계 변경에 필요한 최소만", 마이그레이션 0015를 새로 쓰고 보관 브랜치 fms-order-2026-10-26
(그 브랜치의 0015·0016)은 합치지 않는다. EMR이 배송의 물품 1개당 FMS 주문 1건을 보내고(fms_orders), FMS 이벤트로 배송 단계를 바꾼다.
FMS는 묶음 하나(최대 3개)에 여러 신청을 한 로봇에 싣는다 → 0008의 uq_deliveries_assigned_robot_active를 없앤다.
downgrade는 같은 로봇의 진행 중 배송이 둘 이상이면 인덱스를 다시 만들 수 없어 멈춘다.
계약: docs/api_contract_delivery_2026-10-20.md 10장

Revision ID: 0015_fms_orders
Revises: 0014_robot_server_url
Create Date: 2026-10-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_fms_orders"
down_revision = "0014_robot_server_url"
branch_labels = None
depends_on = None

ROBOT_ACTIVE_SQL = "status IN ('dispatched', 'arrived')"   # 0008과 같은 문자열


def upgrade() -> None:
    op.drop_index("uq_deliveries_assigned_robot_active", table_name="deliveries")
    op.create_table(
        "fms_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("deliveries.id", name="fk_fms_orders_delivery_id", ondelete="CASCADE"), nullable=False),
        sa.Column("supply_id", sa.Integer(), sa.ForeignKey("supplies.id", name="fk_fms_orders_supply_id"), nullable=False),
        sa.Column("nth", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("fms_order_id", sa.String(length=32), nullable=False),   # FMS를 다시 켜면 o-1부터 다시 — UNIQUE 아님
        sa.Column("batch_id", sa.String(length=32), nullable=True),
        sa.Column("fms_robot_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("delivery_id", "supply_id", "nth", name="uq_fms_orders_delivery_supply_nth"),
        sa.CheckConstraint(
            "status IN ('queued', 'assigned', 'loaded', 'delivered', 'canceled', 'failed')", name="ck_fms_orders_status",
        ),
        sa.CheckConstraint("nth >= 1", name="ck_fms_orders_nth"),
    )
    op.create_index("ix_fms_orders_delivery_id", "fms_orders", ["delivery_id"])
    op.create_index("ix_fms_orders_fms_order_id", "fms_orders", ["fms_order_id"])


def downgrade() -> None:
    op.drop_index("ix_fms_orders_fms_order_id", table_name="fms_orders")
    op.drop_index("ix_fms_orders_delivery_id", table_name="fms_orders")
    op.drop_table("fms_orders")
    count = op.get_bind().scalar(sa.text(
        f"SELECT count(*) FROM (SELECT assigned_robot_id FROM deliveries WHERE {ROBOT_ACTIVE_SQL}"
        " GROUP BY assigned_robot_id HAVING count(*) > 1) AS shared"
    ))
    if count:
        raise RuntimeError(f"{count} robots have more than one active delivery; cannot restore uq_deliveries_assigned_robot_active")
    op.create_index(
        "uq_deliveries_assigned_robot_active", "deliveries", ["assigned_robot_id"], unique=True,
        postgresql_where=sa.text(ROBOT_ACTIVE_SQL),
    )
