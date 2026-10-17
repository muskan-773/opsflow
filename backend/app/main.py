"""OpsFlow FastAPI application entry point.

Run with:
  cd backend && uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routes import auth, work_items, dashboard

app = FastAPI(
    title="OpsFlow — Operations Under Pressure",
    description=(
        "Internal operations management API. "
        "Work items, team-based roles, atomic claiming, optimistic locking, "
        "idempotency, workflow enforcement, and append-only activity history."
    ),
    version="1.0.0",
    contact={"name": "Muskan Kumari"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Current-Version"],
)

app.include_router(auth.router)
app.include_router(work_items.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def on_startup():
    """Create tables on startup. Retries briefly so the backend can boot
    before Postgres is fully ready in docker-compose."""
    import time
    last_err = None
    for _ in range(15):
        try:
            init_db()
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2)
    raise RuntimeError(f"Could not initialize database: {last_err}")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "opsflow-api"}
