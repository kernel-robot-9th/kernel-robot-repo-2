# =============================================================================
# 파일   : app/schemas/location.py
# 역할   : 장소(배송 위치·맵 좌표) 스키마
# 작성일 : 2026-10-14
# 구성   :
#   - LocationCreate  등록
#   - LocationUpdate  편집
#   - LocationOut     
# =============================================================================
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import OrmOut
from app.schemas.map import MapOut

MAP_X_DESCRIPTION = "맵 좌표 x (미터)"
MAP_Y_DESCRIPTION = "맵 좌표 y (미터)"
MAP_YAW_DESCRIPTION = "도착 시 로봇이 바라볼 방향 (라디안)"
ROBOT_ONLY_DESCRIPTION = ("로봇 전용 장소(충전·출발점·대기 포켓, 2026-10-22). true면 비품 배송 불가 — 품목 없는 로봇 이동만"
                          "(품목을 보내면 400 location_robot_only, 도착하면 바로 완료). 병상 병실로 고를 수 없다. 로봇 복귀 장소로는 쓴다")
ROBOT_DEST_DESCRIPTION = ("로봇 목적지 이름 (팀원 Pinky API GET /dests, UNIQUE, 2026-10-22). 배송 실행기가 POST /goto {\"dest\"}로 쓴다. "
                          "null이면 대응 없음 — 그 장소로의 배송은 움직이지 않고 destination_blocked")


class _MapPoseFields(BaseModel):
    """좌표 세 값은 함께 보내거나 함께 생략한다."""

    map_x_m: float | None = Field(default=None, description=MAP_X_DESCRIPTION, examples=[12.5])
    map_y_m: float | None = Field(default=None, description=MAP_Y_DESCRIPTION, examples=[3.2])
    map_yaw_rad: float | None = Field(default=None, description=MAP_YAW_DESCRIPTION, examples=[1.57])

    @model_validator(mode="after")
    def _map_pose_all_or_none(self) -> Self:
        given = [value is not None for value in (self.map_x_m, self.map_y_m, self.map_yaw_rad)]
        if any(given) and not all(given):
            raise ValueError("map_x_m, map_y_m, map_yaw_rad must be given together")
        return self


class LocationCreate(_MapPoseFields):
    """장소 등록 본문. 좌표를 생략하면 "좌표 미등록" 장소로 등록된다. 좌표를 넣으면 map_id도 필요하다."""

    map_id: int | None = Field(default=None, description="좌표가 속한 맵 maps.id. 좌표를 보내면 필수")

    name: str = Field(min_length=1, max_length=64, description="장소 이름 (UNIQUE)", examples=["301호"])
    robot_dest: str | None = Field(default=None, min_length=1, max_length=64, description=ROBOT_DEST_DESCRIPTION, examples=["PHARMACY"])
    robot_only: bool = Field(default=False, description=ROBOT_ONLY_DESCRIPTION)


class LocationUpdate(_MapPoseFields):
    """장소 편집 본문. 보낸 필드만 바뀐다(PATCH). 좌표는 세 값을 함께 보낸다. 좌표가 있으면 맵도 지정돼 있어야 한다."""

    map_id: int | None = Field(default=None, description="좌표가 속한 맵 maps.id")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    robot_dest: str | None = Field(default=None, min_length=1, max_length=64, description=ROBOT_DEST_DESCRIPTION)
    robot_only: bool | None = Field(default=None, description=ROBOT_ONLY_DESCRIPTION)


class LocationOut(OrmOut):
    """장소 응답. 좌표가 null이면 좌표 미등록, map이 함께 내려간다."""

    id: int
    name: str
    map_x_m: float | None = Field(description=MAP_X_DESCRIPTION)
    map_y_m: float | None = Field(description=MAP_Y_DESCRIPTION)
    map_yaw_rad: float | None = Field(description=MAP_YAW_DESCRIPTION)
    map_id: int | None = Field(description="좌표가 속한 맵. null이면 맵 미지정")
    robot_dest: str | None = Field(description=ROBOT_DEST_DESCRIPTION)
    robot_only: bool = Field(description=ROBOT_ONLY_DESCRIPTION)
    map: MapOut | None = Field(description="맵 파일 이름과 맵 정보")
