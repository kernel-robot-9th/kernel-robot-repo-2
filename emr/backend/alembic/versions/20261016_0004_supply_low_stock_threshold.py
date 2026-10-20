"""재고 부족 알림 기준 supplies.low_stock_threshold_qty. 기존 비품은 NULL(알림 안 함)

Revision ID: 0004_supply_low_stock_threshold
Revises: 0003_nurse_aruco_marker
Create Date: 2026-10-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_supply_low_stock_threshold"
down_revision = "0003_nurse_aruco_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL 허용 — 기존 비품은 알림 없이 두고, 필요한 품목만 화면에서 기준 수량을 넣는다
    op.add_column('supplies', sa.Column('low_stock_threshold_qty', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_supplies_low_stock_threshold_qty', 'supplies', 'low_stock_threshold_qty >= 0')


def downgrade() -> None:
    op.drop_constraint('ck_supplies_low_stock_threshold_qty', 'supplies', type_='check')
    op.drop_column('supplies', 'low_stock_threshold_qty')
