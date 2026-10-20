"""로그인·내 정보. PostgreSQL 필요."""
from __future__ import annotations

from tests.conftest import requires_db


def _login(client, employee_no: str = "N001", password: str = "nurse1234"):
    return client.post("/api/v1/auth/login", json={"employee_no": employee_no, "password": password})


@requires_db
def test_login_and_me(client, seed):
    response = _login(client)
    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer" and response.json()["expires_in_seconds"] > 0
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["employee_no"] == "N001" and "password" not in me.text


@requires_db
def test_login_rejects_wrong_password_and_unknown_employee(client, seed):
    wrong_password = _login(client, password="wrong-password")
    unknown_employee = _login(client, employee_no="N999")
    assert wrong_password.status_code == unknown_employee.status_code == 401
    assert wrong_password.json() == unknown_employee.json() == {"code": "invalid_credentials", "detail": "invalid credentials"}


@requires_db
def test_me_requires_valid_token(client, seed):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


@requires_db
def test_inactive_nurse_cannot_login_or_use_token(client, seed, auth_headers):
    response = client.post("/api/v1/nurses", headers=auth_headers, json={"employee_no": "N300", "name": "퇴사간호", "password": "pass-1234"})
    other_headers = {"Authorization": f"Bearer {_login(client, 'N300', 'pass-1234').json()['access_token']}"}
    assert client.delete(f"/api/v1/nurses/{response.json()['id']}", headers=auth_headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=other_headers).status_code == 401
    assert _login(client, "N300", "pass-1234").status_code == 401


@requires_db
def test_registered_nurse_can_login(client, auth_headers):
    client.post("/api/v1/nurses", headers=auth_headers, json={"employee_no": "N200", "name": "새간호", "password": "pass-1234"})
    assert _login(client, "N200", "pass-1234").status_code == 200


@requires_db
def test_me_includes_role(client, seed, auth_headers, general_nurse_headers):
    assert client.get("/api/v1/auth/me", headers=auth_headers).json()["role"] == "admin"
    assert client.get("/api/v1/auth/me", headers=general_nurse_headers).json()["role"] == "nurse"


@requires_db
def test_change_own_password(client, seed, general_nurse_headers):
    url = "/api/v1/auth/password"
    # 현재 비밀번호가 틀리면 400 — 401이 아니어야 화면이 로그아웃되지 않는다
    response = client.post(url, headers=general_nurse_headers, json={"current_password": "wrong", "new_password": "changed-1234"})
    assert response.status_code == 400 and response.json()["code"] == "current_password_mismatch"
    assert client.post(url, headers=general_nurse_headers, json={"current_password": "nurse1234", "new_password": "short"}).status_code == 422
    response = client.post(url, headers=general_nurse_headers, json={"current_password": "nurse1234", "new_password": "changed-1234"})
    assert response.status_code == 204, response.text
    assert _login(client, "N090", "nurse1234").status_code == 401
    assert _login(client, "N090", "changed-1234").status_code == 200
    assert client.post(url, json={"current_password": "x", "new_password": "changed-1234"}).status_code == 401  # 로그인 필요


@requires_db
def test_admin_resets_other_nurse_password(client, seed, auth_headers, general_nurse_headers):
    general_nurse_id = client.get("/api/v1/auth/me", headers=general_nurse_headers).json()["id"]
    response = client.post(f"/api/v1/nurses/{general_nurse_id}/password-reset", headers=auth_headers, json={"new_password": "temp-1234"})
    assert response.status_code == 204, response.text
    assert _login(client, "N090", "nurse1234").status_code == 401
    assert _login(client, "N090", "temp-1234").status_code == 200
    assert client.post("/api/v1/nurses/999999/password-reset", headers=auth_headers, json={"new_password": "temp-1234"}).status_code == 404
