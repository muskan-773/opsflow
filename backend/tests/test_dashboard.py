"""Tests: dashboard counts are scoped to the user and computed server-side."""
from .conftest import login, auth


def test_dashboard_stats_shape(client, seeded):
    t = login(client, "lead@test.local", "lead123")
    r = client.get("/dashboard", headers=auth(t))
    assert r.status_code == 200
    d = r.json()
    assert set(d["stats"].keys()) == {
        "total_open", "critical_high", "assigned_to_me",
        "unassigned_urgent", "awaiting_my_approval",
    }
    assert "assigned_to_me" in d
    assert "unassigned_urgent" in d
    assert "awaiting_my_approval" in d


def test_assigned_to_me_counts_own_items(client, seeded):
    member = login(client, "member@test.local", "member123")
    lead = login(client, "lead@test.local", "lead123")
    # Lead assigns an open item to the member.
    created = client.post(
        "/items",
        json={"title": "Mine", "type": "task", "priority": "high",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    ).json()
    client.post(
        f"/items/{created['id']}/assign",
        json={"assignee_id": seeded["member"].id},
        headers=auth(lead),
    )
    d = client.get("/dashboard", headers=auth(member)).json()
    assert d["stats"]["assigned_to_me"] >= 1


def test_unassigned_urgent_lists_unassigned_high_priority(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    client.post(
        "/items",
        json={"title": "Urgent unassigned", "type": "incident", "priority": "critical",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    )
    d = client.get("/dashboard", headers=auth(lead)).json()
    assert d["stats"]["unassigned_urgent"] >= 1
    titles = [i["title"] for i in d["unassigned_urgent"]]
    assert "Urgent unassigned" in titles


def test_viewer_dashboard_returns_empty_lists_but_valid_stats(client, seeded):
    viewer = login(client, "viewer@test.local", "viewer123")
    d = client.get("/dashboard", headers=auth(viewer)).json()
    # Viewer has no actions; lists should be empty but stats may show team counts.
    assert d["assigned_to_me"] == []
    assert d["awaiting_my_approval"] == []
