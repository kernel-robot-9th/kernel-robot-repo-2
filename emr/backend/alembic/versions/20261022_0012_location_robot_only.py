"""로봇 전용 장소 — 충전·출발점·대기 포켓처럼 로봇이 서 있는 곳은 비품 배송 불가, 품목 없는 로봇 이동만

사용자 결정(2026-10-22): "로봇 전용 장소는 배송 불가"(충전 앞 주행 실패 뒤 예외 처리로 고름).
같은 날 "충전에는 재고 없음(품목 해당 사항 없음)"으로 좁힘: robot_only = true인 장소로는 품목 없는 '로봇 이동'만 예약할 수 있고
(품목을 보내면 400 location_robot_only), 도착 보고가 곧 완료(receipt_method none)다. 병상 병실로는 쓸 수 없다.
로봇 복귀 장소로는 쓸 수 있다. 기존 장소는 모두 false.

Revision ID: 0012_location_robot_only
Revises: 0011_location_robot_dest
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_location_robot_only"
down_revision = "0011_location_robot_dest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("robot_only", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("locations", "robot_only")
