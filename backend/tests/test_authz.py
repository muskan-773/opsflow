"""Tests: server-side authorization — team membership and roles.

These confirm the safety net is on the server: even if a malicious caller
knows an item id from another team, the API rejects them with 403.
"""
from .conftest import login, auth


def test_cross_team_read_rejected(client, seeded):
    # 'other' is a member of Payments; tries to read an Operations item.
    lead = login(client, "lead@test.local", "lead123")
    other = login(client, "other@test.local", "other123")
    item_id = client.post(
        "/items",
        json={"title": "Ops secret", "type": "incident", "priority": "high",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    ).json()["id"]

    r = client.get(f"/items/{item_id}", headers=auth(other))
    assert r.status_code == 403


def test_cross_team_create_rejected(client, seeded):
    # 'other' (Payments) tries to create an item in Operations.
    other = login(client, "other@test.local", "other123")
    r = client.post(
        "/items",
        json={"title": "Intrusion", "type": "task", "priority": "low",
              "team_id": seeded["ops_team"].id},
        headers=auth(other),
    )
    assert r.status_code == 403


def test_cross_team_transition_rejected(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    other = login(client, "other@test.local", "other123")
    item_id = client.post(
        "/items",
        json={"title": "Ops item", "type": "incident", "priority": "high",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    ).json()["id"]
    _ = client.post(f"/items/{item_id}/transition", json={"target_status": "in_progress"}, headers=auth(lead))

    r = client.post(
        f"/items/{item_id}/transition",
        json={"target_status": "awaiting_approval"},
        headers=auth(other),
    )
    assert r.status_code == 403


def test_viewer_cannot_edit(client, seeded):
    viewer = login(client, "viewer@test.local", "viewer123")
    lead = login(client, "lead@test.local", "lead123")
    item_id = client.post(
        "/items",
        json={"title": "To edit", "type": "task", "priority": "medium",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    ).json()["id"]
    r = client.patch(
        f"/items/{item_id}",
        json={"title": "Hacked", "version": 1},
        headers=auth(viewer),
    )
    assert r.status_code == 403


def test_member_cannot_assign(client, seeded):
    member = login(client, "member@test.local", "member123")
    item_id = client.post(
        "/items",
        json={"title": "To assign", "type": "task", "priority": "medium",
              "team_id": seeded["ops_team"].id},
        headers=auth(member),
    ).json()["id"]
    r = client.post(
        f"/items/{item_id}/assign",
        json={"assignee_id": seeded["member"].id},
        headers=auth(member),
    )
    assert r.status_code == 403


def test_admin_can_access_any_team(client, seeded):
    admin = login(client, "admin@test.local", "admin123")
    # Create in Payments (team 2) as admin.
    r = client.post(
        "/items",
        json={"title": "Admin cross-team", "type": "payment", "priority": "high",
              "team_id": seeded["pay_team"].id},
        headers=auth(admin),
    )
    assert r.status_code == 201
    # And list it.
    listed = client.get("/items?status=open", headers=auth(admin)).json()
    titles = [i["title"] for i in listed["items"]]
    assert "Admin cross-team" in titles
