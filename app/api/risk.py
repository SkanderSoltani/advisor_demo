"""Point-in-time analytics (allocation, exposures, risk) for the book and each client.

Reports are generated once and saved (see app/risk_analytics/snapshot.py); POST …/refresh
re-generates one on demand.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CurrentUser
from app.db import models as m
from app.risk_analytics.factory import get_risk_provider, get_risk_store
from app.risk_analytics.provider import RiskAnalyticsProvider
from app.risk_analytics.service import RiskAnalyticsService
from app.risk_analytics.snapshot import SnapshotStore
from app.risk_analytics.types import RiskReport

router = APIRouter(tags=["risk analytics"])


def get_risk_service(
    db: DB,
    provider: Annotated[RiskAnalyticsProvider, Depends(get_risk_provider)],
    store: Annotated[SnapshotStore, Depends(get_risk_store)],
) -> RiskAnalyticsService:
    return RiskAnalyticsService(db, provider, store)


RiskService = Annotated[RiskAnalyticsService, Depends(get_risk_service)]


def _run(fn, *args):  # type: ignore[no-untyped-def]
    try:
        return fn(*args)
    except NotImplementedError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _book(svc: RiskAnalyticsService, user: m.User, refresh: bool) -> RiskReport:
    adv = svc.db.get(m.Advisor, user.advisor_id)
    name = adv.name if adv else "Client book"
    return _run(svc.book_report, user.advisor_id, name, refresh)  # type: ignore[no-any-return]


def _client(svc: RiskAnalyticsService, user: m.User, client_id: str, account_id: str | None,
            refresh: bool) -> RiskReport:
    c = svc.db.get(m.Client, client_id)
    if c is None or c.advisor_id != user.advisor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client {client_id} not found")
    if account_id:
        a = next((x for x in c.accounts if x.id == account_id), None)
        if a is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"Account {account_id} not found for client {client_id}")
        return _run(svc.account_report, a, refresh)  # type: ignore[no-any-return]
    return _run(svc.client_report, c, refresh)  # type: ignore[no-any-return]


AccountQ = Query(None, description="Limit to one of the client's accounts")


@router.get("/book/risk", response_model=RiskReport,
            summary="Book allocation, exposures and risk (saved point-in-time snapshot)")
def book_risk(svc: RiskService, user: CurrentUser) -> RiskReport:
    return _book(svc, user, False)


@router.post("/book/risk/refresh", response_model=RiskReport,
             summary="Re-generate the book snapshot")
def book_risk_refresh(svc: RiskService, user: CurrentUser) -> RiskReport:
    return _book(svc, user, True)


@router.get("/clients/{client_id}/risk", response_model=RiskReport,
            summary="Client allocation, exposures and risk (saved point-in-time snapshot)")
def client_risk(client_id: str, svc: RiskService, user: CurrentUser,
                account_id: str | None = AccountQ) -> RiskReport:
    return _client(svc, user, client_id, account_id, False)


@router.post("/clients/{client_id}/risk/refresh", response_model=RiskReport,
             summary="Re-generate the client's snapshot")
def client_risk_refresh(client_id: str, svc: RiskService, user: CurrentUser,
                        account_id: str | None = AccountQ) -> RiskReport:
    return _client(svc, user, client_id, account_id, True)
