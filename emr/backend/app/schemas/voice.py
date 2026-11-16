# =============================================================================
# 파일   : app/schemas/voice.py
# 역할   : 음성 배송 예약 초안 스키마 (2026-10-26) — 음성은 초안만 만들고 예약은 간호사가 폼에서 직접 한다
# 작성일 : 2026-10-26 (~/voice_module app/voice/schemas.py, 2026-10-14에서 옮김)
# 구성   :
#   - SpokenItem / VoiceDraft   LLM이 뽑는 원시 구조 (Gemini 구조화 출력 스키마로 그대로 쓴다)
#   - VoiceTextIn               문장으로 초안 만들기 본문 (마이크를 못 쓸 때)
#   - VoiceSpeakIn              안내 음성 만들기 본문 (POST /voice/speak)
#   - VoiceCandidateOut         매칭 후보 (화면에서 고르기)
#   - VoiceItemOut / VoiceLocationOut / VoiceDraftOut   확인용 응답 — 폼을 채우는 값
# =============================================================================
from __future__ import annotations

from pydantic import BaseModel, Field


class SpokenItem(BaseModel):
    """발화에서 뽑은 품목 하나. 이름은 말한 그대로."""

    name: str = Field(description="발화에서 말한 비품 이름 그대로")
    quantity: int = Field(ge=1, description="요청 수량, 말하지 않았으면 1")


class VoiceDraft(BaseModel):
    """LLM 추출 결과 전체. Gemini 구조화 출력 스키마로 그대로 쓴다."""

    transcript: str = Field(description="음성을 받아 적은 한국어 문장 전체")
    items: list[SpokenItem] = Field(description="요청한 비품 목록")
    location: str | None = Field(default=None, description="배송 장소(병실·병동), 말하지 않았으면 null")
    is_medication: bool = Field(description="약품(의약품) 요청이 포함되면 true")


class VoiceTextIn(BaseModel):
    """문장으로 초안 만들기 — 마이크를 못 쓰는 화면(http로 접속한 다른 PC)·시험용."""

    text: str = Field(min_length=1, max_length=500, examples=["101호에 A 약품 두 개"])


class VoiceSpeakIn(BaseModel):
    """안내 음성으로 읽을 문장. 환자 정보는 넣지 않는다(Google 클라우드로 나간다)."""

    text: str = Field(min_length=1, max_length=300, examples=["101호에 배송 로봇이 도착했습니다."])
    voice: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,32}$",
                              description="\"female\"(여성, 기본 Kore)·\"male\"(남성, 기본 Algenib) 또는 Gemini 목소리 이름(예: Charon). "
                                          "없으면 서버 기본(VOICE_TTS_VOICE)", examples=["male"])


class VoiceCandidateOut(BaseModel):
    """매칭 후보 (supplies.id 또는 locations.id)."""

    id: int
    name: str


class VoiceItemOut(BaseModel):
    """말한 품목과 EMR 비품의 매칭. supply_id가 null이면 확정 못 함 → candidates에서 고른다."""

    spoken_name: str
    quantity: int
    supply_id: int | None = None
    supply_name: str | None = None
    score: float = Field(description="0~1 유사도")
    is_medication: bool = Field(description="약품이면 true — 자동 확정하지 않는다(간호사가 확인 표시)")
    candidates: list[VoiceCandidateOut] = []


class VoiceLocationOut(BaseModel):
    """말한 장소와 EMR 장소의 매칭. location_id가 null이면 확정 못 함(말하지 않았거나 애매)."""

    spoken_name: str | None = None
    location_id: int | None = None
    location_name: str | None = None
    score: float = 0.0
    candidates: list[VoiceCandidateOut] = []


class VoiceDraftOut(BaseModel):
    """확인용 초안. 예약은 만들지 않는다 — 화면이 이 값으로 배송 예약 폼을 채운다."""

    transcript: str = Field(description="받아 적은 문장")
    location: VoiceLocationOut
    items: list[VoiceItemOut]
    needs_review: bool = Field(description="하나라도 확정 못 했거나 약품이 있으면 true")
    warnings: list[str] = Field(
        description="경고 코드: medication_check(약품 확인) · item_unmatched(품목 확정 못 함) · "
                    "location_missing(장소를 말하지 않음) · location_unmatched(장소 확정 못 함) · no_items(품목 없음)",
    )
