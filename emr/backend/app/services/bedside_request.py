# =============================================================================
# 파일   : app/services/bedside_request.py
# 역할   : 병상 단말 환자 요청 — 비품 요청(SR-02)으로 배송을 바로 만들고, "받았습니다" 버튼(SR-06)으로 수령 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - BedsideRequestService  overview(GET /bedside/me), list_supplies, create_request, list_deliveries, confirm_receipt
# 사용자 결정(2026-10-22): 간호사 승인 없음(예약 시각 = 요청 시각 → 로봇이 다음 claim에서 가져감), 병상당 진행 중 1건,
#   품목당 1–5, requestable_by = patient만, 알림은 실패만 관리자에게(DeliveryNotifier), 마커는 내부에만(보여 주지 않음).
# 계약: docs/api_contract_delivery_2026-10-20.md 8장
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, Forbidden, NotFound
from app.models.bedside_device import BedsideDevice
from app.models.delivery import Delivery, DeliveryItem
from app.models.enums import DeliveryEventType, DeliveryRequester, DeliveryStatus, RequestableBy
from app.models.supply import Supply
from app.repositories.bedside_device import BedsideDeviceRepository
from app.repositories.delivery import DeliveryRepository
from app.repositories.supply import SupplyRepository
from app.schemas.bedside import BedsideRequestItemIn
from app.services.delivery import DeliveryService
from app.services.delivery_events import DeliveryEventRecorder

log = structlog.get_logger(__name__)
RECENT_DELIVERY_COUNT = 10


class BedsideRequestService:
    """병상 단말이 부르는 쪽의 업무 규칙. 단말은 키로 확인된 상태로 들어온다(get_current_bedside)."""

    def __init__(self, db: Session) -> None:
        self.devices = BedsideDeviceRepository(db)
        self.repo = DeliveryRepository(db)
        self.supplies = SupplyRepository(db)
        self.deliveries = DeliveryService(db)
        self.events = DeliveryEventRecorder(db)

    def overview(self, device: BedsideDevice) -> Delivery | None:
        """병상의 진행 중 배송.
        [입력] device
        [출력] Delivery | None
        """
        return self.repo.get_active_for_bedside(device.id)

    def list_supplies(self) -> list[Supply]:
        """환자가 요청할 수 있는 품목.
        [입력] 없음
        [출력] list[Supply]: requestable_by = patient, 삭제 안 됨, 이름 순
        """
        return self.supplies.list_requestable_by(RequestableBy.PATIENT)

    def create_request(self, device: BedsideDevice, items: list[BedsideRequestItemIn]) -> Delivery:
        """환자 비품 요청 → 배송을 바로 만든다(reserved, 예약 시각 = 지금, 목적지 = 병실).
        [입력] device / items: 품목·수량 (1–5는 스키마가 확인)
        [출력] Delivery
        거부: 409 bedside_room_has_no_position · bedside_request_in_progress · stock_insufficient,
              400 delivery_item_duplicate · supply_not_found · supply_not_patient_requestable
        """
        locked = self.devices.lock(device.id)   # 같은 병상의 동시 요청을 하나씩
        if locked is None:
            raise NotFound(f"bedside device {device.id} not found", code="bedside_device_not_found")
        room = device.location
        if room.map_id is None or room.map_x_m is None:
            raise Conflict(f"room {room.name} has no map position", code="bedside_room_has_no_position")
        if self.repo.get_active_for_bedside(device.id) is not None:
            raise Conflict(f"bedside {device.name} already has a delivery in progress", code="bedside_request_in_progress")
        self._validate_items(items)
        quantities = {item.supply_id: item.quantity for item in items}
        self.deliveries.reserve_stock(quantities)
        now = datetime.now(UTC)
        delivery = self.repo.add(Delivery(
            requester_type=DeliveryRequester.BEDSIDE, nurse_id=None,
            bedside_device_id=device.id, bedside_name=device.name,
            destination_location_id=room.id, scheduled_at=now,
            items=[DeliveryItem(supply_id=supply_id, quantity=quantity) for supply_id, quantity in quantities.items()],
        ))
        self.events.record_by_bedside(delivery, DeliveryEventType.RESERVED, device.name, now,
                                      self.events.reserved_details(delivery))
        log.info("bedside_request_created", bedside_device_id=device.id, delivery_id=delivery.id)
        return delivery

    def list_deliveries(self, device: BedsideDevice) -> list[Delivery]:
        """병상의 최근 배송.
        [입력] device
        [출력] list[Delivery]: 최근 것부터 RECENT_DELIVERY_COUNT건
        """
        return self.repo.list_for_bedside(device.id, RECENT_DELIVERY_COUNT)

    def confirm_receipt(self, device: BedsideDevice, delivery_id: int) -> Delivery:
        """"받았습니다" 버튼 — 도착한 이 병상의 배송을 수령 처리.
        [입력] device / delivery_id
        [출력] Delivery: received (없으면 404, 다른 병상이면 403 delivery_not_for_bedside, 도착 전·끝났으면 409 delivery_not_arrived)
        """
        delivery = self.repo.get_with_items(delivery_id, lock=True)
        if delivery is None:
            raise NotFound(f"delivery {delivery_id} not found", code="delivery_not_found")
        if delivery.bedside_device_id != device.id:
            raise Forbidden(f"delivery {delivery_id} is not this bedside's", code="delivery_not_for_bedside")
        if delivery.status != DeliveryStatus.ARRIVED:
            raise Conflict(f"delivery {delivery_id} is {delivery.status}; only arrived can be received", code="delivery_not_arrived")
        now = datetime.now(UTC)
        delivery.status = DeliveryStatus.RECEIVED
        delivery.received_at = now
        delivery.received_by_robot_id = delivery.assigned_robot_id   # 가져다준 로봇 (마커를 읽지는 않음)
        self.events.record_by_bedside(delivery, DeliveryEventType.RECEIVED, device.name, now)
        log.info("bedside_receipt_confirmed", bedside_device_id=device.id, delivery_id=delivery.id)
        return delivery

    def _validate_items(self, items: list[BedsideRequestItemIn]) -> None:
        """품목 검사: 중복 없음, 있는 비품, 환자가 요청할 수 있는 비품.
        [입력] items
        [출력] 없음 (틀리면 BadRequest)
        """
        supply_ids = [item.supply_id for item in items]
        if len(supply_ids) != len(set(supply_ids)):
            raise BadRequest("duplicate supply_id in items", code="delivery_item_duplicate")
        for supply_id in supply_ids:
            supply = self.supplies.get(supply_id)
            if supply is None or supply.is_deleted:
                raise BadRequest(f"supply {supply_id} not found", code="supply_not_found")
            if supply.requestable_by != RequestableBy.PATIENT:
                raise BadRequest(f"supply {supply_id} cannot be requested by patients", code="supply_not_patient_requestable")
