# =============================================================================
# 파일   : app/services/omx_signal.py
# 역할   : OMX(팀원 로봇팔 API)가 보내는 완료 신호 받기 — GET /robot/{request_id}/end-point
# 작성일 : 2026-10-26
# 구성   :
#   - OmxSignalService  record_end_point(request_id, client_host) — 서버 로그에 남기고 받은 시각을 돌려준다
# 사용자 결정(2026-10-26): 단순하게 GET, 지금은 성공 신호만, 인증 없음. DB는 쓰지 않는다(로그만) —
#   적재 흐름(FMS /loaded 등)과는 FMS 연동을 다시 시작할 때 잇는다(보관 브랜치 fms-order-2026-10-26)
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime

import structlog

log = structlog.get_logger(__name__)


class OmxSignalService:
    """OMX 완료 신호를 기록한다. 같은 request_id가 여러 번 와도 매번 받는다(기록도 매번)."""

    def record_end_point(self, request_id: str, client_host: str | None) -> datetime:
        """완료 신호 하나를 서버 로그에 남긴다.
        [입력] request_id: OMX /command·/pinky의 request_id / client_host: 보낸 쪽 주소(없으면 None)
        [출력] datetime: 받은 시각(UTC)
        """
        received_at = datetime.now(UTC)
        log.info("omx_end_point", request_id=request_id, client=client_host, received_at=received_at.isoformat())
        return received_at
