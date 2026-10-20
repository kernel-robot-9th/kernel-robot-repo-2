# =============================================================================
# 파일   : app/repositories/notification.py
# 역할   : 실시간 알림 발행 — PostgreSQL NOTIFY
# 작성일 : 2026-10-16
# 구성   :
#   - NOTIFICATION_CHANNEL    LISTEN/NOTIFY 채널 이름 (app/core/notification_hub.py가 LISTEN)
#   - NotificationRepository  publish()
# NOTIFY는 트랜잭션이 commit될 때만 전달된다 — 409 등으로 rollback된 요청의 알림은 나가지 않는다
# =============================================================================
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

NOTIFICATION_CHANNEL = "emr_notifications"


class NotificationRepository:
    """알림 발행. 저장하지 않고 NOTIFY로만 내보낸다."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def publish(self, message: dict[str, Any]) -> None:
        """현재 트랜잭션에 NOTIFY를 건다. commit 시점에 LISTEN 중인 API 프로세스로 전달된다.
        [입력] message: JSON으로 바꿀 수 있는 dict (8000바이트 이하 — PostgreSQL NOTIFY 한도)
        [출력] 없음
        """
        self.db.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": NOTIFICATION_CHANNEL, "payload": json.dumps(message, ensure_ascii=False)},
        )
