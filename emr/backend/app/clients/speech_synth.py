# =============================================================================
# 파일   : app/clients/speech_synth.py
# 역할   : 문장 → 음성 WAV (TTS) — 안내 방송용 (2026-10-26)
# 작성일 : 2026-10-26 (~/voice_module voice_loop.py synthesize(), 2026-10-14에서 옮김)
# 구성   :
#   - SpeechSynthUnavailable   TTS 호출 실패·시간 초과·오디오가 없음
#   - SpeechSynthesizer        바꿔 끼우는 인터페이스 (synthesize)
#   - pcm_to_wav()             헤더 없는 16비트 PCM이 오면 WAV로 감싼다
#   - GeminiSpeechSynthesizer  Gemini Interactions API TTS (google-genai)
#   - gemini_synthesizer()     설정값별 싱글턴
# 문장이 Google 클라우드로 나간다 — 안내 문장만 보내고 환자 정보는 넣지 않는다
# =============================================================================
from __future__ import annotations

import base64
import io
import wave
from functools import lru_cache
from typing import Protocol

GEMINI_PCM_RATE_HZ = 24_000   # Gemini TTS 출력: 24kHz 모노 16비트


class SpeechSynthUnavailable(Exception):
    """음성을 만들지 못함 (메시지는 로그용)."""


class SpeechSynthesizer(Protocol):
    """문장을 WAV로 바꾸는 인터페이스. 로컬 TTS는 같은 모양으로 추가한다."""

    def synthesize(self, text: str, voice: str, style: str) -> bytes:
        """[입력] text: 읽을 문장 / voice: 목소리 이름 / style: 말투 지시 [출력] WAV 바이트"""
        ...


def pcm_to_wav(pcm: bytes, rate_hz: int = GEMINI_PCM_RATE_HZ) -> bytes:
    """[입력] pcm: 16비트 모노 PCM / rate_hz [출력] WAV 바이트"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate_hz)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


class GeminiSpeechSynthesizer:
    """Gemini TTS. 오류는 모두 SpeechSynthUnavailable."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        from google import genai   # 늦은 import: 음성을 끈 서버는 이 패키지를 읽지 않는다

        self._client = genai.Client(api_key=api_key, http_options={"timeout": int(timeout_seconds * 1000)})
        self._model = model

    def synthesize(self, text: str, voice: str, style: str) -> bytes:
        """[입력] text / voice: 예 "Kore" / style: 예 "차분하고 또박또박" [출력] WAV 바이트"""
        try:
            interaction = self._client.interactions.create(
                model=self._model,
                input=[{"type": "user_input", "content": [{
                    "type": "text", "text": text,
                    "annotations": [{"type": "speech_metadata", "style": style}],
                }]}],
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice}]},
            )
            audio = base64.b64decode(interaction.output_audio.data)
        except Exception as error:   # 네트워크·키·할당량·시간 초과·응답 모양 — 모두 같은 503
            raise SpeechSynthUnavailable(f"gemini tts failed: {error.__class__.__name__}") from error
        if not audio:
            raise SpeechSynthUnavailable("gemini tts returned no audio")
        return audio if audio[:4] == b"RIFF" else pcm_to_wav(audio)


@lru_cache(maxsize=2)
def gemini_synthesizer(api_key: str, model: str, timeout_seconds: float) -> GeminiSpeechSynthesizer:
    """설정값이 같으면 같은 클라이언트를 다시 쓴다. [입력] api_key / model / timeout_seconds [출력] GeminiSpeechSynthesizer"""
    return GeminiSpeechSynthesizer(api_key, model, timeout_seconds)
