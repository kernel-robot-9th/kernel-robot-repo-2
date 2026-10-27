# =============================================================================
# 파일   : app/repositories/delivery.py
# 역할   : 배송 예약 조회·품목 교체
# 작성일 : 2026-10-14
# 구성   :
#   - DeliveryRepository  get_with_items, list_by_nurse, replace_items
#                         배정·진행 (2026-10-20): get_active_for_robot, lock_next_claimable, arrived_receipt_marker_ids
#                         병상 요청 (2026-10-22): get_active_for_bedside, list_for_bedside
#                         FMS 보내기 (2026-10-27): lock_due_for_fms
# =============================================================================
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.delivery import Delivery, DeliveryItem
from app.models.enums import DeliveryStatus
from app.models.location import Location
from app.repositories.base import BaseRepository

ACTIVE_STATUSES = (DeliveryStatus.DISPATCHED, DeliveryStatus.ARRIVED)
# 병상 기준 진행 중 = 예약·출발·도착 (병상당 하나 — uq_deliveries_bedside_active)
BEDSIDE_ACTIVE_STATUSES = (DeliveryStatus.RESERVED, DeliveryStatus.DISPATCHED, DeliveryStatus.ARRIVED)


def _with_details():
    """배송 응답에 쓰는 관계를 함께 로드하는 옵션 (품목·품목의 비품·목적지·맡은 로봇).
    [입력] 없음
    [출력] list: select().options(...)에 넘길 로더
    """
    return [
        selectinload(Delivery.items).selectinload(DeliveryItem.supply),
        selectinload(Delivery.destination_location),
        selectinload(Delivery.assigned_robot),
    ]


class DeliveryRepository(BaseRepository[Delivery]):
    """deliveries·delivery_items 접근."""

    model = Delivery

    def get_with_items(self, delivery_id: int, lock: bool = False) -> Delivery | None:
        """품목·배송 위치를 함께 로드해 한 건 조회.
        [입력] delivery_id / lock: True면 SELECT ... FOR UPDATE (디스패처 전송과 동시에 변경·취소되지 않게)
        [출력] Delivery | None
        """
        statement = select(Delivery).options(*_with_details()).where(Delivery.id == delivery_id)
        if lock:
            statement = statement.with_for_update(of=Delivery).execution_options(populate_existing=True)
        return self.db.scalar(statement)

    def list_by_nurse(
        self, nurse_id: int, status: str | None = None, limit: int = 100, offset: int = 0,
    ) -> list[Delivery]:
        """간호사의 예약 목록, 배송 예정 시각이 빠른 순.
        [입력] nurse_id / status: 있으면 그 상태만 / limit / offset
        [출력] list[Delivery]
        """
        statement = select(Delivery).options(*_with_details()).where(Delivery.nurse_id == nurse_id)
        if status:
            statement = statement.where(Delivery.status == status)
        statement = statement.order_by(Delivery.scheduled_at, Delivery.id).limit(limit).offset(offset)
        return list(self.db.scalars(statement))

    def list_waiting(self, due_before: datetime | None, limit: int = 100) -> list[Delivery]:
        """로봇이 아직 맡지 않은(reserved) 배송, 예약 시각이 이른 순 — 로봇 쪽이 조회만 한다 (2026-10-22).
        [입력] due_before: 있으면 예약 시각이 이 시각 이전인 것만 / limit
        [출력] list[Delivery]
        """
        statement = select(Delivery).options(*_with_details()).where(Delivery.status == DeliveryStatus.RESERVED)
        if due_before is not None:
            statement = statement.where(Delivery.scheduled_at <= due_before)
        return list(self.db.scalars(statement.order_by(Delivery.scheduled_at, Delivery.id).limit(limit)))

    def get_active_for_robot(self, robot_id: int) -> Delivery | None:
        """로봇이 지금 맡고 있는(dispatched·arrived) 배송. 부분 유일 인덱스로 많아야 하나.
        [입력] robot_id
        [출력] Delivery | None
        """
        statement = (
            select(Delivery).options(*_with_details())
            .where(Delivery.assigned_robot_id == robot_id, Delivery.status.in_(ACTIVE_STATUSES))
        )
        return self.db.scalar(statement)

    def get_active_for_bedside(self, bedside_device_id: int) -> Delivery | None:
        """병상의 진행 중(예약·출발·도착) 배송. 부분 유일 인덱스로 많아야 하나 (2026-10-22).
        [입력] bedside_device_id
        [출력] Delivery | None
        """
        statement = (
            select(Delivery).options(*_with_details())
            .where(Delivery.bedside_device_id == bedside_device_id, Delivery.status.in_(BEDSIDE_ACTIVE_STATUSES))
        )
        return self.db.scalar(statement)

    def list_for_bedside(self, bedside_device_id: int, limit: int = 10) -> list[Delivery]:
        """병상의 최근 배송, 최근 것부터 (2026-10-22).
        [입력] bedside_device_id / limit
        [출력] list[Delivery]
        """
        statement = (
            select(Delivery).options(*_with_details())
            .where(Delivery.bedside_device_id == bedside_device_id)
            .order_by(Delivery.created_at.desc(), Delivery.id.desc()).limit(limit)
        )
        return list(self.db.scalars(statement))

    def lock_next_claimable(self, now: datetime, lock: bool = True) -> Delivery | None:
        """로봇이 가져갈 다음 배송을 잠가서 가져온다: reserved이고 예약 시각이 지났고, 목적지에 로봇 목적지 이름(robot_dest)이 있는 것 중
        예약 시각이 가장 이른(같으면 id 작은) 한 건. 다른 로봇이 잠근 행은 건너뛴다(SKIP LOCKED).
        2026-10-27: 복귀 장소의 맵·좌표 조건을 없앴다 — 팀원 FMS는 /goto {dest}로 가므로 robot_dest가 있으면 갈 수 있다
        [입력] now: 지금 시각(파이썬 — 테스트 트랜잭션에서는 DB now()가 고정이라)
        / lock: False면 잠그지 않고 있는지만 본다 (로봇 서버에 묻기 전, 2026-10-23)
        [출력] Delivery | None
        """
        statement = (
            select(Delivery)
            .join(Location, Delivery.destination_location_id == Location.id)
            .options(*_with_details())
            .where(
                Delivery.status == DeliveryStatus.RESERVED,
                Delivery.scheduled_at <= now,
                Location.robot_dest.is_not(None),
            )
            .order_by(Delivery.scheduled_at, Delivery.id)
            .limit(1)
        )
        if lock:
            # of=Delivery: 장소 행까지 잠그면 장소를 수정 중일 때 배송이 조용히 건너뛰어진다
            statement = statement.with_for_update(skip_locked=True, of=Delivery)
        return self.db.scalar(statement)

    def lock_due_for_fms(self, now: datetime, limit: int = 50) -> list[Delivery]:
        """FMS로 보낼 배송을 잠가서 가져온다 (2026-10-27): reserved이고 신청 시각이 지났고 목적지에 robot_dest(FMS 방 번호)가 있는 것,
        이른 순. 보내는 동안 간호사 변경·취소가 끼어들지 않게 잠근다 — 끝나면 변경·취소는 delivery_sent_to_fms로 막힌다.
        이미 다 보낸 배송도 batch_assigned 전까지 reserved라 함께 나온다(서비스가 물품별로 건너뛴다).
        [입력] now: 지금 시각 / limit: 한 회차에 볼 배송 수
        [출력] list[Delivery]: 품목·목적지 로드됨
        """
        statement = (
            select(Delivery)
            .join(Location, Delivery.destination_location_id == Location.id)
            .options(*_with_details())
            .where(
                Delivery.status == DeliveryStatus.RESERVED,
                Delivery.scheduled_at <= now,
                Location.robot_dest.is_not(None),
            )
            .order_by(Delivery.scheduled_at, Delivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=Delivery)
        )
        return list(self.db.scalars(statement))

    def arrived_receipt_marker_ids(self) -> set[int]:
        """지금 도착(arrived)해 있는 배송들이 쓰는 일회용 마커 번호.
        [입력] 없음
        [출력] set[int]
        """
        statement = select(Delivery.receipt_marker_id).where(
            Delivery.status == DeliveryStatus.ARRIVED, Delivery.receipt_marker_id.is_not(None),
        )
        return set(self.db.scalars(statement))

    def replace_items(self, delivery: Delivery, items: list[DeliveryItem]) -> None:
        """품목 전체 교체. 기존 행을 먼저 지우고 flush해야 (delivery_id, supply_id) UNIQUE에 안 걸린다.
        [입력] delivery / items: 새 품목
        [출력] 없음
        """
        delivery.items.clear()
        self.db.flush()
        delivery.items.extend(items)
        self.db.flush()
