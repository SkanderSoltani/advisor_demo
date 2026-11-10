"""Provider selection via ANALYTICS_PROVIDER=random|aladdin (default random)."""

from __future__ import annotations

from functools import lru_cache

from app.analytics.aladdin_provider import AladdinAnalyticsProvider
from app.analytics.provider import AnalyticsProvider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.core.config import get_settings
from app.db.catalog import build_fund_proxies, load_catalog
from app.db.synthetic_market import load_or_generate


@lru_cache
def get_provider() -> AnalyticsProvider:
    """Process-wide analytics provider (FastAPI dependency; override in tests)."""
    s = get_settings()
    if s.ANALYTICS_PROVIDER == "aladdin":
        return AladdinAnalyticsProvider(as_of=s.AS_OF_DATE)
    market = load_or_generate(
        s.DATA_DIR, s.SYNTHETIC_SEED, s.AS_OF_DATE, s.UNIVERSE_SIZE, s.PRICE_HISTORY_YEARS
    )
    funds = build_fund_proxies(market, load_catalog(s.MODELS_FILE))
    return RandomAnalyticsProvider(market, seed=s.SYNTHETIC_SEED, funds=funds)
