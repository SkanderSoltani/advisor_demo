"""Provider and snapshot-store selection (FastAPI dependencies; override in tests).

``RISK_ANALYTICS_PROVIDER=mock|aladdin|bloomberg`` (default mock).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.risk_analytics.provider import RiskAnalyticsProvider
from app.risk_analytics.snapshot import SnapshotStore


@lru_cache
def get_risk_provider() -> RiskAnalyticsProvider:
    s = get_settings()
    if s.RISK_ANALYTICS_PROVIDER == "aladdin":
        from app.risk_analytics.aladdin_provider import AladdinRiskProvider

        return AladdinRiskProvider(as_of=s.AS_OF_DATE)
    if s.RISK_ANALYTICS_PROVIDER == "bloomberg":
        from app.risk_analytics.bloomberg_provider import BloombergRiskProvider

        return BloombergRiskProvider(as_of=s.AS_OF_DATE)
    return build_mock_provider()


def build_mock_provider() -> RiskAnalyticsProvider:
    from app.analytics.factory import get_provider
    from app.db.catalog import build_fund_proxies, load_catalog
    from app.db.synthetic_market import load_or_generate
    from app.risk_analytics.mock_provider import MockRiskProvider
    from app.risk_analytics.security_master import SecurityMaster

    s = get_settings()
    base = get_provider()
    market = getattr(base, "market", None) or load_or_generate(
        s.DATA_DIR, s.SYNTHETIC_SEED, s.AS_OF_DATE, s.UNIVERSE_SIZE, s.PRICE_HISTORY_YEARS
    )
    catalog = load_catalog(s.MODELS_FILE)
    funds = getattr(base, "funds", None) or build_fund_proxies(market, catalog)
    master = SecurityMaster.load_or_create(
        s.SECURITY_MASTER_FILE, market.universe,
        [(p.ticker, p.name, p.asset_class, p.proxy) for p in catalog.products], s.SYNTHETIC_SEED,
    )
    return MockRiskProvider(market, funds, master)


@lru_cache
def get_risk_store() -> SnapshotStore:
    return SnapshotStore(get_settings().RISK_SNAPSHOT_FILE)
