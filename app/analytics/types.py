"""Provider-neutral input/output types for analytics.

Inputs describe *what* to analyse (an account, a model); outputs are plain dataclasses that the
service layer serialises. Nothing here reveals whether numbers are simulated or real, except the
``data_source`` tag that every provider exposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

import numpy as np
import numpy.typing as npt

Mat = npt.NDArray[np.float64]


class Granularity(StrEnum):
    MONTH = "month"
    YEAR = "year"


def period_key(d: date, granularity: Granularity) -> str:
    """'YYYY-MM' for monthly buckets, 'YYYY' for yearly buckets."""
    return f"{d.year:04d}-{d.month:02d}" if granularity is Granularity.MONTH else f"{d.year:04d}"


def period_range(start: date, end: date, granularity: Granularity) -> list[str]:
    """All period keys from ``start`` to ``end`` inclusive (so charts have no gaps)."""
    keys: list[str] = []
    if granularity is Granularity.YEAR:
        return [f"{y:04d}" for y in range(start.year, end.year + 1)]
    y, mth = start.year, start.month
    while (y, mth) <= (end.year, end.month):
        keys.append(f"{y:04d}-{mth:02d}")
        mth += 1
        if mth == 13:
            y, mth = y + 1, 1
    return keys


# --------------------------------------------------------------------------- inputs
@dataclass(frozen=True, slots=True)
class EventInput:
    event_id: str
    event_date: date
    event_type: str
    te_before: float
    te_after: float
    realized_st_gain: float
    realized_lt_gain: float
    losses_harvested: float
    est_taxes_saved: float
    turnover: float
    cash_flow_amount: float
    realized_st_loss: float = 0.0  # ST part of losses_harvested (positive number)
    realized_lt_loss: float = 0.0  # LT part of losses_harvested (positive number)


@dataclass(frozen=True, slots=True)
class LotInput:
    lot_id: str
    ticker: str
    quantity: float
    cost_basis_total: float
    acquired_date: date
    locked: bool


@dataclass(frozen=True, slots=True)
class AccountContext:
    """Everything a provider may need to analyse one account."""

    account_id: str
    onboarding_date: date
    as_of: date
    cash: float
    taxable: bool
    st_rate: float
    lt_rate: float
    drift_tolerance_te: float
    lots: tuple[LotInput, ...]
    events: tuple[EventInput, ...]  # sorted by date
    target_model_id: str | None
    target_weights: dict[str, float] = field(default_factory=dict)

    def shares(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for lot in self.lots:
            out[lot.ticker] = out.get(lot.ticker, 0.0) + lot.quantity
        return out


# --------------------------------------------------------------------------- outputs
@dataclass(frozen=True, slots=True)
class RiskModel:
    """Annualised covariance (PSD) aligned with ``tickers``, plus the factor decomposition."""

    tickers: tuple[str, ...]
    covariance: Mat
    factor_names: tuple[str, ...]
    loadings: Mat  # n × k
    factor_covariance: Mat  # k × k
    specific_variance: Mat  # n
    # Optional exact structure for sparse optimisation: covariance = E (B F Bᵀ + diag(D)) Eᵀ
    exposure: Mat | None = None  # n × n_base look-through matrix E
    base_loadings: Mat | None = None  # n_base × k  (B)
    base_specific_variance: Mat | None = None  # n_base  (D)


@dataclass(frozen=True, slots=True)
class DatedValue:
    d: date
    value: float


@dataclass(frozen=True, slots=True)
class TrackingErrorHistory:
    window: int
    series: tuple[DatedValue, ...]  # rolling ex-post TE (annualised, decimal)
    ex_ante_te: float | None


@dataclass(frozen=True, slots=True)
class TaxPeriod:
    period: str
    realized_st_gain: float
    realized_lt_gain: float
    losses_harvested: float
    est_tax_paid: float
    est_taxes_saved: float
    realized_st_loss: float = 0.0
    realized_lt_loss: float = 0.0


@dataclass(frozen=True, slots=True)
class SectorExposure:
    sector: str
    portfolio_weight: float
    target_weight: float

    @property
    def active_weight(self) -> float:
        return self.portfolio_weight - self.target_weight


@dataclass(frozen=True, slots=True)
class SecurityExposure:
    ticker: str
    name: str
    sector: str
    portfolio_weight: float
    target_weight: float

    @property
    def active_weight(self) -> float:
        return self.portfolio_weight - self.target_weight


@dataclass(frozen=True, slots=True)
class FactorExposure:
    factor: str
    portfolio: float
    target: float

    @property
    def active(self) -> float:
        return self.portfolio - self.target


@dataclass(frozen=True, slots=True)
class Exposures:
    sectors: tuple[SectorExposure, ...]  # includes a "Cash" row; portfolio weights sum to 1
    top_active: tuple[SecurityExposure, ...]
    factors: tuple[FactorExposure, ...]
    top10_weight: float
    hhi: float
    n_positions: int
    dividend_yield: float
    target_dividend_yield: float | None
    beta: float
    target_beta: float | None


@dataclass(frozen=True, slots=True)
class ModelStats:
    """Historical and characteristic statistics for a model portfolio.

    (Expected TE vs benchmark and fee are catalog attributes, not provider analytics.)
    """

    model_id: str
    annualized_return: float
    volatility: float
    sharpe: float
    max_drawdown: float  # positive number, e.g. 0.22 = −22%
    dividend_yield: float
    beta: float
    n_holdings: int  # direct holdings (e.g. ETFs)
    n_underlying: int  # look-through stocks
    sector_mix: dict[str, float]
    factor_exposures: dict[str, float]
    history_start: date
    history_end: date


@dataclass(frozen=True, slots=True)
class RegimePerformance:
    regime: str
    n_days: int
    annualized_return: float  # arithmetic mean daily return × 252
    volatility: float
