"""Tests: optimistic locking — stale-version updates are rejected with 409."""
from .conftest import login, auth


def test_stale_version_rejected(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    create = client.post(
        "/items",
        json={"title": "Lock test", "type": "task", "priority": "medium",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    )
    item = create.json()
    original_version = item["version"]

    # First update succeeds.
    patch1 = client.patch(
        f"/items/{item['id']}",
        json={"title": "Updated once", "version": original_version},
        headers=auth(lead),
    )
    assert patch1.status_code == 200
    assert patch1.json()["version"] == original_version + 1

    # Second update with the original (now stale) version fails.
    patch2 = client.patch(
        f"/items/{item['id']}",
        json={"title": "Stale update", "version": original_version},
        headers=auth(lead),
    )
    assert patch2.status_code == 409
    assert "Stale version" in patch2.json()["detail"]


def test_stale_version_response_includes_current_version(client, seeded):
    lead = login(client, "lead@test.local", "lead123")
    item = client.post(
        "/items",
        json={"title": "Version check", "type": "task", "priority": "low",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    ).json()

    # Advance the version once.
    client.patch(
        f"/items/{item['id']}",
        json={"title": "Advanced", "version": item["version"]},
        headers=auth(lead),
    )

    # Now try the stale update and check the current version is in the message.
    r = client.patch(
        f"/items/{item['id']}",
        json={"title": "Stale", "version": item["version"]},
        headers=auth(lead),
    )
    assert r.status_code == 409
    assert "version 2" in r.json()["detail"]


def test_version_increments_on_transition(client, seeded):
    """Transitions also bump the version, so a stale edit after a transition is caught."""
    lead = login(client, "lead@test.local", "lead123")
    item = client.post(
        "/items",
        json={"title": "Trans-version check", "type": "incident", "priority": "high",
              "team_id": seeded["ops_team"].id},
        headers=auth(lead),
    ).json()
    v0 = item["version"]
    client.post(
        f"/items/{item['id']}/transition",
        json={"target_status": "in_progress"},
        headers=auth(lead),
    )
    # Now patch with old version -> 409
    r = client.patch(
        f"/items/{item['id']}",
        json={"title": "Stale after transition", "version": v0},
        headers=auth(lead),
    )
    assert r.status_code == 409
