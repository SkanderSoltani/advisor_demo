"""Shared FastAPI dependencies: auth, provider, service, ownership checks."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.analytics.factory import get_provider
from app.analytics.provider import AnalyticsProvider
from app.core.security import decode_access_token
from app.db import models as m
from app.db.session import get_db
from app.services.portfolio import PortfolioService

bearer = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")

DB = Annotated[Session, Depends(get_db)]
Provider = Annotated[AnalyticsProvider, Depends(get_provider)]


def get_current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> m.User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
    user = db.get(m.User, claims.get("sub"))
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[m.User, Depends(get_current_user)]


def get_service(db: DB, provider: Provider, user: CurrentUser) -> PortfolioService:
    return PortfolioService(db, provider, user.advisor_id)


Service = Annotated[PortfolioService, Depends(get_service)]


def client_or_404(svc: PortfolioService, client_id: str) -> m.Client:
    c = svc.client(client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client {client_id} not found")
    return c


def account_or_404(svc: PortfolioService, account_id: str) -> m.Account:
    a = svc.account(account_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Account {account_id} not found")
    return a


def scoped_accounts(svc: PortfolioService, c: m.Client, account_id: str | None) -> list[m.Account]:
    """Client's accounts, optionally narrowed to one (404 if it isn't the client's)."""
    if account_id is None:
        return list(c.accounts)
    accts = [a for a in c.accounts if a.id == account_id]
    if not accts:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Account {account_id} not found for client {c.id}"
        )
    return accts
