# =============================================================================
# 파일   : app/services/fms_robot_positions.py
# 역할   : 팀원 FMS가 1초마다 보내는 로봇 상태(robot-status)의 마지막 위치를 메모리에 두고, 병원 지도용으로 돌려준다 (2026-10-29)
# 작성일 : 2026-10-29
# 구성   :
#   - FmsRobotPosition        로봇 한 대의 마지막 값 (FMS 단위 그대로: cm, °)
#   - FmsRobotPositionStore   update(body, received_at) — 로봇 번호별 덮어쓰기, 이상한 항목은 건너뜀 / snapshot() / clear()
#   - robot_position_store    프로세스에 하나 (uvicorn 1 프로세스 — docker/backend-entrypoint.sh)
#   - RobotPositionService    list_positions() — 맵 id(FMS_MAP_NAME)·EMR 로봇(FMS_ROBOT_MAP)을 붙이고 cm→m, °→rad
# DB에 쓰지 않는다(로드맵: 위치 보고는 매번 저장하지 않음). 재시작하면 비지만 FMS가 1초 뒤 다시 보낸다.
# FMS pose: 경기장 그림 cm, 왼쪽 아래 원점, heading ° (0 = +x, 90 = +y) — fms/API.md 공통 규칙
# =============================================================================
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.map import MapRepository
from app.repositories.robot import RobotRepository
from app.schemas.robot_position import RobotPositionOut, RobotPositionsOut


@dataclass(frozen=True)
class FmsRobotPosition:
    """FMS robot-status 로봇 한 대의 마지막 값 (FMS 단위 그대로)."""

    fms_robot_number: int
    fms_robot_name: str | None
    x_cm: float
    y_cm: float
    heading_deg: float
    online: bool
    state: str | None
    place: str | None
    received_at: datetime


def _number(value: object) -> float | None:
    """[입력] value [출력] 유한한 숫자면 float, 아니면 None (bool은 숫자로 보지 않음)"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _text(value: object) -> str | None:
    """[입력] value [출력] 문자열이면 그대로, 아니면 None"""
    return value if isinstance(value, str) else None


class FmsRobotPositionStore:
    """로봇 번호 → 마지막 위치. FMS 요청(스레드풀)과 화면 조회가 같이 읽고 써서 잠금으로 감싼다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._positions: dict[int, FmsRobotPosition] = {}

    def update(self, body: dict[str, Any], received_at: datetime) -> int:
        """
        [입력] body: FMS robot-status {time, robots: [...]} / received_at: EMR이 받은 시각
        [출력] 저장한 로봇 수 (robot 번호·pose x·y·heading이 숫자인 항목만)
        """
        robots = body.get("robots")
        if not isinstance(robots, list):
            return 0
        positions: list[FmsRobotPosition] = []
        for robot in robots:
            if not isinstance(robot, dict):
                continue
            fms_robot_number = robot.get("robot")
            pose = robot.get("pose")
            if isinstance(fms_robot_number, bool) or not isinstance(fms_robot_number, int) or not isinstance(pose, dict):
                continue
            x_cm, y_cm, heading_deg = _number(pose.get("x")), _number(pose.get("y")), _number(pose.get("heading"))
            if x_cm is None or y_cm is None or heading_deg is None:
                continue
            positions.append(FmsRobotPosition(
                fms_robot_number=fms_robot_number, fms_robot_name=_text(robot.get("name")),
                x_cm=x_cm, y_cm=y_cm, heading_deg=heading_deg,
                online=robot.get("online") is not False,   # 칸이 없으면 온라인으로 본다 — 오래된 값은 is_stale이 잡는다
                state=_text(robot.get("state")), place=_text(robot.get("place")), received_at=received_at,
            ))
        with self._lock:
            for position in positions:
                self._positions[position.fms_robot_number] = position
        return len(positions)

    def snapshot(self) -> list[FmsRobotPosition]:
        """[입력] 없음 [출력] 로봇 번호 순 마지막 값"""
        with self._lock:
            return [self._positions[number] for number in sorted(self._positions)]

    def clear(self) -> None:
        """[입력] 없음 [출력] 없음 — 시험용"""
        with self._lock:
            self._positions.clear()


robot_position_store = FmsRobotPositionStore()


class RobotPositionService:
    """병원 지도용 로봇 위치 — 메모리의 마지막 값에 EMR 맵·로봇을 붙인다."""

    def __init__(self, db: Session) -> None:
        self.maps = MapRepository(db)
        self.robots = RobotRepository(db)

    def list_positions(self, now: datetime | None = None) -> RobotPositionsOut:
        """
        [입력] now: 오래된 값 판단 기준 시각 (기본 지금)
        [출력] RobotPositionsOut — map_id는 FMS_MAP_NAME 맵(없으면 None, 화면은 로봇을 그리지 않음)
        """
        now = now or datetime.now(UTC)
        fms_map = self.maps.get_by_name(settings.FMS_MAP_NAME)
        robots: list[RobotPositionOut] = []
        for position in robot_position_store.snapshot():
            robot_id = settings.FMS_ROBOT_MAP.get(position.fms_robot_number)
            robot = self.robots.get(robot_id) if robot_id is not None else None
            age_seconds = (now - position.received_at).total_seconds()
            robots.append(RobotPositionOut(
                fms_robot_number=position.fms_robot_number, fms_robot_name=position.fms_robot_name,
                robot_id=robot.id if robot else None, robot_name=robot.name if robot else None,
                map_x_m=position.x_cm / 100, map_y_m=position.y_cm / 100, map_yaw_rad=math.radians(position.heading_deg),
                online=position.online, state=position.state, place=position.place, reported_at=position.received_at,
                is_stale=not position.online or age_seconds > settings.FMS_POSITION_STALE_SECONDS,
            ))
        return RobotPositionsOut(map_id=fms_map.id if fms_map else None, robots=robots)
