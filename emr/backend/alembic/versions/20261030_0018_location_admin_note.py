"""장소 관리자 메모 admin_note — "101호 4인실 왼쪽"의 "4인실 왼쪽"은 관리자 화면에만

사용자 결정(2026-10-30): "'4인실 왼쪽' 이해하기 쉽게 하려고 한 거니 관리자 화면에만 나오게".
장소 이름에 붙여 두었던 설명을 새 칸으로 옮긴다 — 간호사 화면·알림·배송 기록·병상 화면은 이름("101호")만 보인다.
데이터: 이름이 "숫자호 설명" 꼴(예: "101호 4인실 왼쪽")인 장소만 앞부분을 이름, 뒷부분을 admin_note로 나눈다.
나눈 이름이 이미 다른 장소 이름이면 그 장소는 그대로 둔다(UNIQUE). downgrade는 설명을 이름 뒤에 다시 붙인다.

Revision ID: 0018_location_admin_note
Revises: 0017_delivery_preparing
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_location_admin_note"
down_revision = "0017_delivery_preparing"
branch_labels = None
depends_on = None

ROOM_WITH_NOTE_PATTERN = r"^([0-9]+호) (.+)$"


def upgrade() -> None:
    op.add_column("locations", sa.Column("admin_note", sa.String(64), nullable=True))
    op.execute(sa.text(f"""
        UPDATE locations AS location
        SET admin_note = regexp_replace(location.name, '{ROOM_WITH_NOTE_PATTERN}', '\\2'),
            name = regexp_replace(location.name, '{ROOM_WITH_NOTE_PATTERN}', '\\1')
        WHERE location.name ~ '{ROOM_WITH_NOTE_PATTERN}'
          AND NOT EXISTS (
              SELECT 1 FROM locations AS other
              WHERE other.name = regexp_replace(location.name, '{ROOM_WITH_NOTE_PATTERN}', '\\1')
          )
    """))


def downgrade() -> None:
    op.execute(sa.text("UPDATE locations SET name = left(name || ' ' || admin_note, 64) WHERE admin_note IS NOT NULL"))
    op.drop_column("locations", "admin_note")
