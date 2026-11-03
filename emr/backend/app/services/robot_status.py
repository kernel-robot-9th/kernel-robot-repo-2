# =============================================================================
# 파일   : app/services/robot_status.py
# 역할   : claim 때 로봇 서버(팀원 Pinky API)에 지금 상태를 물어 "이 로봇에게 새 배송을 줘도 되는가" 판정
# 작성일 : 2026-10-23
# 구성   :
#   - ClaimSkipReason       배송을 주지 않는 이유 (claim 204 응답의 X-Claim-Skip-Reason 헤더 값)
#   - RobotStatusService    check_before_claim(robot, now) — 묻기·저장·판정
# 사용자 결정(2026-10-23): 오염도는 로봇이 재는 0~100, 배정은 claim 때 그 로봇 상태만 검사,
#   상태는 로봇이 보내는 보고가 아니라 **EMR이 로봇 서버에 요청**(GET {robots.robot_server_url}/status), **claim할 때마다**.
# 로봇 서버 /status에서 읽는 필드: battery_percent·contamination_percent(0~100, 팀원이 넣을 칸), localized·nav2_ready(true),
#   state("idle"). 기준값은 app/core/config.py CLAIM_MIN_BATTERY_PERCENT·CLAIM_MAX_CONTAMINATION_PERCENT·ROBOT_SERVER_TIMEOUT_SECONDS
# =============================================================================
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.clients.robot_server import RobotServerError, fetch_robot_status
from app.core.config import settings
from app.models.robot import Robot
from app.repositories.robot import RobotRepository

log = structlog.get_logger(__name__)


class ClaimSkipReason(StrEnum):
    """claim이 새 배송을 주지 않는 이유 (로봇 상태 때문)."""
    SERVER_NOT_SET = "robot_server_not_set"            # 로봇 서버 주소가 없음 (관리자가 로봇 탭에서 입력)
    SERVER_UNREACHABLE = "robot_server_unreachable"    # 로봇 서버가 응답하지 않음·200이 아님·JSON이 아님
    STATUS_INCOMPLETE = "robot_status_incomplete"      # /status에 battery_percent·contamination_percent(0~100)가 없음
    NOT_READY = "robot_not_ready"                      # 위치 추정·Nav2 준비가 안 됐거나 다른 작업 중(state가 idle이 아님)
    BATTERY_LOW = "robot_battery_low"                  # 배터리 < CLAIM_MIN_BATTERY_PERCENT
    CONTAMINATION_HIGH = "robot_contamination_high"    # 오염도 > CLAIM_MAX_CONTAMINATION_PERCENT


def _percent(value: Any) -> float | None:
    """0~100 숫자면 float, 아니면 None (bool은 숫자로 보지 않는다).
    [입력] value: /status의 값 [출력] float | None
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0 <= value <= 100 else None


class RobotStatusService:
    """로봇 서버에 묻고, 받은 배터리·오염도를 관리자 화면용으로 저장하고, 배송을 줄지 판정한다."""

    def __init__(self, db: Session) -> None:
        self.robots = RobotRepository(db)

    def check_before_claim(self, robot: Robot, now: datetime) -> ClaimSkipReason | None:
        """claim 직전 판정. 위에서부터 첫 번째로 걸리는 이유를 돌려준다.
        [입력] robot: 잠근 로봇 / now: 지금 시각(저장용)
        [출력] ClaimSkipReason | None: None이면 배송을 줘도 된다
        """
        if not robot.robot_server_url:
            return ClaimSkipReason.SERVER_NOT_SET
        try:
            status = fetch_robot_status(robot.robot_server_url, settings.ROBOT_SERVER_TIMEOUT_SECONDS)
        except RobotServerError as error:
            # 맡을 배송이 있을 때만 묻는다(dispatch.claim) — 로봇 서버가 꺼져 있으면 claim 주기(3초)마다 남는다
            log.warning("robot_server_unreachable", robot_id=robot.id, error=str(error))
            return ClaimSkipReason.SERVER_UNREACHABLE
        battery_percent = _percent(status.get("battery_percent"))
        contamination_percent = _percent(status.get("contamination_percent"))
        if battery_percent is None or contamination_percent is None:
            return ClaimSkipReason.STATUS_INCOMPLETE
        self.robots.save_status_report(robot, battery_percent, contamination_percent, now)
        if status.get("localized") is not True or status.get("nav2_ready") is not True or status.get("state") != "idle":
            return ClaimSkipReason.NOT_READY
        if battery_percent < settings.CLAIM_MIN_BATTERY_PERCENT:
            return ClaimSkipReason.BATTERY_LOW
        if contamination_percent > settings.CLAIM_MAX_CONTAMINATION_PERCENT:
            return ClaimSkipReason.CONTAMINATION_HIGH
        return None
