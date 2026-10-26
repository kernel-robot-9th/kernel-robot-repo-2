"""DB 통합 테스트는 TEST_DATABASE_URL이 있을 때만 돈다. 없으면 skip.

    TEST_DATABASE_URL=postgresql+psycopg://emr:emr@localhost:5432/emr_test pytest
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import hash_password
from app.models import Base, Location, Map, Nurse, Supply
from app.models.enums import NurseRole

TEST_DB = os.getenv("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="session")
def engine():
    if not TEST_DB:
        pytest.skip("no test db")
    test_engine = create_engine(TEST_DB)
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """테스트마다 트랜잭션 롤백 — 테이블 재생성보다 빠르다."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def seed(db: Session) -> dict:
    """N001은 관리자. 일반 간호사가 필요하면 general_nurse_headers."""
    nurse = Nurse(employee_no="N001", name="김간호", password_hash=hash_password("nurse1234"), role=NurseRole.ADMIN)
    medication = Supply(code="MED-A", name="A 약품", category="medication", requestable_by="nurse", stock_qty=10)
    blanket = Supply(code="SUP-BLK", name="이불", category="supply", requestable_by="patient", stock_qty=5)
    ward_map = Map(name="3병동", file_name="ward3.yaml", resolution_m_per_pixel=0.05,
                   origin_x_m=-10.0, origin_y_m=-10.0, origin_yaw_rad=0.0)
    db.add(ward_map); db.flush()
    room_301 = Location(name="301호", map_x_m=12.5, map_y_m=3.2, map_yaw_rad=1.57, map_id=ward_map.id)
    room_302 = Location(name="302호")  # 좌표·맵 미등록
    db.add_all([nurse, medication, blanket, room_301, room_302]); db.flush()
    return {"nurse": nurse, "medication": medication, "blanket": blanket, "ward_map": ward_map,
            "room_301": room_301, "room_302": room_302}


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    from app.core.database import get_db
    from app.main import app

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    # lifespan의 SELECT 1은 실제 engine을 치므로 TestClient에서 lifespan 생략
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client: TestClient, seed: dict) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"employee_no": "N001", "password": "nurse1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def logged_in_client(client: TestClient, auth_headers: dict[str, str]) -> TestClient:
    """N001(관리자)로 로그인한 상태의 client. 모든 요청에 Bearer 헤더가 붙는다."""
    client.headers.update(auth_headers)
    return client


@pytest.fixture
def general_nurse_headers(client: TestClient, db: Session, seed: dict) -> dict[str, str]:
    """일반 간호사 N090(관리자 아님)의 Bearer 헤더. 요청마다 headers=로 넘긴다."""
    db.add(Nurse(employee_no="N090", name="일반간호", password_hash=hash_password("nurse1234"), role=NurseRole.NURSE))
    db.flush()
    response = client.post("/api/v1/auth/login", json={"employee_no": "N090", "password": "nurse1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---- 배송 배정·진행 (로드맵 2단계, 2026-10-20) 공용 -----------------------------

ROBOTS_URL = "/api/v1/robots"
DELIVERIES_URL = "/api/v1/deliveries"


@pytest.fixture
def published(monkeypatch) -> list[dict]:
    """발행된 알림 목록. 테스트는 롤백하므로 NOTIFY 대신 여기에 쌓는다."""
    from app.repositories.notification import NotificationRepository

    messages: list[dict] = []
    monkeypatch.setattr(NotificationRepository, "publish", lambda self, message: messages.append(message))
    return messages


@pytest.fixture
def home_location(db: Session, seed: dict) -> Location:
    """복귀 장소 — 301호와 같은 맵(3병동)에 좌표가 있다."""
    station = Location(name="간호사스테이션", map_x_m=10.0, map_y_m=3.0, map_yaw_rad=0.0, map_id=seed["ward_map"].id)
    db.add(station); db.flush()
    return station


ROBOT_SERVER_URL = "http://robot.test:8080"


@pytest.fixture(autouse=True)
def robot_server(monkeypatch) -> dict:
    """가짜 로봇 서버(팀원 Pinky API GET /status) — 테스트는 네트워크에 나가지 않는다 (2026-10-23).
    돌려주는 dict를 고치면 응답이 바뀐다. robot_server["error"] = "..."이면 연결 실패(RobotServerError).
    부른 주소는 robot_server["called"]에 쌓인다.
    """
    from app.clients.robot_server import RobotServerError

    server: dict = {
        "status": {"localized": True, "nav2_ready": True, "state": "idle", "battery_percent": 90, "contamination_percent": 10},
        "error": None, "called": [],
    }

    def _fetch(robot_server_url: str, timeout_seconds: float) -> dict:
        server["called"].append(robot_server_url)
        if server["error"]:
            raise RobotServerError(server["error"])
        return dict(server["status"])

    monkeypatch.setattr("app.services.robot_status.fetch_robot_status", _fetch)
    return server


@pytest.fixture
def make_robot(client: TestClient, auth_headers: dict[str, str]):
    """로봇 만들기: make_robot(name, robot_type="amr", home_location_id=None, robot_server_url=ROBOT_SERVER_URL)
    → {"id", "api_key", "headers"}. robot_server_url: claim 때 상태를 물을 로봇 서버(가짜, robot_server 픽스처) — None이면 넣지 않음
    """
    def _make(name: str, robot_type: str = "amr", home_location_id: int | None = None,
              robot_server_url: str | None = ROBOT_SERVER_URL) -> dict:
        robot = client.post(ROBOTS_URL, headers=auth_headers, json={"name": name, "robot_type": robot_type})
        assert robot.status_code == 201, robot.text
        robot_id = robot.json()["id"]
        issued = client.post(f"{ROBOTS_URL}/{robot_id}/api-key", headers=auth_headers)
        assert issued.status_code == 201, issued.text
        changes = {"home_location_id": home_location_id, "robot_server_url": robot_server_url}
        changes = {field: value for field, value in changes.items() if value is not None}
        if changes:
            patched = client.patch(f"{ROBOTS_URL}/{robot_id}", headers=auth_headers, json=changes)
            assert patched.status_code == 200, patched.text
        api_key = issued.json()["api_key"]
        return {"id": robot_id, "api_key": api_key, "headers": {"X-Robot-Api-Key": api_key}}
    return _make


@pytest.fixture
def robot_with_key(make_robot, home_location: Location) -> dict:
    """키와 복귀 장소(간호사스테이션)가 있는 AMR. {"id", "api_key", "headers"}"""
    return make_robot("배송로봇 1호", home_location_id=home_location.id)


@pytest.fixture
def reserve_overdue(client: TestClient, auth_headers: dict[str, str], db: Session, seed: dict):
    """예약 시각이 지난 reserved 배송 만들기 (API는 미래 시각만 받으므로 만든 뒤 DB에서 과거로 바꾼다).
    reserve_overdue(destination_id=301호, quantity=3, minutes_ago=1, headers=N001) → 응답 JSON
    """
    from app.models.delivery import Delivery

    def _reserve(destination_id: int | None = None, quantity: int = 3, minutes_ago: int = 1,
                 headers: dict[str, str] | None = None) -> dict:
        response = client.post(DELIVERIES_URL, headers=headers or auth_headers, json={
            "destination_location_id": destination_id or seed["room_301"].id,
            "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "items": [{"supply_id": seed["medication"].id, "quantity": quantity}]})
        assert response.status_code == 201, response.text
        delivery = db.get(Delivery, response.json()["id"])
        delivery.scheduled_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
        db.flush()
        return response.json()
    return _reserve


@pytest.fixture
def arrived_delivery(client: TestClient, auth_headers: dict[str, str], robot_with_key: dict, reserve_overdue) -> dict:
    """N001이 예약하고 robot_with_key가 맡아 도착한 배송. {"id", "receipt_marker_id"} (재고 10 → 7)"""
    reserved = reserve_overdue()
    claimed = client.post("/api/v1/robot/deliveries/claim", headers=robot_with_key["headers"])
    assert claimed.status_code == 200 and claimed.json()["id"] == reserved["id"], claimed.text
    arrived = client.post(f"/api/v1/robot/deliveries/{reserved['id']}/progress", headers=robot_with_key["headers"],
                          json={"stage": "arrived"})
    assert arrived.status_code == 200, arrived.text
    marker = client.get(f"{DELIVERIES_URL}/{reserved['id']}", headers=auth_headers).json()["receipt_marker_id"]
    return {"id": reserved["id"], "receipt_marker_id": marker}
