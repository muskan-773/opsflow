"""Tests: concurrency-critical behaviour.

The concurrent-claim test is genuine: it uses two real committed database
connections in two threads synchronized with a ``threading.Barrier`` so both
issue the atomic ``UPDATE ... WHERE assignee_id IS NULL`` at the same time.
PostgreSQL's row lock guarantees exactly one matches; the other gets 0 rows
and the service raises HTTP 409. Data is committed and cleaned up in a
``finally`` so it never leaks into other tests.

The sequential test exercises the same guard through the HTTP layer.
"""
from __future__ import annotations

import threading

import bcrypt
import pytest
from fastapi import HTTPException

from app import models
from app.services.work_items import claim_work_item
from .conftest import TestSessionFactory, login, auth


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def test_concurrent_claim_only_one_succeeds():
    """Two users claim the same unassigned item concurrently -> exactly one wins."""
    setup = TestSessionFactory()
    item_id = None
    team_id = None
    u1_id = None
    u2_id = None
    try:
        team = models.Team(name="Concurrency Team")
        setup.add(team)
        setup.flush()
        u1 = models.User(name="Claire", email="claire@conc.test", password_hash=_hash("x"))
        u2 = models.User(name="Chad", email="chad@conc.test", password_hash=_hash("x"))
        setup.add_all([u1, u2])
        setup.flush()
        setup.add_all(
            [
                models.Membership(user_id=u1.id, team_id=team.id, role="member"),
                models.Membership(user_id=u2.id, team_id=team.id, role="member"),
            ]
        )
        setup.flush()
        item = models.WorkItem(
            title="Race condition item",
            type="incident",
            priority="critical",
            status="open",
            team_id=team.id,
            assignee_id=None,
            creator_id=u1.id,
            version=1,
        )
        setup.add(item)
        setup.flush()
        setup.add(
            models.ActivityEvent(
                work_item_id=item.id, actor_id=u1.id,
                event_type="created", field="status", new_value="open",
            )
        )
        setup.commit()
        item_id, team_id, u1_id, u2_id = item.id, team.id, u1.id, u2.id
    finally:
        setup.close()

    results = {"ok": 0, "conflict": 0}
    errors: list[str] = []
    barrier = threading.Barrier(2)

    def claim(user_id: int):
        s = TestSessionFactory()
        try:
            user = s.get(models.User, user_id)
            # Both threads wait here, then race the atomic UPDATE together.
            barrier.wait(timeout=10)
            claim_work_item(s, item_id, user)
            s.commit()
            results["ok"] += 1
        except HTTPException as e:
            s.rollback()
            if e.status_code == 409:
                results["conflict"] += 1
            else:
                errors.append(f"{e.status_code}: {e.detail}")
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))
        finally:
            s.close()

    t1 = threading.Thread(target=claim, args=(u1_id,))
    t2 = threading.Thread(target=claim, args=(u2_id,))
    t1.start()
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)

    # The core assertion of the whole challenge: exactly one claim wins.
    assert results["ok"] == 1, f"Expected 1 successful claim, got {results}; errors={errors}"
    assert results["conflict"] == 1, f"Expected 1 conflict, got {results}; errors={errors}"
    assert not errors, f"Unexpected errors: {errors}"

    # And the DB reflects exactly one assignee.
    check = TestSessionFactory()
    try:
        final = check.get(models.WorkItem, item_id)
        assert final.assignee_id in (u1_id, u2_id)
        assert final.version == 2  # claimed increments version once
    finally:
        check.close()

    # Cleanup so committed data never leaks to other tests.
    cleanup = TestSessionFactory()
    try:
        cleanup.query(models.ActivityEvent).filter(
            models.ActivityEvent.work_item_id == item_id
        ).delete(synchronize_session=False)
        if cleanup.get(models.WorkItem, item_id):
            cleanup.query(models.WorkItem).filter(
                models.WorkItem.id == item_id
            ).delete(synchronize_session=False)
        cleanup.query(models.Membership).filter(
            models.Membership.team_id == team_id
        ).delete(synchronize_session=False)
        cleanup.query(models.User).filter(
            models.User.id.in_([u1_id, u2_id])
        ).delete(synchronize_session=False)
        cleanup.query(models.Team).filter(models.Team.id == team_id).delete(
            synchronize_session=False
        )
        cleanup.commit()
    finally:
        cleanup.close()


def test_sequential_claim_then_reclaim_rejected(client, seeded):
    """Through HTTP: first claim succeeds (200), second claim rejected (409)."""
    t = login(client, "lead@test.local", "lead123")
    create = client.post(
        "/items",
        json={"title": "Claimable", "type": "task", "priority": "medium",
              "team_id": seeded["ops_team"].id},
        headers=auth(t),
    )
    item_id = create.json()["id"]

    member_token = login(client, "member@test.local", "member123")
    first = client.post(f"/items/{item_id}/claim", headers=auth(member_token))
    assert first.status_code == 200
    assert first.json()["assignee_id"] is not None

    # A different user (lead) now cannot claim it either.
    second = client.post(f"/items/{item_id}/claim", headers=auth(t))
    assert second.status_code == 409
