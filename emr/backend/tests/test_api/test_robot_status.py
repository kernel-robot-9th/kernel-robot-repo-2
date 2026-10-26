"""claim 때 로봇 서버(팀원 Pinky API GET /status)에 상태를 물어 배송을 줄지 정하기 (2026-10-23). PostgreSQL 필요.
로봇 서버는 conftest의 가짜(robot_server 픽스처). 기준값은 config 기본값: 배터리 30 미만·오염도 70 초과면 주지 않는다.
"""
from __future__ import annotations

import pytest

from app.models import RobotStatusReport
from tests.conftest import ROBOT_SERVER_URL, requires_db

CLAIM = "/api/v1/robot/deliveries/claim"
ROBOTS = "/api/v1/robots"
DELIVERIES = "/api/v1/deliveries"
SKIP_HEADER = "X-Claim-Skip-Reason"


def _skipped(client, robot: dict) -> str | None:
    """claim이 204이면 이유 헤더(없으면 None), 200이면 실패시킨다."""
    claim = client.post(CLAIM, headers=robot["headers"])
    assert claim.status_code == 204, claim.text
    return claim.headers.get(SKIP_HEADER)


@requires_db
def test_claim_asks_robot_server_and_saves_last_values(client, robot_server, robot_with_key, reserve_overdue):
    reserved = reserve_overdue()
    robot_server["status"] |= {"battery_percent": 55.5, "contamination_percent": 3}
    claim = client.post(CLAIM, headers=robot_with_key["headers"])
    assert claim.status_code == 200 and claim.json()["id"] == reserved["id"]
    assert robot_server["called"] == [ROBOT_SERVER_URL]
    robot = client.get(f"{ROBOTS}/{robot_with_key['id']}").json()   # 관리자 화면: 서버 주소와 받은 값
    assert robot["robot_server_url"] == ROBOT_SERVER_URL
    assert robot["status_report"]["battery_percent"] == 55.5 and robot["status_report"]["contamination_percent"] == 3


@requires_db
def test_claim_does_not_ask_when_nothing_is_due_or_already_assigned(client, robot_server, robot_with_key, reserve_overdue):
    assert _skipped(client, robot_with_key) is None
    assert robot_server["called"] == []   # 줄 배송이 없으면 로봇 서버에 묻지 않는다
    reserve_overdue()
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200
    robot_server["status"]["battery_percent"] = 5   # 이미 맡은 배송은 상태와 상관없이 다시 준다(멱등), 묻지도 않는다
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200
    assert len(robot_server["called"]) == 1


@requires_db
def test_claim_skips_robot_without_server_url(client, auth_headers, make_robot, home_location, reserve_overdue, robot_server):
    robot = make_robot("배송로봇 2호", home_location_id=home_location.id, robot_server_url=None)
    reserved = reserve_overdue()
    assert _skipped(client, robot) == "robot_server_not_set"
    assert robot_server["called"] == []
    assert client.get(f"{DELIVERIES}/{reserved['id']}", headers=auth_headers).json()["status"] == "reserved"


@requires_db
def test_claim_skips_when_robot_server_is_unreachable(client, robot_server, robot_with_key, reserve_overdue):
    reserve_overdue()
    robot_server["error"] = "GET http://robot.test:8080/status failed: ConnectTimeout"
    assert _skipped(client, robot_with_key) == "robot_server_unreachable"
    assert client.get(f"{ROBOTS}/{robot_with_key['id']}").json()["status_report"] is None   # 받은 값이 없으면 저장도 없음


@pytest.mark.parametrize(("status_change", "reason"), [
    ({"battery_percent": None}, "robot_status_incomplete"),        # 팀원 /status에 칸이 아직 없을 때
    ({"contamination_percent": 120}, "robot_status_incomplete"),   # 0~100 밖
    ({"battery_percent": True}, "robot_status_incomplete"),        # 숫자가 아님
    ({"localized": False}, "robot_not_ready"),
    ({"nav2_ready": False}, "robot_not_ready"),
    ({"state": "running"}, "robot_not_ready"),                     # 다른 작업 중
    ({"battery_percent": 29.9}, "robot_battery_low"),
    ({"contamination_percent": 70.1}, "robot_contamination_high"),
])
@requires_db
def test_claim_skip_reasons(client, robot_server, robot_with_key, reserve_overdue, status_change, reason):
    reserve_overdue()
    robot_server["status"] |= status_change
    assert _skipped(client, robot_with_key) == reason


@requires_db
def test_claim_accepts_boundary_values(client, robot_server, robot_with_key, reserve_overdue):
    reserved = reserve_overdue()
    robot_server["status"] |= {"battery_percent": 30, "contamination_percent": 70}
    claim = client.post(CLAIM, headers=robot_with_key["headers"])
    assert claim.status_code == 200 and claim.json()["id"] == reserved["id"]


@requires_db
def test_robot_server_url_must_be_http_address(client, auth_headers, robot_with_key):
    url = f"{ROBOTS}/{robot_with_key['id']}"
    assert client.patch(url, headers=auth_headers, json={"robot_server_url": "192.168.129.107:8080"}).status_code == 422
    assert client.patch(url, headers=auth_headers, json={"robot_server_url": "http://192.168.129.107:8080/status"}).status_code == 422
    changed = client.patch(url, headers=auth_headers, json={"robot_server_url": "http://192.168.129.107:8080"})
    assert changed.status_code == 200 and changed.json()["robot_server_url"] == "http://192.168.129.107:8080"


@requires_db
def test_deleting_robot_deletes_its_status_report(client, db, auth_headers, robot_with_key, reserve_overdue):
    reserve_overdue()
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200
    assert db.get(RobotStatusReport, robot_with_key["id"]) is not None
    claimed_id = client.get("/api/v1/robot/me", headers=robot_with_key["headers"]).json()["active_delivery"]["id"]
    client.post(f"/api/v1/robot/deliveries/{claimed_id}/progress", headers=robot_with_key["headers"],
                json={"stage": "failed", "failure_reason": "robot_error"})   # 진행 중 배송이 있으면 삭제할 수 없다
    assert client.delete(f"{ROBOTS}/{robot_with_key['id']}", headers=auth_headers).status_code == 204
    db.expire_all()
    assert db.get(RobotStatusReport, robot_with_key["id"]) is None
