"""The AnalyticsProvider interface.

All analytics flow through this interface. Today the only working implementation is
:class:`~app.analytics.random_provider.RandomAnalyticsProvider` (simulated, seeded numbers). The
BlackRock Aladdin implementation (:mod:`app.analytics.aladdin_provider`) is a stub. Callers must
never branch on which provider is active; the only visible difference is ``data_source``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import date

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


class AnalyticsProvider(ABC):
    """Source of every analytics number shown in the product."""

    #: tag added to every analytics API response, e.g. "mock_random" or "aladdin"
    data_source: str
    #: the date all analytics are computed as of
    as_of: date

    # ---- market data / risk -------------------------------------------------
    @abstractmethod
    def get_prices(self, tickers: Sequence[str]) -> dict[str, float]:
        """Latest prices for ``tickers``."""

    @abstractmethod
    def get_risk_model(self, tickers: Sequence[str]) -> RiskModel:
        """Annualised, positive semi-definite covariance for ``tickers`` (optimizer input)."""

    # ---- account level ------------------------------------------------------
    @abstractmethod
    def get_tracking_error_history(self, ctx: AccountContext, window: int) -> TrackingErrorHistory:
        """Rolling ``window``-day ex-post TE vs the account's target, plus ex-ante TE today."""

    @abstractmethod
    def get_ex_ante_te(self, ctx: AccountContext) -> float | None:
        """Ex-ante TE of the account vs its target today (None if no target or no holdings)."""

    @abstractmethod
    def get_tax_history(self, ctx: AccountContext, granularity: Granularity) -> list[TaxPeriod]:
        """Realised ST/LT gains, harvested losses, tax paid and taxes saved per period."""

    @abstractmethod
    def get_aum_history(self, ctx: AccountContext) -> list[DatedValue]:
        """Daily account value from onboarding to as-of."""

    @abstractmethod
    def get_exposures(self, ctx: AccountContext) -> Exposures:
        """Sector / security / factor exposures vs target, concentration, yield and beta."""

    # ---- models ----------------------------------------------------------------
    @abstractmethod
    def get_model_stats(self, model_id: str, weights: Mapping[str, float]) -> ModelStats:
        """Historical and characteristic statistics for a model portfolio."""

    @abstractmethod
    def get_regime_performance(
        self, model_id: str, weights: Mapping[str, float], labels: Mapping[date, str]
    ) -> list[RegimePerformance]:
        """Performance of the model split by macro regime (``labels``: date → regime name)."""
