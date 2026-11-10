"""Account detail and management-event schemas."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from app.schemas.clients import AccountSummary
from app.schemas.common import AnalyticsPayload, Schema


class LotOut(Schema):
    lot_id: str = Field(description="Internal id (used by the API, e.g. for locks)")
    lot_ref: str | None = Field(
        None, description="Lot ID shown to people (statement lot number), unique in the account"
    )
    account_id: str
    ticker: str
    quantity: float
    cost_basis_total: float
    acquired_date: date
    holding_period: str = Field(description='"ST" (≤ 1 year) or "LT"')
    current_price: float
    market_value: float
    unrealized_gain: float
    locked: bool
    source: str
    basis_unknown: bool = False


class HoldingOut(Schema):
    ticker: str
    name: str
    sector: str
    quantity: float
    price: float
    market_value: float
    weight: float
    target_weight: float
    cost_basis_total: float
    unrealized_gain: float
    n_lots: int
    locked: bool = Field(description="True if any lot of this position is locked")


class UnrealizedSplit(Schema):
    st_gains: float
    st_losses: float
    lt_gains: float
    lt_losses: float
    net: float


class AccountDetail(AnalyticsPayload):
    account: AccountSummary
    client_name: str
    unrealized: UnrealizedSplit
    holdings: list[HoldingOut]
    lots: list[LotOut]


class TradeOut(Schema):
    ticker: str
    side: str
    shares: float
    price: float
    value: float
    realized_gain: float
    term: str | None


class EventOut(Schema):
    id: str
    account_id: str
    account_nickname: str | None
    date: date
    type: str
    trigger: str
    n_trades: int
    turnover: float
    realized_st_gain: float
    realized_lt_gain: float
    losses_harvested: float
    est_taxes_saved: float
    te_before: float
    te_after: float
    cash_flow_amount: float
    note: str


class EventList(Schema):
    total: int
    items: list[EventOut]


class EventDetail(EventOut):
    client_id: str
    trades: list[TradeOut]
