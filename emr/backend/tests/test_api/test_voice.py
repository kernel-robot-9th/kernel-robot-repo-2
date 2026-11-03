"""음성 배송 예약 초안 — POST /voice/parse, /voice/parse-text (2026-10-26).
파서는 가짜로 바꾼다(Gemini에 보내지 않는다). 초안만 만들고 예약은 만들지 않는지, 약품은 자동 확정하지 않는지 본다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.clients.voice_parser import VoiceParserUnavailable
from app.main import app
from app.models import Delivery, Location
from app.schemas.voice import SpokenItem, VoiceDraft
from app.services.voice_request import get_voice_parser

PARSE_URL = "/api/v2/voice/parse"
TEXT_URL = "/api/v2/voice/parse-text"


class FakeParser:
    """고정 초안을 돌려준다. 받은 MIME·이름 목록을 남긴다."""

    def __init__(self, draft: VoiceDraft | None = None, error: Exception | None = None) -> None:
        self.draft = draft
        self.error = error
        self.calls: list[dict] = []

    def _answer(self, **call) -> VoiceDraft:
        self.calls.append(call)
        if self.error:
            raise self.error
        return self.draft

    def parse_audio(self, audio, mime_type, supply_names, location_names):
        return self._answer(mime_type=mime_type, supply_names=supply_names, location_names=location_names)

    def parse_text(self, text, supply_names, location_names):
        return self._answer(text=text, supply_names=supply_names, location_names=location_names)


@pytest.fixture
def use_parser():
    """use_parser(draft=..., error=...) → FakeParser. 테스트가 끝나면 client 픽스처가 override를 지운다."""
    def _use(draft: VoiceDraft | None = None, error: Exception | None = None) -> FakeParser:
        fake = FakeParser(draft, error)
        app.dependency_overrides[get_voice_parser] = lambda: fake
        return fake
    return _use


def draft_of(*items: tuple[str, int], location: str | None = "301호", is_medication: bool = False) -> VoiceDraft:
    return VoiceDraft(transcript="시험 문장", items=[SpokenItem(name=name, quantity=quantity) for name, quantity in items],
                      location=location, is_medication=is_medication)


def test_medication_is_matched_but_needs_review(client, auth_headers, seed, use_parser):
    use_parser(draft_of(("A 약품", 2), is_medication=True))
    response = client.post(TEXT_URL, json={"text": "301호에 A 약품 두 개"}, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "시험 문장"
    assert body["location"]["location_id"] == seed["room_301"].id
    [item] = body["items"]
    assert (item["supply_id"], item["quantity"], item["is_medication"]) == (seed["medication"].id, 2, True)
    assert body["needs_review"] is True and body["warnings"] == ["medication_check"]


def test_catalog_has_nurse_supplies_only_and_no_robot_only_places(client, auth_headers, db, seed, use_parser):
    db.add(Location(name="충전", robot_only=True)); db.flush()
    fake = use_parser(draft_of(("A 약품", 1)))
    client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers)
    assert fake.calls[0]["supply_names"] == ["A 약품"]          # 환자 품목(이불) 빠짐
    assert "충전" not in fake.calls[0]["location_names"] and "301호" in fake.calls[0]["location_names"]


def test_patient_supply_is_not_matched(client, auth_headers, seed, use_parser):
    use_parser(draft_of(("이불", 1)))
    body = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers).json()
    assert body["items"][0]["supply_id"] is None
    assert "item_unmatched" in body["warnings"] and body["needs_review"] is True


def test_missing_and_unknown_location(client, auth_headers, seed, use_parser):
    use_parser(draft_of(("A 약품", 1), location=None))
    body = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers).json()
    assert body["location"]["location_id"] is None and "location_missing" in body["warnings"]

    use_parser(draft_of(("A 약품", 1), location="옥상"))
    body = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers).json()
    assert body["location"] == {"spoken_name": "옥상", "location_id": None, "location_name": None,
                                "score": body["location"]["score"], "candidates": body["location"]["candidates"]}
    assert "location_unmatched" in body["warnings"]


def test_same_supply_twice_is_merged(client, auth_headers, seed, use_parser):
    use_parser(draft_of(("A 약품", 1), ("A약품", 2)))
    body = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers).json()
    assert [(item["supply_id"], item["quantity"]) for item in body["items"]] == [(seed["medication"].id, 3)]


def test_no_items(client, auth_headers, seed, use_parser):
    use_parser(draft_of())
    body = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers).json()
    assert body["items"] == [] and "no_items" in body["warnings"]


def test_draft_does_not_create_delivery_or_change_stock(client, auth_headers, db, seed, use_parser):
    use_parser(draft_of(("A 약품", 2)))
    client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers)
    assert db.scalar(select(func.count()).select_from(Delivery)) == 0
    db.refresh(seed["medication"])
    assert seed["medication"].stock_qty == 10


def test_audio_strips_codec_and_passes_mime(client, auth_headers, seed, use_parser):
    fake = use_parser(draft_of(("A 약품", 1)))
    response = client.post(PARSE_URL, headers=auth_headers,
                           files={"audio": ("rec.webm", b"\x1a\x45\xdf\xa3fake", "audio/webm;codecs=opus")})
    assert response.status_code == 200, response.text
    assert fake.calls[0]["mime_type"] == "audio/webm"


@pytest.mark.parametrize(("content", "content_type"), [(b"hi", "text/plain"), (b"", "audio/webm")])
def test_bad_audio_is_400(client, auth_headers, seed, use_parser, content, content_type):
    fake = use_parser(draft_of(("A 약품", 1)))
    response = client.post(PARSE_URL, headers=auth_headers, files={"audio": ("a.bin", content, content_type)})
    assert response.status_code == 400 and response.json()["code"] == "voice_audio_invalid"
    assert fake.calls == []


def test_parser_failure_is_503(client, auth_headers, seed, use_parser):
    use_parser(error=VoiceParserUnavailable("down"))
    response = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers)
    assert response.status_code == 503 and response.json()["code"] == "voice_unavailable"


def test_disabled_by_default_is_503(client, auth_headers, seed, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "VOICE_PARSER", "disabled")
    response = client.post(TEXT_URL, json={"text": "x"}, headers=auth_headers)
    assert response.status_code == 503 and response.json()["code"] == "voice_disabled"


def test_login_required(client, seed, use_parser):
    use_parser(draft_of(("A 약품", 1)))
    assert client.post(TEXT_URL, json={"text": "x"}).status_code == 401


@pytest.mark.parametrize("text", ["", "x" * 501])
def test_bad_text_is_422(client, auth_headers, seed, use_parser, text):
    use_parser(draft_of(("A 약품", 1)))
    assert client.post(TEXT_URL, json={"text": text}, headers=auth_headers).status_code == 422
