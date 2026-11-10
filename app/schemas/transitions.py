"""Transition sessions, locks, optimization and frontier schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.common import DISCLAIMER, AnalyticsPayload, Schema

BudgetModeIn = Literal["net_gain", "tax", "none"]


class TransitionCreate(Schema):
    client_id: str = Field(examples=["cli_009"])
    account_id: str = Field(examples=["acc_017"])


class TransitionOut(Schema):
    transition_id: str
    client_id: str
    account_id: str
    state: str
    target_model_id: str | None
    locked_lot_ids: list[str] = Field(description="Locks set in this transition")
    account_locked_lot_ids: list[str] = Field(description="Locked on the account (always held)")
    has_optimization: bool
    has_frontier: bool
    created_at: datetime
    updated_at: datetime


class LocksRequest(Schema):
    lot_ids: list[str] = Field(default_factory=list, max_length=5000)


class Constraints(Schema):
    min_cash_buffer: float = Field(0.005, ge=0, le=0.2)
    transaction_cost_bps: float = Field(5.0, ge=0, le=100)
    turnover_penalty: float = Field(0.0, ge=0, le=1)
    min_trade_value: float = Field(0.0, ge=0)
    max_names: int | None = Field(None, ge=1, le=1000)
    max_weight: float | None = Field(None, gt=0, le=1)
    sector_band: float | None = Field(None, gt=0, le=1)
    round_shares: bool = True
    lot_relief: Literal["optimizer", "tax_optimal", "hifo"] = "optimizer"


class OptimizeRequest(Schema):
    budget_mode: BudgetModeIn = Field("tax", examples=["tax"])
    budget_value: float | None = Field(
        None, ge=0, description="USD. Ignored when budget_mode='none'.", examples=[20000]
    )
    constraints: Constraints = Field(default_factory=Constraints)
    target_model_id: str | None = Field(
        None, description="Defaults to the transition's chosen target, then the account's target"
    )
    glide_path_budgets: list[float] | None = Field(
        None,
        min_length=1,
        max_length=3,
        description="Optional annual budgets (same mode) to split the transition over 1–3 years",
    )


class FrontierRequest(Schema):
    n_points: int = Field(15, ge=3, le=25)
    budget_mode: Literal["net_gain", "tax"] = "tax"
    constraints: Constraints = Field(default_factory=Constraints)
    target_model_id: str | None = None


class LotSellOut(Schema):
    lot_id: str
    lot_ref: str | None = Field(None, description="Lot ID shown to people (see LotOut.lot_ref)")
    ticker: str
    shares: float
    price: float
    proceeds: float
    cost_basis: float
    realized_gain: float
    term: str
    acquired_date: date


class BuyOut(Schema):
    ticker: str
    shares: float
    price: float
    value: float


class Trades(Schema):
    sells: list[LotSellOut]
    buys: list[BuyOut]


class TradeSummary(Schema):
    n_lot_sells: int
    n_buys: int
    proceeds: float
    purchases: float
    turnover: float
    cash_before: float
    cash_after: float
    total_value: float


class RealizedSummary(Schema):
    st_gain: float
    st_loss: float
    lt_gain: float
    lt_loss: float
    net_gain: float
    est_tax: float = Field(description="Exact tax after ST/LT netting at the household's rates")
    budget_used_pct: float | None


class PortfolioSnapshot(Schema):
    te: float
    n_holdings: int
    dividend_yield: float
    beta: float
    sector_active: dict[str, float] = Field(description="Look-through sector weight − target")
    factor_active: dict[str, float]


class TEContributionOut(Schema):
    ticker: str
    active_weight: float
    te_contribution: float = Field(description="Contributions sum to the residual TE")
    reason: Literal["locked", "wash_sale", "budget", "underweight", "other"]


class Diagnostics(Schema):
    solver: str
    status: str
    solve_ms: float
    binding_constraints: list[str]
    relaxations: list[str]
    notes: list[str]
    explanation: list[str] = Field(description="Plain-English reasons the residual TE is not 0")
    te_contributions: list[TEContributionOut]
    wash_blocked_lot_ids: list[str]
    lot_relief_check: dict[str, float]


class GlideYearOut(Schema):
    year: int
    budget: float
    est_tax: float
    net_gain: float
    te_after: float
    n_trades: int


class OptimizationResult(AnalyticsPayload):
    transition_id: str
    account_id: str
    target_model_id: str
    as_of: date
    taxable: bool
    budget_mode: BudgetModeIn
    budget_value: float | None
    constraints: Constraints
    trades: Trades
    summary: TradeSummary
    realized: RealizedSummary
    pre: PortfolioSnapshot
    post: PortfolioSnapshot
    glide_path: list[GlideYearOut] | None = None
    diagnostics: Diagnostics
    disclaimer: str = DISCLAIMER

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "data_source": "mock_random",
                    "transition_id": "trn_1a2b3c4d",
                    "account_id": "acc_017",
                    "target_model_id": "SCHWAB-TR",
                    "as_of": "2026-10-30",
                    "taxable": True,
                    "budget_mode": "tax",
                    "budget_value": 25000,
                    "constraints": {"min_cash_buffer": 0.005},
                    "trades": {
                        "sells": [
                            {
                                "lot_id": "lot_001650",
                                "ticker": "BPC",
                                "shares": 12.5,
                                "price": 494.62,
                                "proceeds": 6182.75,
                                "cost_basis": 4129.7,
                                "realized_gain": 2053.05,
                                "term": "LT",
                                "acquired_date": "2019-03-14",
                            }
                        ],
                        "buys": [
                            {"ticker": "SCHX", "shares": 7081, "price": 27.22, "value": 192744.82}
                        ],
                    },
                    "summary": {
                        "n_lot_sells": 47,
                        "n_buys": 3,
                        "proceeds": 1410000.0,
                        "purchases": 1396000.0,
                        "turnover": 0.51,
                        "cash_before": 98000.0,
                        "cash_after": 13800.0,
                        "total_value": 2750000.0,
                    },
                    "realized": {
                        "st_gain": 3100.0,
                        "st_loss": 21500.0,
                        "lt_gain": 168000.0,
                        "lt_loss": 61000.0,
                        "net_gain": 88600.0,
                        "est_tax": 24999.77,
                        "budget_used_pct": 99.99,
                    },
                    "pre": {
                        "te": 0.0853,
                        "n_holdings": 38,
                        "dividend_yield": 0.019,
                        "beta": 1.04,
                        "sector_active": {"Financials": 0.06},
                        "factor_active": {"value": 0.12},
                    },
                    "post": {
                        "te": 0.0415,
                        "n_holdings": 12,
                        "dividend_yield": 0.017,
                        "beta": 1.06,
                        "sector_active": {"Financials": 0.02},
                        "factor_active": {"value": 0.04},
                    },
                    "glide_path": None,
                    "diagnostics": {
                        "solver": "CLARABEL",
                        "status": "optimal",
                        "solve_ms": 24.0,
                        "binding_constraints": ["tax budget", "cash buffer", "locked lots"],
                        "relaxations": [],
                        "notes": [],
                        "explanation": [
                            "Locked lots in JUP contribute 2.93% of the 4.15% residual TE."
                        ],
                        "te_contributions": [
                            {
                                "ticker": "JUP",
                                "active_weight": 0.104,
                                "te_contribution": 0.0293,
                                "reason": "locked",
                            }
                        ],
                        "wash_blocked_lot_ids": [],
                        "lot_relief_check": {"optimizer_tax": 24999.77},
                    },
                    "disclaimer": DISCLAIMER,
                }
            ]
        },
    )


class FrontierPointOut(Schema):
    budget: float
    est_tax: float
    net_gain: float
    te: float
    turnover: float


class FrontierResult(AnalyticsPayload):
    transition_id: str
    target_model_id: str
    budget_mode: Literal["net_gain", "tax"]
    max_budget: float = Field(description="Budget needed for the full (unconstrained) transition")
    te_before: float
    points: list[FrontierPointOut]
    chosen_index: int | None = Field(
        None, description="Point closest to the last optimization's budget, if any"
    )
    disclaimer: str = DISCLAIMER
