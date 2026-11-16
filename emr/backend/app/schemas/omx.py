# =============================================================================
# 파일   : app/schemas/omx.py
# 역할   : 관리자 OMX(로봇팔) 명령·상태 스키마 (2026-10-26)
# 작성일 : 2026-10-26
# 구성   :
#   - OmxCommandCounts  색깔별 개수 {"blue": n, "green": n} (2026-10-27 — 문장 형식에서 바꿈)
#   - OmxCommandIn      {"command": {"blue": n, "green": n}} 또는 임시로 문장 {"command": "pick and place blue gauze"} (10-27 — 예전 버전, OMX에 그대로)
#   - OmxCommandOut     EMR이 만든 request_id·받은 command·보낸 시각·OMX 응답
# 색 대응(약품 → blue, 비품 → green)은 app/services/omx_items.py
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# 한 번에 실을 수 있는 개수 — Pinky 적재 한도(FMS 묶음 최대 3)와 같게 둔다
# [검토 필요] OMX가 한 명령에 몇 개까지 집는지 팀원 확인 전 가정값
OMX_MAX_ITEMS_PER_COMMAND = 3


class OmxCommandCounts(BaseModel):
    """OMX가 집을 색깔별 개수. blue = 약품(파란 거즈), green = 비품(녹색 거즈)."""

    model_config = ConfigDict(extra="forbid")

    blue: int = Field(default=0, ge=0, le=OMX_MAX_ITEMS_PER_COMMAND, description="파란 거즈(약품) 개수")
    green: int = Field(default=0, ge=0, le=OMX_MAX_ITEMS_PER_COMMAND, description="녹색 거즈(비품) 개수")

    @model_validator(mode="after")
    def _total_in_range(self) -> OmxCommandCounts:
        """합계 1개 이상, 한도 이하.
        [입력] 없음 [출력] self (어긋나면 ValueError → 422)
        """
        total = self.blue + self.green
        if not 1 <= total <= OMX_MAX_ITEMS_PER_COMMAND:
            raise ValueError(f"blue + green must be 1..{OMX_MAX_ITEMS_PER_COMMAND} (got {total})")
        return self


# 임시(2026-10-27 사용자: "문장으로 수정해줘") — 예전 버전처럼 명령 문장을 받아 OMX에 그대로 보낸다. 지금 실제 OMX(vision 47bcb47)가 문장만 받아서.
# 같은 날 "합의한 내용으로 변경" — 설정 OMX_COMMAND_FORMAT=sentence일 때만 받는다(services/omx_control.py, 아니면 400 omx_sentence_disabled)
# 길이 한도는 OMX CommandRequest와 같다(1~2000자)
OmxCommandSentence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class OmxCommandIn(BaseModel):
    """OMX에 보낼 명령 — 색깔별 개수 {"blue": n, "green": n}, 또는 임시로 문장("pick and place blue gauze", OMX에 그대로)."""

    command: OmxCommandCounts | OmxCommandSentence = Field(
        examples=["pick and place blue gauze", {"blue": 1, "green": 0}],
        description="개수(10-27 결정) 또는 문장(임시, 예전 버전 — 실제 OMX가 문장만 받는 동안). 개수는 설정 OMX_COMMAND_FORMAT=sentence면 거즈 문장 하나로 바뀐다",
    )


class OmxCommandOut(BaseModel):
    """보낸 결과. OMX가 끝나면 같은 request_id로 GET /api/v1/robot/{request_id}/end-point를 부른다."""

    request_id: str = Field(description="EMR이 만든 작업 번호 (OMX에 그대로 보냄)")
    command: OmxCommandCounts | str = Field(description="받은 command 그대로")
    sent_at: datetime = Field(description="EMR이 보낸 시각(UTC)")
    omx_response: dict[str, Any] = Field(description="OMX POST /command 응답 그대로")
