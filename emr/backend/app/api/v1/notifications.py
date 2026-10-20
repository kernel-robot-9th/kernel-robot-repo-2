# =============================================================================
# 파일   : app/api/v1/notifications.py
# 역할   : 알림 엔드포인트 (/notifications) — 재고 부족 (2026-10-16), 수령 완료 (본인에게만, 2026-10-19)
# 작성일 : 2026-10-16
# 구성   :
#   - list_low_stock        지금 재고가 알림 기준 이하인 비품 (알림창 목록)
#   - stream_notifications  SSE. 재고 부족 상태가 바뀔 때마다 event: low_stock | low_stock_resolved (모두에게),
#                           내 예약을 로봇이 수령 확인하면 event: delivery_received (예약한 간호사에게만)
# 둘 다 로그인 필수. 브라우저 EventSource는 헤더를 못 붙이므로 프론트는 fetch 스트림으로 Authorization을 보낸다
# =============================================================================
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.deps import DB, CurrentNurse, get_current_nurse
from app.core.notification_hub import notification_hub
from app.schemas.supply import SupplyOut
from app.services.supply import SupplyService

router = APIRouter(dependencies=[Depends(get_current_nurse)], responses={401: {"description": "토큰 없음·만료·비활성 간호사"}})

HEARTBEAT_SECONDS = 25        # 프록시가 놀고 있는 연결을 끊지 않도록 주석 줄을 보낸다
STREAM_MAX_SECONDS = 600      # 이 시간이 지나면 연결을 닫는다 — 클라이언트가 다시 붙으며 토큰·계정 상태를 다시 검사받는다
CLIENT_RETRY_MILLISECONDS = 3000


@router.get(
    "/low-stock", response_model=list[SupplyOut],
    summary="재고 부족 비품",
    description="재고(`stock_qty`)가 알림 기준(`low_stock_threshold_qty`) 이하인 활성 비품. 기준이 null인 비품은 나오지 않는다.",
)
def list_low_stock(db: DB) -> list[SupplyOut]:
    """
    [입력] 없음
    [출력] list[SupplyOut]: 재고가 적은 순
    """
    return [SupplyOut.model_validate(supply) for supply in SupplyService(db).list_low_stock()]


def format_server_sent_event(message: dict[str, Any]) -> str:
    """알림 dict → SSE 한 덩어리.
    [입력] message: {"event": ..., ...}
    [출력] str: "event: <종류>\\ndata: <JSON>\\n\\n"
    """
    return f"event: {message['event']}\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"


@router.get(
    "/stream",
    summary="실시간 알림 (SSE)",
    description=(
        "`text/event-stream`. 비품 재고가 알림 기준 이하로 내려가면 `event: low_stock`, 다시 올라가면 "
        "`event: low_stock_resolved` — 모든 간호사에게. `data`는 JSON `{event, supply_id, code, name, stock_qty, low_stock_threshold_qty}`. "
        "**내가 예약한** 배송의 단계 — 예약한 간호사에게만: `event: delivery_dispatched`(출발) · `delivery_arrived`(도착, "
        "`receipt_marker_id`·`receipt_deadline_at` 포함 — 로봇 카메라에 보여 줄 일회용 마커) · `delivery_received`(수령, `received_at`) · "
        "`delivery_failed`(실패, `failure_reason` — **관리자에게도**). 공통 `data`: "
        "`{event, recipient_nurse_id, delivery_id, destination_location_name, robot_name, items: [{name, quantity}], item_count}` "
        "(`items`는 앞 5개까지, `robot_name`은 로봇이 지워졌으면 null). "
        f"{HEARTBEAT_SECONDS}초마다 `: ping` 주석, {STREAM_MAX_SECONDS}초 뒤 서버가 닫는다(다시 연결할 것)."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "알림 스트림"}},
)
async def stream_notifications(nurse: CurrentNurse) -> StreamingResponse:
    """
    [입력] nurse: 로그인한 간호사 (본인에게 온 알림만 받는다)
    [출력] StreamingResponse: 연결이 끊기거나 STREAM_MAX_SECONDS가 지날 때까지 열려 있다
    """
    queue = notification_hub.subscribe(nurse.id, nurse.role)  # 응답을 돌려주기 전에 등록 — 연결 직후 생긴 알림도 놓치지 않는다

    async def event_stream() -> AsyncIterator[str]:
        """구독 큐를 SSE 텍스트로 흘려보낸다. 끝나면(끊김 포함) 구독 해제.
        [입력] 없음
        [출력] str 조각들
        """
        loop = asyncio.get_running_loop()
        closes_at = loop.time() + STREAM_MAX_SECONDS
        try:
            yield f"retry: {CLIENT_RETRY_MILLISECONDS}\n\n"
            while (remaining_seconds := closes_at - loop.time()) > 0:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=min(HEARTBEAT_SECONDS, remaining_seconds))
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield format_server_sent_event(message)
        finally:
            notification_hub.unsubscribe(queue)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # nginx 등 프록시 버퍼링 끄기
    )
