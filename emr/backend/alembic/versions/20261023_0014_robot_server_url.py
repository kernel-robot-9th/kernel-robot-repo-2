"""로봇 서버 주소 — claim 때 EMR이 팀원 Pinky API GET /status로 배터리·오염도·주행 준비를 묻는다

사용자 결정(2026-10-23): "팀원도 서버가 있기에 로봇에 정확한 정보 요청해야" — 로봇이 보내는 보고(0013 직후의 POST 방식) 대신
EMR이 claim할 때마다 로봇 서버에 묻는다. robots.robot_server_url(예: http://192.168.129.107:8080), NULL이면 배송을 맡지 않는다.
기존 로봇은 NULL — 관리자가 로봇 탭에서 넣는다. robot_status_reports(0013)는 그때 받은 값을 관리자 화면용으로 저장하는 데 그대로 쓴다.

Revision ID: 0014_robot_server_url
Revises: 0013_robot_status_reports
Create Date: 2026-10-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_robot_server_url"
down_revision = "0013_robot_status_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("robots", sa.Column("robot_server_url", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("robots", "robot_server_url")
