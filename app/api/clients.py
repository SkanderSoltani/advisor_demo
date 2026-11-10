"""Clients (households): list, onboard, detail, edit, accounts, analytics, events."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, select

from app.analytics.types import Granularity as AGranularity
from app.api.deps import DB, Service, client_or_404, scoped_accounts
from app.db import models as m
from app.schemas.accounts import EventList
from app.schemas.analytics import ClientAnalyticsSummary, TaxSavings, TrackingError
from app.schemas.clients import (
    AccountCreate,
    AccountList,
    AccountSummary,
    ClientCreate,
    ClientDetail,
    ClientList,
    ClientOut,
    ClientUpdate,
)
from app.schemas.common import ClientStatus, EventTypeOut, Granularity, TEWindow
from app.services.events import event_out

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=ClientList, summary="Client list with summary rows")
def list_clients(
    svc: Service,
    search: str | None = Query(None, description="Case-insensitive match on name or email"),
    status_: ClientStatus | None = Query(None, alias="status"),
) -> ClientList:
    pairs = svc.client_rows()
    if search:
        needle = search.lower().strip()
        pairs = [(r, e) for r, e in pairs if needle in r.name.lower() or needle in e]
    rows = [r for r, _ in pairs]
    if status_ is not None:
        rows = [r for r in rows if r.status == status_]
    return ClientList(data_source=svc.p.data_source, total=len(rows), items=rows)


@router.post(
    "",
    response_model=ClientOut,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a new client (household)",
)
def create_client(body: ClientCreate, svc: Service, db: DB) -> ClientOut:
    tp = body.tax_profile
    c = m.Client(
        id=f"cli_{uuid.uuid4().hex[:8]}",
        advisor_id=svc.advisor_id,
        name=body.name.strip(),
        email=str(body.email).lower(),
        phone=body.phone,
        client_type=body.client_type,
        notes=body.notes,
        federal_st_rate=tp.federal_st_rate,
        federal_lt_rate=tp.federal_lt_rate,
        state=tp.state.upper(),
        state_rate=tp.state_rate,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return svc.client_out(c)


@router.get("/{client_id}", response_model=ClientDetail, summary="Client detail")
def get_client(client_id: str, svc: Service) -> ClientDetail:
    return svc.client_detail(client_or_404(svc, client_id))


@router.patch("/{client_id}", response_model=ClientOut, summary="Edit profile or tax profile")
def update_client(client_id: str, body: ClientUpdate, svc: Service, db: DB) -> ClientOut:
    c = client_or_404(svc, client_id)
    data = body.model_dump(exclude_unset=True)
    tp = data.pop("tax_profile", None) or {}
    for k, v in data.items():
        if v is None and k in {"name", "client_type"}:
            continue
        setattr(c, k, str(v).lower() if k == "email" and v else v)
    for k, v in tp.items():
        if v is not None:
            setattr(c, k, v.upper() if k == "state" else v)
    db.commit()
    db.refresh(c)
    return svc.client_out(c)


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a client with all its accounts, lots and history",
)
def delete_client(client_id: str, svc: Service, db: DB) -> None:
    """Permanently removes the household (accounts, lots, management events and any transition
    in progress). The book file is rewritten without it."""
    c = client_or_404(svc, client_id)
    account_ids = [a.id for a in c.accounts]
    if account_ids:
        db.execute(delete(m.Transition).where(m.Transition.account_id.in_(account_ids)))
    db.delete(c)
    db.commit()


@router.get("/{client_id}/accounts", response_model=AccountList, summary="Client's accounts")
def list_accounts(client_id: str, svc: Service) -> AccountList:
    c = client_or_404(svc, client_id)
    return AccountList(
        data_source=svc.p.data_source, items=[svc.account_summary(a) for a in c.accounts]
    )


@router.post(
    "/{client_id}/accounts",
    response_model=AccountSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Add an account (starts with no holdings)",
)
def create_account(client_id: str, body: AccountCreate, svc: Service, db: DB) -> AccountSummary:
    c = client_or_404(svc, client_id)
    if body.target_model_id is not None and db.get(m.ModelPortfolio, body.target_model_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown model {body.target_model_id}"
        )
    a = m.Account(
        id=f"acc_{uuid.uuid4().hex[:8]}",
        client_id=c.id,
        account_type=body.account_type,
        custodian=body.custodian,
        nickname=body.nickname,
        target_model_id=body.target_model_id,
        cash=0.0,
        onboarding_date=svc.as_of,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return svc.account_summary(a)


# ------------------------------------------------------------------ analytics
@router.get(
    "/{client_id}/analytics/tracking-error",
    response_model=TrackingError,
    summary="Rolling TE to target (value-weighted across accounts), with event markers",
)
def client_te(
    client_id: str,
    svc: Service,
    window: TEWindow = Query(TEWindow.d63),
    account_id: str | None = None,
) -> TrackingError:
    c = client_or_404(svc, client_id)
    return svc.tracking_error(scoped_accounts(svc, c, account_id), window, account_id)


@router.get(
    "/{client_id}/analytics/tax-savings",
    response_model=TaxSavings,
    summary="Estimated taxes saved per period, plus cumulative since inception",
)
def client_tax(
    client_id: str,
    svc: Service,
    granularity: Granularity = Granularity.month,
    account_id: str | None = None,
) -> TaxSavings:
    c = client_or_404(svc, client_id)
    return svc.tax_savings(
        scoped_accounts(svc, c, account_id), AGranularity(granularity.value), account_id
    )


@router.get(
    "/{client_id}/analytics/summary",
    response_model=ClientAnalyticsSummary,
    summary="AUM over time and per-year realized gains, losses, rebalances and turnover",
)
def client_summary(
    client_id: str, svc: Service, account_id: str | None = None
) -> ClientAnalyticsSummary:
    c = client_or_404(svc, client_id)
    return svc.client_summary(scoped_accounts(svc, c, account_id), account_id)


# ------------------------------------------------------------------ events
@router.get("/{client_id}/events", response_model=EventList, summary="Management event timeline")
def client_events(
    client_id: str,
    svc: Service,
    db: DB,
    type_: EventTypeOut | None = Query(None, alias="type"),
    account_id: str | None = None,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
) -> EventList:
    c = client_or_404(svc, client_id)
    ids = [a.id for a in scoped_accounts(svc, c, account_id)]
    stmt = select(m.ManagementEvent).where(m.ManagementEvent.account_id.in_(ids))
    if type_ is not None:
        stmt = stmt.where(m.ManagementEvent.event_type == type_.value)
    if from_ is not None:
        stmt = stmt.where(m.ManagementEvent.event_date >= from_)
    if to is not None:
        stmt = stmt.where(m.ManagementEvent.event_date <= to)
    stmt = stmt.order_by(m.ManagementEvent.event_date.desc(), m.ManagementEvent.id.desc())
    items = [event_out(e) for e in db.scalars(stmt)]
    return EventList(total=len(items), items=items)
