# =============================================================================
# 파일   : app/clients/voice_parser.py
# 역할   : 음성·문장 → 배송 요청 초안(VoiceDraft) — 받아 적기와 품목·장소 추출을 LLM 한 번으로
# 작성일 : 2026-10-26 (~/voice_module app/voice/parser.py, 2026-10-14에서 옮김)
# 구성   :
#   - VoiceParserUnavailable  LLM 호출 실패·시간 초과·응답 모양이 틀림
#   - VoiceParser             바꿔 끼우는 인터페이스 (parse_audio·parse_text)
#   - build_prompt()          품목·장소 이름 목록을 넣은 추출 지시문
#   - GeminiVoiceParser       Gemini Interactions API 구현 (google-genai)
#   - gemini_parser()         설정값별 싱글턴
# 사용자 결정(2026-10-26): Gemini로 시작, 로컬(faster-whisper + Ollama)은 같은 인터페이스 구현을 추가해 바꾼다.
# 음성이 Google 클라우드로 나간다 — 시연·시험 동안만. 키는 .env의 GEMINI_API_KEY (문서·로그에 넣지 않는다)
# =============================================================================
from __future__ import annotations

import base64
from functools import lru_cache
from typing import Protocol

from pydantic import ValidationError

from app.schemas.voice import VoiceDraft


class VoiceParserUnavailable(Exception):
    """LLM이 초안을 만들지 못함 (메시지는 로그용)."""


class VoiceParser(Protocol):
    """음성·문장을 VoiceDraft로 바꾸는 인터페이스. 구현만 바꿔 끼운다."""

    def parse_audio(self, audio: bytes, mime_type: str, supply_names: list[str], location_names: list[str]) -> VoiceDraft:
        """[입력] 오디오 바이트 / MIME / 품목 이름 목록 / 장소 이름 목록 [출력] VoiceDraft"""
        ...

    def parse_text(self, text: str, supply_names: list[str], location_names: list[str]) -> VoiceDraft:
        """[입력] 요청 문장 / 품목 이름 목록 / 장소 이름 목록 [출력] VoiceDraft"""
        ...


def build_prompt(supply_names: list[str], location_names: list[str], source: str) -> str:
    """추출 지시문. 이름은 목록에서 가장 가까운 것으로 적게 하되, 최종 id는 코드(voice_matcher)가 정한다.
    [입력] supply_names / location_names / source: "audio" | "text" [출력] str
    """
    supplies = "\n".join(f"- {name}" for name in supply_names)
    locations = "\n".join(f"- {name}" for name in location_names)
    head = "다음 음성은" if source == "audio" else "다음 문장은"
    return f"""{head} 병원 간호사가 로봇 배송을 예약하려고 말한 내용이다.
규칙:
1. transcript에는 들은/받은 문장을 한국어로 그대로 적는다.
2. items에는 요청한 비품과 수량을 넣는다. 수량을 말하지 않았으면 1.
3. 품목 이름은 아래 비품 목록 중 가장 가까운 이름으로 적되, 목록에 없으면 말한 그대로 적는다. 지어내지 않는다.
4. 배송 장소(병실·병동)를 말했으면 location에 아래 장소 목록 중 가장 가까운 이름으로, 목록에 없으면 말한 그대로, 말하지 않았으면 null.
5. 약품(의약품, 주사제, 진통제 등)을 요청하면 is_medication=true. 비품만이면 false.

비품 목록:
{supplies}

장소 목록:
{locations}
"""


class GeminiVoiceParser:
    """Gemini로 받아 적기와 구조화 추출을 한 번에. 오류는 모두 VoiceParserUnavailable."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        from google import genai   # 늦은 import: 음성을 끈 서버(VOICE_PARSER=disabled)는 이 패키지를 읽지 않는다

        self._client = genai.Client(api_key=api_key, http_options={"timeout": int(timeout_seconds * 1000)})
        self._model = model
        self._format = {"type": "text", "mime_type": "application/json", "schema": VoiceDraft.model_json_schema()}

    def _run(self, input_parts: list[dict]) -> VoiceDraft:
        """[입력] Interactions 입력 파트 [출력] 검증한 VoiceDraft"""
        try:
            interaction = self._client.interactions.create(model=self._model, input=input_parts, response_format=self._format)
        except Exception as error:   # google-genai 오류 종류가 많다(네트워크·키·할당량·시간 초과) — 모두 같은 503
            raise VoiceParserUnavailable(f"gemini call failed: {error.__class__.__name__}") from error
        try:
            return VoiceDraft.model_validate_json(interaction.output_text)
        except (ValidationError, TypeError) as error:
            raise VoiceParserUnavailable("gemini returned an invalid draft") from error

    def parse_audio(self, audio: bytes, mime_type: str, supply_names: list[str], location_names: list[str]) -> VoiceDraft:
        """[입력] 오디오 바이트 / MIME / 품목·장소 이름 [출력] VoiceDraft"""
        return self._run([
            {"type": "text", "text": build_prompt(supply_names, location_names, "audio")},
            {"type": "audio", "data": base64.b64encode(audio).decode("ascii"), "mime_type": mime_type},
        ])

    def parse_text(self, text: str, supply_names: list[str], location_names: list[str]) -> VoiceDraft:
        """[입력] 요청 문장 / 품목·장소 이름 [출력] VoiceDraft"""
        return self._run([
            {"type": "text", "text": build_prompt(supply_names, location_names, "text")},
            {"type": "text", "text": text},
        ])


@lru_cache(maxsize=2)
def gemini_parser(api_key: str, model: str, timeout_seconds: float) -> GeminiVoiceParser:
    """설정값이 같으면 같은 클라이언트를 다시 쓴다. [입력] api_key / model / timeout_seconds [출력] GeminiVoiceParser"""
    return GeminiVoiceParser(api_key, model, timeout_seconds)
