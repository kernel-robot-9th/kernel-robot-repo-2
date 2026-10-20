# =============================================================================
# 파일   : app/core/notification_hub.py
# 역할   : 실시간 알림 중계 — PostgreSQL LISTEN 한 줄을 SSE 구독자 여럿에게 나눠 준다
# 작성일 : 2026-10-16
# 구성   :
#   - NotificationHub   start/stop(lifespan), subscribe/unsubscribe(SSE 연결마다 큐 하나, 연결한 간호사 id·역할과 함께)
#   - notification_hub  프로세스당 하나
# 받는 사람: payload에 recipient_nurse_id·recipient_role이 하나도 없으면 모두에게. 있으면 간호사 id가 같거나 역할이 같은
# 연결에만 (2026-10-19·20). 한 메시지라서 관리자이면서 예약자여도 한 번만 받는다
# 발행은 app/repositories/notification.py(NOTIFY). DB를 거치므로 uvicorn 워커가 여러 개여도 모든 워커가 받는다
# =============================================================================
from __future__ import annotations

import asyncio
import json
from typing import Any

import psycopg
import structlog

from app.core.config import settings
from app.repositories.notification import NOTIFICATION_CHANNEL

log = structlog.get_logger(__name__)

RECIPIENT_FIELD = "recipient_nurse_id"     # 이 간호사에게
RECIPIENT_ROLE_FIELD = "recipient_role"     # 이 역할(admin 등)에게 — 둘 다 있으면 어느 쪽이든 맞으면 받는다
RECONNECT_DELAY_SECONDS = 3.0   # LISTEN 연결이 끊기면 이만큼 쉬고 다시 붙는다
SUBSCRIBER_QUEUE_SIZE = 100     # 느린 구독자의 큐가 차면 그 구독자에게만 알림을 버린다


class NotificationHub:
    """DB 연결 하나로 LISTEN하고, 받은 알림을 구독 중인 SSE 연결마다 큐로 넣는다."""

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue[dict[str, Any]], tuple[int, str | None]] = {}   # 큐 → (간호사 id, 역할)
        self._listen_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """LISTEN 작업을 백그라운드로 시작한다. DB가 아직 없어도 기동을 막지 않고 다시 시도한다.
        [입력] 없음
        [출력] 없음
        """
        if self._listen_task is None:
            self._listen_task = asyncio.create_task(self._listen_forever(), name="notification-listen")

    async def stop(self) -> None:
        """LISTEN 작업을 멈춘다.
        [입력] 없음
        [출력] 없음
        """
        if self._listen_task is None:
            return
        self._listen_task.cancel()
        try:
            await self._listen_task
        except asyncio.CancelledError:
            pass
        self._listen_task = None

    def subscribe(self, nurse_id: int, role: str | None = None) -> asyncio.Queue[dict[str, Any]]:
        """SSE 연결 하나를 구독자로 등록한다.
        [입력] nurse_id: 연결한(로그인한) 간호사 / role: 그 간호사의 역할 — 본인·역할에게 온 알림만 고르는 데 쓴다
        [출력] Queue: 이 연결로 보낼 알림이 쌓인다. 끝나면 반드시 unsubscribe
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers[queue] = (nurse_id, role)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """구독 해제.
        [입력] queue: subscribe가 준 큐
        [출력] 없음
        """
        self._subscribers.pop(queue, None)

    def broadcast(self, message: dict[str, Any]) -> None:
        """구독자에게 알림을 넣는다. 받는 사람이 정해져 있으면(recipient_nurse_id·recipient_role) 맞는 연결에만
        (같은 간호사가 탭 여러 개면 모두). 큐가 찬 구독자는 건너뛴다.
        [입력] message: NOTIFY payload를 JSON으로 푼 dict
        [출력] 없음
        """
        recipient_nurse_id = message.get(RECIPIENT_FIELD)
        recipient_role = message.get(RECIPIENT_ROLE_FIELD)
        targeted = recipient_nurse_id is not None or recipient_role is not None
        for queue, (nurse_id, role) in list(self._subscribers.items()):
            if targeted and nurse_id != recipient_nurse_id and (recipient_role is None or role != recipient_role):
                continue
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("notification_dropped", event=message.get("event"))

    async def _listen_forever(self) -> None:
        """LISTEN 연결을 유지한다. 끊기면 RECONNECT_DELAY_SECONDS 뒤 다시 연결.
        [입력] 없음
        [출력] 없음 (stop()이 취소할 때까지 돈다)
        """
        connection_url = settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(connection_url, autocommit=True) as connection:
                    await connection.execute(f"LISTEN {NOTIFICATION_CHANNEL}")
                    log.info("notification_listen_started", channel=NOTIFICATION_CHANNEL)
                    async for notify in connection.notifies():
                        try:
                            self.broadcast(json.loads(notify.payload))
                        except json.JSONDecodeError:
                            log.warning("notification_payload_invalid", payload=notify.payload[:200])
            except asyncio.CancelledError:
                raise
            except Exception as error:  # DB 재시작·네트워크 끊김 — 서버는 계속 살리고 다시 붙는다
                log.warning("notification_listen_failed", error=str(error))
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


notification_hub = NotificationHub()
