"""Auth routes: login and current-user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import create_access_token, get_current_user, verify_password
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_with_memberships(user: models.User, db: Session) -> schemas.UserOut:
    mems = []
    for m in user.memberships:
        team = db.get(models.Team, m.team_id)
        mems.append(
            schemas.MembershipOut(
                team_id=m.team_id, team_name=team.name if team else "", role=m.role
            )
        )
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        memberships=mems,
    )


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated.")
    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(access_token=token, user=_user_with_memberships(user, db))


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_with_memberships(current_user, db)
