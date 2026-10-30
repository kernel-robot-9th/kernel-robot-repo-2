# =============================================================================
# 파일   : app/schemas/robot_position.py
# 역할   : 병원 지도용 로봇 위치 응답 (GET /robot-positions, 2026-10-29)
# 작성일 : 2026-10-29
# 구성   :
#   - RobotPositionOut    로봇 한 대 — FMS robot-status 마지막 값을 EMR 맵 단위(m·rad)로, 배터리·오염도 % (2026-10-30)
#   - RobotPositionsOut   map_id(그릴 맵) + 로봇들
# =============================================================================
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RobotPositionOut(BaseModel):
    """로봇 한 대의 마지막 위치. 좌표는 EMR 맵 미터(FMS 그림 cm / 100), 방향은 라디안(0 = +x, 반시계)."""

    fms_robot_number: int = Field(description="FMS 로봇 번호 (fms/robots.yaml 1·2·3)")
    fms_robot_name: str | None = Field(description="FMS의 핑키 이름 (예 pinky_6364)")
    robot_id: int | None = Field(description="EMR 로봇 id (FMS_ROBOT_MAP). 대응이 없으면 null")
    robot_name: str | None = Field(description="EMR 로봇 이름. 대응이 없으면 null")
    map_x_m: float
    map_y_m: float
    map_yaw_rad: float
    online: bool = Field(description="FMS가 보낸 online")
    state: str | None = Field(description="FMS 로봇 state (idle·moving·docking …)")
    place: str | None = Field(description="FMS가 보낸 사람이 읽는 위치 (아래 복도, 101호 …)")
    reported_at: datetime = Field(description="EMR이 이 값을 받은 시각")
    is_stale: bool = Field(description="online=false이거나 FMS_POSITION_STALE_SECONDS보다 오래 받지 못함 — 화면은 '연결 끊김'")
    fatigue_percent: float | None = Field(description="FMS fatigue 피로도 0~100 — 실제 배터리가 아니라 FMS 모델 값(2026-10-30, 병실마다 −10·충전 자리 100). 없으면 null")
    contamination_percent: float | None = Field(description="FMS contamination 0~100 — FMS 모델 값(2026-10-30). 없으면 null")


class RobotPositionsOut(BaseModel):
    """병원 지도용 로봇 위치 목록."""

    map_id: int | None = Field(description="위치를 그릴 EMR 맵 (설정 FMS_MAP_NAME). 맵이 없으면 null")
    robots: list[RobotPositionOut] = Field(description="FMS 로봇 번호 순. FMS에서 아직 받은 적 없으면 빈 목록")
