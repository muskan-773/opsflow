"""Tests: work-item creation, listing, detail, and update."""
import pytest
from .conftest import login, auth


def _create_item(client, token, team_id=None, **overrides):
    if team_id is None:
        # resolve ops team id from seeded data
        r = client.get("/auth/me", headers=auth(token))
        team_id = r.json()["memberships"][0]["team_id"]
    payload = {
        "title": "Test incident",
        "type": "incident",
        "priority": "high",
        "team_id": team_id,
        **overrides,
    }
    return client.post("/items", json=payload, headers=auth(token))


class TestCreate:
    def test_member_can_create(self, client, seeded):
        t = login(client, "member@test.local", "member123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["title"] == "Test incident"
        assert d["status"] == "open"
        assert d["version"] == 1

    def test_viewer_cannot_create(self, client, seeded):
        t = login(client, "viewer@test.local", "viewer123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id)
        assert r.status_code == 403

    def test_create_invalid_type_rejected(self, client, seeded):
        t = login(client, "member@test.local", "member123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id, type="nonsense")
        assert r.status_code == 422

    def test_initial_status_is_open(self, client, seeded):
        t = login(client, "lead@test.local", "lead123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id)
        assert r.json()["status"] == "open"

    def test_activity_created_event(self, client, seeded):
        t = login(client, "lead@test.local", "lead123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id)
        item_id = r.json()["id"]
        detail = client.get(f"/items/{item_id}", headers=auth(t)).json()
        events = [e["event_type"] for e in detail["activity"]]
        assert "created" in events


class TestList:
    def test_list_returns_paginated(self, client, seeded):
        t = login(client, "lead@test.local", "lead123")
        # create 3 items
        for _ in range(3):
            _create_item(client, t, team_id=seeded["ops_team"].id)
        r = client.get("/items?size=2", headers=auth(t))
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        assert "meta" in d
        assert d["meta"]["size"] == 2

    def test_status_filter(self, client, seeded):
        t = login(client, "lead@test.local", "lead123")
        _create_item(client, t, team_id=seeded["ops_team"].id, priority="low")
        r = client.get("/items?status=open", headers=auth(t))
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == "open"

    def test_search_filter(self, client, seeded):
        t = login(client, "lead@test.local", "lead123")
        _create_item(client, t, team_id=seeded["ops_team"].id, title="Unique XYZ Title")
        r = client.get("/items?q=Unique+XYZ", headers=auth(t))
        titles = [i["title"] for i in r.json()["items"]]
        assert any("Unique XYZ" in title for title in titles)


class TestUpdate:
    def test_member_can_update_own(self, client, seeded):
        t = login(client, "member@test.local", "member123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id)
        item = r.json()
        patch = client.patch(
            f"/items/{item['id']}",
            json={"title": "Updated title", "version": item["version"]},
            headers=auth(t),
        )
        assert patch.status_code == 200
        assert patch.json()["title"] == "Updated title"
        assert patch.json()["version"] == item["version"] + 1

    def test_update_version_increments(self, client, seeded):
        t = login(client, "lead@test.local", "lead123")
        r = _create_item(client, t, team_id=seeded["ops_team"].id)
        item = r.json()
        p = client.patch(
            f"/items/{item['id']}",
            json={"title": "New title", "version": item["version"]},
            headers=auth(t),
        )
        assert p.json()["version"] == 2
