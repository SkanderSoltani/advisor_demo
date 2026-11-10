"""Analytics payloads for book, client and account pages."""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict, Field

from app.schemas.common import AnalyticsPayload, DatedValueOut, Granularity, Schema


# ---------------------------------------------------------------- book
class BookSummary(AnalyticsPayload):
    as_of: date
    n_clients: int
    n_accounts: int
    total_aum: float
    taxes_saved_ytd: float
    taxes_saved_since_inception: float
    avg_ex_ante_te: float | None = Field(description="AUM-weighted across accounts with a target")
    n_accounts_outside_tolerance: int
    clients_by_status: dict[str, int]


class BookTEPoint(Schema):
    date: date
    avg_te: float = Field(description="AUM-weighted average rolling TE across accounts")
    p10: float
    p90: float
    n_accounts: int


class BookTrackingError(AnalyticsPayload):
    window: int
    series: list[BookTEPoint]


class TaxImpactPeriod(Schema):
    period: str = Field(examples=["2026-03"])
    taxes_saved: float
    losses_harvested: float
    realized_st_gain: float
    realized_lt_gain: float
    realized_st_loss: float = Field(description="Short-term part of losses_harvested (positive)")
    realized_lt_loss: float = Field(description="Long-term part of losses_harvested (positive)")
    cum_taxes_saved: float
    cum_losses_harvested: float
    cum_realized_st_gain: float
    cum_realized_lt_gain: float
    cum_realized_st_loss: float
    cum_realized_lt_loss: float


class TaxImpact(AnalyticsPayload):
    granularity: Granularity
    periods: list[TaxImpactPeriod]


class ActivityPeriod(Schema):
    period: str
    counts: dict[str, int] = Field(
        description="Events per type (transition, rebalance, tax_loss_harvest, cash_flow, "
        "model_change)"
    )
    total: int
    aum: float = Field(description="Total AUM at period end")


class Activity(AnalyticsPayload):
    granularity: Granularity
    periods: list[ActivityPeriod]


# ---------------------------------------------------------------- client / account
class EventMarker(Schema):
    event_id: str
    account_id: str
    date: date
    type: str


class TEPoint(Schema):
    date: date
    te: float


class TrackingError(AnalyticsPayload):
    """Rolling ex-post TE vs target (value-weighted across accounts at client level)."""

    window: int
    account_id: str | None
    series: list[TEPoint]
    ex_ante_te: float | None
    events: list[EventMarker]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "data_source": "mock_random",
                    "window": 63,
                    "account_id": None,
                    "series": [{"date": "2026-10-29", "te": 0.0094}],
                    "ex_ante_te": 0.0101,
                    "events": [
                        {
                            "event_id": "evt_00042",
                            "account_id": "acc_001",
                            "date": "2026-10-16",
                            "type": "rebalance",
                        }
                    ],
                }
            ]
        },
    )


class TaxSavingsPeriod(Schema):
    period: str
    taxes_saved: float
    losses_harvested: float
    cum_taxes_saved: float
    realized_st_gain: float
    realized_lt_gain: float
    realized_st_loss: float = Field(description="Short-term part of losses_harvested (positive)")
    realized_lt_loss: float = Field(description="Long-term part of losses_harvested (positive)")


class TaxSavings(AnalyticsPayload):
    granularity: Granularity
    account_id: str | None
    periods: list[TaxSavingsPeriod]
    taxes_saved_ytd: float
    taxes_saved_since_inception: float


class YearSummary(Schema):
    year: int
    realized_st_gain: float
    realized_lt_gain: float
    losses_harvested: float
    taxes_saved: float
    n_rebalances: int
    turnover: float = Field(
        description="Annual turnover: sum of event turnover in the year, averaged across accounts"
    )


class ClientAnalyticsSummary(AnalyticsPayload):
    account_id: str | None
    aum_history: list[DatedValueOut] = Field(description="Month-end AUM")
    by_year: list[YearSummary]
    avg_annual_turnover: float | None


class TaxHistoryPeriod(Schema):
    period: str
    realized_st_gain: float
    realized_lt_gain: float
    losses_harvested: float
    est_tax_paid: float
    taxes_saved: float


class TaxHistory(AnalyticsPayload):
    account_id: str
    granularity: Granularity
    taxable: bool
    periods: list[TaxHistoryPeriod]
    totals: TaxHistoryPeriod


class SectorWeight(Schema):
    sector: str
    portfolio_weight: float
    target_weight: float
    active_weight: float


class ActiveWeight(Schema):
    ticker: str
    name: str
    sector: str
    portfolio_weight: float
    target_weight: float
    active_weight: float


class FactorWeight(Schema):
    factor: str
    portfolio: float
    target: float
    active: float


class ExposuresOut(AnalyticsPayload):
    account_id: str
    target_model_id: str | None
    sectors: list[SectorWeight]
    top_active_weights: list[ActiveWeight]
    factor_exposures: list[FactorWeight]
    top10_weight: float
    hhi: float
    n_positions: int
    dividend_yield: float
    target_dividend_yield: float | None
    beta: float
    target_beta: float | None
