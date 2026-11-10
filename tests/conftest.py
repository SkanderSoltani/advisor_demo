"""Shared fixtures: one synthetic market and one seeded in-memory DB per test session."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.random_provider import RandomAnalyticsProvider
from app.core.config import get_settings
from app.db.catalog import FundProxies, build_fund_proxies, load_catalog
from app.db.seed import SeedSummary, seed_demo
from app.db.session import make_engine
from app.db.synthetic_market import SyntheticMarket, generate_market

TEST_SEED = 20240501
TEST_AS_OF = date(2026, 10, 30)


@pytest.fixture(scope="session")
def market() -> SyntheticMarket:
    return generate_market(seed=TEST_SEED, as_of=TEST_AS_OF, n_names=300, years=5)


@pytest.fixture(scope="session")
def funds(market: SyntheticMarket) -> FundProxies:
    return build_fund_proxies(market, load_catalog(get_settings().MODELS_FILE))


@pytest.fixture(scope="session")
def provider(market: SyntheticMarket, funds: FundProxies) -> RandomAnalyticsProvider:
    return RandomAnalyticsProvider(market, seed=TEST_SEED, funds=funds)


@pytest.fixture(scope="session")
def engine() -> Engine:
    from sqlalchemy import create_engine

    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


@pytest.fixture(scope="session")
def seeded(engine: Engine, market: SyntheticMarket) -> SeedSummary:
    with sessionmaker(bind=engine)() as s:
        return seed_demo(s, engine, market, TEST_SEED)


@pytest.fixture()
def db(engine: Engine, seeded: SeedSummary) -> Iterator[Session]:
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


__all__ = ["make_engine"]
