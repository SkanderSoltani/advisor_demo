"""Bloomberg source (BLPAPI / PORT / B-PIPE) — stub until access is granted.

Keep the ``RiskReport`` shape unchanged so the API and UI need no change.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.risk_analytics.provider import RiskAnalyticsProvider
from app.risk_analytics.types import Portfolio, RiskReport, SecurityRef

_MSG = "Bloomberg is not connected yet; set RISK_ANALYTICS_PROVIDER=mock."


class BloombergRiskProvider(RiskAnalyticsProvider):
    data_source = "bloomberg"
    source_label = "Bloomberg"

    def __init__(self, as_of: date) -> None:
        # TODO(bloomberg): open a blpapi session (host/port or B-PIPE auth), services
        # //blp/refdata and the PORT / MARS risk services.
        self.as_of = as_of

    def prices(self, tickers: Sequence[str]) -> dict[str, float]:
        # TODO(bloomberg): ReferenceDataRequest, field PX_LAST (or HistoricalDataRequest at as_of).
        raise NotImplementedError(_MSG)

    def security_reference(self, tickers: Sequence[str]) -> dict[str, SecurityRef]:
        # TODO(bloomberg): fields GICS_SECTOR_NAME, CNTRY_OF_RISK, BICS / asset class,
        # SECURITY_NAME; fund look-through via the fund holdings fields.
        raise NotImplementedError(_MSG)

    def analyze(self, portfolio: Portfolio, scope: str = "client") -> RiskReport:
        # TODO(bloomberg): PORT risk (Bloomberg factor model) for total risk and factor
        # decomposition, VaR/CVaR and scenarios; map the results onto RiskReport.
        raise NotImplementedError(_MSG)
