"""API tests for the model catalog, comparison and regime labels (Milestone 3)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.main import create_app
from tests.conftest import TEST_SEED

API = "/api/v1"


@pytest.fixture(scope="module")
def client(market: SyntheticMarket, provider: RandomAnalyticsProvider) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with sessionmaker(bind=engine)() as s:
        seed_demo(s, engine, market, TEST_SEED)
    app = create_app(sync_catalog=False)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    def _db() -> Iterator[object]:
        with maker() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    with TestClient(app) as c:
        tok = c.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
        yield c


def test_catalog(client: TestClient) -> None:
    r = client.get(f"{API}/models").json()
    assert r["data_source"] == "mock_random" and r["total"] == 2
    for m in r["items"]:
        st = m["stats"]
        assert 0.05 < st["volatility"] < 0.35 and 0 < st["max_drawdown"] < 0.6
        assert sum(st["sector_mix"].values()) == pytest.approx(1, abs=1e-4)
        assert st["n_holdings"] <= 10 < st["n_underlying"]
        assert 0 < m["fee_bps"] < 20 and 0 < m["expected_te"] < 0.06
    inc = client.get(f"{API}/models?objective=income").json()["items"]
    assert [m["id"] for m in inc] == ["SCHWAB-INC"]
    assert client.get(f"{API}/models?objective=growth").status_code == 422


def test_model_detail(client: TestClient) -> None:
    d = client.get(f"{API}/models/SCHWAB-INC").json()
    assert sum(h["weight"] for h in d["holdings"]) == pytest.approx(1)
    assert all(h["security_type"] == "fund" for h in d["holdings"])
    assert d["regime_performance"] is None
    assert client.get(f"{API}/models/NOPE").status_code == 404


def test_compare_legacy_account(client: TestClient) -> None:
    body = {"model_ids": ["SCHWAB-TR", "SCHWAB-INC", "SCHWAB-TR"], "account_id": "acc_017"}
    r = client.post(f"{API}/models/compare", json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["taxable"] and "Not tax or investment advice" in p["disclaimer"]
    assert [c["model"]["id"] for c in p["comparisons"]] == ["SCHWAB-TR", "SCHWAB-INC"]
    cur = p["current"]
    assert cur["locked_value"] > 0 and sum(cur["sector_mix"].values()) == pytest.approx(1, abs=1e-4)
    for c in p["comparisons"]:
        ft = c["full_transition"]
        assert c["te_from_current"] > 0.01
        assert ft["est_tax"] > 0 and ft["n_lot_sales"] > 0
        assert ft["locked_value_retained"] == pytest.approx(cur["locked_value"], rel=0.05)
        assert 0 < ft["post_te"] < c["te_from_current"]  # locked lots keep TE above zero


def test_compare_ira_and_unlocked(client: TestClient) -> None:
    p = client.post(
        f"{API}/models/compare", json={"model_ids": ["SCHWAB-INC"], "account_id": "acc_003"}
    ).json()
    ft = p["comparisons"][0]["full_transition"]
    assert not p["taxable"] and ft["est_tax"] == 0
    assert ft["locked_value_retained"] == 0 and ft["post_te"] < 0.003


def test_compare_errors_and_empty_account(client: TestClient) -> None:
    bad = client.post(f"{API}/models/compare", json={"model_ids": ["X"], "account_id": "acc_001"})
    assert bad.status_code == 404
    bad = client.post(f"{API}/models/compare", json={"model_ids": ["SCHWAB-TR"], "account_id": "z"})
    assert bad.status_code == 404
    assert (
        client.post(
            f"{API}/models/compare", json={"model_ids": [], "account_id": "acc_001"}
        ).status_code
        == 422
    )
    acct = client.post(
        f"{API}/clients/cli_009/accounts", json={"account_type": "ira", "custodian": "Schwab"}
    ).json()
    p = client.post(
        f"{API}/models/compare", json={"model_ids": ["SCHWAB-TR"], "account_id": acct["id"]}
    ).json()
    c = p["comparisons"][0]
    assert c["te_from_current"] is None and c["full_transition"]["est_tax"] == 0


def test_regimes(client: TestClient) -> None:
    csv = "date,regime\n2022-01-01,risk_off\n2023-01-01,risk_on\n2025-06-01,risk_off\n"
    r = client.post(f"{API}/analytics/regimes", files={"file": ("r.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["regimes"] == {"risk_off": 2, "risk_on": 1}
    perf = client.get(f"{API}/models/SCHWAB-TR").json()["regime_performance"]
    assert {p["regime"] for p in perf} == {"risk_off", "risk_on"}
    assert sum(p["n_days"] for p in perf) > 1000
    bad = client.post(
        f"{API}/analytics/regimes", files={"file": ("r.csv", "2022-13-01,x\n", "text/csv")}
    )
    assert bad.status_code == 422 and "invalid date" in bad.text
    assert client.delete(f"{API}/analytics/regimes").status_code == 204
    assert client.get(f"{API}/models/SCHWAB-TR").json()["regime_performance"] is None
