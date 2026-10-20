"""배송 수령 확인 — deliveries 상태 received·수령 기록, robots 로봇별 API 키(해시). 기존 행은 모두 NULL

Revision ID: 0005_delivery_receipt
Revises: 0004_supply_low_stock_threshold
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_delivery_receipt"
down_revision = "0004_supply_low_stock_threshold"
branch_labels = None
depends_on = None

RECEIPT_CONSISTENCY_SQL = (
    "(status = 'received' AND received_at IS NOT NULL AND received_by_nurse_id IS NOT NULL)"
    " OR (status <> 'received' AND received_at IS NULL AND received_by_nurse_id IS NULL AND received_by_robot_id IS NULL)"
)


def upgrade() -> None:
    # 로봇별 API 키. 평문은 저장하지 않고 sha256만 — 키가 없는 로봇은 NULL
    op.add_column('robots', sa.Column('api_key_hash', sa.String(length=64), nullable=True))
    op.add_column('robots', sa.Column('api_key_issued_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_robots_api_key_hash', 'robots', ['api_key_hash'])

    # 수령 기록. 기존 예약은 reserved·cancelled라 모두 NULL로 둔다
    op.add_column('deliveries', sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deliveries', sa.Column('received_by_nurse_id', sa.Integer(), nullable=True))
    op.add_column('deliveries', sa.Column('received_by_robot_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_deliveries_received_by_nurse_id', 'deliveries', 'nurses', ['received_by_nurse_id'], ['id'])
    op.create_foreign_key(
        'fk_deliveries_received_by_robot_id', 'deliveries', 'robots', ['received_by_robot_id'], ['id'], ondelete='SET NULL',
    )
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled', 'received')")
    op.create_check_constraint('ck_deliveries_receipt', 'deliveries', RECEIPT_CONSISTENCY_SQL)


def downgrade() -> None:
    # 수령된 예약을 reserved·cancelled 중 무엇으로 되돌릴지 정할 수 없다 — 있으면 멈춘다
    received_count = op.get_bind().scalar(sa.text("SELECT count(*) FROM deliveries WHERE status = 'received'"))
    if received_count:
        raise RuntimeError(f"{received_count} received deliveries exist; downgrade would lose receipt records")
    op.drop_constraint('ck_deliveries_receipt', 'deliveries', type_='check')
    op.drop_constraint('ck_deliveries_status', 'deliveries', type_='check')
    op.create_check_constraint('ck_deliveries_status', 'deliveries', "status IN ('reserved', 'cancelled')")
    op.drop_constraint('fk_deliveries_received_by_robot_id', 'deliveries', type_='foreignkey')
    op.drop_constraint('fk_deliveries_received_by_nurse_id', 'deliveries', type_='foreignkey')
    op.drop_column('deliveries', 'received_by_robot_id')
    op.drop_column('deliveries', 'received_by_nurse_id')
    op.drop_column('deliveries', 'received_at')
    op.drop_constraint('uq_robots_api_key_hash', 'robots', type_='unique')
    op.drop_column('robots', 'api_key_issued_at')
    op.drop_column('robots', 'api_key_hash')
