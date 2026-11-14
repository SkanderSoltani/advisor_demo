"""API tests for transitions: create, locks, optimize, frontier, exports (Milestone 4)."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import pairwise

import pdfplumber
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


def new_transition(c: TestClient, client_id: str = "cli_009", account_id: str = "acc_017") -> str:
    r = c.post(f"{API}/transitions", json={"client_id": client_id, "account_id": account_id})
    assert r.status_code == 201, r.text
    return str(r.json()["transition_id"])


def test_create_and_validation(client: TestClient) -> None:
    tid = new_transition(client)
    t = client.get(f"{API}/transitions/{tid}").json()
    assert t["state"] == "INGEST_CHOICE" and t["target_model_id"] is None
    assert t["account_locked_lot_ids"] and not t["has_optimization"]
    assert (
        client.post(
            f"{API}/transitions", json={"client_id": "cli_001", "account_id": "acc_017"}
        ).status_code
        == 404
    )
    assert client.get(f"{API}/transitions/trn_nope").status_code == 404
    # no target yet
    r = client.post(f"{API}/transitions/{tid}/optimize", json={"budget_value": 1000})
    assert r.status_code == 422 and "target" in r.text
    assert client.get(f"{API}/transitions/{tid}/trades.csv").status_code == 404


def test_new_empty_account_starts_at_ingest(client: TestClient) -> None:
    acct = client.post(
        f"{API}/clients/cli_009/accounts",
        json={"account_type": "ira", "custodian": "Schwab", "target_model_id": "TR-CORE-96-04"},
    ).json()
    tid = new_transition(client, "cli_009", acct["id"])
    assert client.get(f"{API}/transitions/{tid}").json()["state"] == "INGEST_CHOICE"
    r = client.post(f"{API}/transitions/{tid}/optimize", json={"budget_value": 1000})
    assert r.status_code == 422 and "holdings" in r.text


def test_optimize_flow(client: TestClient) -> None:
    tid = new_transition(client)
    body = {"budget_mode": "tax", "budget_value": 25_000, "target_model_id": "TR-CORE-96-04"}
    r = client.post(f"{API}/transitions/{tid}/optimize", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["data_source"] == "mock_random" and "Not tax or investment advice" in j["disclaimer"]
    assert j["realized"]["est_tax"] <= 25_001
    assert j["post"]["te"] < j["pre"]["te"]
    assert j["diagnostics"]["status"] == "optimal" and j["diagnostics"]["explanation"]
    locked = set(client.get(f"{API}/transitions/{tid}").json()["account_locked_lot_ids"])
    assert not locked & {s["lot_id"] for s in j["trades"]["sells"]}
    core_96 = {"SCHX", "SCHA", "SCHF", "SCHC", "SCHE", "SCHH", "CASH"}
    assert {b["ticker"] for b in j["trades"]["buys"]} <= core_96
    assert client.get(f"{API}/transitions/{tid}").json()["target_model_id"] == "TR-CORE-96-04"

    # budget ↑ ⇒ TE ↓ (the happy-path assertion from the spec)
    j2 = client.post(
        f"{API}/transitions/{tid}/optimize", json={**body, "budget_value": 80_000}
    ).json()
    assert j2["post"]["te"] < j["post"]["te"]


def test_locks(client: TestClient) -> None:
    tid = new_transition(client)
    lots = client.get(f"{API}/accounts/acc_017").json()["lots"]
    unlocked = [x["lot_id"] for x in lots if not x["locked"]]
    r = client.put(f"{API}/transitions/{tid}/locks", json={"lot_ids": unlocked[:5]})
    assert r.status_code == 200 and r.json()["locked_lot_ids"] == sorted(unlocked[:5])
    j = client.post(
        f"{API}/transitions/{tid}/optimize",
        json={"budget_mode": "none", "target_model_id": "TR-CORE-96-04"},
    ).json()
    assert not set(unlocked[:5]) & {s["lot_id"] for s in j["trades"]["sells"]}
    bad = client.put(f"{API}/transitions/{tid}/locks", json={"lot_ids": ["lot_999999"]})
    assert bad.status_code == 422
    # changing locks invalidates downstream results
    client.put(f"{API}/transitions/{tid}/locks", json={"lot_ids": []})
    assert not client.get(f"{API}/transitions/{tid}").json()["has_optimization"]


def test_frontier_and_chosen_point(client: TestClient) -> None:
    tid = new_transition(client)
    client.post(
        f"{API}/transitions/{tid}/optimize",
        json={"budget_mode": "tax", "budget_value": 30_000, "target_model_id": "TR-CORE-96-04"},
    )
    f = client.post(f"{API}/transitions/{tid}/frontier", json={"n_points": 10}).json()
    assert len(f["points"]) == 10 and f["max_budget"] > 0
    tes = [p["te"] for p in f["points"]]
    assert all(b <= a + 1e-5 for a, b in pairwise(tes))
    assert f["chosen_index"] is not None
    assert abs(f["points"][f["chosen_index"]]["budget"] - 30_000) <= f["max_budget"] / 9
    assert client.post(f"{API}/transitions/{tid}/frontier", json={"n_points": 2}).status_code == 422


def test_glide_path_and_exports(client: TestClient) -> None:
    tid = new_transition(client)
    j = client.post(
        f"{API}/transitions/{tid}/optimize",
        json={
            "budget_mode": "net_gain",
            "budget_value": 60_000,
            "target_model_id": "INC-60-40",
            "glide_path_budgets": [60_000, 60_000],
            "constraints": {"min_trade_value": 1000, "lot_relief": "hifo"},
        },
    ).json()
    assert [y["year"] for y in j["glide_path"]] == [1, 2]
    assert j["glide_path"][1]["te_after"] <= j["glide_path"][0]["te_after"]
    csv = client.get(f"{API}/transitions/{tid}/trades.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.strip().splitlines()
    assert "Not tax or investment advice" in lines[0]
    assert len(lines) == 3 + len(j["trades"]["sells"]) + len(j["trades"]["buys"])
    pdf = client.get(f"{API}/transitions/{tid}/summary.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    import io

    with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
        text = doc.pages[0].extract_text() or ""
    assert "Not tax or investment advice" in text and "INC-60-40" in text


def test_ira_transition(client: TestClient) -> None:
    tid = new_transition(client, "cli_001", "acc_003")
    j = client.post(
        f"{API}/transitions/{tid}/optimize", json={"budget_mode": "tax", "budget_value": 0}
    ).json()
    assert not j["taxable"] and j["realized"]["est_tax"] == 0
    assert j["post"]["te"] < 0.005  # tax-free: can move fully into its current target


def test_three_portfolio_analytics(client: TestClient) -> None:
    tid = new_transition(client)
    body = {"budget_mode": "tax", "budget_value": 25_000, "target_model_id": "TR-CORE-56-44"}
    j = client.post(f"{API}/transitions/{tid}/optimize", json=body).json()
    w = j["portfolios"]
    for k in ("current", "transition", "target"):
        assert sum(w[k].values()) == pytest.approx(1.0, abs=1e-4)
    r = client.get(f"{API}/transitions/{tid}/analytics")
    assert r.status_code == 200, r.text
    a = r.json()
    assert set(a["reports"]) == {"current", "transition", "target"}
    assert a["te_ex_ante"]["transition"] == j["post"]["te"]
    rep = a["reports"]
    # every portfolio is measured against the target, not a blended index
    assert {x["benchmark"]["short"] for x in rep.values()} == {"Target"}
    assert rep["target"]["tracking_error"] == pytest.approx(0.0, abs=1e-9)
    assert rep["target"]["equity_pct"] == pytest.approx(0.56, abs=0.01)
    # the transition lands between today's portfolio and the target
    gap = {k: abs(rep[k]["equity_pct"] - rep["target"]["equity_pct"]) for k in rep}
    assert gap["transition"] <= gap["current"] + 1e-6
    assert client.get(f"{API}/transitions/{new_transition(client)}/analytics").status_code == 404


def test_diagnosis_and_fixes(client: TestClient) -> None:
    d = client.get(f"{API}/accounts/acc_017/diagnosis", params={"use_target": False}).json()
    assert d["benchmark_kind"] == "blend" and d["findings"]
    checks = {f["check"] for f in d["findings"]}
    assert checks & {"concentration", "sector", "region", "risk", "tax", "cash"}
    for f in d["findings"]:
        assert f["title"] and f["detail"] and set(f["fixes"]) <= set(d["fixes"])
    dt = client.get(f"{API}/accounts/acc_017/diagnosis",
                    params={"target_model_id": "TR-CORE-56-44"}).json()
    assert dt["benchmark_kind"] == "target" and dt["benchmark"]["short"] == "Target"
    h = client.get(f"{API}/clients/cli_009/diagnosis").json()
    assert h["scope"] == "household" and h["market_value"] >= d["market_value"]

    # fixes picked on the client page travel with the new transition; the cap holds
    r = client.post(f"{API}/transitions", json={"client_id": "cli_009", "account_id": "acc_017",
                                               "fixes": ["cap_stocks", "bogus"]})
    tid = r.json()["transition_id"]
    t = client.post(f"{API}/transitions/{tid}/chat", json={"quick_reply": "use_existing"}).json()
    assert t["state"] == "ACCOUNT_REVIEW" and t["ui_payload"]["data"]["applied"] == ["cap_stocks"]
    body = {"budget_mode": "none", "target_model_id": "TR-CORE-56-44",
            "constraints": {"max_stock_weight": 0.05, "round_shares": False}}
    j = client.post(f"{API}/transitions/{tid}/optimize", json=body).json()
    w = j["portfolios"]["transition"]
    stocks = {k: v for k, v in w.items() if not k.startswith("SCH") and k != "CASH"}
    lots = client.get(f"{API}/accounts/acc_017").json()["lots"]
    locked_t = {x["ticker"] for x in lots if x["locked"]}
    over = {k for k, v in stocks.items() if v > 0.05 + 1e-3}
    assert stocks and over <= locked_t  # only locked positions may stay above the cap
    assert max(w.get(k, 0) for k in ("SCHZ", "SCHX")) > 0.05  # funds aren't capped
