"""OMX 클라이언트 — POST /command(색깔별 개수, 2026-10-27)·GET /status, 실패를 OmxUnavailable·OmxRejected로 바꾸는지 (2026-10-26). DB 불필요, 네트워크 안 나감."""
from __future__ import annotations

import httpx
import pytest

from app.clients import omx
from app.clients.omx import OmxRejected, OmxUnavailable, get_status, send_command

BASE_URL = "http://omx.test:8000/"


def test_send_command_posts_color_counts_and_request_id(monkeypatch):
    called: list[tuple[str, dict]] = []

    def _post(url: str, json: dict, timeout: float) -> httpx.Response:
        called.append((url, json))
        return httpx.Response(200, json={"accepted": True, "request_id": json["request_id"]})

    monkeypatch.setattr(omx.httpx, "post", _post)
    assert send_command(BASE_URL, {"blue": 1, "green": 2}, "emr-1", 3.0) == {"accepted": True, "request_id": "emr-1"}
    assert called == [("http://omx.test:8000/command", {"command": {"blue": 1, "green": 2}, "request_id": "emr-1"})]


def test_get_status_joins_url(monkeypatch):
    called: list[str] = []

    def _get(url: str, timeout: float) -> httpx.Response:
        called.append(url)
        return httpx.Response(200, json={"state": "idle"})

    monkeypatch.setattr(omx.httpx, "get", _get)
    assert get_status(BASE_URL, 3.0) == {"state": "idle"}
    assert called == ["http://omx.test:8000/status"]


def test_4xx_is_rejected_with_detail(monkeypatch):
    monkeypatch.setattr(omx.httpx, "post", lambda url, json, timeout: httpx.Response(409, json={"detail": "busy"}))
    with pytest.raises(OmxRejected) as caught:
        send_command(BASE_URL, {"blue": 1, "green": 0}, "emr-1", 3.0)
    assert caught.value.status_code == 409 and caught.value.detail == "busy"


@pytest.mark.parametrize("response", [
    httpx.Response(500, json={"detail": "boom"}),
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json=[1, 2]),
])
def test_bad_responses_are_unavailable(monkeypatch, response):
    monkeypatch.setattr(omx.httpx, "get", lambda url, timeout: response)
    with pytest.raises(OmxUnavailable):
        get_status(BASE_URL, 3.0)


def test_connection_failure_is_unavailable(monkeypatch):
    def _post(url: str, json: dict, timeout: float) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(omx.httpx, "post", _post)
    with pytest.raises(OmxUnavailable):
        send_command(BASE_URL, {"blue": 1, "green": 0}, "emr-1", 3.0)
