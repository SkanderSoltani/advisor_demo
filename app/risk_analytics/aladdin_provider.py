"""BlackRock Aladdin source — stub until access is granted.

Keep the ``RiskReport`` shape unchanged so the API and UI need no change.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.risk_analytics.provider import RiskAnalyticsProvider
from app.risk_analytics.types import Portfolio, RiskReport, SecurityRef

_MSG = "Aladdin is not connected yet; set RISK_ANALYTICS_PROVIDER=mock."


class AladdinRiskProvider(RiskAnalyticsProvider):
    data_source = "aladdin"
    source_label = "BlackRock Aladdin"

    def __init__(self, as_of: date) -> None:
        # TODO(aladdin): client-credentials auth, base URL, risk model id (e.g. a US equity
        # factor model), portfolio / benchmark identifiers.
        self.as_of = as_of

    def prices(self, tickers: Sequence[str]) -> dict[str, float]:
        # TODO(aladdin): pricing service — close prices as of self.as_of.
        raise NotImplementedError(_MSG)

    def security_reference(self, tickers: Sequence[str]) -> dict[str, SecurityRef]:
        # TODO(aladdin): security master — asset class, GICS sector, country of risk.
        raise NotImplementedError(_MSG)

    def analyze(self, portfolio: Portfolio, scope: str = "client") -> RiskReport:
        # TODO(aladdin): upload/lookup the portfolio, then call the risk service for:
        #   * exposures by asset class, GICS sector, region/country (look-through for funds)
        #   * ex-ante volatility and its factor decomposition (market/sector/style/specific)
        #   * historical / parametric VaR and CVaR at 95% and 99% (1-day, 1-month)
        #   * stress scenarios, beta, top risk contributors
        # and map the responses onto RiskReport.
        raise NotImplementedError(_MSG)
