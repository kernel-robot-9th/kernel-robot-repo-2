# =============================================================================
# 파일   : app/services/fms_events.py
# 역할   : 팀원 FMS가 보낸 이벤트로 EMR 배송 단계를 바꾼다 (2026-10-27, FMS API v1 연동 1단계)
# 작성일 : 2026-10-27
# 구성   :
#   - FmsEventHandler  handle(event) — batch_assigned → 주문에 묶음·로봇만(배송은 reserved 그대로),
#                      robot_called(Pinky를 약제실로 부름) → preparing(준비), 약제실 정밀 주차 끝 → dispatched(출발) (2026-10-29),
#                      order_delivered(배송의 물품 모두) → arrived, order_failed → failed(robot_error), order_canceled → 주문 상태만.
#                      그 밖·우리 주문이 아니면 무시
#                      2단계(FMS_OMX_ENABLED, 2026-10-27): batch_assigned → fms_batches 한 줄(OMX에 보낼 색깔별 개수),
#                      robot_at_pharmacy(정밀 주차 끝) → 도착 시각. OMX·FMS ready·loaded 호출은 services/fms_omx.py 주기 작업
#                      pinky_docked_at_pharmacy() — FMS_PHARMACY_SIGNAL=pinky면 실물 Pinky의 POST /robot/arrived가 정밀 주차 끝 (2026-10-28)
#   - pinky_signals_pharmacy()  정밀 주차 끝을 실물 Pinky 신호로 보는지 (아니면 FMS robot_at_pharmacy)
# 2026-10-29 사용자 "OMX 적재 준비 단계 추가 — 호출부터 준비, 정밀 주차 출발": 출발 알림·기록은 정밀 주차 끝에.
#   정밀 주차 신호를 놓쳐도 order_delivered가 오면 출발을 먼저 남기고 도착으로 (배송이 준비에 멈추지 않게)
# 바깥 HTTP 호출 없음(DB만) — FMS는 1초 안에 2xx를 기다린다. 같은 이벤트가 다시 와도 결과가 같다(상태 전이가 멱등).
# 도착·실패는 DispatchService.report_progress를 그대로 쓴다(일회용 마커·알림·배송 기록·재고 복구가 한 곳).
# 계약: docs/api_contract_delivery_2026-10-20.md 10.2
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import DomainError
from app.models.enums import DeliveryEventType, DeliveryFailureReason, DeliveryStatus, FmsBatchStep, FmsOrderStatus
from app.models.delivery import Delivery
from app.models.fms_batch import FmsBatch
from app.models.fms_order import FmsOrder
from app.models.robot import Robot
from app.repositories.delivery import DeliveryRepository
from app.repositories.fms_order import FmsOrderRepository
from app.repositories.robot import RobotRepository
from app.repositories.supply import SupplyRepository
from app.services.delivery_events import DeliveryEventRecorder
from app.services.delivery_notifier import DeliveryNotifier
from app.services.dispatch import STAGE_ARRIVED, STAGE_FAILED, DispatchService
from app.services.omx_items import omx_counts

log = structlog.get_logger(__name__)


def pinky_signals_pharmacy() -> bool:
    """정밀 주차 끝을 실물 Pinky의 POST /robot/arrived로 보는지 (FMS_OMX_ENABLED이고 FMS_PHARMACY_SIGNAL=pinky, 2026-10-28).
    [입력] 없음 [출력] bool: False면 FMS robot_at_pharmacy
    """
    return settings.FMS_OMX_ENABLED and settings.FMS_PHARMACY_SIGNAL == "pinky"


class FmsEventHandler:
    """FMS 이벤트 1건 처리. commit은 요청 끝(get_db)."""

    def __init__(self, db: Session) -> None:
        self.orders = FmsOrderRepository(db)
        self.deliveries = DeliveryRepository(db)
        self.robots = RobotRepository(db)
        self.supplies = SupplyRepository(db)
        self.db = db
        self.dispatch = DispatchService(db)
        self.notifier = DeliveryNotifier(db)
        self.events = DeliveryEventRecorder(db)

    def handle(self, event: dict[str, Any]) -> bool:
        """이벤트 하나.
        [입력] event: FMS 이벤트 {event_id, seq, time, type, …종류별 필드}
        [출력] bool: EMR 주문·배송에 무엇이든 반영했으면 True (우리 주문이 아니거나 모르는 종류면 False)
        """
        kind = event.get("type")
        if kind == "batch_assigned":
            return self._batch_assigned(event)
        if kind == "robot_called":
            return self._robot_called(event)
        if kind == "order_delivered":
            return self._order_delivered(event)
        if kind == "order_failed":
            return self._order_failed(event)
        if kind == "order_canceled":
            return self._set_order_status(event.get("order_id"), FmsOrderStatus.CANCELED) is not None
        if kind == "robot_at_pharmacy":
            return self._robot_at_pharmacy(event)
        return False

    def _batch_assigned(self, event: dict[str, Any]) -> bool:
        """묶음 배차 → 주문에 묶음·로봇 번호. 배송은 reserved 그대로 — Pinky는 아직 제자리에서 기다린다(준비는 robot_called).
        [입력] event: {batch_id, robot, orders: [{order_id, …}], …}
        [출력] bool
        """
        ours: list[FmsOrder] = []
        for listed in event.get("orders") or []:
            order = self._set_order_status(listed.get("order_id"), FmsOrderStatus.ASSIGNED)
            if order is None:
                continue
            order.batch_id = event.get("batch_id")
            order.fms_robot_number = event.get("robot")
            ours.append(order)
        if ours and settings.FMS_OMX_ENABLED:
            self._open_omx_batch(event, ours)
        return bool(ours)

    def _robot_called(self, event: dict[str, Any]) -> bool:
        """FMS가 ready를 받고 Pinky를 약제실로 부름 → 묶음의 reserved 배송을 preparing(준비), 맡은 로봇 = FMS 로봇 번호의 EMR 로봇.
        알림은 없다(출발 알림은 정밀 주차 끝). 같은 이벤트가 다시 오면 그대로.
        [입력] event: {batch_id, robot, eta_s}
        [출력] bool: 우리 묶음이면 True
        """
        orders = self.orders.list_assigned_for_batch(str(event.get("batch_id") or ""))
        if not orders:
            return False
        robot = self._emr_robot(event.get("robot"), batch_id=event.get("batch_id"))
        if robot is None:
            return True
        now = datetime.now(UTC)
        for delivery in self._deliveries_of(orders, (DeliveryStatus.RESERVED,)):
            delivery.status = DeliveryStatus.PREPARING
            delivery.assigned_robot_id = robot.id
            delivery.assigned_robot = robot
            log.info("delivery_preparing", delivery_id=delivery.id, robot_id=robot.id, batch_id=event.get("batch_id"),
                     eta_s=event.get("eta_s"))
            self.events.record_by_robot(delivery, DeliveryEventType.PREPARING, robot, now)
        return True

    def _open_omx_batch(self, event: dict[str, Any], orders: list[FmsOrder]) -> None:
        """2단계: 이 묶음을 OMX로 싣도록 fms_batches 한 줄 (같은 이벤트가 다시 오면 만들지 않는다).
        [입력] event: batch_assigned / orders: 묶음 안의 우리 주문 [출력] 없음
        """
        batch_id = str(event.get("batch_id") or "")
        if not batch_id or self._active_omx_batch(batch_id) is not None:
            return
        counts = omx_counts((self.supplies.get(order.supply_id).category, 1) for order in orders)
        now = datetime.now(UTC)
        self.db.add(FmsBatch(
            batch_id=batch_id, fms_robot_number=int(event.get("robot") or 0), blue_count=counts["blue"],
            green_count=counts["green"], step=FmsBatchStep.PICK, step_changed_at=now, created_at=now,
        ))
        self.db.flush()
        log.info("fms_omx_batch_opened", batch_id=batch_id, blue=counts["blue"], green=counts["green"])

    def _robot_at_pharmacy(self, event: dict[str, Any]) -> bool:
        """FMS의 Pinky 정밀 주차 끝 → OMX 묶음에 도착 시각(내려놓기 /pinky는 주기 작업이 보낸다)·묶음의 배송을 출발로.
        실물 Pinky 신호를 쓰는 동안(pinky_signals_pharmacy)은 둘 다 그 신호(pinky_docked_at_pharmacy)로 하고 여기선 무시한다.
        [입력] event: {batch_id, robot} [출력] bool: 우리 묶음이면 True
        """
        if pinky_signals_pharmacy():
            return False
        batch_id = str(event.get("batch_id") or "")
        handled = False
        if settings.FMS_OMX_ENABLED:
            batch = self._active_omx_batch(batch_id)
            if batch is not None:
                if batch.at_pharmacy_at is None:
                    batch.at_pharmacy_at = datetime.now(UTC)
                handled = True
        return self._dispatch_batch(batch_id, event.get("robot")) or handled

    def pinky_docked_at_pharmacy(self) -> FmsBatch | None:
        """실물 Pinky가 약제실 정밀 주차를 마쳤다(POST /robot/arrived) → 가장 오래 기다린 OMX 묶음의 정밀 주차 시각 (2026-10-28),
        그 묶음의 배송을 출발로 (2026-10-29).
        FMS가 가상인 동안 쓰는 임시 신호(FMS_PHARMACY_SIGNAL=pinky) — Pinky 한 대라 어느 묶음인지는 가장 먼저 연 묶음으로 본다.
        [입력] 없음
        [출력] FmsBatch | None: 기다리던 묶음이 없으면 None
        """
        waiting = (FmsBatchStep.PICK, FmsBatchStep.PICKING, FmsBatchStep.READY, FmsBatchStep.CALLED)
        batch = self.db.scalar(
            select(FmsBatch).where(FmsBatch.step.in_(waiting), FmsBatch.at_pharmacy_at.is_(None))
            .order_by(FmsBatch.id).limit(1).with_for_update()
        )
        if batch is not None:
            batch.at_pharmacy_at = datetime.now(UTC)
            log.info("pinky_docked_at_pharmacy", batch_id=batch.batch_id, step=batch.step)
            self._dispatch_batch(batch.batch_id, batch.fms_robot_number)
        return batch

    def delivery_for_batch(self, batch: FmsBatch):
        """묶음에 실린 EMR 배송 하나 (응답용) — 가장 나중에 보낸 주문의 배송.
        [입력] batch [출력] Delivery | None
        """
        order = self.db.scalar(
            select(FmsOrder).where(FmsOrder.batch_id == batch.batch_id).order_by(FmsOrder.id.desc()).limit(1)
        )
        return self.deliveries.get_with_items(order.delivery_id) if order is not None else None

    def _active_omx_batch(self, batch_id: str) -> FmsBatch | None:
        """FMS batch_id로 끝나지 않은 가장 나중 묶음 (FMS를 다시 켜면 b-1부터 다시라).
        [입력] batch_id [출력] FmsBatch | None
        """
        statement = (
            select(FmsBatch)
            .where(FmsBatch.batch_id == batch_id, FmsBatch.step.not_in((FmsBatchStep.DELIVERING, FmsBatchStep.FAILED)))
            .order_by(FmsBatch.id.desc()).limit(1).with_for_update()
        )
        return self.db.scalar(statement)

    def _order_delivered(self, event: dict[str, Any]) -> bool:
        """주문 하나 배송 끝 → 배송의 물품이 모두 보내졌고 모두 delivered면 arrived.
        [입력] event: {order_id, room, robot, batch_id}
        [출력] bool
        """
        order = self._set_order_status(event.get("order_id"), FmsOrderStatus.DELIVERED)
        if order is None:
            return False
        if order.delivered_at is None:
            order.delivered_at = datetime.now(UTC)
        delivery = self.deliveries.get_with_items(order.delivery_id)
        orders = self.orders.list_for_delivery(order.delivery_id)
        item_count = sum(item.quantity for item in delivery.items) if delivery else 0
        all_delivered = len(orders) == item_count and all(each.status == FmsOrderStatus.DELIVERED for each in orders)
        if delivery is None or not all_delivered:
            return True
        if delivery.status in (DeliveryStatus.RESERVED, DeliveryStatus.PREPARING):
            # 정밀 주차 신호를 놓쳤다(예: 실물 Pinky 신호를 쓰는데 FMS 가상 Pinky가 배송) — 출발을 먼저 남긴다
            robot = delivery.assigned_robot or self._emr_robot(order.fms_robot_number, batch_id=order.batch_id)
            if robot is None:
                return True
            log.warning("delivery_dispatched_late", delivery_id=delivery.id, status=delivery.status, batch_id=order.batch_id)
            self._dispatch(delivery, robot, datetime.now(UTC))
        if delivery.status != DeliveryStatus.DISPATCHED:
            return True
        self._report(delivery.id, delivery.assigned_robot_id, STAGE_ARRIVED, None)
        return True

    def _order_failed(self, event: dict[str, Any]) -> bool:
        """주문 실패 → 그 배송을 failed(robot_error, 재고 복구·실패 알림). 시뮬레이터에는 아직 없는 이벤트.
        [입력] event: {order_id, batch_id, reason}
        [출력] bool
        """
        order = self._set_order_status(event.get("order_id"), FmsOrderStatus.FAILED)
        if order is None:
            return False
        delivery = self.deliveries.get_with_items(order.delivery_id)
        if delivery is not None and delivery.status in (DeliveryStatus.PREPARING, DeliveryStatus.DISPATCHED, DeliveryStatus.ARRIVED):
            log.warning("fms_order_failed", delivery_id=delivery.id, fms_order_id=order.fms_order_id, reason=event.get("reason"))
            self._report(delivery.id, delivery.assigned_robot_id, STAGE_FAILED, DeliveryFailureReason.ROBOT_ERROR)
        return True

    def _dispatch_batch(self, batch_id: str, fms_robot_number: Any) -> bool:
        """묶음이 약제실 정밀 주차를 마쳤다 → 그 묶음의 reserved·preparing 배송을 dispatched(출발 알림·기록).
        [입력] batch_id / fms_robot_number: 준비를 건너뛴 배송에 붙일 로봇
        [출력] bool: 우리 묶음이면 True
        """
        orders = self.orders.list_assigned_for_batch(batch_id)
        if not orders:
            return False
        now = datetime.now(UTC)
        for delivery in self._deliveries_of(orders, (DeliveryStatus.RESERVED, DeliveryStatus.PREPARING)):
            robot = delivery.assigned_robot or self._emr_robot(fms_robot_number, batch_id=batch_id)
            if robot is not None:
                self._dispatch(delivery, robot, now)
        return True

    def _dispatch(self, delivery: Delivery, robot: Robot, now: datetime) -> None:
        """출발 — 상태·출발 시각·맡은 로봇, 예약 간호사 알림, 배송 기록.
        [입력] delivery: reserved·preparing / robot / now [출력] 없음
        """
        delivery.status = DeliveryStatus.DISPATCHED
        delivery.assigned_robot_id = robot.id
        delivery.assigned_robot = robot
        delivery.dispatched_at = now
        log.info("delivery_dispatched", delivery_id=delivery.id, robot_id=robot.id)
        self.notifier.notify_dispatched(delivery)
        self.events.record_by_robot(delivery, DeliveryEventType.DISPATCHED, robot, now)

    def _deliveries_of(self, orders: list[FmsOrder], statuses: tuple[DeliveryStatus, ...]) -> list[Delivery]:
        """주문들의 배송(겹치지 않게, 잠가서) 중 이 상태인 것.
        [입력] orders / statuses [출력] list[Delivery]: 품목 로드됨
        """
        delivery_ids = list(dict.fromkeys(order.delivery_id for order in orders))
        deliveries = (self.deliveries.get_with_items(delivery_id, lock=True) for delivery_id in delivery_ids)
        return [delivery for delivery in deliveries if delivery is not None and delivery.status in statuses]

    def _emr_robot(self, fms_robot_number: Any, batch_id: Any) -> Robot | None:
        """FMS 로봇 번호 → EMR 로봇 (FMS_ROBOT_MAP). 이어지지 않으면 로그 경고 — 배송은 그 단계에 남는다.
        [입력] fms_robot_number / batch_id: 로그용 [출력] Robot | None
        """
        robot_id = settings.FMS_ROBOT_MAP.get(fms_robot_number) if isinstance(fms_robot_number, int) else None
        robot = self.robots.get(robot_id) if robot_id is not None else None
        if robot is None:
            log.warning("fms_robot_not_mapped", fms_robot_number=fms_robot_number, batch_id=batch_id,
                        detail="FMS_ROBOT_MAP has no EMR robot for this FMS robot — delivery stays in its step")
        return robot

    def _set_order_status(self, fms_order_id: Any, status: FmsOrderStatus) -> FmsOrder | None:
        """우리가 보낸 주문이면 상태를 바꾼다.
        [입력] fms_order_id: 이벤트의 order_id / status
        [출력] FmsOrder | None (우리 주문이 아니면 None)
        """
        if not isinstance(fms_order_id, str):
            return None
        order = self.orders.get_by_fms_order_id(fms_order_id, lock=True)
        if order is not None:
            order.status = status
        return order

    def _report(self, delivery_id: int, robot_id: int | None, stage: str, failure_reason: DeliveryFailureReason | None) -> None:
        """도착·실패 처리 — DispatchService.report_progress와 같은 규칙. 맞지 않는 전이는 로그만(FMS에 4xx를 주지 않는다).
        [입력] delivery_id / robot_id: 맡은 로봇 / stage / failure_reason
        [출력] 없음
        """
        if robot_id is None:
            return
        try:
            self.dispatch.report_progress(delivery_id, robot_id, stage, failure_reason)
        except DomainError as error:
            log.warning("fms_event_not_applied", delivery_id=delivery_id, stage=stage, code=error.code)
