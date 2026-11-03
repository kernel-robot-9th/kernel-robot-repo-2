# =============================================================================
# 파일   : app/services/delivery_events.py
# 역할   : 배송 기록 남기기·보기 (로드맵 4단계) — DeliveryService·DispatchService가 함께 쓴다
# 작성일 : 2026-10-21
# 구성   :
#   - DeliverySnapshot      바꾸기 전·후를 비교할 배송 값 (예약 시각·목적지·품목, 이름은 당시 값)
#   - DeliveryEventRecorder record_by_nurse / record_by_robot / record_by_bedside(2026-10-22), reserved_details / update_changes
#   - DeliveryEventService  history(배송 한 건 — 본인·관리자), list_for_admin(관리자 기록 화면)
# 기록은 상태를 바꾼 요청과 같은 트랜잭션에 쓴다 — 409 등으로 롤백되면 기록도 남지 않는다(알림과 같은 규칙).
# 일회용 수령 마커 번호는 기록하지 않는다(예약 간호사 화면에만 보여야 하는 값 — 관리자 기록 화면에도 안 나가게).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import Forbidden, NotFound
from app.models.delivery import Delivery
from app.models.delivery_event import DeliveryEvent
from app.models.enums import DeliveryEventActor, DeliveryEventType, NurseRole
from app.models.nurse import Nurse
from app.models.robot import Robot
from app.repositories.delivery import DeliveryRepository
from app.repositories.delivery_event import DeliveryEventRepository


@dataclass(frozen=True)
class DeliverySnapshot:
    """변경 전·후 비교용 값. JSON에 그대로 넣을 수 있는 형태로 둔다."""
    scheduled_at: str
    destination: dict[str, Any]       # {"id", "name"}
    items: tuple[tuple[int, str, int], ...]  # (supply_id, 이름, 수량), supply_id 순

    @classmethod
    def of(cls, delivery: Delivery) -> DeliverySnapshot:
        """배송의 지금 값.
        [입력] delivery: 품목·비품·목적지 로드된(또는 로드 가능한) 배송
        [출력] DeliverySnapshot
        """
        return cls(
            scheduled_at=delivery.scheduled_at.astimezone(UTC).isoformat(),  # 같은 시각이 시간대 표기만 달라도 같게
            destination={"id": delivery.destination_location.id, "name": delivery.destination_location.name},
            items=tuple(sorted((item.supply_id, item.supply.name, item.quantity) for item in delivery.items)),
        )

    def items_json(self) -> list[dict[str, Any]]:
        """품목을 JSON 목록으로.
        [입력] 없음
        [출력] list[dict]: [{"supply_id", "name", "quantity"}]
        """
        return [{"supply_id": supply_id, "name": name, "quantity": quantity} for supply_id, name, quantity in self.items]


class DeliveryEventRecorder:
    """배송 기록 한 줄을 만든다. 상태를 바꾸는 서비스가 같은 세션으로 부른다."""

    def __init__(self, db: Session) -> None:
        self.repo = DeliveryEventRepository(db)

    def record_by_nurse(
        self, delivery: Delivery, event_type: DeliveryEventType, nurse_id: int, occurred_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> DeliveryEvent:
        """간호사가 한 일 (예약·변경·취소).
        [입력] delivery / event_type / nurse_id: 토큰의 간호사 / occurred_at / details
        [출력] DeliveryEvent (flush됨, commit은 요청 끝에)
        """
        return self.repo.add(DeliveryEvent(
            delivery_id=delivery.id, event_type=event_type, occurred_at=occurred_at,
            actor_type=DeliveryEventActor.NURSE, actor_nurse_id=nurse_id, details=details,
        ))

    def record_by_robot(
        self, delivery: Delivery, event_type: DeliveryEventType, robot: Robot, occurred_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> DeliveryEvent:
        """로봇이 한 일 (출발·도착·수령·실패). 로봇 이름은 스냅숏으로 남긴다(로봇을 지워도 누가 했는지 보이게).
        [입력] delivery / event_type / robot: 키로 확인된 로봇 / occurred_at / details
        [출력] DeliveryEvent
        """
        return self.repo.add(DeliveryEvent(
            delivery_id=delivery.id, event_type=event_type, occurred_at=occurred_at,
            actor_type=DeliveryEventActor.ROBOT, actor_robot_id=robot.id, actor_robot_name=robot.name, details=details,
        ))

    def record_by_bedside(
        self, delivery: Delivery, event_type: DeliveryEventType, bedside_name: str, occurred_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> DeliveryEvent:
        """병상 단말이 한 일 (환자 요청·받았습니다, 2026-10-22). 병상 이름은 스냅숏.
        [입력] delivery / event_type / bedside_name / occurred_at / details
        [출력] DeliveryEvent
        """
        return self.repo.add(DeliveryEvent(
            delivery_id=delivery.id, event_type=event_type, occurred_at=occurred_at,
            actor_type=DeliveryEventActor.BEDSIDE, actor_bedside_name=bedside_name, details=details,
        ))

    @staticmethod
    def reserved_details(delivery: Delivery) -> dict[str, Any]:
        """예약 기록 내용 — 예약 시각·목적지·품목 (이름은 당시 값).
        [입력] delivery: 방금 만든 배송
        [출력] dict
        """
        snapshot = DeliverySnapshot.of(delivery)
        return {"scheduled_at": snapshot.scheduled_at, "destination": snapshot.destination, "items": snapshot.items_json()}

    @staticmethod
    def update_changes(before: DeliverySnapshot, after: DeliverySnapshot) -> dict[str, Any]:
        """변경 기록 내용 — 바뀐 것만 {"필드": {"from", "to"}}.
        [입력] before / after: 바꾸기 전·후 값
        [출력] dict: 아무것도 안 바뀌었으면 빈 dict (그때는 기록하지 않는다)
        """
        changes: dict[str, Any] = {}
        if before.scheduled_at != after.scheduled_at:
            changes["scheduled_at"] = {"from": before.scheduled_at, "to": after.scheduled_at}
        if before.destination["id"] != after.destination["id"]:
            changes["destination"] = {"from": before.destination, "to": after.destination}
        if [(supply_id, quantity) for supply_id, _, quantity in before.items] != \
                [(supply_id, quantity) for supply_id, _, quantity in after.items]:
            changes["items"] = {"from": before.items_json(), "to": after.items_json()}
        return changes


class DeliveryEventService:
    """배송 기록 보기."""

    def __init__(self, db: Session) -> None:
        self.repo = DeliveryEventRepository(db)
        self.deliveries = DeliveryRepository(db)

    def history(self, delivery_id: int, nurse: Nurse) -> list[DeliveryEvent]:
        """배송 한 건의 기록. 예약한 간호사 본인이나 관리자만.
        [입력] delivery_id / nurse: 로그인한 간호사
        [출력] list[DeliveryEvent]: 일어난 순서 (없으면 NotFound, 남의 배송이면 Forbidden)
        """
        delivery = self.deliveries.get(delivery_id)
        if delivery is None:
            raise NotFound(f"delivery {delivery_id} not found", code="delivery_not_found")
        if delivery.nurse_id != nurse.id and nurse.role != NurseRole.ADMIN:
            raise Forbidden("not your delivery", code="delivery_not_owned")
        return self.repo.list_for_delivery(delivery_id)

    def list_for_admin(
        self,
        event_type: DeliveryEventType | None = None,
        robot_id: int | None = None,
        nurse_id: int | None = None,
        delivery_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DeliveryEvent]:
        """관리자 기록 화면 (권한은 라우터의 관리자 의존성이 확인).
        [입력] 거르기 조건 (DeliveryEventRepository.list_filtered와 같음)
        [출력] list[DeliveryEvent]: 최근 것부터
        """
        return self.repo.list_filtered(event_type, robot_id, nurse_id, delivery_id, since, until, limit, offset)
