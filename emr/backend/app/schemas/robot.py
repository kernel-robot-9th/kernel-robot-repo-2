# =============================================================================
# 파일   : app/schemas/robot.py
# 역할   : 로봇 등록·편집·응답 스키마
# 작성일 : 2026-10-14
# 구성   :
#   - RobotCreate  등록
#   - RobotUpdate  이름·상태·복귀 장소 변경
#   - RobotOut         키는 있는지·언제 발급했는지만 (해시 노출 안 함 — 로봇 조회는 무인증)
#   - RobotApiKeyOut   키 발급 응답. 평문 키는 이 응답에만 한 번 나온다
#   - RobotStatusReportOut   claim 때 로봇 서버에서 받은 마지막 배터리·오염도 (2026-10-23)
# =============================================================================
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import RobotStatus, RobotType
from app.schemas.common import OrmOut

ROBOT_TYPE_DESCRIPTION = "manipulator(적재 로봇팔) | amr(주행 배송 로봇). 등록 후 변경 불가"
STATUS_DESCRIPTION = "idle(대기) | delivering(배송 중) | charging(충전 중) | maintenance(점검·사용 불가)"


class RobotCreate(BaseModel):
    """로봇 등록 본문. 상태는 idle로 시작한다."""

    name: str = Field(min_length=1, max_length=64, description="로봇 이름 (UNIQUE)", examples=["배송로봇 1호"])
    robot_type: RobotType = Field(description=ROBOT_TYPE_DESCRIPTION)


class RobotUpdate(BaseModel):
    """로봇 편집 본문. 보낸 필드만 바뀐다(PATCH, null은 무시). 종류는 바꿀 수 없다."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    status: RobotStatus | None = Field(default=None, description=STATUS_DESCRIPTION)
    home_location_id: int | None = Field(
        default=None, description="복귀 장소 locations.id — 배송을 마치거나 실패하면 돌아가는 곳. 좌표가 있어야 배송을 맡는다",
    )
    robot_server_url: str | None = Field(
        default=None, max_length=255, pattern=r"^https?://[^\s/]+(:\d+)?/?$",
        description="로봇 서버(팀원 Pinky API) 주소 — claim 때 EMR이 GET {주소}/status로 배터리·오염도·주행 준비를 묻는다 (2026-10-23)",
        examples=["http://192.168.129.107:8080"],
    )


class RobotStatusReportOut(OrmOut):
    """claim 때 EMR이 로봇 서버에서 받은 마지막 상태 (2026-10-23)."""

    battery_percent: float = Field(description="배터리 0~100 %")
    contamination_percent: float = Field(description="오염도 0(깨끗)~100, 로봇이 잰 값")
    reported_at: datetime = Field(description="EMR이 로봇 서버에서 받은 시각")


class RobotOut(OrmOut):
    """로봇 응답."""

    id: int
    name: str
    robot_type: str = Field(description=ROBOT_TYPE_DESCRIPTION)
    status: str = Field(description=STATUS_DESCRIPTION)
    updated_at: datetime = Field(description="마지막 변경 시각 (이름·상태)")
    has_api_key: bool = Field(description="로봇 전용 API(/robot/...)용 키가 발급되어 있는지")
    api_key_issued_at: datetime | None = Field(description="지금 키를 발급한 시각. 키가 없으면 null")
    home_location_id: int | None = Field(description="복귀 장소. null이면 미지정 — 배송을 맡지 않는다")
    robot_server_url: str | None = Field(description="로봇 서버(팀원 Pinky API) 주소. null이면 배송을 맡지 않는다 (2026-10-23)")
    status_report: RobotStatusReportOut | None = Field(
        description="claim 때 로봇 서버에서 받은 마지막 배터리·오염도. null이면 아직 받은 적 없음 (2026-10-23)",
    )


class RobotApiKeyOut(BaseModel):
    """로봇 API 키 발급 응답. api_key는 다시 조회할 수 없다 — 로봇에 바로 설정한다."""

    robot_id: int
    api_key: str = Field(description="평문 키. 요청 헤더 X-Robot-Api-Key에 넣는다. 서버는 해시만 보관")
    issued_at: datetime
