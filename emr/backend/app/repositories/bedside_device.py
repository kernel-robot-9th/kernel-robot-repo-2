# =============================================================================
# 파일   : app/repositories/bedside_device.py
# 역할   : 병상 단말 조회 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - BedsideDeviceRepository  list_ordered, get_by_name, get_by_api_key_hash, lock, delete
# =============================================================================
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.bedside_device import BedsideDevice
from app.repositories.base import BaseRepository


class BedsideDeviceRepository(BaseRepository[BedsideDevice]):
    """bedside_devices 접근."""

    model = BedsideDevice

    def list_ordered(self, limit: int = 100, offset: int = 0) -> list[BedsideDevice]:
        """병상 목록, 이름 순 (병실 함께 로드).
        [입력] limit / offset
        [출력] list[BedsideDevice]
        """
        statement = (select(BedsideDevice).options(selectinload(BedsideDevice.location))
                     .order_by(BedsideDevice.name).limit(limit).offset(offset))
        return list(self.db.scalars(statement))

    def get_by_name(self, name: str) -> BedsideDevice | None:
        """이름으로 조회 (중복 검사).
        [입력] name
        [출력] BedsideDevice | None
        """
        return self.db.scalar(select(BedsideDevice).where(BedsideDevice.name == name))

    def get_by_api_key_hash(self, api_key_hash: str) -> BedsideDevice | None:
        """키 해시로 조회 (병상 단말 인증).
        [입력] api_key_hash: sha256 hex
        [출력] BedsideDevice | None
        """
        return self.db.scalar(
            select(BedsideDevice).options(selectinload(BedsideDevice.location))
            .where(BedsideDevice.api_key_hash == api_key_hash)
        )

    def lock(self, device_id: int) -> BedsideDevice | None:
        """병상 행을 잠가 다시 읽는다 — 같은 병상의 요청이 동시에 두 번 와도 하나씩 (진행 중 1건 확인).
        [입력] device_id
        [출력] BedsideDevice | None
        """
        statement = (select(BedsideDevice).where(BedsideDevice.id == device_id).with_for_update()
                     .execution_options(populate_existing=True))
        return self.db.scalar(statement)

    def delete(self, device: BedsideDevice) -> None:
        """행 삭제 (지난 배송의 bedside_device_id는 NULL, bedside_name 스냅숏은 남음).
        [입력] device
        [출력] 없음
        """
        self.db.delete(device)
        self.db.flush()
