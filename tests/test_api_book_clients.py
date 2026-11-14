"""API tests for auth, book, clients, accounts and events (Milestone 2)."""

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
    # own DB: this module writes (onboarding), so it must not leak into other test modules
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
        assert tok.status_code == 200
        c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
        yield c


def get(c: TestClient, path: str, code: int = 200) -> dict:  # type: ignore[type-arg]
    r = c.get(API + path)
    assert r.status_code == code, (path, r.text[:500])
    return r.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------- auth
def test_auth(client: TestClient) -> None:
    me = get(client, "/auth/me")
    assert me["email"] == DEMO_EMAIL and me["firm"]
    anon = TestClient(client.app)
    assert anon.get(f"{API}/book/summary").status_code == 401
    assert (
        anon.get(f"{API}/book/summary", headers={"Authorization": "Bearer junk"}).status_code == 401
    )
    bad = anon.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": "nope"})
    assert bad.status_code == 401


# ---------------------------------------------------------------- book
def test_book_summary_consistent_with_clients(client: TestClient) -> None:
    s = get(client, "/book/summary")
    rows = get(client, "/clients")["items"]
    assert s["data_source"] == "mock_random"
    assert s["n_clients"] == len(rows)
    assert s["n_accounts"] == sum(r["n_accounts"] for r in rows)
    assert s["total_aum"] == pytest.approx(sum(r["market_value"] for r in rows), abs=1)
    assert s["taxes_saved_ytd"] == pytest.approx(sum(r["taxes_saved_ytd"] for r in rows), abs=1)
    assert sum(s["clients_by_status"].values()) == len(rows)
    assert s["n_accounts_outside_tolerance"] > 0
    assert 0.003 < s["avg_ex_ante_te"] < 0.10


def test_book_tracking_error(client: TestClient) -> None:
    for w in (63, 252):
        te = get(client, f"/book/analytics/tracking-error?window={w}")
        assert te["window"] == w and len(te["series"]) > 200
        for p in te["series"]:
            assert p["p10"] <= p["p90"]
            assert 0.002 <= p["avg_te"] <= 0.06
    get(client, "/book/analytics/tracking-error?window=10", 422)


def test_book_tax_impact_equals_sum_of_clients(client: TestClient) -> None:
    book = get(client, "/book/analytics/tax-impact?granularity=year")["periods"]
    assert [p["period"] for p in book] == sorted(p["period"] for p in book)
    total_book = book[-1]["cum_taxes_saved"]
    rows = get(client, "/clients")["items"]
    total_clients = sum(
        get(client, f"/clients/{r['id']}/analytics/tax-savings")["taxes_saved_since_inception"]
        for r in rows
    )
    assert total_book == pytest.approx(total_clients, abs=1)
    cums = [p["cum_taxes_saved"] for p in book]
    assert cums == sorted(cums)
    monthly = get(client, "/book/analytics/tax-impact?granularity=month")["periods"]
    assert monthly[-1]["cum_taxes_saved"] == pytest.approx(total_book, abs=1)


def test_book_activity(client: TestClient) -> None:
    act = get(client, "/book/analytics/activity?granularity=month")["periods"]
    assert all(p["total"] == sum(p["counts"].values()) for p in act)
    assert sum(p["counts"]["transition"] for p in act) >= 8
    assert act[-1]["aum"] == pytest.approx(get(client, "/book/summary")["total_aum"], rel=1e-6)
    yearly = get(client, "/book/analytics/activity?granularity=year")["periods"]
    assert sum(p["total"] for p in yearly) == sum(p["total"] for p in act)


# ---------------------------------------------------------------- clients
def test_client_list_filters(client: TestClient) -> None:
    allc = get(client, "/clients")
    assert allc["total"] == 9
    statuses = {r["status"] for r in allc["items"]}
    assert "onboarding" in statuses
    assert statuses <= {"onboarding", "on_target", "drifting", "needs_review"}
    only = get(client, "/clients?status=onboarding")["items"]
    assert len(only) == 1 and only[0]["ex_ante_te"] is None
    found = get(client, "/clients?search=okafor")["items"]
    assert [r["name"] for r in found] == ["Okafor Family"]
    assert get(client, "/clients?search=zzz-nobody")["total"] == 0
    assert get(client, "/clients?search=m.lindqvist")["total"] == 1  # email match


def test_client_detail_and_analytics(client: TestClient) -> None:
    d = get(client, "/clients/cli_001")
    assert d["tax_profile"]["st_rate"] == pytest.approx(0.37 + 0.133)
    assert len(d["accounts"]) == 3
    assert d["metrics"]["market_value"] == pytest.approx(
        sum(a["market_value"] for a in d["accounts"]), abs=1
    )
    te = get(client, "/clients/cli_001/analytics/tracking-error?window=63")
    assert te["series"] and te["events"]
    assert {e["account_id"] for e in te["events"]} == {a["id"] for a in d["accounts"]}
    one = get(client, "/clients/cli_001/analytics/tracking-error?window=252&account_id=acc_002")
    assert {e["account_id"] for e in one["events"]} == {"acc_002"}
    get(client, "/clients/cli_001/analytics/tracking-error?account_id=acc_004", 404)

    ts = get(client, "/clients/cli_001/analytics/tax-savings?granularity=month")
    assert ts["periods"][-1]["cum_taxes_saved"] == pytest.approx(
        ts["taxes_saved_since_inception"], abs=1
    )
    sm = get(client, "/clients/cli_001/analytics/summary")
    assert sm["aum_history"][-1]["value"] == pytest.approx(d["metrics"]["market_value"], rel=1e-6)
    assert [y["year"] for y in sm["by_year"]] == list(range(2023, 2027))
    assert sum(y["n_rebalances"] for y in sm["by_year"]) > 5


def test_events(client: TestClient) -> None:
    ev = get(client, "/clients/cli_001/events")
    dates = [e["date"] for e in ev["items"]]
    assert dates == sorted(dates, reverse=True)
    tlh = get(client, "/clients/cli_001/events?type=tax_loss_harvest&from=2025-01-01&to=2025-12-31")
    assert all(
        e["type"] == "tax_loss_harvest" and "2025-01-01" <= e["date"] <= "2025-12-31"
        for e in tlh["items"]
    )
    acc = get(client, "/clients/cli_001/events?account_id=acc_003")
    assert {e["account_id"] for e in acc["items"]} == {"acc_003"}
    detail = get(client, f"/events/{ev['items'][0]['id']}")
    assert detail["client_id"] == "cli_001" and len(detail["trades"]) == detail["n_trades"]
    get(client, "/events/evt_99999", 404)
    get(client, "/clients/cli_001/events?type=bogus", 422)


# ---------------------------------------------------------------- accounts
def test_account_detail_and_analytics(client: TestClient) -> None:
    a = get(client, "/accounts/acc_004")
    acct = a["account"]
    assert acct["n_lots"] == len(a["lots"]) and acct["n_positions"] == len(a["holdings"])
    u = a["unrealized"]
    assert u["st_gains"] >= 0 >= u["st_losses"] and u["lt_gains"] >= 0 >= u["lt_losses"]
    assert sum(lot["unrealized_gain"] for lot in a["lots"]) == pytest.approx(u["net"], abs=1)
    assert any(h["locked"] for h in a["holdings"])  # Lindqvist restricted stock
    assert {lot["holding_period"] for lot in a["lots"]} == {"ST", "LT"}

    th = get(client, "/accounts/acc_004/analytics/tax-history?granularity=year")
    assert th["taxable"] and th["totals"]["taxes_saved"] == pytest.approx(
        acct["taxes_saved_since_inception"], abs=1
    )
    te = get(client, "/accounts/acc_004/analytics/tracking-error?window=252")
    assert te["ex_ante_te"] == acct["ex_ante_te"]
    x = get(client, "/accounts/acc_004/analytics/exposures")
    assert sum(s["portfolio_weight"] for s in x["sectors"]) == pytest.approx(1, abs=1e-4)
    assert x["target_model_id"] == "TR-CORE-96-04"
    get(client, "/accounts/acc_nope", 404)


def test_ira_has_no_tax(client: TestClient) -> None:
    th = get(client, "/accounts/acc_003/analytics/tax-history")
    assert not th["taxable"]
    assert th["totals"]["est_tax_paid"] == 0 and th["totals"]["taxes_saved"] == 0


def test_onboarding_empty_states(client: TestClient) -> None:
    d = get(client, "/clients/cli_009")
    assert d["status"] == "onboarding"
    assert get(client, "/clients/cli_009/analytics/tracking-error")["series"] == []
    assert get(client, "/clients/cli_009/events")["total"] == 0
    ts = get(client, "/clients/cli_009/analytics/tax-savings")
    assert ts["taxes_saved_since_inception"] == 0


# ---------------------------------------------------------------- onboarding flow
def test_onboard_client_and_add_account(client: TestClient) -> None:
    body = {
        "name": "Rivera Household",
        "email": "Rivera@Example.com",
        "client_type": "couple",
        "tax_profile": {
            "federal_st_rate": 0.32,
            "federal_lt_rate": 0.15,
            "state": "or",
            "state_rate": 0.099,
        },
    }
    r = client.post(f"{API}/clients", json=body)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "onboarding" and c["email"] == "rivera@example.com"
    assert c["tax_profile"]["state"] == "OR"

    p = client.patch(
        f"{API}/clients/{c['id']}",
        json={"phone": "555-0200", "tax_profile": {"state_rate": 0.0875}},
    )
    assert p.status_code == 200 and p.json()["tax_profile"]["state_rate"] == 0.0875
    assert p.json()["tax_profile"]["federal_st_rate"] == 0.32

    bad = client.post(
        f"{API}/clients/{c['id']}/accounts",
        json={"account_type": "ira", "custodian": "Schwab", "target_model_id": "X"},
    )
    assert bad.status_code == 422
    a = client.post(
        f"{API}/clients/{c['id']}/accounts",
        json={
            "account_type": "joint_taxable",
            "custodian": "Schwab",
            "nickname": "Joint",
            "target_model_id": "TR-CORE-96-04",
        },
    )
    assert a.status_code == 201, a.text
    acct = a.json()
    assert acct["market_value"] == 0 and acct["n_lots"] == 0 and acct["ex_ante_te"] is None

    # empty states everywhere for the brand-new account
    assert get(client, f"/accounts/{acct['id']}")["holdings"] == []
    x = get(client, f"/accounts/{acct['id']}/analytics/exposures")
    assert x["n_positions"] == 0
    assert get(client, f"/accounts/{acct['id']}/analytics/tracking-error")["series"] == []
    assert get(client, f"/clients/{c['id']}/accounts")["items"][0]["id"] == acct["id"]
    assert get(client, "/book/summary")["n_clients"] == 10

    invalid = client.post(f"{API}/clients", json={**body, "client_type": "corp"})
    assert invalid.status_code == 422
