# =============================================================================
# 파일   : app/api/v2/voice.py
# 역할   : 음성 (/api/v2/voice) — 배송 예약 초안·안내 음성. 간호사 로그인 필요, 예약은 만들지 않는다 (2026-10-26)
#          같은 날 사용자 결정: 음성은 v2에서 고도화(성능 비교·스트리밍·로컬 TTS 등), v1 주소는 없앰
# 작성일 : 2026-10-26
# 구성   :
#   - parse_voice  POST /voice/parse       — 녹음 파일(multipart audio) → 초안
#   - parse_text   POST /voice/parse-text  — 문장 → 초안 (마이크를 못 쓰는 화면·시험용)
#   - speak        POST /voice/speak       — 문장 → 안내 음성 WAV (2026-10-26)
# 화면은 초안으로 배송 예약 폼을 채우고, 간호사가 확인한 뒤 POST /deliveries로 예약한다
# =============================================================================
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile

from app.clients.speech_synth import SpeechSynthesizer
from app.clients.voice_parser import VoiceParser
from app.core.deps import DB, CurrentNurse
from app.schemas.voice import VoiceDraftOut, VoiceSpeakIn, VoiceTextIn
from app.services.voice_request import MAX_AUDIO_BYTES, VoiceRequestService, get_voice_parser
from app.services.voice_speech import SpeechService, get_speech_synthesizer

router = APIRouter()
VoiceParserDep = Annotated[VoiceParser, Depends(get_voice_parser)]
SpeechSynthesizerDep = Annotated[SpeechSynthesizer, Depends(get_speech_synthesizer)]
VOICE_RESPONSES = {
    401: {"description": "토큰 없음·만료"},
    503: {"description": "voice_disabled — 음성 기능 꺼짐(VOICE_PARSER·GEMINI_API_KEY) · voice_unavailable — 음성 분석 실패·시간 초과"},
}


@router.post(
    "/parse", response_model=VoiceDraftOut,
    summary="녹음 → 배송 예약 초안",
    description=(
        "녹음 파일(webm·ogg·wav·mp3·m4a, 15MB 이하)을 받아 적고 품목·수량·장소를 EMR 목록과 맞춘 **초안**을 돌려준다. "
        "예약은 만들지 않는다. 약품·확정 못 한 품목·장소는 `needs_review`와 `warnings`로 알린다. 2026-10-26"
    ),
    responses={**VOICE_RESPONSES, 400: {"description": "voice_audio_invalid — 빈 녹음·형식·크기"}},
)
def parse_voice(db: DB, nurse: CurrentNurse, parser: VoiceParserDep, audio: UploadFile = File(description="녹음 파일")) -> VoiceDraftOut:
    """
    [입력] audio: 녹음 파일 / nurse: 로그인(누가 했는지는 쓰지 않음 — 로그인 필수용)
    [출력] VoiceDraftOut
    """
    data = audio.file.read(MAX_AUDIO_BYTES + 1)   # 한도를 넘으면 서비스가 400 — 그 이상은 읽지 않는다
    return VoiceRequestService(db, parser).from_audio(data, audio.content_type or "")


@router.post(
    "/parse-text", response_model=VoiceDraftOut,
    summary="문장 → 배송 예약 초안",
    description="`/voice/parse`와 같은 초안을 문장으로 만든다(마이크를 못 쓰는 화면·시험용). 예약은 만들지 않는다. 2026-10-26",
    responses=VOICE_RESPONSES,
)
def parse_text(db: DB, nurse: CurrentNurse, parser: VoiceParserDep, data: VoiceTextIn) -> VoiceDraftOut:
    """
    [입력] data.text: 요청 문장 / nurse: 로그인
    [출력] VoiceDraftOut
    """
    return VoiceRequestService(db, parser).from_text(data.text)


@router.post(
    "/speak", response_class=Response,
    summary="문장 → 안내 음성 (WAV)",
    description=(
        "문장을 읽은 음성을 `audio/wav`(24kHz 모노 16비트)로 돌려준다 — 안내 방송용. Gemini TTS, 같은 문장·목소리는 서버 메모리 캐시"
        "(최근 64개, 헤더 `X-Voice-Cache: hit|miss`). `voice`는 `female`(기본 Kore)·`male`(기본 Algenib) 또는 Gemini 목소리 이름, "
        "실제로 쓴 이름은 헤더 `X-Voice-Name`. 문장은 Google 클라우드로 나가므로 **환자 정보는 넣지 않는다**. 2026-10-26·27"
    ),
    responses={**VOICE_RESPONSES, 200: {"content": {"audio/wav": {}}, "description": "WAV 음성"}},
)
def speak(nurse: CurrentNurse, synthesizer: SpeechSynthesizerDep, data: VoiceSpeakIn) -> Response:
    """
    [입력] data.text: 읽을 문장 / data.voice: "female"·"male" 또는 목소리 이름(선택) / nurse: 로그인
    [출력] Response: audio/wav
    """
    audio, cached, voice = SpeechService(synthesizer).speak(data.text, data.voice)
    return Response(content=audio, media_type="audio/wav",
                    headers={"X-Voice-Cache": "hit" if cached else "miss", "X-Voice-Name": voice, "Cache-Control": "no-store"})
