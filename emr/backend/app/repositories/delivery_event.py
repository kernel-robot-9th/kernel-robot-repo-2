# =============================================================================
# 파일   : app/repositories/delivery_event.py
# 역할   : 배송 기록 조회·추가 (로드맵 4단계)
# 작성일 : 2026-10-21
# 구성   :
#   - DeliveryEventRepository  add(BaseRepository), list_for_delivery(배송 한 건, 오래된 순),
#                              list_filtered(관리자 기록 화면, 최근 순)
# =============================================================================
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.delivery import Delivery
from app.models.delivery_event import DeliveryEvent
from app.repositories.base import BaseRepository


class DeliveryEventRepository(BaseRepository[DeliveryEvent]):
    """delivery_events 접근. 추가만 하고 고치거나 지우지 않는다."""

    model = DeliveryEvent

    def list_for_delivery(self, delivery_id: int) -> list[DeliveryEvent]:
        """배송 한 건의 기록, 일어난 순서대로.
        [입력] delivery_id
        [출력] list[DeliveryEvent]: occurred_at, id 오름차순 (행위 간호사 로드됨)
        """
        statement = (
            select(DeliveryEvent)
            .options(selectinload(DeliveryEvent.actor_nurse))
            .where(DeliveryEvent.delivery_id == delivery_id)
            .order_by(DeliveryEvent.occurred_at, DeliveryEvent.id)
        )
        return list(self.db.scalars(statement))

    def list_filtered(
        self,
        event_type: str | None = None,
        robot_id: int | None = None,
        nurse_id: int | None = None,
        delivery_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DeliveryEvent]:
        """관리자 기록 화면 — 조건에 맞는 기록, 최근 것부터.
        [입력] event_type / robot_id: 그 로봇이 한 사건 / nurse_id: 그 간호사가 **예약한** 배송의 사건
               / delivery_id / since·until: occurred_at 범위 (since 포함, until 미포함) / limit / offset
        [출력] list[DeliveryEvent]: occurred_at, id 내림차순 (행위 간호사·배송·목적지·예약 간호사 로드됨)
        """
        statement = select(DeliveryEvent).options(
            selectinload(DeliveryEvent.actor_nurse),
            selectinload(DeliveryEvent.delivery).selectinload(Delivery.destination_location),
            selectinload(DeliveryEvent.delivery).selectinload(Delivery.nurse),
        )
        if event_type:
            statement = statement.where(DeliveryEvent.event_type == event_type)
        if robot_id is not None:
            statement = statement.where(DeliveryEvent.actor_robot_id == robot_id)
        if nurse_id is not None:
            statement = statement.join(Delivery, DeliveryEvent.delivery_id == Delivery.id).where(
                Delivery.nurse_id == nurse_id
            )
        if delivery_id is not None:
            statement = statement.where(DeliveryEvent.delivery_id == delivery_id)
        if since is not None:
            statement = statement.where(DeliveryEvent.occurred_at >= since)
        if until is not None:
            statement = statement.where(DeliveryEvent.occurred_at < until)
        statement = statement.order_by(DeliveryEvent.occurred_at.desc(), DeliveryEvent.id.desc())
        return list(self.db.scalars(statement.limit(limit).offset(offset)))
