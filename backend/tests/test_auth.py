"""Tests: authentication — login success and failure cases."""
from .conftest import login, auth


def test_login_success(client):
    token = login(client, "member@test.local", "member123")
    assert len(token) > 20, "JWT should be a non-trivial string"


def test_login_bad_password(client):
    r = client.post("/auth/login", json={"email": "member@test.local", "password": "WRONG"})
    assert r.status_code == 401
    assert "Incorrect" in r.json()["detail"]


def test_login_unknown_email(client):
    r = client.post("/auth/login", json={"email": "nobody@test.local", "password": "x"})
    assert r.status_code == 401


def test_me_returns_current_user(client):
    token = login(client, "lead@test.local", "lead123")
    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "lead@test.local"
    assert any(m["role"] == "lead" for m in data["memberships"])


def test_protected_route_requires_auth(client):
    r = client.get("/items")
    assert r.status_code == 401


def test_admin_flag_in_me(client):
    token = login(client, "admin@test.local", "admin123")
    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["is_admin"] is True
