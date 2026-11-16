"""OMX 완료 신호 — GET /robot/{request_id}/end-point (2026-10-26). 인증 없음, 성공 신호만, DB 쓰지 않음(로그만).
테스트는 로봇 키 검사를 켠 상태(ROBOT_KEY_DISABLED=0)로 돌린다 — 키 없이도 200이어야 한다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

URL = "/api/v1/robot/{request_id}/end-point"


def test_signal_is_accepted_without_robot_key(client):
    response = client.get(URL.format(request_id="yolo-8b5efa75"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_id"] == "yolo-8b5efa75" and body["received"] is True
    assert datetime.fromisoformat(body["received_at"].replace("Z", "+00:00")).tzinfo is not None
    assert response.headers["cache-control"] == "no-store"


def test_same_request_id_twice_is_fine(client):
    first = client.get(URL.format(request_id="omx.job_1"))
    second = client.get(URL.format(request_id="omx.job_1"))
    assert first.status_code == second.status_code == 200


@pytest.mark.parametrize("request_id", ["a b", "x" * 65, "한글", "semi;colon"])
def test_bad_request_id_is_422(client, request_id):
    assert client.get(URL.format(request_id=request_id)).status_code == 422


def test_only_get(client):
    assert client.post(URL.format(request_id="yolo-1")).status_code == 405
