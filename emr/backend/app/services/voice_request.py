# =============================================================================
# 파일   : app/services/voice_request.py
# 역할   : 음성·문장 → 배송 예약 초안 (2026-10-26) — 초안만 만든다. 예약은 간호사가 폼에서 POST /deliveries로 직접
# 작성일 : 2026-10-26 (~/voice_module app/voice/service.py, 2026-10-14에서 옮김)
# 구성   :
#   - get_voice_parser()    FastAPI 의존성 — 설정 VOICE_PARSER로 고름, disabled·키 없음이면 503 voice_disabled
#   - VoiceRequestService   from_audio(audio, mime_type) · from_text(text) → VoiceDraftOut
# 사용자 결정(2026-10-26):
#   - 간호사 배송 예약 화면만. 카탈로그 = requestable_by=nurse 비품, 장소 = 로봇 전용(robot_only)이 아닌 장소
#   - 약품도 초안에 넣되 **자동 확정하지 않는다**(is_medication + 경고 medication_check — 화면이 확인 표시 전엔 예약을 막음).
#     모듈(10-14)은 약품이면 품목을 비웠다 — 지금 간호사 품목이 모두 약품이라 바꿈
#   - 로그에 받아 적은 문장·품목을 남기지 않는다(환자 정보가 들어갈 수 있음) — 길이·처리 시간·needs_review만
# DB에 쓰지 않는다.
# =============================================================================
from __future__ import annotations

import time
from collections.abc import Callable

import structlog
from sqlalchemy.orm import Session

from app.clients.voice_parser import VoiceParser, VoiceParserUnavailable, gemini_parser
from app.core.config import settings
from app.core.exceptions import BadRequest, ServiceUnavailable
from app.models.enums import RequestableBy, SupplyCategory
from app.repositories.location import LocationRepository
from app.repositories.supply import SupplyRepository
from app.schemas.voice import VoiceCandidateOut, VoiceDraft, VoiceDraftOut, VoiceItemOut, VoiceLocationOut
from app.services.voice_matcher import MatchTarget, best_match

log = structlog.get_logger(__name__)

MAX_AUDIO_BYTES = 15 * 1024 * 1024   # Gemini 인라인 요청 20MB 제한보다 작게 (브라우저 녹음은 30초에서 멈춘다)
ALLOWED_AUDIO_TYPES = frozenset({"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac"})

WARNING_MEDICATION = "medication_check"
WARNING_ITEM_UNMATCHED = "item_unmatched"
WARNING_NO_ITEMS = "no_items"
WARNING_LOCATION_MISSING = "location_missing"
WARNING_LOCATION_UNMATCHED = "location_unmatched"


def get_voice_parser() -> VoiceParser:
    """설정에 맞는 파서. [입력] 없음 [출력] VoiceParser (꺼져 있으면 503 voice_disabled)"""
    if settings.VOICE_PARSER == "gemini" and settings.GEMINI_API_KEY:
        return gemini_parser(settings.GEMINI_API_KEY, settings.VOICE_MODEL, settings.VOICE_TIMEOUT_SECONDS)
    raise ServiceUnavailable("voice parser is disabled (VOICE_PARSER / GEMINI_API_KEY)", code="voice_disabled")


def _candidates_out(targets: list[MatchTarget]) -> list[VoiceCandidateOut]:
    """[입력] 후보 대상 [출력] 응답용 후보"""
    return [VoiceCandidateOut(id=target.id, name=target.name) for target in targets]


class VoiceRequestService:
    """초안 만들기. 파서가 받아 적고 이름을 뽑으면, 최종 비품·장소 id는 voice_matcher가 EMR 목록에서 정한다."""

    def __init__(self, db: Session, parser: VoiceParser) -> None:
        self.parser = parser
        supplies = SupplyRepository(db).list_requestable_by(RequestableBy.NURSE)
        self.supply_targets = [MatchTarget(supply.id, supply.name) for supply in supplies]
        self.medication_supply_ids = {supply.id for supply in supplies if supply.category == SupplyCategory.MEDICATION}
        self.location_targets = [MatchTarget(location.id, location.name)
                                 for location in LocationRepository(db).list_by_name(limit=500) if not location.robot_only]

    def from_audio(self, audio: bytes, mime_type: str) -> VoiceDraftOut:
        """녹음 → 초안.
        [입력] audio: 녹음 바이트 / mime_type: 예 "audio/webm" (";codecs=..." 붙어도 됨)
        [출력] VoiceDraftOut (빈 녹음·형식·크기 400 voice_audio_invalid, LLM 실패 503 voice_unavailable)
        """
        mime_type = mime_type.split(";")[0].strip().lower()
        if mime_type not in ALLOWED_AUDIO_TYPES:
            raise BadRequest(f"unsupported audio type: {mime_type or '(none)'}", code="voice_audio_invalid")
        if not audio:
            raise BadRequest("empty audio", code="voice_audio_invalid")
        if len(audio) > MAX_AUDIO_BYTES:
            raise BadRequest(f"audio larger than {MAX_AUDIO_BYTES} bytes", code="voice_audio_invalid")
        return self._run("audio", len(audio), lambda supply_names, location_names: self.parser.parse_audio(
            audio, mime_type, supply_names, location_names))

    def from_text(self, text: str) -> VoiceDraftOut:
        """문장 → 초안 (마이크를 못 쓰는 화면·시험용).
        [입력] text [출력] VoiceDraftOut (LLM 실패 503 voice_unavailable)
        """
        return self._run("text", len(text), lambda supply_names, location_names: self.parser.parse_text(
            text, supply_names, location_names))

    def _run(self, source: str, input_size: int, parse: Callable[[list[str], list[str]], VoiceDraft]) -> VoiceDraftOut:
        """파서 부르기 → 매칭 → 로그(내용 없이).
        [입력] source: audio | text / input_size: 바이트 수·글자 수 / parse(품목 이름, 장소 이름) [출력] VoiceDraftOut
        """
        started = time.perf_counter()
        attempt = log.bind(source=source, input_size=input_size)
        try:
            draft = parse([target.name for target in self.supply_targets], [target.name for target in self.location_targets])
        except VoiceParserUnavailable as error:
            attempt.warning("voice_draft_failed", error=str(error))
            raise ServiceUnavailable(str(error), code="voice_unavailable") from error
        result = self._finalize(draft)
        attempt.info("voice_draft_made", elapsed_ms=round((time.perf_counter() - started) * 1000),
                     item_count=len(result.items), needs_review=result.needs_review)
        return result

    def _finalize(self, draft: VoiceDraft) -> VoiceDraftOut:
        """LLM 초안 → 비품·장소 매칭과 경고.
        [입력] draft [출력] VoiceDraftOut — 같은 비품을 두 번 말하면 수량을 합친다(예약은 같은 비품을 한 줄만 받는다)
        """
        warnings: list[str] = []
        items: list[VoiceItemOut] = []
        by_supply_id: dict[int, VoiceItemOut] = {}
        for spoken in draft.items:
            match = best_match(spoken.name, self.supply_targets)
            if match.target is not None and match.target.id in by_supply_id:
                by_supply_id[match.target.id].quantity += spoken.quantity
                continue
            item = VoiceItemOut(
                spoken_name=spoken.name, quantity=spoken.quantity, score=match.score,
                supply_id=match.target.id if match.target else None,
                supply_name=match.target.name if match.target else None,
                # 확정 못 한 줄도 약품이라고 들었으면 약품으로 본다 — 화면이 고른 뒤에 다시 확인하게
                is_medication=(match.target.id in self.medication_supply_ids) if match.target else draft.is_medication,
                candidates=_candidates_out(match.candidates),
            )
            items.append(item)
            if match.target is not None:
                by_supply_id[match.target.id] = item

        if not items:
            warnings.append(WARNING_NO_ITEMS)
        if any(item.supply_id is None for item in items):
            warnings.append(WARNING_ITEM_UNMATCHED)
        if draft.is_medication or any(item.is_medication for item in items):
            warnings.append(WARNING_MEDICATION)

        location = VoiceLocationOut(spoken_name=draft.location)
        if not draft.location:
            warnings.append(WARNING_LOCATION_MISSING)
        else:
            match = best_match(draft.location, self.location_targets)
            location.score = match.score
            location.candidates = _candidates_out(match.candidates)
            if match.target is not None:
                location.location_id, location.location_name = match.target.id, match.target.name
            else:
                warnings.append(WARNING_LOCATION_UNMATCHED)

        return VoiceDraftOut(transcript=draft.transcript, location=location, items=items,
                             needs_review=bool(warnings), warnings=warnings)
