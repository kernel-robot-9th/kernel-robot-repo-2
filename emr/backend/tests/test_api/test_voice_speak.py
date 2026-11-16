"""안내 음성 — POST /voice/speak (2026-10-26). TTS는 가짜로 바꾼다(Gemini에 보내지 않는다)."""
from __future__ import annotations

import io
import wave

import pytest

from app.clients.speech_synth import SpeechSynthUnavailable, pcm_to_wav
from app.main import app
from app.services.voice_speech import clear_speech_cache, get_speech_synthesizer

SPEAK_URL = "/api/v2/voice/speak"


class FakeSynthesizer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def synthesize(self, text: str, voice: str, style: str) -> bytes:
        self.calls.append((text, voice, style))
        if self.error:
            raise self.error
        return pcm_to_wav(b"\x00\x00" * 2400)   # 0.1초 무음


@pytest.fixture
def use_synth():
    clear_speech_cache()

    def _use(error: Exception | None = None) -> FakeSynthesizer:
        fake = FakeSynthesizer(error)
        app.dependency_overrides[get_speech_synthesizer] = lambda: fake
        return fake
    yield _use
    clear_speech_cache()


def test_returns_wav(client, auth_headers, use_synth):
    fake = use_synth()
    response = client.post(SPEAK_URL, json={"text": "4인실 왼쪽에 배송 로봇이 도착했습니다."}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav" and response.headers["x-voice-cache"] == "miss"
    with wave.open(io.BytesIO(response.content)) as wav_file:
        assert (wav_file.getnchannels(), wav_file.getframerate()) == (1, 24_000)
    from app.core.config import settings
    assert fake.calls == [("4인실 왼쪽에 배송 로봇이 도착했습니다.", settings.VOICE_TTS_VOICE, settings.VOICE_TTS_STYLE)]


def test_same_sentence_comes_from_cache(client, auth_headers, use_synth):
    fake = use_synth()
    first = client.post(SPEAK_URL, json={"text": "안내"}, headers=auth_headers)
    second = client.post(SPEAK_URL, json={"text": "안내"}, headers=auth_headers)
    other_voice = client.post(SPEAK_URL, json={"text": "안내", "voice": "Charon"}, headers=auth_headers)
    assert second.headers["x-voice-cache"] == "hit" and second.content == first.content
    assert other_voice.headers["x-voice-cache"] == "miss"
    assert [call[1] for call in fake.calls] == [fake.calls[0][1], "Charon"]


def test_failure_is_503_and_not_cached(client, auth_headers, use_synth):
    use_synth(SpeechSynthUnavailable("down"))
    response = client.post(SPEAK_URL, json={"text": "안내"}, headers=auth_headers)
    assert response.status_code == 503 and response.json()["code"] == "voice_unavailable"
    fake = use_synth()
    assert client.post(SPEAK_URL, json={"text": "안내"}, headers=auth_headers).headers["x-voice-cache"] == "miss"
    assert len(fake.calls) == 1


def test_disabled_is_503(client, auth_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "VOICE_PARSER", "disabled")
    response = client.post(SPEAK_URL, json={"text": "안내"}, headers=auth_headers)
    assert response.status_code == 503 and response.json()["code"] == "voice_disabled"


def test_login_required(client, seed, use_synth):
    use_synth()
    assert client.post(SPEAK_URL, json={"text": "안내"}).status_code == 401


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "x" * 301}, {"text": "안내", "voice": "../etc"}])
def test_bad_body_is_422(client, auth_headers, use_synth, body):
    fake = use_synth()
    assert client.post(SPEAK_URL, json=body, headers=auth_headers).status_code == 422
    assert fake.calls == []


def test_pcm_is_wrapped_as_wav():
    data = pcm_to_wav(b"\x01\x00" * 10)
    assert data[:4] == b"RIFF"


@pytest.mark.parametrize(("voice", "expected"), [("male", "VOICE_TTS_VOICE_MALE"), ("FEMALE", "VOICE_TTS_VOICE_FEMALE"),
                                                 (None, "VOICE_TTS_VOICE")])
def test_gender_names_map_to_configured_voices(client, auth_headers, use_synth, voice, expected):
    from app.core.config import settings

    fake = use_synth()
    body = {"text": "안내"} if voice is None else {"text": "안내", "voice": voice}
    response = client.post(SPEAK_URL, json=body, headers=auth_headers)
    assert response.status_code == 200
    assert fake.calls[0][1] == getattr(settings, expected) == response.headers["x-voice-name"]


def test_gender_name_and_voice_name_share_cache(client, auth_headers, use_synth):
    from app.core.config import settings

    fake = use_synth()
    client.post(SPEAK_URL, json={"text": "안내", "voice": "male"}, headers=auth_headers)
    second = client.post(SPEAK_URL, json={"text": "안내", "voice": settings.VOICE_TTS_VOICE_MALE}, headers=auth_headers)
    assert second.headers["x-voice-cache"] == "hit" and len(fake.calls) == 1
