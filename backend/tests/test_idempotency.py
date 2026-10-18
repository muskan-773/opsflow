"""Tests: idempotency — repeated key does not create a duplicate."""
from .conftest import login, auth


def _create(client, token, team_id, key=None, title="Idempotent item"):
    headers = auth(token)
    if key:
        headers["Idempotency-Key"] = key
    return client.post(
        "/items",
        json={"title": title, "type": "incident", "priority": "high", "team_id": team_id},
        headers=headers,
    )


def test_repeated_key_creates_one_item(client, seeded):
    t = login(client, "lead@test.local", "lead123")
    team_id = seeded["ops_team"].id

    first = _create(client, t, team_id, key="key-001", title="Unique Idempotent Title")
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = _create(client, t, team_id, key="key-001", title="Unique Idempotent Title")
    assert second.status_code == 201
    assert second.json()["id"] == first_id, "Repeated key must return the same item id"

    # No duplicate: exactly one item with that title in the list.
    listed = client.get("/items?q=Unique+Idempotent", headers=auth(t)).json()
    matching = [i for i in listed["items"] if i["title"] == "Unique Idempotent Title"]
    assert len(matching) == 1, f"Expected 1 item, found {len(matching)}"


def test_different_keys_create_distinct_items(client, seeded):
    t = login(client, "lead@test.local", "lead123")
    team_id = seeded["ops_team"].id

    a = _create(client, t, team_id, key="key-A", title="Item A")
    b = _create(client, t, team_id, key="key-B", title="Item B")
    assert a.json()["id"] != b.json()["id"]


def test_key_reuse_with_different_body_rejected(client, seeded):
    t = login(client, "lead@test.local", "lead123")
    team_id = seeded["ops_team"].id

    first = _create(client, t, team_id, key="key-X", title="Original")
    assert first.status_code == 201

    # Same key but a different body -> 422 (mismatched reuse), not a duplicate.
    second = _create(client, t, team_id, key="key-X", title="Different Body Entirely")
    assert second.status_code == 422
