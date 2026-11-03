"""장소의 로봇 목적지 이름 — 팀원 Pinky API 목적지(GET /dests)와 EMR 장소를 잇는다

사용자 결정(2026-10-22): 배송 실행기는 팀원 Pinky API로 주행(POST /goto {"dest"}). 목적지 이름을 장소에 두면
실행기 설정의 대응 표 없이 EMR이 로봇에 알려 준다(로봇용 응답 destination·home_location의 robot_dest).
채우기: backend/scripts/import_pinky_dests.py. NULL = 대응 없음(그 장소로의 배송은 실행기가 움직이지 않고 destination_blocked).

Revision ID: 0011_location_robot_dest
Revises: 0010_bedside_requests
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_location_robot_dest"
down_revision = "0010_bedside_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("robot_dest", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_locations_robot_dest", "locations", ["robot_dest"])


def downgrade() -> None:
    op.drop_constraint("uq_locations_robot_dest", "locations", type_="unique")
    op.drop_column("locations", "robot_dest")
