"""pytest configuration: test database, isolated session, seeded users.

Tests run against a dedicated ``opsflow_test`` database. Each test function
gets a fresh session via a transaction that is rolled back after the test,
so tests are order-independent and don't leave junk in the DB.

The FastAPI app's ``get_db`` dependency is overridden with the test session
factory so every request in a TestClient uses the same transaction.
"""
from __future__ import annotations

import os
import pytest
import bcrypt

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Point at the test database BEFORE importing app code that reads settings.
TEST_DB = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://opsflow:opsflowdev@localhost:5432/opsflow_test",
)
os.environ.setdefault("DATABASE_URL", TEST_DB)
os.environ["DATABASE_URL"] = TEST_DB

from app.database import Base, get_db
from app.main import app
from app import models

engine = create_engine(TEST_DB, pool_pre_ping=True, future=True)
TestSessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed(db: Session):
    """Insert the minimal set of users, teams and memberships needed by tests."""
    ops = models.Team(name="Operations", description="ops")
    pay = models.Team(name="Payments", description="pay")
    db.add_all([ops, pay])
    db.flush()

    admin = models.User(name="Admin User", email="admin@test.local", password_hash=_hash("admin123"), is_admin=True)
    lead = models.User(name="Lead User", email="lead@test.local", password_hash=_hash("lead123"), is_admin=False)
    member = models.User(name="Member User", email="member@test.local", password_hash=_hash("member123"), is_admin=False)
    viewer = models.User(name="Viewer User", email="viewer@test.local", password_hash=_hash("viewer123"), is_admin=False)
    other = models.User(name="Other Team User", email="other@test.local", password_hash=_hash("other123"), is_admin=False)
    db.add_all([admin, lead, member, viewer, other])
    db.flush()

    db.add_all([
        models.Membership(user_id=lead.id, team_id=ops.id, role="lead"),
        models.Membership(user_id=member.id, team_id=ops.id, role="member"),
        models.Membership(user_id=viewer.id, team_id=ops.id, role="viewer"),
        models.Membership(user_id=other.id, team_id=pay.id, role="member"),
    ])
    db.flush()

    return {
        "ops_team": ops, "pay_team": pay,
        "admin": admin, "lead": lead, "member": member,
        "viewer": viewer, "other": other,
    }


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create tables once per test session."""
    _setup_db()
    yield
    # leave tables for debugging; they'll be dropped on next run


@pytest.fixture(scope="function")
def db():
    """Yield a session whose transaction is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestSessionFactory(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def seeded(db):
    """Seed minimal test data and return references."""
    data = _seed(db)
    return data


def _override_get_db_for(session: Session):
    def _get_test_db():
        try:
            yield session
        finally:
            pass
    return _get_test_db


@pytest.fixture(scope="function")
def client(db, seeded):
    """FastAPI TestClient backed by the rolled-back test session."""
    app.dependency_overrides[get_db] = _override_get_db_for(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# Test login and auth helpers
def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}
