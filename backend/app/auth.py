"""JWT authentication and password utilities for OpsFlow.

Design decisions:
* Passwords are hashed with ``bcrypt`` directly (no passlib wrapper) because
  passlib 1.7.x is incompatible with bcrypt >= 4.0 (``__about__`` attribute
  removed). Using the library directly removes the middle-man.
* JWTs use python-jose with HS256. The secret is never committed; it lives in
  .env only.
* ``get_current_user`` is a FastAPI dependency — any route that includes it
  gets a validated User model or an HTTP 401.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from . import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain``."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches ``hashed``."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(payload: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Encode a JWT with an expiry claim."""
    to_encode = payload.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT; raise JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """FastAPI dependency: return the authenticated User or raise 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.get(models.User, int(user_id))
    if user is None or not user.is_active:
        raise credentials_exception
    return user
