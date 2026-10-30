# =============================================================================
# 파일   : app/api/v1/fms_inbound.py
# 역할   : 팀원 FMS → EMR (/fms) — FMS API v1 웹훅 받는 곳 (2026-10-27, 연동 1단계)
# 작성일 : 2026-10-27
# 구성   :
#   - receive_robot_status  POST /fms/robot-status — 1초마다 로봇 전부. 마지막 위치·배터리·오염도를 메모리에 둔다 → 병원 지도(GET /robot-positions, 2026-10-29)
#   - receive_event         POST /fms/events       — 이벤트 1건 → 배송 단계 (services/fms_events.py)
# 인증 없음(10-27 사용자 결정). FMS는 1초 안에 2xx를 기다리고, 4xx면 다시 보내지 않는다 → 올바른 JSON 객체면 늘 200.
# FMS는 --control-url http://<EMR>:8000 으로 띄운다. 계약: docs/api_contract_delivery_2026-10-20.md 10.2
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Body

from app.core.deps import DB
from app.services.fms_events import FmsEventHandler
from app.services.fms_robot_positions import robot_position_store

router = APIRouter()
log = structlog.get_logger(__name__)


@router.post(
    "/robot-status",
    summary="FMS 로봇 상태 받기 (인증 없음)",
    description=(
        "팀원 FMS가 1초마다 `{time, robots: [...]}`를 보낸다. 로봇마다 마지막 위치(pose)·online·state·place·배터리·오염도(10-30)를 메모리에 덮어쓰고 "
        "병원 지도가 `GET /robot-positions`로 읽는다(2026-10-29). DB·바깥 호출 없음, 올바른 JSON 객체면 늘 200. 2026-10-27"
    ),
)
def receive_robot_status(body: dict[str, Any] = Body(...)) -> dict[str, bool]:
    """
    [입력] body: FMS robot-status 본문
    [출력] {"ok": true}
    """
    robot_position_store.update(body, datetime.now(UTC))
    return {"ok": True}


@router.post(
    "/events",
    summary="FMS 이벤트 받기 (인증 없음)",
    description=(
        "팀원 FMS가 이벤트 1건씩 보낸다. `batch_assigned` → 그 주문의 신청을 **출발(dispatched)**, "
        "`order_delivered`로 신청의 물품이 모두 배송되면 **도착(arrived)**, `order_failed` → 실패. "
        "우리 주문이 아니거나 모르는 종류면 `handled: false`로 200. 같은 이벤트를 다시 보내도 결과가 같다. 2026-10-27"
    ),
)
def receive_event(db: DB, body: dict[str, Any] = Body(...)) -> dict[str, bool]:
    """
    [입력] db / body: FMS 이벤트 {event_id, seq, time, type, …}
    [출력] {"ok": true, "handled": bool}
    """
    handled = FmsEventHandler(db).handle(body)
    log.info("fms_event_received", event_id=body.get("event_id"), seq=body.get("seq"), type=body.get("type"), handled=handled)
    return {"ok": True, "handled": handled}
