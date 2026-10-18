#!/usr/bin/env python3
"""Seed script: creates tables, teams, demo users and sample work items.

Run from the backend directory:
  python seed.py

Safe to run multiple times: existing rows are skipped via upsert-or-ignore.
Passwords are bcrypt-hashed.
"""
from __future__ import annotations

import sys
import os
import random
from datetime import date, timedelta

# Resolve app imports from the backend directory.
sys.path.insert(0, os.path.dirname(__file__))

import bcrypt
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, init_db
from app import models

TEAMS = [
    {"name": "Operations", "description": "Core ops team handling incidents and compliance."},
    {"name": "Payments", "description": "Payment processing and reconciliation team."},
    {"name": "Support", "description": "Customer-facing support and issue resolution."},
]

USERS = [
    # name, email, password, is_admin, memberships: [(team_name, role)]
    {
        "name": "Muskan Admin",
        "email": "admin@opsflow.demo",
        "password": "admin123",
        "is_admin": True,
        "memberships": [("Operations", "lead"), ("Payments", "lead"), ("Support", "lead")],
    },
    {
        "name": "Aryan Lead",
        "email": "lead.ops@opsflow.demo",
        "password": "lead123",
        "is_admin": False,
        "memberships": [("Operations", "lead")],
    },
    {
        "name": "Priya Lead",
        "email": "lead.pay@opsflow.demo",
        "password": "lead123",
        "is_admin": False,
        "memberships": [("Payments", "lead")],
    },
    {
        "name": "Rahul Member",
        "email": "member.ops@opsflow.demo",
        "password": "member123",
        "is_admin": False,
        "memberships": [("Operations", "member")],
    },
    {
        "name": "Sneha Member",
        "email": "member.pay@opsflow.demo",
        "password": "member123",
        "is_admin": False,
        "memberships": [("Payments", "member")],
    },
    {
        "name": "Kunal Member",
        "email": "member.sup@opsflow.demo",
        "password": "member123",
        "is_admin": False,
        "memberships": [("Support", "member"), ("Operations", "member")],
    },
    {
        "name": "Divya Viewer",
        "email": "viewer.ops@opsflow.demo",
        "password": "viewer123",
        "is_admin": False,
        "memberships": [("Operations", "viewer")],
    },
    {
        "name": "Ankit Lead Support",
        "email": "lead.sup@opsflow.demo",
        "password": "lead123",
        "is_admin": False,
        "memberships": [("Support", "lead")],
    },
]


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


ITEM_TEMPLATES = [
    # (title, type, priority)
    ("Production database latency spike", "incident", "critical"),
    ("Payment gateway timeout", "payment", "critical"),
    ("Customer data export compliance check", "compliance", "high"),
    ("Third-party API rate limit hit", "incident", "high"),
    ("Onboarding flow broken for new signups", "customer_issue", "high"),
    ("Billing invoice generation error", "payment", "high"),
    ("Monthly GDPR audit report", "compliance", "medium"),
    ("Password reset email not delivered", "customer_issue", "medium"),
    ("Internal dashboard slow on mobile", "task", "medium"),
    ("Log rotation cron job missing", "task", "medium"),
    ("Update SSL certificates — expires next month", "task", "high"),
    ("Database backup verification failed", "incident", "critical"),
    ("Refund webhook not retrying on timeout", "payment", "high"),
    ("User reported unauthorized charge", "customer_issue", "critical"),
    ("Missing index on work_items.team_id", "task", "low"),
    ("Add rate-limiting to public API endpoints", "task", "medium"),
    ("Investigate spike in 500 errors on /checkout", "incident", "critical"),
    ("PCI-DSS quarterly penetration test", "compliance", "high"),
    ("Onboarding email template outdated", "customer_issue", "low"),
    ("Archive closed items older than 90 days", "task", "low"),
]

STATUSES = ["open", "in_progress", "awaiting_approval", "resolved", "closed"]


def main():
    print("[seed] Initializing database tables...")
    init_db()

    db = SessionLocal()
    try:
        # Teams
        print("[seed] Seeding teams...")
        team_map: dict[str, models.Team] = {}
        for td in TEAMS:
            t = db.query(models.Team).filter(models.Team.name == td["name"]).first()
            if t is None:
                t = models.Team(name=td["name"], description=td["description"])
                db.add(t)
                db.flush()
                print(f"   + Team: {t.name}")
            team_map[t.name] = t

        # Users
        print("[seed] Seeding users...")
        user_map: dict[str, models.User] = {}
        for ud in USERS:
            u = db.query(models.User).filter(models.User.email == ud["email"]).first()
            if u is None:
                u = models.User(
                    name=ud["name"],
                    email=ud["email"],
                    password_hash=_hash(ud["password"]),
                    is_admin=ud["is_admin"],
                )
                db.add(u)
                db.flush()
                print(f"   + User: {u.email} ({'admin' if u.is_admin else 'regular'})")
            user_map[u.email] = u

            # Memberships
            for team_name, role in ud["memberships"]:
                team = team_map.get(team_name)
                if not team:
                    continue
                existing_mem = (
                    db.query(models.Membership)
                    .filter(models.Membership.user_id == u.id, models.Membership.team_id == team.id)
                    .first()
                )
                if existing_mem is None:
                    db.add(models.Membership(user_id=u.id, team_id=team.id, role=role))

        db.flush()

        # Work items
        existing_count = db.query(models.WorkItem).count()
        if existing_count < 5:
            print("[seed] Seeding initial work items...")
            team_names = list(team_map.keys())
            member_emails = [e for e in user_map if "member" in e or "lead" in e or "admin" in e]
            creators = [user_map[e] for e in member_emails]

            for i, (title, wtype, prio) in enumerate(ITEM_TEMPLATES):
                team = team_map[team_names[i % len(team_names)]]
                creator = creators[i % len(creators)]
                assignee = None
                if i % 3 != 0:
                    candidates = [
                        user_map[e] for e in member_emails
                        if any(m.team_id == team.id for m in user_map[e].memberships)
                    ]
                    if candidates:
                        assignee = candidates[i % len(candidates)]

                status_val = STATUSES[i % len(STATUSES)]
                due = date.today() + timedelta(days=random.randint(-5, 30))
                item = models.WorkItem(
                    title=title,
                    description=f"Sample item generated during seeding. "
                                f"This is a {wtype} with {prio} priority.",
                    type=wtype,
                    priority=prio,
                    status=status_val,
                    team_id=team.id,
                    assignee_id=assignee.id if assignee else None,
                    creator_id=creator.id,
                    due_date=due,
                    version=1,
                )
                db.add(item)
                db.flush()
                db.add(
                    models.ActivityEvent(
                        work_item_id=item.id,
                        actor_id=creator.id,
                        event_type="created",
                        field="status",
                        old_value=None,
                        new_value="open",
                    )
                )
                if status_val != "open":
                    db.add(
                        models.ActivityEvent(
                            work_item_id=item.id,
                            actor_id=creator.id,
                            event_type="status_changed",
                            field="status",
                            old_value="open",
                            new_value=status_val,
                        )
                    )

            print(f"   + {len(ITEM_TEMPLATES)} work items created.")
        else:
            print(f"   [skip] Work item seed skipped ({existing_count} items already present).")

        db.commit()
        print("\n[seed] Seed completed successfully.")
        print("\nDemo credentials:")
        print("  Admin:  admin@opsflow.demo     / admin123")
        print("  Lead:   lead.ops@opsflow.demo  / lead123")
        print("  Lead:   lead.pay@opsflow.demo  / lead123")
        print("  Member: member.ops@opsflow.demo / member123")
        print("  Viewer: viewer.ops@opsflow.demo / viewer123")

    except Exception as e:
        db.rollback()
        print(f"\n[seed] Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
