# =============================================================================
# 파일   : app/models/bedside_device.py
# 역할   : bedside_devices — 병상 단말 (환자가 비품을 요청하고 "받았습니다"를 누르는 태블릿)
# 작성일 : 2026-10-22
# 구성   :
#   - BedsideDevice  병상 이름·병실 장소·단말 키(sha256). 환자 개인정보는 저장하지 않는다
# 사용자 결정(2026-10-22): 환자 식별은 병상 단말 키(로봇 키와 같은 방식). 관리자가 등록·키 발급
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.location import Location


class BedsideDevice(TimestampMixin, Base):
    """병상 단말 한 대. 요청한 배송의 목적지는 이 병상의 병실(location)."""

    __tablename__ = "bedside_devices"
    __table_args__ = (UniqueConstraint("api_key_hash", name="uq_bedside_devices_api_key_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 병상 이름 (예: "301호-1")
    # 병실. 병상이 쓰는 장소는 지울 수 없다(RESTRICT, 서비스가 409 location_is_bedside_room)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", name="fk_bedside_devices_location_id", ondelete="RESTRICT"), nullable=False
    )
    # 단말 키의 sha256. 평문은 발급 응답에서 한 번만. NULL=키 없음
    api_key_hash: Mapped[str | None] = mapped_column(String(64))
    api_key_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    location: Mapped[Location] = relationship()

    @property
    def has_api_key(self) -> bool:
        """키가 발급되어 있는지 (BedsideDeviceOut용).
        [입력] 없음
        [출력] bool
        """
        return self.api_key_hash is not None
