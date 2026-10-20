# =============================================================================
# 파일   : app/schemas/map.py
# 역할   : 맵(파일 이름·맵 정보) 스키마
# 작성일 : 2026-10-14
# 구성   :
#   - MapCreate  등록
#   - MapUpdate  편집
#   - MapOut     맵 정보 + 이미지 유무·크기 (이미지 자체는 GET /maps/{id}/image)
# =============================================================================
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import OrmOut

FILE_NAME_DESCRIPTION = "맵 yaml 파일 이름 (UNIQUE)"
RESOLUTION_DESCRIPTION = "픽셀 하나의 크기 (미터/픽셀)"
ORIGIN_X_DESCRIPTION = "맵 이미지 왼쪽 아래 픽셀의 x (미터)"
ORIGIN_Y_DESCRIPTION = "맵 이미지 왼쪽 아래 픽셀의 y (미터)"
ORIGIN_YAW_DESCRIPTION = "맵 회전 (라디안)"


class MapCreate(BaseModel):
    """맵 등록 본문. 값은 맵 yaml의 resolution·origin을 그대로 옮긴다."""

    name: str = Field(min_length=1, max_length=64, description="맵 이름 (UNIQUE)", examples=["3병동"])
    file_name: str = Field(min_length=1, max_length=128, description=FILE_NAME_DESCRIPTION, examples=["ward3.yaml"])
    resolution_m_per_pixel: float = Field(gt=0, description=RESOLUTION_DESCRIPTION, examples=[0.05])
    origin_x_m: float = Field(default=0.0, description=ORIGIN_X_DESCRIPTION, examples=[-10.0])
    origin_y_m: float = Field(default=0.0, description=ORIGIN_Y_DESCRIPTION, examples=[-10.0])
    origin_yaw_rad: float = Field(default=0.0, description=ORIGIN_YAW_DESCRIPTION, examples=[0.0])


class MapUpdate(BaseModel):
    """맵 편집 본문. 보낸 필드만 바뀐다(PATCH)."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    file_name: str | None = Field(default=None, min_length=1, max_length=128, description=FILE_NAME_DESCRIPTION)
    resolution_m_per_pixel: float | None = Field(default=None, gt=0, description=RESOLUTION_DESCRIPTION)
    origin_x_m: float | None = Field(default=None, description=ORIGIN_X_DESCRIPTION)
    origin_y_m: float | None = Field(default=None, description=ORIGIN_Y_DESCRIPTION)
    origin_yaw_rad: float | None = Field(default=None, description=ORIGIN_YAW_DESCRIPTION)


class MapOut(OrmOut):
    """맵 응답."""

    id: int
    name: str
    file_name: str = Field(description=FILE_NAME_DESCRIPTION)
    resolution_m_per_pixel: float = Field(description=RESOLUTION_DESCRIPTION)
    origin_x_m: float = Field(description=ORIGIN_X_DESCRIPTION)
    origin_y_m: float = Field(description=ORIGIN_Y_DESCRIPTION)
    origin_yaw_rad: float = Field(description=ORIGIN_YAW_DESCRIPTION)
    has_image: bool = Field(description="맵 이미지가 있는지. 있으면 GET /maps/{id}/image (PNG)")
    image_width_px: int | None = Field(description="이미지 가로 픽셀. 이미지가 없으면 null")
    image_height_px: int | None = Field(description="이미지 세로 픽셀. 픽셀↔미터 변환에 필요 (ROS는 y가 위로, 이미지는 아래로)")
    image_file_name: str | None = Field(description="올린 이미지의 원래 이름 (예: my_map.pgm)")
    updated_at: datetime = Field(description="마지막 변경 시각. 이미지 주소에 붙여 캐시를 새로 고친다")
