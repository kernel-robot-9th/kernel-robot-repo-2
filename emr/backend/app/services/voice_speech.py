# =============================================================================
# 파일   : app/services/voice_speech.py
# 역할   : 안내 음성 만들기 — 문장 → WAV (2026-10-26, 사용자 요청: "문장으로 동작하는 음성 출력 API, 안내에 사용")
# 작성일 : 2026-10-26
# 구성   :
#   - get_speech_synthesizer()  FastAPI 의존성 — VOICE_PARSER·GEMINI_API_KEY가 음성 초안과 같다. 꺼져 있으면 503 voice_disabled
#   - SpeechService             speak(text, voice) → WAV 바이트. 같은 (문장, 목소리, 말투)는 메모리 캐시에서
# 안내 문장은 되풀이되므로 최근 SPEECH_CACHE_SIZE개를 프로세스 메모리에 둔다(재시작하면 비어 있음, DB 저장 없음).
# 로그에는 글자 수·목소리·캐시 여부·처리 시간만 — 문장은 남기지 않는다(음성 초안과 같은 원칙)
# =============================================================================
from __future__ import annotations

import time
from collections import OrderedDict

import structlog

from app.clients.speech_synth import SpeechSynthesizer, SpeechSynthUnavailable, gemini_synthesizer
from app.core.config import settings
from app.core.exceptions import ServiceUnavailable

log = structlog.get_logger(__name__)

SPEECH_CACHE_SIZE = 64
_cache: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()   # (문장, 목소리, 말투) → WAV, 오래 안 쓴 것부터 버림


def get_speech_synthesizer() -> SpeechSynthesizer:
    """설정에 맞는 TTS. [입력] 없음 [출력] SpeechSynthesizer (꺼져 있으면 503 voice_disabled)"""
    if settings.VOICE_PARSER == "gemini" and settings.GEMINI_API_KEY:
        return gemini_synthesizer(settings.GEMINI_API_KEY, settings.VOICE_TTS_MODEL, settings.VOICE_TIMEOUT_SECONDS)
    raise ServiceUnavailable("voice is disabled (VOICE_PARSER / GEMINI_API_KEY)", code="voice_disabled")


def clear_speech_cache() -> None:
    """캐시 비우기 (테스트용). [입력] 없음 [출력] 없음"""
    _cache.clear()


class SpeechService:
    """문장 → WAV. TTS 실패는 503 voice_unavailable."""

    def __init__(self, synthesizer: SpeechSynthesizer) -> None:
        self.synthesizer = synthesizer

    def speak(self, text: str, voice: str | None = None) -> tuple[bytes, bool]:
        """안내 음성.
        [입력] text: 읽을 문장 / voice: 목소리 이름(없으면 설정 VOICE_TTS_VOICE)
        [출력] (WAV 바이트, 캐시에서 꺼냈는지)
        """
        voice = voice or settings.VOICE_TTS_VOICE
        key = (text, voice, settings.VOICE_TTS_STYLE)
        attempt = log.bind(text_length=len(text), voice=voice)
        if key in _cache:
            _cache.move_to_end(key)
            attempt.info("voice_speech_made", cached=True, elapsed_ms=0)
            return _cache[key], True
        started = time.perf_counter()
        try:
            audio = self.synthesizer.synthesize(text, voice, settings.VOICE_TTS_STYLE)
        except SpeechSynthUnavailable as error:
            attempt.warning("voice_speech_failed", error=str(error))
            raise ServiceUnavailable(str(error), code="voice_unavailable") from error
        _cache[key] = audio
        if len(_cache) > SPEECH_CACHE_SIZE:
            _cache.popitem(last=False)
        attempt.info("voice_speech_made", cached=False, elapsed_ms=round((time.perf_counter() - started) * 1000), audio_bytes=len(audio))
        return audio, False
