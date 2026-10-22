# =============================================================================
# 파일   : app/services/bedside_device.py
# 역할   : 병상 단말 등록·수정·삭제·키 관리 (관리자, 2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - BedsideDeviceService  list/get/create/update/delete, issue_api_key/revoke_api_key (로봇 키와 같은 방식)
# 삭제: 진행 중 배송이 있으면 409. 지난 배송은 bedside_device_id가 NULL이 되고 bedside_name 스냅숏은 남는다.
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.core.security import generate_bedside_api_key, hash_robot_api_key
from app.models.bedside_device import BedsideDevice
from app.repositories.bedside_device import BedsideDeviceRepository
from app.repositories.delivery import DeliveryRepository
from app.repositories.location import LocationRepository
from app.schemas.bedside import BedsideDeviceCreate, BedsideDeviceUpdate

log = structlog.get_logger(__name__)


class BedsideDeviceService:
    """병상 단말 관리. 권한(관리자)은 라우터가 확인한다."""

    def __init__(self, db: Session) -> None:
        self.repo = BedsideDeviceRepository(db)
        self.locations = LocationRepository(db)
        self.deliveries = DeliveryRepository(db)

    def list(self, limit: int = 100, offset: int = 0) -> list[BedsideDevice]:
        """[입력] limit / offset  [출력] list[BedsideDevice]: 이름 순"""
        return self.repo.list_ordered(limit, offset)

    def get(self, device_id: int) -> BedsideDevice:
        """[입력] device_id  [출력] BedsideDevice (없으면 NotFound)"""
        device = self.repo.get(device_id)
        if device is None:
            raise NotFound(f"bedside device {device_id} not found", code="bedside_device_not_found")
        return device

    def create(self, data: BedsideDeviceCreate) -> BedsideDevice:
        """병상 등록. 이름 중복이면 Conflict, 병실이 없으면 BadRequest.
        [입력] data
        [출력] BedsideDevice (키 없음 — 따로 발급)
        """
        if self.repo.get_by_name(data.name):
            raise Conflict(f"bedside name {data.name} already exists", code="bedside_name_duplicate")
        room = self._room(data.location_id)
        return self.repo.add(BedsideDevice(name=data.name, location_id=room.id, location=room))

    def update(self, device_id: int, data: BedsideDeviceUpdate) -> BedsideDevice:
        """보낸 필드만 수정 (null 무시).
        [입력] device_id / data
        [출력] BedsideDevice
        """
        device = self.get(device_id)
        changes = data.model_dump(exclude_none=True)
        if "name" in changes and changes["name"] != device.name and self.repo.get_by_name(changes["name"]):
            raise Conflict(f"bedside name {changes['name']} already exists", code="bedside_name_duplicate")
        if "location_id" in changes:
            # FK와 관계를 함께 바꾼다 — 응답에 옛 병실이 남지 않게
            room = self._room(changes.pop("location_id"))
            device.location = room
            device.location_id = room.id
        for field, value in changes.items():
            setattr(device, field, value)
        return device

    def delete(self, device_id: int) -> None:
        """병상 삭제. 진행 중 배송이 있으면 Conflict.
        [입력] device_id
        [출력] 없음
        """
        device = self.get(device_id)
        if self.deliveries.get_active_for_bedside(device_id) is not None:
            raise Conflict(f"bedside device {device_id} has an active delivery", code="bedside_has_active_delivery")
        self.repo.delete(device)

    def issue_api_key(self, device_id: int) -> tuple[BedsideDevice, str]:
        """키 발급·재발급. 이전 키는 즉시 쓸 수 없다.
        [입력] device_id
        [출력] (BedsideDevice, 평문 키) — 평문은 응답으로 한 번만, 저장·로그하지 않는다
        """
        device = self.get(device_id)
        raw_api_key = generate_bedside_api_key()
        device.api_key_hash = hash_robot_api_key(raw_api_key)
        device.api_key_issued_at = datetime.now(UTC)
        log.info("bedside_api_key_issued", bedside_device_id=device.id)
        return device, raw_api_key

    def revoke_api_key(self, device_id: int) -> None:
        """키 폐기. 이후 그 단말의 요청은 401.
        [입력] device_id
        [출력] 없음 (키가 이미 없어도 성공)
        """
        device = self.get(device_id)
        device.api_key_hash = None
        device.api_key_issued_at = None
        log.info("bedside_api_key_revoked", bedside_device_id=device.id)

    def _room(self, location_id: int):
        """병실 장소 확인.
        [입력] location_id
        [출력] Location (없으면 BadRequest location_not_found)
        """
        room = self.locations.get(location_id)
        if room is None:
            raise BadRequest(f"location {location_id} not found", code="location_not_found")
        return room
