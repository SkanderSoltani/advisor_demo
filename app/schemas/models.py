"""Model catalog, comparison and regime schemas."""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict, Field

from app.schemas.common import DISCLAIMER, AnalyticsPayload, Schema


class ModelStatsOut(Schema):
    annualized_return: float
    volatility: float
    sharpe: float
    max_drawdown: float = Field(description="Peak-to-trough loss, positive (0.22 = −22%)")
    dividend_yield: float
    beta: float
    n_holdings: int = Field(description="Direct holdings (e.g. ETFs)")
    n_underlying: int = Field(description="Look-through stocks")
    sector_mix: dict[str, float]
    factor_exposures: dict[str, float]
    history_start: date
    history_end: date


class ModelHoldingOut(Schema):
    ticker: str
    name: str
    security_type: str
    asset_class: str | None
    expense_ratio_bps: float
    weight: float


class RegimePerformanceOut(Schema):
    regime: str
    n_days: int
    annualized_return: float
    volatility: float


class ModelSummary(Schema):
    id: str
    name: str
    provider: str
    objective: str
    construction: str
    benchmark: str
    description: str
    rationale: str
    target_yield: float
    expected_te: float = Field(description="Ex-ante TE vs the model's benchmark")
    fee_bps: float = Field(description="Weighted product expense ratio + advisory fee")
    regime_overlay: bool
    stats: ModelStatsOut


class ModelList(AnalyticsPayload):
    total: int
    items: list[ModelSummary]


class ModelDetail(ModelSummary):
    data_source: str = "mock_random"
    holdings: list[ModelHoldingOut]
    regime_performance: list[RegimePerformanceOut] | None = Field(
        None, description="Present when regime labels have been uploaded (/analytics/regimes)"
    )


class CompareRequest(Schema):
    model_ids: list[str] = Field(min_length=1, max_length=6, examples=[["SCHWAB-TR", "SCHWAB-INC"]])
    account_id: str = Field(examples=["acc_017"])


class CurrentPortfolio(Schema):
    account_id: str
    market_value: float
    cash: float
    n_positions: int
    target_model_id: str | None
    dividend_yield: float
    beta: float
    sector_mix: dict[str, float] = Field(description="Look-through, including Cash")
    factor_exposures: dict[str, float]
    unrealized_gain: float
    locked_value: float


class FullTransitionOut(Schema):
    """Reference point: sell/buy everything today to match the model exactly."""

    est_tax: float
    realized_st_gain: float
    realized_st_loss: float
    realized_lt_gain: float
    realized_lt_loss: float
    net_realized_gain: float
    n_lot_sales: int
    n_buys: int
    turnover: float
    locked_value_retained: float = Field(
        description="Value of locked lots above target that cannot be sold"
    )
    post_te: float = Field(description="Ex-ante TE after the full transition (locked lots ⇒ > 0)")


class ModelComparison(Schema):
    model: ModelSummary
    te_from_current: float | None = Field(
        description="Ex-ante TE of today's holdings vs this model (None for an empty account)"
    )
    yield_change: float
    full_transition: FullTransitionOut


class ComparisonPayload(AnalyticsPayload):
    as_of: date
    taxable: bool
    current: CurrentPortfolio
    comparisons: list[ModelComparison]
    disclaimer: str = DISCLAIMER

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "data_source": "mock_random",
                    "as_of": "2026-10-30",
                    "taxable": True,
                    "current": {
                        "account_id": "acc_017",
                        "market_value": 2750000.0,
                        "cash": 98000.0,
                        "n_positions": 38,
                        "target_model_id": None,
                        "dividend_yield": 0.018,
                        "beta": 1.04,
                        "sector_mix": {"Financials": 0.21, "Cash": 0.036},
                        "factor_exposures": {"value": 0.1, "quality": 0.2},
                        "unrealized_gain": 690000.0,
                        "locked_value": 310000.0,
                    },
                    "comparisons": [
                        {
                            "model": {"id": "SCHWAB-TR", "name": "...", "stats": {}},
                            "te_from_current": 0.041,
                            "yield_change": -0.001,
                            "full_transition": {
                                "est_tax": 142000.0,
                                "realized_st_gain": 30000.0,
                                "realized_st_loss": 12000.0,
                                "realized_lt_gain": 610000.0,
                                "realized_lt_loss": 41000.0,
                                "net_realized_gain": 587000.0,
                                "n_lot_sales": 96,
                                "n_buys": 4,
                                "turnover": 0.88,
                                "locked_value_retained": 290000.0,
                                "post_te": 0.012,
                            },
                        }
                    ],
                    "disclaimer": DISCLAIMER,
                }
            ]
        },
    )


class RegimeUploadResult(Schema):
    n_dates: int
    first_date: date
    last_date: date
    regimes: dict[str, int] = Field(description="Label → number of dates")
