# =============================================================================
# 파일   : app/schemas/omx.py
# 역할   : 관리자 OMX(로봇팔) 명령·상태 스키마 (2026-10-26)
# 작성일 : 2026-10-26
# 구성   :
#   - OmxCommandIn   명령 문장 (예전 형식)
#   - OmxCommandOut  EMR이 만든 request_id·보낸 시각·OMX 응답
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OmxCommandIn(BaseModel):
    """OMX에 보낼 명령 문장 (POST /command 예전 형식)."""

    command: str = Field(min_length=1, max_length=200, description="명령 문장", examples=["pick and place green gauze"])


class OmxCommandOut(BaseModel):
    """보낸 결과. OMX가 끝나면 같은 request_id로 GET /api/v1/robot/{request_id}/end-point를 부른다."""

    request_id: str = Field(description="EMR이 만든 작업 번호 (OMX에 그대로 보냄)")
    command: str
    sent_at: datetime = Field(description="EMR이 보낸 시각(UTC)")
    omx_response: dict[str, Any] = Field(description="OMX POST /command 응답 그대로")
