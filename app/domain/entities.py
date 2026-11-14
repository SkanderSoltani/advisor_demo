"""Pure domain objects: Advisor → Client (household) → Account → Lot, plus models, events and
constraints.

These are framework-free dataclasses used by analytics and the optimizer. The ORM layer
(``app.db.models``) maps to/from them; the API layer (``app.schemas``) serialises them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

LONG_TERM_DAYS = 365  # held MORE than one year → long-term (IRS rule)


class AccountType(StrEnum):
    INDIVIDUAL_TAXABLE = "individual_taxable"
    JOINT_TAXABLE = "joint_taxable"
    TRUST = "trust"
    IRA = "ira"
    ROTH_IRA = "roth_ira"

    @property
    def is_taxable(self) -> bool:
        return self not in (AccountType.IRA, AccountType.ROTH_IRA)


class ClientType(StrEnum):
    INDIVIDUAL = "individual"
    COUPLE = "couple"
    FAMILY = "family"
    TRUST = "trust"


class HoldingPeriod(StrEnum):
    SHORT_TERM = "ST"
    LONG_TERM = "LT"


class LotSource(StrEnum):
    PLAID = "plaid"
    PDF = "pdf"
    SEED = "seed"


class Objective(StrEnum):
    TOTAL_RETURN = "total_return"
    INCOME = "income"
    TAX_EFFICIENT = "tax_efficient"


class Construction(StrEnum):
    MARKET_CAP = "market_cap"
    FUNDAMENTAL = "market_cap_fundamental"
    ACTIVE = "market_cap_fundamental_active"


class EventType(StrEnum):
    TRANSITION = "transition"
    REBALANCE = "rebalance"
    TAX_LOSS_HARVEST = "tax_loss_harvest"
    CASH_FLOW = "cash_flow"
    MODEL_CHANGE = "model_change"


class EventTrigger(StrEnum):
    SCHEDULED = "scheduled"
    DRIFT = "drift"
    HARVEST_OPPORTUNITY = "harvest_opportunity"
    CLIENT_REQUEST = "client_request"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


def holding_period(acquired: date, as_of: date) -> HoldingPeriod:
    """Return ST if held one year or less at ``as_of``, else LT."""
    return (
        HoldingPeriod.LONG_TERM
        if (as_of - acquired).days > LONG_TERM_DAYS
        else HoldingPeriod.SHORT_TERM
    )


@dataclass(frozen=True, slots=True)
class TaxProfile:
    """Household-level tax rates (decimals, e.g. 0.37)."""

    federal_st_rate: float
    federal_lt_rate: float
    state: str
    state_rate: float

    @property
    def st_rate(self) -> float:
        """Combined marginal rate on short-term gains."""
        return self.federal_st_rate + self.state_rate

    @property
    def lt_rate(self) -> float:
        """Combined marginal rate on long-term gains."""
        return self.federal_lt_rate + self.state_rate


@dataclass(frozen=True, slots=True)
class Advisor:
    advisor_id: str
    name: str
    firm: str


@dataclass(slots=True)
class Client:
    client_id: str
    advisor_id: str
    name: str
    client_type: ClientType
    tax_profile: TaxProfile
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class Lot:
    """A single tax lot. Derived fields depend on the price and as-of date supplied."""

    lot_id: str
    account_id: str
    ticker: str
    quantity: float
    cost_basis_total: float
    acquired_date: date
    locked: bool = False
    source: LotSource = LotSource.SEED

    def holding_period(self, as_of: date) -> HoldingPeriod:
        return holding_period(self.acquired_date, as_of)

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_gain(self, price: float) -> float:
        return self.market_value(price) - self.cost_basis_total

    @property
    def cost_per_share(self) -> float:
        return self.cost_basis_total / self.quantity if self.quantity else 0.0


@dataclass(slots=True)
class Account:
    account_id: str
    client_id: str
    account_type: AccountType
    custodian: str
    cash: float
    onboarding_date: date
    target_model_id: str | None = None
    nickname: str | None = None
    drift_tolerance_te: float = 0.015
    lots: list[Lot] = field(default_factory=list)

    def positions(self) -> dict[str, float]:
        """Aggregate lots into total shares per ticker."""
        out: dict[str, float] = {}
        for lot in self.lots:
            out[lot.ticker] = out.get(lot.ticker, 0.0) + lot.quantity
        return out

    def market_value(self, prices: dict[str, float]) -> float:
        """Total value of securities plus cash."""
        return self.cash + sum(lot.market_value(prices[lot.ticker]) for lot in self.lots)


@dataclass(frozen=True, slots=True)
class Position:
    ticker: str
    quantity: float
    market_value: float
    weight: float


@dataclass(slots=True)
class ModelPortfolio:
    model_id: str
    name: str
    objective: Objective
    construction: Construction
    benchmark: str
    weights: dict[str, float]
    description: str = ""
    rationale: str = ""
    target_yield: float = 0.0
    expected_te: float = 0.0
    fee_bps: float = 0.0
    regime_overlay: bool = False


@dataclass(slots=True)
class ManagementEvent:
    event_id: str
    account_id: str
    event_date: date
    event_type: EventType
    trigger: EventTrigger
    n_trades: int
    turnover: float
    realized_st_gain: float
    realized_lt_gain: float
    losses_harvested: float
    est_taxes_saved: float
    te_before: float
    te_after: float
    note: str = ""


@dataclass(frozen=True, slots=True)
class Constraint:
    """Optional optimizer constraints (used from Milestone 4)."""

    min_cash_buffer: float = 0.005
    min_trade_value: float = 0.0
    max_names: int | None = None
    max_weight: float | None = None
    sector_band: float | None = None
    turnover_penalty: float = 0.0
    transaction_cost_bps: float = 5.0
