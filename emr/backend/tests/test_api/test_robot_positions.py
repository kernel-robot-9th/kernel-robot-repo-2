"""병원 지도 로봇 위치 — FMS robot-status → 메모리 → GET /robot-positions (2026-10-29). PostgreSQL 필요."""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.services.fms_robot_positions import robot_position_store
from tests.conftest import requires_db

ROBOT_STATUS = "/api/v1/fms/robot-status"
POSITIONS = "/api/v1/robot-positions"
MAP_NAME = "시험 아레나"


@pytest.fixture(autouse=True)
def empty_store(monkeypatch):
    """시험마다 메모리 위치를 비우고, 그릴 맵 이름을 시험용으로."""
    robot_position_store.clear()
    monkeypatch.setattr(settings, "FMS_MAP_NAME", MAP_NAME)
    yield
    robot_position_store.clear()


def _robot(number: int, x_cm: float, y_cm: float, heading_deg: float, **fields) -> dict:
    return {"robot": number, "name": f"pinky_{number}", "online": True, "state": "moving", "place": "아래 복도",
            "pose": {"x": x_cm, "y": y_cm, "heading": heading_deg}, **fields}


@requires_db
def test_positions_in_map_units_with_emr_robot(client, logged_in_client, make_robot, monkeypatch):
    map_id = logged_in_client.post("/api/v1/maps", json={
        "name": MAP_NAME, "file_name": "arena.yaml", "resolution_m_per_pixel": 0.0015,
        "origin_x_m": 0.0, "origin_y_m": 0.0, "origin_yaw_rad": 0.0}).json()["id"]
    robot_id = make_robot("배송로봇 시험")["id"]
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {1: robot_id})

    response = client.post(ROBOT_STATUS, json={"time": "2026-10-29T10:00:00+09:00",
                                               "robots": [_robot(2, 20, 137.5, 0), _robot(1, 130.0, 80.1, 90.0)]})
    assert response.status_code == 200 and response.json() == {"ok": True}

    body = logged_in_client.get(POSITIONS).json()
    assert body["map_id"] == map_id
    first, second = body["robots"]
    assert first["fms_robot_number"] == 1 and first["robot_id"] == robot_id and first["robot_name"] == "배송로봇 시험"
    assert (first["map_x_m"], first["map_y_m"]) == pytest.approx((1.3, 0.801))
    assert first["map_yaw_rad"] == pytest.approx(math.pi / 2)
    assert first["fms_robot_name"] == "pinky_1" and first["state"] == "moving" and first["place"] == "아래 복도"
    assert first["is_stale"] is False
    assert second["fms_robot_number"] == 2 and second["robot_id"] is None and second["robot_name"] is None

    client.post(ROBOT_STATUS, json={"robots": [_robot(1, 40, 70, 180)]})   # 다음 1초 — 덮어쓰기
    moved = logged_in_client.get(POSITIONS).json()["robots"][0]
    assert (moved["map_x_m"], moved["map_y_m"]) == pytest.approx((0.4, 0.7))


@requires_db
def test_bad_entries_are_skipped_and_still_200(client, logged_in_client):
    for body in ({"robots": "x"}, {"time": "t"}, {"robots": [1, {"robot": "1", "pose": {"x": 1, "y": 1, "heading": 0}},
                                                               {"robot": 3, "pose": {"x": "a", "y": 1, "heading": 0}},
                                                               {"robot": 4}, _robot(5, 10, 20, 0)]}):
        assert client.post(ROBOT_STATUS, json=body).status_code == 200
    body = logged_in_client.get(POSITIONS).json()
    assert body["map_id"] is None   # 그 이름의 맵이 없음 — 화면은 그리지 않는다
    assert [robot["fms_robot_number"] for robot in body["robots"]] == [5]


@requires_db
def test_offline_or_old_value_is_stale(client, logged_in_client):
    client.post(ROBOT_STATUS, json={"robots": [_robot(1, 10, 10, 0), _robot(2, 10, 10, 0, online=False)]})
    robots = logged_in_client.get(POSITIONS).json()["robots"]
    assert [robot["is_stale"] for robot in robots] == [False, True]

    old = datetime.now(UTC) - timedelta(seconds=settings.FMS_POSITION_STALE_SECONDS + 1)
    robot_position_store.update({"robots": [_robot(1, 10, 10, 0)]}, old)
    assert logged_in_client.get(POSITIONS).json()["robots"][0]["is_stale"] is True


@requires_db
def test_positions_need_login(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    assert client.get(POSITIONS).status_code == 401


@requires_db
def test_fatigue_and_contamination_for_cards(client, logged_in_client):
    """10-30 지도 아래 로봇 카드: FMS fatigue(피로도, 10-30 battery에서 이름 바뀜)·contamination(0~100) → fatigue_percent·contamination_percent.
    칸이 없거나 숫자가 아니거나 범위 밖이면 null이고 위치는 그대로 저장."""
    client.post(ROBOT_STATUS, json={"robots": [
        _robot(1, 10, 10, 0, fatigue=70, contamination=10),
        _robot(2, 20, 20, 0),
        _robot(3, 30, 30, 0, fatigue="full", contamination=150),
    ]})
    robots = logged_in_client.get(POSITIONS).json()["robots"]
    assert [(robot["fatigue_percent"], robot["contamination_percent"]) for robot in robots] == [(70, 10), (None, None), (None, None)]
    assert [robot["fms_robot_number"] for robot in robots] == [1, 2, 3]
