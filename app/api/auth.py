from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.security import create_access_token, verify_password
from app.db import models as m
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(u: m.User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        name=u.name,
        role=u.role,
        advisor_id=u.advisor_id,
        firm=u.advisor.firm,
    )


@router.post("/login", response_model=TokenResponse, summary="Log in (mock JWT auth)")
def login(body: LoginRequest, db: DB) -> TokenResponse:
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower().strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    token = create_access_token(user.id, {"role": user.role, "advisor_id": user.advisor_id})
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
