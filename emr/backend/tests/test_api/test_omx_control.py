"""관리자 OMX 명령·상태 — POST /omx/command, GET /omx/status (2026-10-26).
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

    def _send(omx_base_url: str, command: str, request_id: str, timeout_seconds: float) -> dict:
        sent.append({"command": command, "request_id": request_id})
        return {"accepted": True, "request_id": request_id}

    monkeypatch.setattr(omx_control, "send_command", _send)
    return sent


def test_admin_sends_command_with_generated_request_id(client, auth_headers, omx_sent):
    response = client.post(COMMAND_URL, json={"command": "pick and place green gauze"}, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert omx_sent == [{"command": "pick and place green gauze", "request_id": body["request_id"]}]
    assert body["request_id"].startswith("emr-") and END_POINT_PATTERN.match(body["request_id"])
    assert body["omx_response"] == {"accepted": True, "request_id": body["request_id"]}
    assert body["command"] == "pick and place green gauze" and body["sent_at"]


def test_request_ids_differ(client, auth_headers, omx_sent):
    first = client.post(COMMAND_URL, json={"command": "a"}, headers=auth_headers).json()["request_id"]
    second = client.post(COMMAND_URL, json={"command": "a"}, headers=auth_headers).json()["request_id"]
    assert first != second


def test_general_nurse_and_anonymous_cannot_send(client, general_nurse_headers, omx_sent):
    assert client.post(COMMAND_URL, json={"command": "a"}, headers=general_nurse_headers).status_code == 403
    assert client.post(COMMAND_URL, json={"command": "a"}).status_code == 401
    assert client.get(STATUS_URL, headers=general_nurse_headers).status_code == 403
    assert omx_sent == []


@pytest.mark.parametrize("command", ["", "x" * 201])
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
    for response in (client.post(COMMAND_URL, json={"command": "a"}, headers=auth_headers), client.get(STATUS_URL, headers=auth_headers)):
        assert response.status_code == status_code and response.json()["code"] == code


def test_status_is_passed_through(client, auth_headers, monkeypatch):
    monkeypatch.setattr(omx_control, "get_status", lambda omx_base_url, timeout_seconds: {"state": "idle", "phase": "ready"})
    response = client.get(STATUS_URL, headers=auth_headers)
    assert response.status_code == 200 and response.json() == {"state": "idle", "phase": "ready"}
