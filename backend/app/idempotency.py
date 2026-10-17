"""Idempotency-key handling.

For a create request that carries an ``Idempotency-Key`` header:
  * If the key already exists, return the stored response (same body + status).
    If the request payload differs from the first one, reject with 422
    (mismatched reuse of a key) to avoid silently returning the wrong result.
  * Otherwise, process the request, then store the key + response in the same
    transaction as the create. A repeated key after commit returns the stored
    response, so double-clicks or retries never create a duplicate.

The key is scoped to the user: two different users reusing the same key would
both store separate rows. (For this app a user-owned key is sufficient; a
global key would require a separate user_id column in the lookup — it has
one.)
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def _hash_request(body: Optional[bytes]) -> Optional[str]:
    if body is None:
        return None
    return hashlib.sha256(body).hexdigest()


def get_existing(
    db: Session, key: str, user_id: int
) -> Optional[models.IdempotencyKey]:
    return db.get(models.IdempotencyKey, key)


def store(
    db: Session,
    key: str,
    user_id: int,
    request_body: Optional[bytes],
    response_body: str,
    status_code: int,
) -> models.IdempotencyKey:
    record = models.IdempotencyKey(
        key=key,
        user_id=user_id,
        request_hash=_hash_request(request_body),
        response_body=response_body,
        status_code=status_code,
    )
    db.add(record)
    db.flush()
    return record


def request_hash_matches(record: models.IdempotencyKey, request_body: Optional[bytes]) -> bool:
    """True if the new request hash equals the stored one (or both None)."""
    new_hash = _hash_request(request_body)
    return (record.request_hash or None) == (new_hash or None)
