"""로봇 상태 보고 — 배터리·오염도의 마지막 값 (로봇 한 대에 한 줄)

사용자 결정(2026-10-23): "요청 시 로봇 상태를 가져와서 배터리, 오염도 넣어서 미션을 할당".
로봇(팀원 FMS)이 POST /robot/status로 보고하고, claim 때 그 로봇의 마지막 보고가 기준(배터리 하한·오염도 상한·보고 나이)을
넘지 못하면 배송을 주지 않는다. 오염도는 로봇이 재는 0~100 수치. 이력은 남기지 않고 덮어쓴다.
새 테이블이라 기존 행에 채울 값은 없다 — 배포 직후에는 보고가 없어 로봇이 보고할 때까지 claim이 배송을 주지 않는다.

Revision ID: 0013_robot_status_reports
Revises: 0012_location_robot_only
Create Date: 2026-10-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_robot_status_reports"
down_revision = "0012_location_robot_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "robot_status_reports",
        sa.Column("robot_id", sa.Integer(), nullable=False),
        sa.Column("battery_percent", sa.Float(), nullable=False),
        sa.Column("contamination_percent", sa.Float(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["robot_id"], ["robots.id"], name="fk_robot_status_reports_robot_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("robot_id", name="robot_status_reports_pkey"),
        sa.CheckConstraint("battery_percent BETWEEN 0 AND 100", name="ck_robot_status_reports_battery_percent"),
        sa.CheckConstraint("contamination_percent BETWEEN 0 AND 100", name="ck_robot_status_reports_contamination_percent"),
    )


def downgrade() -> None:
    op.drop_table("robot_status_reports")
