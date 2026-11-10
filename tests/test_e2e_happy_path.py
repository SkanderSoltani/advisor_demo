"""End-to-end happy path, through the public API only (spec §10).

Advisor logs in → sees the book → onboards a household → adds an empty account → starts a
transition → uploads a tax-lot PDF → reviews and confirms → gets help choosing a target →
compares models → confirms → locks a position → tries several tax budgets → reviews the
frontier → approves → sees the transition in the account and book.

Asserts the spec's sensible-output checks: TE falls as the budget rises, locked lots are never
sold, and tax never exceeds the budget.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm import MockLLM, get_llm
from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.db import models as m
from app.db.sample_pdf import render_statement_pdf
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.ingest.plaid_client import MockPlaidGateway, get_plaid_gateway
from app.main import create_app
from tests.conftest import TEST_AS_OF, TEST_SEED

API = "/api/v1"
BUDGETS = [0.0, 10_000.0, 40_000.0, 120_000.0]


@pytest.fixture(scope="module")
def world(
    market: SyntheticMarket, provider: RandomAnalyticsProvider, tmp_path_factory: Any
) -> Iterator[tuple[TestClient, Path]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    pdf = tmp_path_factory.mktemp("e2e") / "statement.pdf"
    with maker() as s:
        seed_demo(s, engine, market, TEST_SEED)
        legacy = s.query(m.Account).filter(m.Account.target_model_id.is_(None)).one()
        render_statement_pdf(s, legacy.id, pdf, TEST_AS_OF)

    app = create_app(sync_catalog=False)

    def _db() -> Iterator[object]:
        with maker() as s:
            yield s

    prices = provider.get_prices(list(market.universe.index))
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_llm] = MockLLM
    app.dependency_overrides[get_plaid_gateway] = lambda: MockPlaidGateway(prices, TEST_SEED)
    with TestClient(app) as c:
        yield c, pdf


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text[:600]
    return r.json()


def test_happy_path(world: tuple[TestClient, Path]) -> None:
    c, pdf = world

    # ---- 1. login and the landing page
    assert c.get(f"{API}/book/summary").status_code == 401
    login = ok(c.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}))
    c.headers["Authorization"] = f"Bearer {login['access_token']}"
    book = ok(c.get(f"{API}/book/summary"))
    assert book["data_source"] == "mock_random" and book["n_clients"] == 9
    assert ok(c.get(f"{API}/book/analytics/tracking-error?window=63"))["series"]
    assert ok(c.get(f"{API}/models"))["total"] == 2

    # ---- 2. onboard a household and an empty taxable account
    client = ok(
        c.post(
            f"{API}/clients",
            json={
                "name": "Rivera Household",
                "email": "rivera@example.com",
                "client_type": "couple",
                "tax_profile": {
                    "federal_st_rate": 0.35,
                    "federal_lt_rate": 0.238,
                    "state": "CA",
                    "state_rate": 0.133,
                },
            },
        ),
        201,
    )
    acct = ok(
        c.post(
            f"{API}/clients/{client['id']}/accounts",
            json={
                "account_type": "joint_taxable",
                "custodian": "Schwab",
                "nickname": "Joint (legacy)",
            },
        ),
        201,
    )
    assert acct["n_lots"] == 0 and client["status"] == "onboarding"

    # ---- 3. start the guided transition; ingest a statement
    tid = ok(
        c.post(f"{API}/transitions", json={"client_id": client["id"], "account_id": acct["id"]}),
        201,
    )["transition_id"]

    def chat(**body: Any) -> dict[str, Any]:
        return ok(c.post(f"{API}/transitions/{tid}/chat", json=body))  # type: ignore[no-any-return]

    turn = chat()
    assert turn["state"] == "INGEST_CHOICE" and turn["progress"]["step"] == 1
    turn = chat(message="I'll upload a statement")
    assert turn["ui_payload"]["data"]["pdf_upload_url"] == f"{API}/ingest/pdf"
    with pdf.open("rb") as f:
        preview = ok(
            c.post(
                f"{API}/ingest/pdf",
                data={"transition_id": tid},
                files={"file": ("statement.pdf", f, "application/pdf")},
            )
        )
    assert preview["method"] == "table" and preview["summary"]["n_error_rows"] == 0
    assert ok(c.get(f"{API}/accounts/{acct['id']}"))["account"]["n_lots"] == 0  # not committed

    turn = chat()
    assert turn["state"] == "INGEST_REVIEW" and turn["ui_payload"]["type"] == "parse_preview"
    turn = chat(quick_reply="confirm")
    assert turn["state"] == "TARGET_KNOWLEDGE"
    detail = ok(c.get(f"{API}/accounts/{acct['id']}"))
    assert detail["account"]["n_lots"] == preview["summary"]["n_rows"]
    assert detail["account"]["market_value"] > 2_000_000

    # ---- 4. choose a target with help
    turn = chat(message="not sure — help me choose")
    assert turn["state"] == "Q_OBJECTIVE"
    turn = chat(message="total return please")
    assert turn["state"] == "TARGET_COMPARE"
    comparison = turn["ui_payload"]["data"]["comparisons"]
    assert comparison[0]["model"]["id"] == "SCHWAB-TR"
    full_tax = comparison[0]["full_transition"]["est_tax"]
    assert full_tax > max(BUDGETS[:-1])
    turn = chat(quick_reply="choose:SCHWAB-TR")
    turn = chat(message="yes")
    assert turn["state"] == "TRANSITION_SETUP"

    # ---- 5. lock the largest position
    biggest = max(detail["holdings"], key=lambda h: h["market_value"])["ticker"]
    turn = chat(message=f"don't sell {biggest}")
    assert turn["interpretation"]["intent"] == "lock"
    locked_ids = set(ok(c.get(f"{API}/transitions/{tid}"))["locked_lot_ids"])
    assert locked_ids == {x["lot_id"] for x in detail["lots"] if x["ticker"] == biggest}

    # ---- 6. budgets: TE falls as the budget rises; tax ≤ budget; locked lots never sold
    tes = []
    for b in BUDGETS:
        turn = chat(quick_reply=f"budget:tax:{b:.0f}")
        assert turn["state"] == "TRANSITION_RESULTS"
        opt = turn["ui_payload"]["data"]["optimization"]
        assert opt["realized"]["est_tax"] <= b + 1.0
        assert not locked_ids & {s["lot_id"] for s in opt["trades"]["sells"]}
        assert opt["diagnostics"]["status"] == "optimal"
        tes.append(opt["post"]["te"])
    assert all(later < earlier for earlier, later in pairwise(tes)), tes
    assert tes[0] < opt["pre"]["te"]  # even a $0 budget improves TE by harvesting losses
    assert any(c_["reason"] == "locked" for c_ in opt["diagnostics"]["te_contributions"])

    frontier = turn["ui_payload"]["data"]["frontier"]["points"]
    assert all(q["te"] <= p["te"] + 1e-5 for p, q in pairwise(frontier))
    assert all(p["est_tax"] <= p["budget"] + 1.0 for p in frontier)

    # ---- 7. settle on $40k, export, approve
    turn = chat(message="I'd rather not pay more than 40k in taxes")
    final = turn["ui_payload"]["data"]["optimization"]
    assert final["budget_value"] == 40_000 and final["realized"]["est_tax"] <= 40_001
    csv = c.get(f"{API}/transitions/{tid}/trades.csv")
    assert csv.status_code == 200 and "Not tax or investment advice" in csv.text
    # sells carry the lot's Lot ID, in the results and in the CSV
    refs = {x["lot_id"]: x["lot_ref"] for x in detail["lots"]}
    assert all(s["lot_ref"] == refs[s["lot_id"]] for s in final["trades"]["sells"])
    assert all(s["lot_ref"] in csv.text for s in final["trades"]["sells"])
    pdf_bytes = c.get(f"{API}/transitions/{tid}/summary.pdf").content
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as doc:
        assert "SCHWAB-TR" in (doc.pages[0].extract_text() or "")

    turn = chat(quick_reply="approve")
    assert turn["state"] == "TRANSITION_APPROVE"
    turn = chat(action="approve")
    assert turn["state"] == "DONE"
    event_id = turn["ui_payload"]["data"]["event_id"]

    # ---- 8. the account, client and book reflect the transition
    event = ok(c.get(f"{API}/events/{event_id}"))
    assert event["type"] == "transition" and event["te_after"] == pytest.approx(final["post"]["te"])
    assert event["n_trades"] == len(final["trades"]["sells"]) + len(final["trades"]["buys"])
    after = ok(c.get(f"{API}/accounts/{acct['id']}"))
    assert after["account"]["target_model_id"] == "SCHWAB-TR"
    assert after["account"]["ex_ante_te"] == pytest.approx(final["post"]["te"], abs=1e-4)
    assert {h["ticker"] for h in after["holdings"]} >= {
        b["ticker"] for b in final["trades"]["buys"]
    }
    assert all(
        x["lot_id"] in {y["lot_id"] for y in after["lots"]}
        for x in detail["lots"]
        if x["lot_id"] in locked_ids
    )
    after_refs = [x["lot_ref"] for x in after["lots"]]  # new buy lots get fresh Lot IDs
    assert all(after_refs) and len(set(after_refs)) == len(after_refs)
    events = ok(c.get(f"{API}/clients/{client['id']}/events"))
    assert events["total"] == 1
    book_after = ok(c.get(f"{API}/book/summary"))
    assert book_after["n_clients"] == 10 and book_after["n_accounts"] == book["n_accounts"] + 1
    row = next(r for r in ok(c.get(f"{API}/clients?search=rivera"))["items"])
    assert row["status"] != "onboarding" and row["target_models"] == ["SCHWAB-TR"]
