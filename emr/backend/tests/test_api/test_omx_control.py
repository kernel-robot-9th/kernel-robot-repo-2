"""관리자 OMX 명령·상태 — POST /omx/command(2026-10-27부터 색깔별 개수), GET /omx/status (2026-10-26).
OMX 클라이언트는 가짜로 바꾼다(실제 로봇팔에 보내지 않는다).
"""
from __future__ import annotations

import re

import pytest

from app.clients.omx import OmxRejected, OmxUnavailable
from app.services import omx_control

COMMAND_URL = "/api/v1/omx/command"
STATUS_URL = "/api/v1/omx/status"
END_POINT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")   # robot_access.omx_end_point 경로 규칙


@pytest.fixture
def omx_sent(monkeypatch) -> list[dict]:
    """send_command를 가짜로 — 보낸 것을 모아 둔다."""
    sent: list[dict] = []

    def _send(omx_base_url: str, counts: dict, request_id: str, timeout_seconds: float) -> dict:
        sent.append({"command": counts, "request_id": request_id})
        return {"accepted": True, "request_id": request_id}

    monkeypatch.setattr(omx_control, "send_command", _send)
    return sent


ONE_BLUE = {"command": {"blue": 1, "green": 0}}


def test_admin_sends_color_counts_with_generated_request_id(client, auth_headers, omx_sent):
    response = client.post(COMMAND_URL, json={"command": {"blue": 2, "green": 1}}, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert omx_sent == [{"command": {"blue": 2, "green": 1}, "request_id": body["request_id"]}]
    assert body["request_id"].startswith("emr-") and END_POINT_PATTERN.match(body["request_id"])
    assert body["omx_response"] == {"accepted": True, "request_id": body["request_id"]}
    assert body["command"] == {"blue": 2, "green": 1} and body["sent_at"]


def test_zero_count_color_is_left_out(client, auth_headers, omx_sent):
    """개수가 0인 색은 OMX에 보내지 않는다(10-28 사용자 "갯수가 0이면 생략")."""
    assert client.post(COMMAND_URL, json={"command": {"green": 1}}, headers=auth_headers).status_code == 200
    assert client.post(COMMAND_URL, json={"command": {"blue": 0, "green": 2}}, headers=auth_headers).status_code == 200
    assert [sent["command"] for sent in omx_sent] == [{"green": 1}, {"green": 2}]


def test_request_ids_differ(client, auth_headers, omx_sent):
    first = client.post(COMMAND_URL, json=ONE_BLUE, headers=auth_headers).json()["request_id"]
    second = client.post(COMMAND_URL, json=ONE_BLUE, headers=auth_headers).json()["request_id"]
    assert first != second


def test_general_nurse_and_anonymous_cannot_send(client, general_nurse_headers, omx_sent):
    assert client.post(COMMAND_URL, json=ONE_BLUE, headers=general_nurse_headers).status_code == 403
    assert client.post(COMMAND_URL, json=ONE_BLUE).status_code == 401
    assert client.get(STATUS_URL, headers=general_nurse_headers).status_code == 403
    assert omx_sent == []


@pytest.mark.parametrize("command", [
    "",                                  # 빈 문장
    "   ",
    {"blue": 0, "green": 0},             # 합계 0
    {"blue": 2, "green": 2},             # 합계가 한도(3) 초과
    {"blue": -1, "green": 1},
    {"blue": 1, "red": 1},               # 모르는 색
])
def test_bad_command_is_422(client, auth_headers, omx_sent, command):
    assert client.post(COMMAND_URL, json={"command": command}, headers=auth_headers).status_code == 422
    assert omx_sent == []


@pytest.mark.parametrize(("error", "status_code", "code"), [
    (OmxUnavailable("down"), 503, "omx_unavailable"),
    (OmxRejected(409, "busy"), 409, "omx_rejected"),
])
def test_omx_failures_map_to_codes(client, auth_headers, monkeypatch, error, status_code, code):
    def _send(*args, **kwargs):
        raise error

    monkeypatch.setattr(omx_control, "send_command", _send)
    monkeypatch.setattr(omx_control, "get_status", _send)
    for response in (client.post(COMMAND_URL, json=ONE_BLUE, headers=auth_headers), client.get(STATUS_URL, headers=auth_headers)):
        assert response.status_code == status_code and response.json()["code"] == code


def test_status_is_passed_through(client, auth_headers, monkeypatch):
    monkeypatch.setattr(omx_control, "get_status", lambda omx_base_url, timeout_seconds: {"state": "idle", "phase": "ready"})
    response = client.get(STATUS_URL, headers=auth_headers)
    assert response.status_code == 200 and response.json() == {"state": "idle", "phase": "ready"}


def test_sentence_mode_sends_one_gauze_sentence_ignoring_counts(client, auth_headers, omx_sent, monkeypatch):
    """임시(10-27): OMX_COMMAND_FORMAT=sentence면 수량을 무시하고 거즈 문장 하나 — 파란 거즈가 있으면 blue, 아니면 green."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "OMX_COMMAND_FORMAT", "sentence")
    first = client.post(COMMAND_URL, json={"command": {"blue": 2, "green": 1}}, headers=auth_headers)
    second = client.post(COMMAND_URL, json={"command": {"green": 3}}, headers=auth_headers)
    assert first.status_code == 200 and second.status_code == 200
    assert [sent["command"] for sent in omx_sent] == ["pick and place blue gauze", "pick and place green gauze"]
    assert first.json()["command"] == {"blue": 2, "green": 1}   # EMR 응답은 받은 개수 그대로


def test_sentence_command_only_while_temporary_switch_is_on(client, auth_headers, omx_sent, monkeypatch):
    """임시(10-27): 문장은 OMX_COMMAND_FORMAT=sentence일 때만 OMX에 그대로. 기본(counts, 합의한 형식)이면 400."""
    from app.core.config import settings

    closed = client.post(COMMAND_URL, json={"command": "pick and place green gauze"}, headers=auth_headers)
    assert closed.status_code == 400 and closed.json()["code"] == "omx_sentence_disabled" and omx_sent == []

    monkeypatch.setattr(settings, "OMX_COMMAND_FORMAT", "sentence")
    response = client.post(COMMAND_URL, json={"command": "pick and place green gauze"}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert omx_sent == [{"command": "pick and place green gauze", "request_id": response.json()["request_id"]}]
    assert response.json()["command"] == "pick and place green gauze"

