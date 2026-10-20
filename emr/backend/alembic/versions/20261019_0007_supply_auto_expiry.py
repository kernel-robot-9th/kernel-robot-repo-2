"""비품 유효기간 자동 — 비어 있는 기존 비품의 유효기간을 오늘부터 6개월~1년 사이 무작위로 채운다 (데이터만, 스키마 변경 없음)

새로 등록하는 비품은 SupplyService.create가 같은 범위로 채운다(app/services/supply.py auto_expiry_date).
2026-10-19 사용자 결정: 화면에서 유효기간을 고르지 않는다.

Revision ID: 0007_supply_auto_expiry
Revises: 0006_map_image
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op

revision = "0007_supply_auto_expiry"
down_revision = "0006_map_image"
branch_labels = None
depends_on = None

AUTO_EXPIRY_MIN_DAYS = 183   # app/services/supply.py와 같은 값 (마이그레이션은 앱 코드를 import하지 않는다)
AUTO_EXPIRY_MAX_DAYS = 365


def upgrade() -> None:
    # 행마다 random()을 따로 뽑는다: MIN + 0..(MAX-MIN)일
    op.execute(
        "UPDATE supplies SET expiry_date = CURRENT_DATE + "
        f"({AUTO_EXPIRY_MIN_DAYS} + floor(random() * {AUTO_EXPIRY_MAX_DAYS - AUTO_EXPIRY_MIN_DAYS + 1}))::int "
        "WHERE expiry_date IS NULL"
    )


def downgrade() -> None:
    # 되돌리지 않는다: 원래 비어 있던 행과 사람이 넣은 행을 구별할 기록이 없다. 스키마는 그대로라 downgrade는 안전하다
    pass
