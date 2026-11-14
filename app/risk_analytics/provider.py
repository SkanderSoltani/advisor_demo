"""The RiskAnalyticsProvider interface.

Every point-in-time analytics number comes from a provider. Callers never branch on which one is
active; the report's ``data_source`` / ``source_label`` say where the numbers came from.

A provider has three jobs:

1. ``prices``             – value positions (security master / pricing).
2. ``security_reference`` – asset class, GICS sector, country (security master).
3. ``analyze``            – the full report for one portfolio (allocation, exposures, risk).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date

from app.risk_analytics.types import Portfolio, RiskReport, SecurityRef


class RiskAnalyticsProvider(ABC):
    #: short id stored with each report, e.g. "mock", "aladdin", "bloomberg"
    data_source: str
    #: human label shown in the UI
    source_label: str
    #: the date every number is computed as of
    as_of: date

    @abstractmethod
    def prices(self, tickers: Sequence[str]) -> dict[str, float]:
        """Latest price per ticker (unknown tickers are left out)."""

    @abstractmethod
    def security_reference(self, tickers: Sequence[str]) -> dict[str, SecurityRef]:
        """Reference data per ticker (unknown tickers are left out)."""

    @abstractmethod
    def analyze(self, portfolio: Portfolio, scope: str = "client") -> RiskReport:
        """Point-in-time report for ``portfolio`` (positions already valued)."""
