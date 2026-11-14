"""Vendor-neutral inputs and outputs for point-in-time portfolio analytics.

Weights are decimals of total market value (cash included). Risk numbers are decimals too:
``volatility = 0.15`` means a 15% annualised standard deviation; VaR / CVaR are positive losses.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- inputs
class Position(BaseModel):
    ticker: str
    market_value: float


class Portfolio(BaseModel):
    """What to analyse: positions (stocks or funds) plus cash, valued at the provider's prices."""

    id: str
    name: str
    positions: list[Position]
    cash: float = 0.0

    @property
    def market_value(self) -> float:
        return sum(p.market_value for p in self.positions) + self.cash


class SecurityRef(BaseModel):
    """Reference data for one security (security master)."""

    ticker: str
    name: str
    asset_class: str
    sector: str  # GICS sector
    country: str
    region: str
    size: str = ""  # Large / Mid / Small (equities)
    is_fund: bool = False


# --------------------------------------------------------------------------- outputs
class Slice(BaseModel):
    name: str
    weight: float
    market_value: float
    group: str = ""  # asset allocation: Equity / Fixed Income / Preferred / Cash


class CountrySlice(Slice):
    region: str


class FactorContribution(BaseModel):
    factor: str
    exposure: float | None  # portfolio factor loading (None for grouped / specific rows)
    pct_of_variance: float  # share of total variance (sums to 1; may be negative = diversifier)
    vol_contribution: float  # pct_of_variance × volatility


class TailRisk(BaseModel):
    horizon: str
    days: int
    confidence: float
    var: float
    cvar: float
    var_usd: float
    cvar_usd: float


class HistBin(BaseModel):
    x0: float
    x1: float
    count: int


class StressResult(BaseModel):
    name: str
    description: str
    pnl_pct: float
    pnl_usd: float


class RiskContributor(BaseModel):
    ticker: str
    name: str
    weight: float
    pct_of_risk: float


class AccountRisk(BaseModel):
    account_id: str
    label: str
    market_value: float
    volatility: float
    beta: float
    var_95_1d: float
    var_95_1d_usd: float


class RiskReport(BaseModel):
    scope: Literal["book", "client", "account"]
    scope_id: str
    name: str
    as_of: date
    generated_at: datetime
    data_source: str  # "mock" | "aladdin" | "bloomberg"
    source_label: str
    methodology: list[str] = Field(default_factory=list)

    market_value: float
    cash_weight: float
    n_positions: int
    n_underlying: int  # look-through securities

    asset_allocation: list[Slice]
    sectors: list[Slice]
    regions: list[Slice]
    countries: list[CountrySlice]

    volatility: float  # ex-ante, factor model, annualised
    realized_volatility: float  # historical, annualised
    beta: float
    systematic_pct: float
    specific_pct: float
    decomposition: list[FactorContribution]
    sector_factor_detail: list[FactorContribution]

    tail: list[TailRisk]
    return_histogram: list[HistBin]
    stress_tests: list[StressResult]
    top_contributors: list[RiskContributor]
    top10_weight: float
    effective_n: float
    accounts: list[AccountRisk] = Field(default_factory=list)
