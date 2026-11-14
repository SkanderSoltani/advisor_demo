"""Ingestion: normalizer, PDF parser (table + LLM fallback), LLM adapters, Plaid, API flow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm import AnthropicLLM, ExtractedLot, LLMError, LotExtraction, MockLLM, get_llm
from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.db import models as m
from app.db.sample_pdf import render_messy_statement_pdf, render_statement_pdf
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.ingest.normalizer import (
    SecurityRef,
    map_header,
    normalize_rows,
    parse_date,
    parse_number,
)
from app.ingest.pdf_parser import PdfError, parse_pdf
from app.ingest.plaid_client import (
    MOCK_PUBLIC_TOKEN,
    MockPlaidGateway,
    PlaidHolding,
    PlaidPortfolio,
    PlaidTxn,
    get_plaid_gateway,
    holdings_to_rows,
)
from app.main import create_app
from tests.conftest import TEST_AS_OF, TEST_SEED

API = "/api/v1"


# ---------------------------------------------------------------- normalizer
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,234.50", 1234.5),
        ("(12.00)", -12.0),
        ("12.00-", -12.0),
        ("-3", -3.0),
        ("—", None),
        ("", None),
        ("abc", None),
        (7, 7.0),
        (" 1,000 ", 1000.0),
    ],
)
def test_parse_number(raw: object, expected: float | None) -> None:
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "01/05/2021",
        "1/5/21",
        "2021-01-05",
        "Jan 05, 2021",
        "Jan 5 2021",
        "January 5, 2021",
        "05-Jan-2021",
    ],
)
def test_parse_date(raw: str) -> None:
    assert parse_date(raw) == date(2021, 1, 5)


def test_parse_date_invalid() -> None:
    assert parse_date("13/45/2021") is None and parse_date(None) is None


def test_map_header() -> None:
    h = map_header(
        [
            "Sym",
            "Security Description",
            "Open Date",
            "Qty",
            "Adj Cost Basis",
            "Mkt Value",
            "Gain/(Loss)",
        ]
    )
    assert h == {
        0: "ticker",
        1: "description",
        2: "acquired_date",
        3: "quantity",
        4: "cost_basis_total",
        5: "current_value",
        6: "gain",
    }


SECS = {"AAA": SecurityRef("AAA", "Alpha Corp", 10.0), "BBB": SecurityRef("BBB", "Beta Inc", 20.0)}


def _codes(row: Any) -> set[str]:
    return {i.code for i in row.issues}


def test_normalize_validation() -> None:
    raw = [
        {
            "ticker": "AAA",
            "quantity": "10",
            "acquired_date": "2020-01-02",
            "cost_basis_total": "50",
            "current_value": "100",
        },
        {
            "ticker": "AAX",
            "description": "Alpha Corp",
            "quantity": "1",
            "acquired_date": "2020-01-02",
            "cost_basis_total": "5",
        },
        {"ticker": "BBB", "quantity": "-2", "acquired_date": "", "cost_basis_total": None},
        {
            "ticker": "BBB",
            "quantity": "1",
            "acquired_date": "2030-01-01",
            "cost_basis_total": "1",
            "current_value": "99",
        },
        {
            "ticker": "AAA",
            "quantity": "10",
            "acquired_date": "2020-01-02",
            "cost_basis_total": "50",
        },
    ]
    rows = normalize_rows(raw, SECS, TEST_AS_OF)
    ok, typo, bad, future, dup = rows
    assert not ok.issues and ok.confidence == 1.0 and ok.holding_period == "LT"
    assert ok.unrealized_gain == 50.0 and ok.market_value == 100.0
    assert "unknown_ticker" in _codes(typo) and typo.suggested_ticker == "AAA"
    assert {"negative_quantity", "missing_date", "missing_basis"} <= _codes(bad)
    assert bad.has_errors and bad.confidence < 0.5
    assert {"future_date", "value_mismatch"} <= _codes(future)
    assert "duplicate_row" in _codes(dup) and not dup.has_errors


# ---------------------------------------------------------------- PDF parser
@pytest.fixture(scope="module")
def pdfs(tmp_path_factory: pytest.TempPathFactory, engine: Any, seeded: Any) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("pdf")
    with sessionmaker(bind=engine)() as s:
        acct = s.query(m.Account).filter(m.Account.target_model_id.is_(None)).one()
        return {
            "clean": render_statement_pdf(s, acct.id, d / "clean.pdf", TEST_AS_OF),
            "messy": render_messy_statement_pdf(s, acct.id, d / "messy.pdf", TEST_AS_OF),
            "account": acct.id,  # type: ignore[dict-item]
        }


@pytest.fixture(scope="module")
def secrefs(engine: Any, seeded: Any, provider: RandomAnalyticsProvider) -> dict[str, SecurityRef]:
    with sessionmaker(bind=engine)() as s:
        rows = s.query(m.Security).all()
        prices = provider.get_prices([r.ticker for r in rows])
        return {r.ticker: SecurityRef(r.ticker, r.name, prices[r.ticker]) for r in rows}


def _truth(db: Session, account_id: str) -> list[tuple[str, float, float, date]]:
    lots = db.query(m.Lot).filter_by(account_id=account_id).all()
    return sorted((x.ticker, x.quantity, x.cost_basis_total, x.acquired_date) for x in lots)


def test_parse_clean_pdf_with_tables(
    pdfs: dict[str, Path], secrefs: dict[str, SecurityRef], db: Session
) -> None:
    r = parse_pdf(pdfs["clean"].read_bytes(), secrefs, TEST_AS_OF, MockLLM())
    assert r.method == "table" and r.confidence > 0.95
    truth = _truth(db, str(pdfs["account"]))
    got = sorted((x.ticker, x.quantity, x.cost_basis_total, x.acquired_date) for x in r.rows)
    assert len(got) == len(truth)
    for g, t in zip(got, truth, strict=True):
        assert g[0] == t[0] and g[3] == t[3]
        assert g[1] == pytest.approx(t[1], abs=1e-3) and g[2] == pytest.approx(t[2], abs=0.01)
    assert r.cash is not None and r.statement_date == TEST_AS_OF


def test_parse_messy_pdf_falls_back_to_llm(
    pdfs: dict[str, Path], secrefs: dict[str, SecurityRef], db: Session
) -> None:
    r = parse_pdf(pdfs["messy"].read_bytes(), secrefs, TEST_AS_OF, MockLLM())
    assert r.method == "llm" and r.llm_provider == "mock"
    truth = _truth(db, str(pdfs["account"]))
    assert len(r.rows) == len(truth)
    errors = [x for x in r.rows if x.has_errors]
    assert len(errors) == 1 and "unknown_ticker" in _codes(errors[0])
    assert errors[0].suggested_ticker in {t[0] for t in truth}
    good = sorted((x.quantity, x.cost_basis_total, x.acquired_date) for x in r.rows)
    want = sorted((t[1], t[2], t[3]) for t in truth)
    for g, w in zip(good, want, strict=True):
        assert g[0] == pytest.approx(w[0], abs=1e-3) and g[1] == pytest.approx(w[1], abs=0.01)
        assert g[2] == w[2]


def _truth_refs(db: Session, account_id: str) -> set[tuple[str, date, str | None]]:
    lots = db.query(m.Lot).filter_by(account_id=account_id).all()
    return {(x.ticker, x.acquired_date, x.lot_ref) for x in lots}


@pytest.mark.parametrize("which", ["clean", "messy"])
def test_parse_pdf_reads_lot_ids(
    which: str, pdfs: dict[str, Path], secrefs: dict[str, SecurityRef], db: Session
) -> None:
    r = parse_pdf(pdfs[which].read_bytes(), secrefs, TEST_AS_OF, MockLLM())
    truth = _truth_refs(db, str(pdfs["account"]))
    refs = [x.lot_ref for x in r.rows]
    assert all(refs) and len(set(refs)) == len(refs)
    assert set(refs) == {t[2] for t in truth}
    good = {(x.ticker, x.acquired_date, x.lot_ref) for x in r.rows if not x.has_errors}
    assert good <= truth  # each Lot ID stays with its own lot


def test_normalize_duplicate_lot_id() -> None:
    row = {"ticker": "AAA", "quantity": "1", "acquired_date": "2020-01-02", "cost_basis_total": "5"}
    sec = {"AAA": SecurityRef("AAA", "Alpha", 10.0)}
    out = normalize_rows(
        [
            dict(row, lot_ref="X-1"),
            dict(row, quantity="2", lot_ref=" X-1 "),
            dict(row, quantity="3"),
        ],
        sec,
        date(2026, 1, 1),
    )
    assert out[0].lot_ref == "X-1" and not out[0].has_errors
    assert "duplicate_lot_id" in _codes(out[1]) and out[1].has_errors
    assert out[2].lot_ref is None and not out[2].has_errors


def test_next_lot_refs() -> None:
    from app.db.lot_refs import make_lot_ref, next_lot_refs

    assert make_lot_ref("acc_017", 42) == "L017-0042"
    got = next_lot_refs("acc_017", ["L017-0001", "L017-0003", "BROKER-9", None], 3)
    assert got == ["L017-0004", "L017-0005", "L017-0006"]


class FailingLLM(MockLLM):
    def extract_lots(self, pdf_bytes: bytes, text: str) -> LotExtraction:
        raise LLMError("offline")


def test_parse_errors(pdfs: dict[str, Path], secrefs: dict[str, SecurityRef]) -> None:
    with pytest.raises(PdfError, match="Not a PDF"):
        parse_pdf(b"hello", secrefs, TEST_AS_OF, MockLLM())
    with pytest.raises(PdfError, match="Could not extract"):
        parse_pdf(pdfs["messy"].read_bytes(), secrefs, TEST_AS_OF, FailingLLM())


# ---------------------------------------------------------------- LLM adapters
def test_mock_assign_uses_price_relationship() -> None:
    # qty, cost, price, value, gain
    assert MockLLM._assign([10.0, 500.0, 75.0, 750.0, 250.0]) == (10.0, 500.0, 750.0)
    # qty, cost, value, gain (no price column)
    assert MockLLM._assign([10.0, 500.0, 750.0, 250.0]) == (10.0, 500.0, 750.0)


def test_anthropic_adapter_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    parsed = LotExtraction(rows=[ExtractedLot(ticker="AAA", quantity=1.0)])

    def fake_parse(**kwargs: Any) -> Any:
        calls.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, _request_id="req_1")

    llm = AnthropicLLM("claude-opus-5-5")
    monkeypatch.setattr(llm.client.beta.messages, "parse", fake_parse)
    out = llm.extract_lots(b"%PDF-1.4 test", "text")
    assert out == parsed
    assert calls["model"] == "claude-opus-5-5" and calls["output_format"] is LotExtraction
    assert calls["fallbacks"] == "default"
    assert calls["betas"] == ["server-side-fallback-2026-07-01"]
    content = calls["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[0]["source"]["media_type"] == "application/pdf"
    assert "temperature" not in calls and "thinking" not in calls

    monkeypatch.setattr(
        llm.client.beta.messages,
        "parse",
        lambda **_: SimpleNamespace(stop_reason="refusal", parsed_output=None, _request_id="r"),
    )
    with pytest.raises(LLMError, match="declined"):
        llm.extract_lots(b"%PDF", "")


def test_anthropic_adapter_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    llm = AnthropicLLM("claude-opus-5-5", server_fallback=False)
    monkeypatch.setattr(
        llm.client.beta.messages,
        "parse",
        lambda **kw: (
            calls.update(kw)
            or SimpleNamespace(
                stop_reason="end_turn", parsed_output=LotExtraction(rows=[]), _request_id="r"
            )
        ),
    )
    llm.extract_lots(b"%PDF", "")
    assert "fallbacks" not in calls and "betas" not in calls


# ---------------------------------------------------------------- Plaid
def test_holdings_to_rows_rebuilds_lots() -> None:
    pf = PlaidPortfolio(
        holdings=[
            PlaidHolding("AAA", "Alpha", 10.0, 80.0, 100.0),
            PlaidHolding("BBB", "Beta", 5.0, None, 100.0),
        ],
        transactions=[
            PlaidTxn(date(2024, 1, 2), "buy", "AAA", 4.0, 6.0),
            PlaidTxn(date(2025, 6, 2), "buy", "AAA", 4.0, 9.0),
            PlaidTxn(date(2025, 7, 2), "sell", "AAA", 2.0, 9.5),
        ],
    )
    rows = holdings_to_rows(pf, TEST_AS_OF)
    aaa = [r for r in rows if r["ticker"] == "AAA"]
    assert [r["quantity"] for r in aaa] == [4.0, 4.0, 2.0]  # newest buys first, then remainder
    assert aaa[0]["acquired_date"] == date(2025, 6, 2) and aaa[0]["cost_basis_total"] == 36.0
    assert aaa[2]["acquired_date"] is None and aaa[2]["basis_estimated"] is True
    assert aaa[2]["cost_basis_total"] == pytest.approx(16.0)  # 20% of the average-cost basis
    bbb = [r for r in rows if r["ticker"] == "BBB"]
    assert len(bbb) == 1 and bbb[0]["cost_basis_total"] is None


def test_mock_gateway_deterministic(provider: RandomAnalyticsProvider) -> None:
    prices = provider.get_prices(list(provider.market.universe.index))
    g = MockPlaidGateway(prices, TEST_SEED)
    tok = g.exchange_public_token(MOCK_PUBLIC_TOKEN)
    a, b = g.fetch_portfolio(tok, TEST_AS_OF), g.fetch_portfolio(tok, TEST_AS_OF)
    assert a.holdings == b.holdings and len(a.holdings) == 24
    assert any(h.cost_basis is None for h in a.holdings)


# ---------------------------------------------------------------- API
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

    prices = provider.get_prices(list(market.universe.index))
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_llm] = MockLLM
    app.dependency_overrides[get_plaid_gateway] = lambda: MockPlaidGateway(prices, TEST_SEED)
    with TestClient(app) as c:
        tok = c.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
        yield c


def _new_empty(c: TestClient) -> tuple[str, str]:
    a = c.post(
        f"{API}/clients/cli_009/accounts",
        json={"account_type": "joint_taxable", "custodian": "Schwab"},
    ).json()
    t = c.post(f"{API}/transitions", json={"client_id": "cli_009", "account_id": a["id"]}).json()
    return a["id"], t["transition_id"]


def test_pdf_upload_preview_and_confirm(client: TestClient, pdfs: dict[str, Path]) -> None:
    acct, tid = _new_empty(client)
    assert client.post(f"{API}/ingest/{tid}/confirm", json={"rows": []}).status_code == 409
    with pdfs["messy"].open("rb") as f:
        r = client.post(
            f"{API}/ingest/pdf",
            data={"transition_id": tid},
            files={"file": ("s.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["method"] == "llm" and pv["summary"]["n_error_rows"] == 1
    assert client.get(f"{API}/transitions/{tid}").json()["state"] == "INGEST_REVIEW"
    # nothing committed yet
    assert client.get(f"{API}/accounts/{acct}").json()["account"]["n_lots"] == 0

    rows = [
        {
            "row_id": x["row_id"],
            "lot_ref": x["lot_ref"],
            "ticker": x["ticker"],
            "quantity": x["quantity"],
            "acquired_date": x["acquired_date"],
            "cost_basis_total": x["cost_basis_total"],
        }
        for x in pv["rows"]
    ]
    assert all(x["lot_ref"] for x in pv["rows"])  # Lot IDs read from the statement
    bad = client.post(f"{API}/ingest/{tid}/confirm", json={"rows": rows})
    assert bad.status_code == 422 and len(bad.json()["detail"]["rows"]) == 1  # the typo
    typo = next(x for x in pv["rows"] if x["issues"])
    fixed = [
        dict(rw, ticker=typo["suggested_ticker"]) if rw["row_id"] == typo["row_id"] else rw
        for rw in rows
    ]
    fixed[0]["include"] = False
    fixed[1]["locked"] = True
    ok = client.post(f"{API}/ingest/{tid}/confirm", json={"rows": fixed})
    assert ok.status_code == 200, ok.text
    res = ok.json()
    assert res["n_committed"] == len(rows) - 1 and res["n_excluded"] == 1
    assert res["state"] == "TARGET_KNOWLEDGE" and res["cash"] == pv["cash_detected"]
    detail = client.get(f"{API}/accounts/{acct}").json()
    assert detail["account"]["n_lots"] == len(rows) - 1
    assert {x["source"] for x in detail["lots"]} == {"pdf"}
    assert sum(x["locked"] for x in detail["lots"]) == 1
    # the statement's Lot IDs are kept on the committed lots
    assert sorted(x["lot_ref"] for x in detail["lots"]) == sorted(r["lot_ref"] for r in fixed[1:])
    # preview consumed
    assert client.post(f"{API}/ingest/{tid}/confirm", json={"rows": fixed}).status_code == 409


def test_pdf_upload_rejections(client: TestClient) -> None:
    _, tid = _new_empty(client)
    r = client.post(
        f"{API}/ingest/pdf",
        data={"transition_id": tid},
        files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
    )
    assert r.status_code == 422
    big = b"%PDF" + b"0" * (10 * 1024 * 1024)
    r = client.post(
        f"{API}/ingest/pdf",
        data={"transition_id": tid},
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert r.status_code == 413
    r = client.post(
        f"{API}/ingest/pdf",
        data={"transition_id": "trn_nope"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 404


def test_plaid_flow_with_average_cost(client: TestClient) -> None:
    lt = client.post(f"{API}/ingest/plaid/link-token").json()
    assert lt["mode"] == "mock" and lt["mock_public_token"]
    acct, tid = _new_empty(client)
    pv = client.post(
        f"{API}/ingest/plaid/exchange",
        json={"public_token": lt["mock_public_token"], "transition_id": tid},
    ).json()
    assert pv["source"] == "plaid" and pv["requires_basis_decision"]
    rows = [
        {
            "ticker": x["ticker"],
            "quantity": x["quantity"],
            "acquired_date": x["acquired_date"],
            "cost_basis_total": x["cost_basis_total"],
        }
        for x in pv["rows"]
    ]
    assert client.post(f"{API}/ingest/{tid}/confirm", json={"rows": rows}).status_code == 422
    ok = client.post(
        f"{API}/ingest/{tid}/confirm", json={"rows": rows, "assume_average_cost": True}
    ).json()
    assert ok["n_committed"] == len(rows) and ok["assumptions"]
    lots = client.get(f"{API}/accounts/{acct}").json()["lots"]
    assert any(x["basis_unknown"] for x in lots) and {x["source"] for x in lots} == {"plaid"}
    refs = [x["lot_ref"] for x in lots]  # Plaid has no lot numbers: Lot IDs are assigned
    assert all(refs) and len(set(refs)) == len(refs)
    # the account can now be optimized
    o = client.post(
        f"{API}/transitions/{tid}/optimize",
        json={"budget_mode": "tax", "budget_value": 5000, "target_model_id": "TR-CORE-96-04"},
    )
    assert o.status_code == 200 and o.json()["realized"]["est_tax"] <= 5001
    bad = client.post(
        f"{API}/ingest/plaid/exchange", json={"public_token": "garbage", "transition_id": tid}
    )
    assert bad.status_code == 502
