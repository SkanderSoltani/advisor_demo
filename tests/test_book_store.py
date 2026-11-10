"""The book file (data/book/book.json): round trip, totals, write-through and reload."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm import MockLLM, get_llm
from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.db import models as m
from app.db.book_generator import generate_clients
from app.db.book_store import (
    check_book,
    disable_write_through,
    enable_write_through,
    export_book,
    read_book_file,
    save_book,
    set_price_source,
    sync_from_file,
    wait_for_book_writes,
    write_book_file,
)
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.main import create_app
from tests.conftest import TEST_AS_OF, TEST_SEED

API = "/api/v1"


def _engine() -> Any:
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


@pytest.fixture(scope="module")
def setup(
    market: SyntheticMarket, provider: RandomAnalyticsProvider, tmp_path_factory: Any
) -> Iterator[tuple[TestClient, Any, Path]]:
    """Own DB + a book file with write-through on (turned off again afterwards)."""
    engine = _engine()
    path = tmp_path_factory.mktemp("book") / "book.json"
    with sessionmaker(bind=engine)() as s:
        seed_demo(s, engine, market, TEST_SEED)
        save_book(s, path, TEST_AS_OF, provider.get_prices)
        s.commit()
    app = create_app(sync_catalog=False)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    def _db() -> Iterator[object]:
        with maker() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_llm] = MockLLM
    enable_write_through(path, TEST_AS_OF, provider.get_prices, engine=engine)
    try:
        with TestClient(app) as c:
            tok = c.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
            c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
            yield c, engine, path
    finally:
        disable_write_through()
        set_price_source(None)


def _file(path: Path) -> dict[str, Any]:
    assert wait_for_book_writes()  # the file is written in the background
    return json.loads(path.read_text())


def test_book_file_totals_add_up_and_match_the_app(setup: tuple[TestClient, Any, Path]) -> None:
    c, _, path = setup
    book = _file(path)
    assert check_book(book) == []
    s = book["summary"]
    api = c.get(f"{API}/book/summary").json()
    assert s["n_clients"] == api["n_clients"] and s["n_accounts"] == api["n_accounts"]
    assert s["total_aum"] == pytest.approx(api["total_aum"], abs=1.0)
    rows = {r["id"]: r for r in c.get(f"{API}/clients").json()["items"]}
    for cl in book["clients"]:
        assert cl["summary"]["aum"] == pytest.approx(rows[cl["id"]]["market_value"], abs=1.0)
    last = c.get(f"{API}/book/analytics/tax-impact").json()["periods"][-1]
    r = s["realized"]
    assert r["st_gain"] == pytest.approx(last["cum_realized_st_gain"], abs=1.0)
    assert r["lt_gain"] == pytest.approx(last["cum_realized_lt_gain"], abs=1.0)
    assert r["st_loss"] == pytest.approx(last["cum_realized_st_loss"], abs=1.0)
    assert r["lt_loss"] == pytest.approx(last["cum_realized_lt_loss"], abs=1.0)
    assert r["st_loss"] + r["lt_loss"] == pytest.approx(r["losses_harvested"], abs=1.0)
    assert r["est_taxes_saved"] == pytest.approx(last["cum_taxes_saved"], abs=1.0)


def test_round_trip_is_exact(setup: tuple[TestClient, Any, Path], market: SyntheticMarket) -> None:
    _, _engine_unused, path = setup
    data, _ = read_book_file(path)
    other = _engine()
    with sessionmaker(bind=other)() as s:
        seed_demo(s, other, market, TEST_SEED, book_data=data)
        again = export_book(s, TEST_AS_OF)
    assert again == data


def test_new_client_and_approved_transition_are_written(
    setup: tuple[TestClient, Any, Path],
) -> None:
    c, _, path = setup
    body = {
        "name": "Ada Book-File",
        "client_type": "individual",
        "email": "ada@example.com",
        "tax_profile": {
            "federal_st_rate": 0.37,
            "federal_lt_rate": 0.238,
            "state": "CA",
            "state_rate": 0.133,
        },
    }
    r = c.post(f"{API}/clients", json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert any(x["id"] == cid and x["name"] == "Ada Book-File" for x in _file(path)["clients"])
    assert c.get(f"{API}/book/summary").json()["n_clients"] == _file(path)["summary"]["n_clients"]

    # a full transition on a managed account: the approved event lands in the file
    tid = c.post(f"{API}/transitions", json={"client_id": "cli_001", "account_id": "acc_001"})
    tid = tid.json()["transition_id"]

    def chat(**b: Any) -> dict[str, Any]:
        resp = c.post(f"{API}/transitions/{tid}/chat", json=b)
        assert resp.status_code == 200, resp.text
        return resp.json()  # type: ignore[no-any-return]

    chat()
    chat(quick_reply="use_existing")
    chat(quick_reply="choose:SCHWAB-INC")
    chat(message="yes")
    t = chat(quick_reply="budget:tax:50000")
    assert t["state"] == "TRANSITION_RESULTS", t["state"]
    rz = t["ui_payload"]["data"]["optimization"]["realized"]
    holdings_before = {
        h["ticker"]: h["shares"]
        for a in next(cl for cl in _file(path)["clients"] if cl["id"] == "cli_001")["accounts"]
        if a["id"] == "acc_001"
        for h in a["summary"]["holdings"]
    }
    trades = t["ui_payload"]["data"]["optimization"]["trades"]
    t = chat(quick_reply="approve")
    assert t["state"] == "TRANSITION_APPROVE"
    assert any(q["label"] == "Trade" for q in t["quick_replies"])
    t = chat(action="approve")  # "Trade"
    assert t["state"] == "DONE" and "holdings are updated" in t["assistant_message"]
    event_id = t["ui_payload"]["data"]["event_id"]

    # holdings in the file = the account's holdings in the app, after the trades
    detail = c.get(f"{API}/accounts/acc_001").json()
    app_h = {h["ticker"]: h for h in detail["holdings"]}
    file_acct = next(
        a for cl in _file(path)["clients"] for a in cl["accounts"] if a["id"] == "acc_001"
    )
    file_h = {h["ticker"]: h for h in file_acct["summary"]["holdings"]}
    assert set(file_h) == set(app_h)
    for tk, h in file_h.items():
        assert h["shares"] == pytest.approx(app_h[tk]["quantity"], abs=1e-3)
        assert h["market_value"] == pytest.approx(app_h[tk]["market_value"], abs=0.05)
    for b in trades["buys"]:
        assert file_h[b["ticker"]]["shares"] >= b["shares"] - 1e-6
    sold = {}
    for sl in trades["sells"]:
        sold[sl["ticker"]] = sold.get(sl["ticker"], 0.0) + sl["shares"]
    for tk, q in sold.items():
        after = file_h.get(tk, {"shares": 0.0})["shares"]
        bought = sum(b["shares"] for b in trades["buys"] if b["ticker"] == tk)
        assert after == pytest.approx(holdings_before[tk] - q + bought, abs=2e-3)
    assert file_acct["summary"]["cash"] == pytest.approx(detail["account"]["cash"], abs=0.01)

    book = _file(path)
    acct = next(a for cl in book["clients"] for a in cl["accounts"] if a["id"] == "acc_001")
    ev = next(e for e in acct["events"] if e["id"] == event_id)
    assert ev["realized_st_gain"] == pytest.approx(rz["st_gain"], abs=0.01)
    assert ev["realized_lt_gain"] == pytest.approx(rz["lt_gain"], abs=0.01)
    assert ev["realized_st_loss"] == pytest.approx(rz["st_loss"], abs=0.01)
    assert ev["realized_lt_loss"] == pytest.approx(rz["lt_loss"], abs=0.01)
    assert acct["target_model_id"] == "SCHWAB-INC"
    assert check_book(book) == []
    # the cached book numbers were refreshed by the change
    api = c.get(f"{API}/book/summary").json()
    assert api["total_aum"] == pytest.approx(book["summary"]["total_aum"], abs=1.0)


def test_startup_reloads_an_edited_file(market: SyntheticMarket, tmp_path: Path) -> None:
    engine = _engine()
    path = tmp_path / "book.json"
    with sessionmaker(bind=engine)() as s:
        seed_demo(s, engine, market, TEST_SEED)
        assert sync_from_file(s, path, TEST_AS_OF) == "created"
        assert sync_from_file(s, path, TEST_AS_OF) == "unchanged"
    data = _file(path)
    data["clients"][0]["name"] = "Renamed In File"
    data["clients"][0]["summary"]["aum"] = 1.0  # stale summary: recomputed on reload
    write_book_file(path, data)
    with sessionmaker(bind=engine)() as s:
        assert sync_from_file(s, path, TEST_AS_OF) == "reloaded"
        assert s.get(m.Client, data["clients"][0]["id"]).name == "Renamed In File"  # type: ignore[union-attr]
    fixed = _file(path)
    assert fixed["clients"][0]["summary"]["aum"] > 1.0 and check_book(fixed) == []


def test_generator_hits_the_target() -> None:
    specs = generate_clients(TEST_SEED, 91, 1.45e9)
    assert len(specs) == 91 and len({s.name for s in specs}) == 91
    total = sum(a.market_value for s in specs for a in s.accounts)
    assert total == pytest.approx(1.45e9, rel=0.001)
    assert all(a.target_model_id in {"TR", "INC"} for s in specs for a in s.accounts)
    assert all(1.0 <= a.years_managed <= 3.0 for s in specs for a in s.accounts)


def test_delete_client_removes_it_everywhere(setup: tuple[TestClient, Any, Path]) -> None:
    c, engine, path = setup
    before = _file(path)
    victim = next(cl for cl in before["clients"] if cl["id"] == "cli_002")
    acct_ids = [a["id"] for a in victim["accounts"]]
    # a transition in progress on one of its accounts goes too
    t = c.post(f"{API}/transitions", json={"client_id": "cli_002", "account_id": acct_ids[0]})
    assert t.status_code == 201
    r = c.delete(f"{API}/clients/cli_002")
    assert r.status_code == 204, r.text
    assert c.get(f"{API}/clients/cli_002").status_code == 404
    assert c.get(f"{API}/accounts/{acct_ids[0]}").status_code == 404
    assert c.get(f"{API}/transitions/{t.json()['transition_id']}").status_code == 404
    assert c.delete(f"{API}/clients/cli_002").status_code == 404

    after = _file(path)
    assert all(cl["id"] != "cli_002" for cl in after["clients"])
    assert after["summary"]["n_clients"] == before["summary"]["n_clients"] - 1
    assert after["summary"]["total_aum"] == pytest.approx(
        before["summary"]["total_aum"] - victim["summary"]["aum"], abs=1.0
    )
    for k, v in victim["summary"]["realized"].items():
        assert after["summary"]["realized"][k] == pytest.approx(
            before["summary"]["realized"][k] - v, abs=1.0
        )
    assert check_book(after) == []
    api = c.get(f"{API}/book/summary").json()  # cached numbers refreshed
    assert api["n_clients"] == after["summary"]["n_clients"]
    assert api["total_aum"] == pytest.approx(after["summary"]["total_aum"], abs=1.0)
    with sessionmaker(bind=engine)() as s:
        assert s.query(m.Lot).filter(m.Lot.account_id.in_(acct_ids)).count() == 0
        assert (
            s.query(m.ManagementEvent).filter(m.ManagementEvent.account_id.in_(acct_ids)).count()
            == 0
        )
