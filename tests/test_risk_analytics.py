"""Point-in-time risk analytics: mock provider math, saved snapshots and the API."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.core.config import get_settings
from app.db import models as m
from app.db.catalog import FundProxies, load_catalog
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.main import create_app
from app.risk_analytics.factory import get_risk_provider, get_risk_store
from app.risk_analytics.mock_provider import MockRiskProvider
from app.risk_analytics.security_master import SecurityMaster
from app.risk_analytics.service import RiskAnalyticsService
from app.risk_analytics.snapshot import SnapshotStore
from app.risk_analytics.types import Portfolio, Position
from tests.conftest import TEST_SEED

API = "/api/v1"


@pytest.fixture(scope="module")
def tmp(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("risk")


@pytest.fixture(scope="module")
def risk(market: SyntheticMarket, funds: FundProxies, tmp: Path) -> MockRiskProvider:
    cat = load_catalog(get_settings().MODELS_FILE)
    sm = SecurityMaster.load_or_create(tmp / "sm.json", market.universe,
                                       [(p.ticker, p.name) for p in cat.products], TEST_SEED)
    return MockRiskProvider(market, funds, sm)


def _port(risk: MockRiskProvider) -> Portfolio:
    t = risk.tickers
    return Portfolio(id="p", name="P", cash=50_000, positions=[
        Position(ticker=t[0], market_value=300_000), Position(ticker=t[5], market_value=150_000),
        Position(ticker="SCHD", market_value=500_000)])


def test_report_is_consistent(risk: MockRiskProvider) -> None:
    r = risk.analyze(_port(risk))
    assert r.market_value == pytest.approx(1_000_000)
    assert sum(s.weight for s in r.asset_allocation) == pytest.approx(1.0, abs=1e-5)
    for slices in (r.sectors, r.regions):  # securities only: no cash row
        assert "Cash" not in {s.name for s in slices}
        assert sum(s.weight for s in slices) == pytest.approx(1.0 - r.cash_weight, abs=1e-5)
    assert sum(d.pct_of_variance for d in r.decomposition) == pytest.approx(1.0, abs=1e-3)
    assert r.systematic_pct + r.specific_pct == pytest.approx(1.0, abs=1e-4)
    assert 0.03 < r.volatility < 0.6 and 0.2 < r.beta < 2
    tail = {(x.days, x.confidence): x for x in r.tail}
    assert 0 < tail[(1, .95)].var < tail[(1, .99)].var
    assert tail[(1, .95)].cvar >= tail[(1, .95)].var
    assert tail[(21, .95)].var > tail[(1, .95)].var
    assert [(s.name, s.group) for s in r.asset_allocation] == [
        ("US Equity", "Equity"), ("Non-US Stocks", "Equity"), ("US Bonds", "Fixed Income"),
        ("Non-US Bonds", "Fixed Income"), ("Preferred", "Preferred"), ("Cash", "Cash")]
    assert r.asset_allocation[-1].weight == pytest.approx(0.05)
    assert {"SCHD"} <= {c.ticker for c in r.top_contributors}


def test_deterministic_and_security_master_saved(risk: MockRiskProvider, market: SyntheticMarket,
                                                 tmp: Path) -> None:
    a, b = risk.analyze(_port(risk)), risk.analyze(_port(risk))
    assert a.model_dump(exclude={"generated_at"}) == b.model_dump(exclude={"generated_at"})
    again = SecurityMaster.load_or_create(tmp / "sm.json", market.universe, [], TEST_SEED + 1)
    assert again.rows == risk.master.rows  # file wins: generated once


def test_snapshot_generated_once(risk: MockRiskProvider, db: Session, tmp: Path) -> None:
    store = SnapshotStore(tmp / "snap.json")
    svc = RiskAnalyticsService(db, risk, store)
    c = db.scalars(select(m.Client)).first()
    assert c is not None
    first = svc.client_report(c)
    assert len(first.accounts) == len(c.accounts)
    calls = []
    orig = risk.analyze
    risk.analyze = lambda *a, **k: calls.append(1) or orig(*a, **k)  # type: ignore[method-assign]
    try:
        cached = RiskAnalyticsService(db, risk, SnapshotStore(tmp / "snap.json")).client_report(c)
        assert not calls and cached.generated_at == first.generated_at
        svc.client_report(c, refresh=True)
        assert calls
    finally:
        del risk.analyze
    book = svc.book_report(c.advisor_id, "Adv")
    assert book.scope == "book" and book.market_value > first.market_value


@pytest.fixture(scope="module")
def api(market: SyntheticMarket, provider: RandomAnalyticsProvider, risk: MockRiskProvider,
        tmp: Path) -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    with sessionmaker(bind=engine)() as s:
        seed_demo(s, engine, market, TEST_SEED)
    app = create_app(sync_catalog=False)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    def _db() -> Iterator[object]:
        with maker() as s:
            yield s

    store = SnapshotStore(tmp / "api_snap.json")
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_risk_provider] = lambda: risk
    app.dependency_overrides[get_risk_store] = lambda: store
    with TestClient(app) as c:
        tok = c.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
        yield c


def test_api(api: TestClient, tmp: Path) -> None:
    b = api.get(f"{API}/book/risk")
    assert b.status_code == 200, b.text
    assert b.json()["scope"] == "book" and (tmp / "api_snap.json").exists()
    assert api.get(f"{API}/book/risk").json()["generated_at"] == b.json()["generated_at"]
    cid = api.get(f"{API}/clients").json()["items"][0]["id"]
    r = api.get(f"{API}/clients/{cid}/risk")
    assert r.status_code == 200 and r.json()["accounts"]
    assert api.post(f"{API}/clients/{cid}/risk/refresh").status_code == 200
    assert api.get(f"{API}/clients/nope/risk").status_code == 404
    aid = r.json()["accounts"][0]["account_id"]
    one = api.get(f"{API}/clients/{cid}/risk", params={"account_id": aid})
    assert one.status_code == 200 and one.json()["scope"] == "account"
    assert one.json()["market_value"] < r.json()["market_value"] or len(r.json()["accounts"]) == 1
    assert api.get(f"{API}/clients/{cid}/risk", params={"account_id": "x"}).status_code == 404
