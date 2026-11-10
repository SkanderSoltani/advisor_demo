"""AladdinAnalyticsProvider — placeholder for the BlackRock Aladdin integration.

Every method raises ``NotImplementedError``. The TODOs mark where Aladdin calls go. Response
*shapes* must stay identical to the random provider so the API contract does not change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from app.analytics.provider import AnalyticsProvider
from app.analytics.types import (
    AccountContext,
    DatedValue,
    Exposures,
    Granularity,
    ModelStats,
    RegimePerformance,
    RiskModel,
    TaxPeriod,
    TrackingErrorHistory,
)

_MSG = "Aladdin analytics are not connected yet; set ANALYTICS_PROVIDER=random."


class AladdinAnalyticsProvider(AnalyticsProvider):
    """Stub. Wire each method to the corresponding Aladdin service when access is granted."""

    data_source = "aladdin"

    def __init__(self, as_of: date) -> None:
        # TODO(aladdin): authenticate (client credentials), configure base URL, risk-model id
        # (e.g. a US equity factor model) and portfolio/benchmark identifiers.
        self.as_of = as_of

    def get_prices(self, tickers: Sequence[str]) -> dict[str, float]:
        # TODO(aladdin): security master / pricing service — close prices as of self.as_of.
        raise NotImplementedError(_MSG)

    def get_risk_model(self, tickers: Sequence[str]) -> RiskModel:
        # TODO(aladdin): risk service — factor exposures, factor covariance and specific risk
        # for `tickers`; assemble B·F·Bᵀ + D (annualised). Must be PSD.
        raise NotImplementedError(_MSG)

    def get_tracking_error_history(self, ctx: AccountContext, window: int) -> TrackingErrorHistory:
        # TODO(aladdin): performance/risk history — ex-post TE of the account vs its target
        # model over a rolling `window`; ex-ante TE from the risk service.
        raise NotImplementedError(_MSG)

    def get_ex_ante_te(self, ctx: AccountContext) -> float | None:
        # TODO(aladdin): risk service — ex-ante active risk of holdings vs target weights.
        raise NotImplementedError(_MSG)

    def get_tax_history(self, ctx: AccountContext, granularity: Granularity) -> list[TaxPeriod]:
        # TODO(aladdin): realised gain/loss and tax lot accounting history.
        raise NotImplementedError(_MSG)

    def get_aum_history(self, ctx: AccountContext) -> list[DatedValue]:
        # TODO(aladdin): daily market value history for the account.
        raise NotImplementedError(_MSG)

    def get_exposures(self, ctx: AccountContext) -> Exposures:
        # TODO(aladdin): sector/security/factor exposures, concentration, yield and beta.
        raise NotImplementedError(_MSG)

    def get_model_stats(self, model_id: str, weights: Mapping[str, float]) -> ModelStats:
        # TODO(aladdin): backtest / characteristics for the model portfolio.
        raise NotImplementedError(_MSG)

    def get_regime_performance(
        self, model_id: str, weights: Mapping[str, float], labels: Mapping[date, str]
    ) -> list[RegimePerformance]:
        # TODO(aladdin): model return history bucketed by the supplied regime labels.
        raise NotImplementedError(_MSG)
