# =============================================================================
# 파일   : app/models/robot_status_report.py
# 역할   : robot_status_reports — claim 때 로봇 서버에서 받은 마지막 배터리·오염도 (로봇 한 대에 한 줄)
# 작성일 : 2026-10-23
# 구성   :
#   - RobotStatusReport  battery_percent·contamination_percent(0~100)·reported_at
# EMR이 claim 때 로봇 서버(GET /status)에 물을 때마다 덮어쓴다(이력은 남기지 않음). 판정은 그때 받은 값으로 하고, 이 표는 관리자 화면용.
# robots 행에 두지 않은 까닭: 몇 초마다 받는 값이 robots.updated_at(이름·상태 변경 시각)을 계속 바꾸지 않게
# =============================================================================
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RobotStatusReport(Base):
    """로봇의 마지막 상태 보고. 로봇을 지우면 함께 지운다."""

    __tablename__ = "robot_status_reports"
    __table_args__ = (
        CheckConstraint("battery_percent BETWEEN 0 AND 100", name="ck_robot_status_reports_battery_percent"),
        CheckConstraint("contamination_percent BETWEEN 0 AND 100", name="ck_robot_status_reports_contamination_percent"),
    )

    robot_id: Mapped[int] = mapped_column(
        ForeignKey("robots.id", name="fk_robot_status_reports_robot_id", ondelete="CASCADE"), primary_key=True,
    )
    battery_percent: Mapped[float] = mapped_column(Float, nullable=False)        # 0~100
    contamination_percent: Mapped[float] = mapped_column(Float, nullable=False)  # 0(깨끗)~100, 로봇이 잰 값
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # EMR이 로봇 서버에서 받은 시각
