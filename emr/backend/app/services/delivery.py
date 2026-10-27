# =============================================================================
# 파일   : app/services/delivery.py
# 역할   : 배송 — 간호사 예약 등록·조회·변경·취소
# 작성일 : 2026-10-14
# 구성   :
#   - DeliveryService  create/list_for_nurse/get/update/cancel (간호사 쪽), restore_stock (취소·실패 공용)
#                      예약·변경·취소는 배송 기록(delivery_events)에도 남긴다 (2026-10-21)
#                      confirm_receipt — 간호사 "받았습니다" 버튼 수령 (2026-10-22, NURSE_RECEIPT_METHOD=button)
#                      require_arrived·mark_received — 수령 공용 (간호사·환자 버튼, 로봇 마커, 로봇 전용 장소 이동 — 2026-10-23)
# 로봇 쪽(배송 가져가기·진행 보고·수령 확인)은 app/services/dispatch.py (2026-10-20)
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, Forbidden, NotFound
from app.models.delivery import Delivery, DeliveryItem
from app.models.enums import DeliveryEventType, DeliveryStatus, ReceiptMethod
from app.models.location import Location
from app.repositories.delivery import DeliveryRepository
from app.repositories.fms_order import FmsOrderRepository
from app.repositories.location import LocationRepository
from app.repositories.supply import SupplyRepository
from app.schemas.delivery import (
    DeliveryCreate, DeliveryItemIn, DeliveryUpdate,
)
from app.services.delivery_events import DeliveryEventRecorder, DeliverySnapshot
from app.services.delivery_notifier import DeliveryNotifier
from app.services.low_stock import LowStockNotifier, is_low_stock


SCHEDULED_AT_GRACE = timedelta(minutes=5)   # "지금"(브라우저·서버 시계 차이 포함)으로 예약하면 바로 로봇이 가져갈 수 있다 (2026-10-22)


class DeliveryService:
    """배송 일정 예약. 간호사 본인 예약만 조회·변경·취소할 수 있다. 변경·취소는 reserved 상태에서만(로봇이 맡기 전).
    재고는 예약할 때 빼고, 취소·실패하면 되돌리고, 품목을 바꾸면 차이만큼 조정한다 (2026-10-15·20 결정).
    그래서 supplies.stock_qty는 '지금 예약할 수 있는 수량'이다.
    """

    def __init__(self, db: Session) -> None:
        self.repo = DeliveryRepository(db)
        self.fms_orders = FmsOrderRepository(db)
        self.supplies = SupplyRepository(db)
        self.locations = LocationRepository(db)
        self.low_stock_notifier = LowStockNotifier(db)
        self.events = DeliveryEventRecorder(db)
        self.notifier = DeliveryNotifier(db)

    def create(self, data: DeliveryCreate, nurse_id: int) -> Delivery:
        """예약 등록.
        [입력] data / nurse_id: 토큰에서 복원된 간호사
        [출력] Delivery: status=reserved
        """
        self._validate_scheduled_at(data.scheduled_at)
        destination = self._validate_destination(data.destination_location_id)
        self._validate_items_for(destination, data.items)
        self._validate_items(data.items)
        self._adjust_stock(self._quantities(data.items))
        delivery = self.repo.add(Delivery(
            nurse_id=nurse_id, destination_location_id=data.destination_location_id, scheduled_at=data.scheduled_at,
            items=self._to_items(data.items),
        ))
        self.events.record_by_nurse(
            delivery, DeliveryEventType.RESERVED, nurse_id, datetime.now(UTC), self.events.reserved_details(delivery),
        )
        return delivery

    def list_for_nurse(
        self, nurse_id: int, status: DeliveryStatus | None = None, limit: int = 100, offset: int = 0,
    ) -> list[Delivery]:
        """간호사 본인 예약 목록.
        [입력] nurse_id / status: 있으면 그 상태만 / limit / offset
        [출력] list[Delivery]: 배송 예정 시각이 빠른 순
        """
        return self.repo.list_by_nurse(nurse_id, status, limit, offset)

    def get(self, delivery_id: int, nurse_id: int, lock: bool = False) -> Delivery:
        """한 건 조회 (품목 포함). 본인 예약만.
        [입력] delivery_id / nurse_id: 조회하는 간호사 / lock: 변경·취소 전 행 잠금 (로봇 claim과 경합 방지)
        [출력] Delivery (없으면 NotFound, 남의 예약이면 Forbidden)
        """
        delivery = self.repo.get_with_items(delivery_id, lock=lock)
        if delivery is None:
            raise NotFound(f"delivery {delivery_id} not found", code="delivery_not_found")
        if delivery.nurse_id != nurse_id:
            raise Forbidden("not your delivery", code="delivery_not_owned")
        return delivery

    def update(self, delivery_id: int, data: DeliveryUpdate, nurse_id: int) -> Delivery:
        """예약 변경. items를 보내면 품목 전체 교체. null로 보낸 필드는 무시.
        [입력] delivery_id / data / nurse_id
        [출력] Delivery (reserved 아니면 Conflict)
        """
        delivery = self._get_reserved(delivery_id, nurse_id)
        before = DeliverySnapshot.of(delivery)
        if data.scheduled_at is not None:
            self._validate_scheduled_at(data.scheduled_at)
            delivery.scheduled_at = data.scheduled_at
        if data.destination_location_id is not None:
            # FK와 관계를 함께 바꾼다 — FK만 바꾸면 이미 로드된 destination_location이 응답에 옛 장소로 남는다
            delivery.destination_location = self._validate_destination(data.destination_location_id)
            delivery.destination_location_id = data.destination_location_id
        if data.items is not None:
            self._validate_items(data.items)
            previous_quantities = {item.supply_id: item.quantity for item in delivery.items}
            new_quantities = self._quantities(data.items)
            self._adjust_stock({
                supply_id: new_quantities.get(supply_id, 0) - previous_quantities.get(supply_id, 0)
                for supply_id in previous_quantities.keys() | new_quantities.keys()
            })
            self.repo.replace_items(delivery, self._to_items(data.items))
        self._validate_items_for(delivery.destination_location, delivery.items)   # 바뀐 목적지·품목 조합 확인
        changes = self.events.update_changes(before, DeliverySnapshot.of(delivery))
        if changes:   # 같은 값을 다시 보낸 변경은 기록하지 않는다
            self.events.record_by_nurse(delivery, DeliveryEventType.UPDATED, nurse_id, datetime.now(UTC), changes)
        return delivery

    def confirm_receipt(self, delivery_id: int, nurse_id: int) -> Delivery:
        """"받았습니다" 버튼 — 도착한 본인 배송을 수령 처리 (2026-10-22, 마커 대신). 실행기는 /robot/me로 알아차리고 돌아간다.
        [입력] delivery_id / nurse_id
        [출력] Delivery: received (남의 예약 403, 도착 전·끝났으면 409 delivery_not_arrived, 마커 방식이면 409 delivery_receipt_by_marker)
        """
        delivery = self.get(delivery_id, nurse_id, lock=True)
        self.require_arrived(delivery)
        if delivery.receipt_method != ReceiptMethod.BUTTON:
            raise Conflict(f"delivery {delivery_id} is received by the robot reading the marker", code="delivery_receipt_by_marker")
        now = datetime.now(UTC)
        self.mark_received(delivery, now, nurse_id)
        self.notifier.notify_received(delivery)   # 같은 간호사의 다른 탭·화면도 목록을 새로 고친다
        self.events.record_by_nurse(delivery, DeliveryEventType.RECEIVED, nurse_id, now)
        return delivery

    @staticmethod
    def require_arrived(delivery: Delivery) -> None:
        """수령할 수 있는 상태(arrived)인지 — 간호사·환자 "받았습니다" 공용.
        [입력] delivery
        [출력] 없음 (아니면 Conflict delivery_not_arrived)
        """
        if delivery.status != DeliveryStatus.ARRIVED:
            raise Conflict(f"delivery {delivery.id} is {delivery.status}; only arrived can be received", code="delivery_not_arrived")

    @staticmethod
    def mark_received(delivery: Delivery, received_at: datetime, nurse_id: int | None) -> None:
        """received로 바꾸고 수령 기록을 채운다 — 간호사·환자 버튼, 로봇 마커, 로봇 전용 장소 이동 공용 (2026-10-23 묶음).
        받은 로봇은 언제나 맡은 로봇(가져다준 로봇). 알림·배송 기록은 부르는 쪽이 한다(누가 했는지가 다르다).
        [입력] delivery / received_at / nurse_id: 받은 간호사 (병상 배송은 None)
        [출력] 없음
        """
        delivery.status = DeliveryStatus.RECEIVED
        delivery.received_at = received_at
        delivery.received_by_nurse_id = nurse_id
        delivery.received_by_robot_id = delivery.assigned_robot_id

    def cancel(self, delivery_id: int, nurse_id: int) -> Delivery:
        """예약 취소. 예약했던 수량을 재고로 되돌린다.
        [입력] delivery_id / nurse_id
        [출력] Delivery: status=cancelled (reserved 아니면 Conflict)
        """
        delivery = self._get_reserved(delivery_id, nurse_id)
        self.restore_stock(delivery)
        delivery.status = DeliveryStatus.CANCELLED
        self.events.record_by_nurse(delivery, DeliveryEventType.CANCELLED, nurse_id, datetime.now(UTC))
        return delivery

    def reserve_stock(self, quantity_by_supply_id: dict[int, int]) -> None:
        """새 배송만큼 재고를 뺀다 — 병상 요청(BedsideRequestService)이 같은 규칙(잠금·부족이면 409·부족 알림)을 쓰게 (2026-10-22).
        [입력] quantity_by_supply_id: {supply_id: 수량}
        [출력] 없음 (모자라면 Conflict stock_insufficient)
        """
        self._adjust_stock(quantity_by_supply_id)

    def restore_stock(self, delivery: Delivery) -> None:
        """예약 때 뺀 수량을 재고로 되돌린다 — 취소와 배송 실패(DispatchService)가 함께 쓴다.
        [입력] delivery: 품목이 로드된 배송
        [출력] 없음 (부족 상태가 풀린 비품은 알림)
        """
        self._adjust_stock({item.supply_id: -item.quantity for item in delivery.items})

    # ---- 내부 ----------------------------------------------------------------

    def _get_reserved(self, delivery_id: int, nurse_id: int) -> Delivery:
        """본인 예약이고 reserved 상태인지 확인하고 반환.
        [입력] delivery_id / nurse_id
        [출력] Delivery (reserved 아니면 Conflict — 로봇이 이미 맡았거나 끝난 예약.
        물품을 하나라도 FMS에 보냈으면 Conflict delivery_sent_to_fms — FMS 취소 연동 전까지, 2026-10-27)
        """
        delivery = self.get(delivery_id, nurse_id, lock=True)
        if delivery.status != DeliveryStatus.RESERVED:
            raise Conflict(f"delivery {delivery_id} is {delivery.status}; only reserved can be changed", code="delivery_not_reserved")
        if self.fms_orders.delivery_has_orders(delivery.id):
            raise Conflict(f"delivery {delivery_id} is already sent to FMS", code="delivery_sent_to_fms")
        return delivery

    def _validate_scheduled_at(self, scheduled_at: datetime) -> None:
        """배송 예정 시각 확인 — "지금" 예약도 받는다(SCHEDULED_AT_GRACE 안의 과거까지, 2026-10-22: 바로 claim해 시험하려고).
        [입력] scheduled_at: 시간대 포함
        [출력] 없음 (그보다 과거면 BadRequest)
        """
        if scheduled_at < datetime.now(UTC) - SCHEDULED_AT_GRACE:
            raise BadRequest("scheduled_at must not be in the past", code="scheduled_at_not_future")

    def _validate_destination(self, destination_location_id: int) -> Location:
        """배송 위치가 등록된 장소인지 확인. 좌표 미등록 장소도 예약은 가능하다. 로봇 전용 장소의 품목 규칙은 _validate_items_for.
        [입력] destination_location_id
        [출력] Location (없으면 BadRequest location_not_found)
        """
        location = self.locations.get(destination_location_id)
        if location is None:
            raise BadRequest(f"location {destination_location_id} not found", code="location_not_found")
        return location

    @staticmethod
    def _validate_items_for(destination: Location, items: list) -> None:
        """목적지와 품목 조합 (2026-10-22): 로봇 전용 장소(충전·출발점·대기 포켓)는 품목 없는 '로봇 이동'만 — 비품 배송 불가.
        보통 장소는 품목이 하나 이상.
        [입력] destination / items [출력] 없음 (틀리면 BadRequest location_robot_only · delivery_items_required)
        """
        if destination.robot_only and items:
            raise BadRequest(f"location {destination.id} is robot-only; send no items (robot move)", code="location_robot_only")
        if not destination.robot_only and not items:
            raise BadRequest("items are required", code="delivery_items_required")

    def _validate_items(self, items: list[DeliveryItemIn]) -> None:
        """품목 중복·존재·삭제 여부 확인.
        [입력] items
        [출력] 없음 (BadRequest)
        """
        supply_ids = [item.supply_id for item in items]
        if len(supply_ids) != len(set(supply_ids)):
            raise BadRequest("duplicate supply_id in items", code="delivery_item_duplicate")
        for supply_id in supply_ids:
            supply = self.supplies.get(supply_id)
            if supply is None or supply.is_deleted:
                raise BadRequest(f"supply {supply_id} not found", code="supply_not_found")

    def _adjust_stock(self, reserved_change_by_supply_id: dict[int, int]) -> None:
        """예약 수량이 늘어난 만큼 재고를 빼고, 줄어든 만큼 되돌린다. 비품 행을 잠근 뒤 확인·반영한다.
        [입력] reserved_change_by_supply_id: {supply_id: 늘어난 예약 수량 (줄었으면 음수)}
        [출력] 없음 (하나라도 재고가 모자라면 아무것도 바꾸지 않고 Conflict). 부족 상태가 바뀐 비품은 알림
        """
        changes = {supply_id: change for supply_id, change in reserved_change_by_supply_id.items() if change != 0}
        if not changes:
            return
        supplies = self.supplies.lock_many(sorted(changes))
        for supply_id, change in changes.items():
            if change > supplies[supply_id].stock_qty:
                raise Conflict(
                    f"supply {supply_id} stock {supplies[supply_id].stock_qty} is less than {change}",
                    code="stock_insufficient",
                )
        for supply_id, change in changes.items():
            was_low_stock = is_low_stock(supplies[supply_id])
            supplies[supply_id].stock_qty -= change
            self.low_stock_notifier.notify_if_changed(supplies[supply_id], was_low_stock)

    @staticmethod
    def _quantities(items: list[DeliveryItemIn]) -> dict[int, int]:
        """품목 목록 → {supply_id: 수량}. 같은 비품 중복은 _validate_items가 먼저 막는다.
        [입력] items
        [출력] dict[int, int]
        """
        return {item.supply_id: item.quantity for item in items}

    @staticmethod
    def _to_items(items: list[DeliveryItemIn]) -> list[DeliveryItem]:
        """입력 스키마 → ORM 품목.
        [입력] items
        [출력] list[DeliveryItem]
        """
        return [DeliveryItem(supply_id=item.supply_id, quantity=item.quantity) for item in items]
