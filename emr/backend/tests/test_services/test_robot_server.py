"""로봇 서버 클라이언트 — GET /status 실패를 RobotServerError로 바꾸는지 (2026-10-23). DB 불필요."""
from __future__ import annotations

import httpx
import pytest

from app.clients import robot_server
from app.clients.robot_server import RobotServerError, fetch_robot_status


def _serve(monkeypatch, handler) -> list[str]:
    """httpx.get을 handler(url) → httpx.Response로 바꾼다. 부른 주소 목록을 돌려준다."""
    called: list[str] = []

    def _get(url: str, timeout: float) -> httpx.Response:
        called.append(url)
        return handler(url)

    monkeypatch.setattr(robot_server.httpx, "get", _get)
    return called


def test_returns_status_object_and_joins_url(monkeypatch):
    called = _serve(monkeypatch, lambda url: httpx.Response(200, json={"state": "idle", "battery_percent": 80}))
    assert fetch_robot_status("http://192.168.129.107:8080/", 2.0) == {"state": "idle", "battery_percent": 80}
    assert called == ["http://192.168.129.107:8080/status"]


@pytest.mark.parametrize("response", [
    httpx.Response(503, json={"detail": "no pose"}),
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json=[1, 2]),
])
def test_bad_responses_raise(monkeypatch, response):
    _serve(monkeypatch, lambda url: response)
    with pytest.raises(RobotServerError):
        fetch_robot_status("http://robot.test:8080", 2.0)


def test_connection_failure_raises(monkeypatch):
    def _refuse(url):
        raise httpx.ConnectError("refused")
    _serve(monkeypatch, _refuse)
    with pytest.raises(RobotServerError):
        fetch_robot_status("http://robot.test:8080", 2.0)
