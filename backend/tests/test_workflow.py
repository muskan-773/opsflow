"""Tests: workflow enforcement — valid transitions and rejections."""
from .conftest import login, auth


def _transition(client, token, item_id, target):
    return client.post(
        f"/items/{item_id}/transition",
        json={"target_status": target},
        headers=auth(token),
    )


def _create(client, token, team_id):
    return client.post(
        "/items",
        json={"title": "Workflow item", "type": "incident", "priority": "high", "team_id": team_id},
        headers=auth(token),
    )


def test_valid_path_open_to_resolved(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    team_id = seeded["ops_team"].id
    item_id = _create(client, lead, team_id).json()["id"]

    assert _transition(client, lead, item_id, "in_progress").status_code == 200
    assert _transition(client, lead, item_id, "awaiting_approval").status_code == 200
    assert _transition(client, lead, item_id, "resolved").status_code == 200
    assert _transition(client, lead, item_id, "closed").status_code == 200


def test_invalid_transition_open_to_closed_rejected(client, seeded):
    member = login(client, "member@test.local", "member123")
    item_id = _create(client, member, seeded["ops_team"].id).json()["id"]
    r = _transition(client, member, item_id, "closed")
    assert r.status_code == 409
    assert "not allowed" in r.json()["detail"]


def test_invalid_transition_in_progress_to_open_rejected(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    _transition(client, lead, item_id, "in_progress")
    r = _transition(client, lead, item_id, "open")
    assert r.status_code == 409


def test_member_cannot_approve(client, seeded):
    member = login(client, "member@test.local", "member123")
    lead = login(client, "lead@test.local", "lead123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    _transition(client, member, item_id, "in_progress")
    _transition(client, member, item_id, "awaiting_approval")

    # Member attempts the approval step -> 403
    r = _transition(client, member, item_id, "resolved")
    assert r.status_code == 403
    assert "cannot make this transition" in r.json()["detail"]


def test_lead_can_approve(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    member = login(client, "member@test.local", "member123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    _transition(client, member, item_id, "in_progress")
    _transition(client, member, item_id, "awaiting_approval")

    r = _transition(client, lead, item_id, "resolved")
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


def test_lead_can_reject_back_to_in_progress(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    member = login(client, "member@test.local", "member123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    _transition(client, member, item_id, "in_progress")
    _transition(client, member, item_id, "awaiting_approval")

    r = _transition(client, lead, item_id, "in_progress")
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


def test_viewer_cannot_transition(client, seeded):
    viewer = login(client, "viewer@test.local", "viewer123")
    lead = login(client, "lead@test.local", "lead123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    r = _transition(client, viewer, item_id, "in_progress")
    assert r.status_code == 403


def test_transition_records_activity(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    member = login(client, "member@test.local", "member123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    _transition(client, member, item_id, "in_progress")

    detail = client.get(f"/items/{item_id}", headers=auth(lead)).json()
    events = [e["event_type"] for e in detail["activity"]]
    assert "status_changed" in events
    assert "created" in events


def test_lead_can_reopen_resolved(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    item_id = _create(client, lead, seeded["ops_team"].id).json()["id"]
    _transition(client, lead, item_id, "in_progress")
    _transition(client, lead, item_id, "awaiting_approval")
    _transition(client, lead, item_id, "resolved")
    r = _transition(client, lead, item_id, "in_progress")
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"
