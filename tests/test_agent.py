"""Guided conversation: interpreter rules, number guard, LLM adapters, engine flow via the API."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.guard import numbers_in_text, unverified_numbers
from app.agent.intents import (
    Intent,
    ModelRef,
    allowed_intents,
    parse_amount,
    rule_interpret,
    smalltalk_kind,
)
from app.agent.llm import AnthropicLLM, InterpretContext, MockLLM, get_llm
from app.agent.states import State, keys_after
from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.ingest.plaid_client import MockPlaidGateway, get_plaid_gateway
from app.main import create_app
from tests.conftest import TEST_SEED

API = "/api/v1"
MODELS = [
    ModelRef("TR-CORE-96-04", "Schwab Core Equity — Total Return", "total_return", "market_cap"),
    ModelRef("INC-60-40", "Schwab Dividend Income", "income", "market_cap_fundamental"),
]


# ---------------------------------------------------------------- rules
@pytest.mark.parametrize(
    ("state", "text", "intent", "slots"),
    [
        (
            State.TRANSITION_SETUP,
            "I'd rather not pay more than 20k in taxes",
            "set_budget",
            {"budget_mode": "tax", "budget_value": 20000.0},
        ),
        (
            State.TRANSITION_SETUP,
            "cap realized gains at $1.5m",
            "set_budget",
            {"budget_mode": "net_gain", "budget_value": 1_500_000.0},
        ),
        (
            State.TRANSITION_SETUP,
            "no limit, do the full transition",
            "set_budget",
            {"budget_mode": "none"},
        ),
        (State.TRANSITION_SETUP, "don't sell AAPL or MSFT", "lock", {"tickers": ["AAPL", "MSFT"]}),
        (State.TRANSITION_SETUP, "keep 2% in cash", "set_cash", {"cash_buffer": 0.02}),
        (State.TRANSITION_RESULTS, "looks good, approve", "approve", {}),
        (State.Q_OBJECTIVE, "we want dividends", "set_objective", {"objective": "income"}),
        (
            State.Q_CONSTRUCTION,
            "something with quality tilts",
            "set_construction",
            {"construction": "market_cap_fundamental"},
        ),
        (State.TARGET_KNOWLEDGE, "not sure, help me", "help", {}),
        (
            State.TARGET_PICK_LIST,
            "the dividend income one",
            "choose_model",
            {"model_id": "INC-60-40"},
        ),
        (State.INGEST_CHOICE, "I'll upload a statement", "upload_pdf", {}),
        (State.TARGET_CONFIRM, "yes go ahead", "yes", {}),
        (State.TARGET_CONFIRM, "what is the TE to INC-60-40?", "question", {}),
        (State.TRANSITION_SETUP, "go back", "back", {}),
        (State.TRANSITION_SETUP, "blorp", "unknown", {}),
        (State.INGEST_CHOICE, "hey are you here?", "smalltalk", {}),
        (State.TRANSITION_SETUP, "hello", "smalltalk", {}),
        (State.TARGET_PICK_LIST, "thanks!", "smalltalk", {}),
        (State.TRANSITION_RESULTS, "what can you do?", "smalltalk", {}),
        # a real request inside a greeting is still the request
        (
            State.TRANSITION_SETUP,
            "hey, keep taxes under $20k",
            "set_budget",
            {"budget_value": 20000},
        ),
        (State.TARGET_CONFIRM, "no thanks", "no", {}),
    ],
)
def test_rule_interpret(state: State, text: str, intent: str, slots: dict[str, Any]) -> None:
    it = rule_interpret(state, text, MODELS, {"AAPL", "MSFT", "SCHX"})
    assert it.intent == intent
    for k, v in slots.items():
        assert getattr(it, k) == v
    if intent not in ("unknown",):
        assert it.confidence >= 0.75


def test_ambiguous_amount_needs_confirmation() -> None:
    it = rule_interpret(State.TRANSITION_SETUP, "20k", MODELS, set())
    assert it.intent == "set_budget" and it.budget_value == 20000 and it.confidence < 0.75


def test_parse_amount() -> None:
    assert parse_amount("$25,000") == 25000 and parse_amount("2.5 million") == 2_500_000
    assert parse_amount("12%") is None


def test_keys_after() -> None:
    assert "optimization" in keys_after(State.TRANSITION_SETUP)
    assert "setup" not in keys_after(State.TRANSITION_SETUP)
    assert {"objective", "setup"} <= set(keys_after(State.TARGET_KNOWLEDGE))


# ---------------------------------------------------------------- guard
def test_number_guard() -> None:
    facts = {"te": 0.0415, "tax": 24999.77, "n": 47}
    assert numbers_in_text("TE 4.15% and $25,000; 20k") == [4.15, 25000.0, 20000.0]
    assert unverified_numbers("TE falls to 4.15% with tax $24,999.77 over 47 sells", facts) == []
    assert unverified_numbers("tax $25,000 or 25k", facts) == []  # rounding at shown precision
    assert unverified_numbers("tax $25,100", facts) == [25100.0]  # not a rounding of 24,999.77
    assert unverified_numbers("TE 4.2%", facts) == []
    assert unverified_numbers("saves 3 steps", facts) == []  # small integers allowed
    assert unverified_numbers("TE 9.99%", facts) == [9.99]


# ---------------------------------------------------------------- Anthropic adapter (no network)
def _ctx(state: State = State.TRANSITION_SETUP) -> InterpretContext:
    return InterpretContext(state, allowed_intents(state), MODELS, {"AAPL"})


def test_anthropic_interpret_validates_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = AnthropicLLM("claude-opus-5-5")
    seen: dict[str, Any] = {}

    def parse(**kw: Any) -> Any:
        seen.update(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            parsed_output=Intent(
                intent="set_budget", confidence=0.95, budget_mode="tax", budget_value=15000
            ),
        )

    monkeypatch.setattr(llm.client.beta.messages, "parse", parse)
    it = llm.interpret(_ctx(), "keep taxes to 15 grand")
    assert it.budget_value == 15000 and seen["output_format"] is Intent
    assert seen["output_config"] == {"effort": "low"} and seen["fallbacks"] == "default"
    # an intent outside the allowed set falls back to the rule interpreter
    monkeypatch.setattr(
        llm.client.beta.messages,
        "parse",
        lambda **_: SimpleNamespace(
            stop_reason="end_turn", parsed_output=Intent(intent="launch_rockets", confidence=1)
        ),
    )
    assert llm.interpret(_ctx(), "lock AAPL").intent == "lock"


def _block(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def test_anthropic_question_tool_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = AnthropicLLM("claude-opus-5-5")
    calls: list[dict[str, Any]] = []
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[
                _block(type="text", text="Checking."),
                _block(
                    type="tool_use", id="tu_1", name="te_to_model", input={"model_id": "INC-60-40"}
                ),
            ],
        ),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[
                _block(type="text", text="TE to INC-60-40 is 6.15%."),
            ],
        ),
    ]

    def create(**kw: Any) -> Any:
        calls.append(kw)
        return responses[len(calls) - 1]

    monkeypatch.setattr(llm.client.beta.messages, "create", create)
    tools = SimpleNamespace(
        read_only_dispatch=lambda: {
            "te_to_model": lambda model_id: {"model_id": model_id, "te_from_current": 0.0615}
        }
    )
    answer, outputs = llm.answer_question("TE to income?", tools, "ctx")
    assert answer == "TE to INC-60-40 is 6.15%."
    assert outputs == [{"model_id": "INC-60-40", "te_from_current": 0.0615}]
    assert calls[0]["tool_choice"] == {"type": "auto"}
    assert all(t["strict"] for t in calls[0]["tools"])
    second = calls[1]["messages"]
    assert second[1]["role"] == "assistant" and second[2]["content"][0]["tool_use_id"] == "tu_1"
    assert unverified_numbers(answer, outputs) == []


# ---------------------------------------------------------------- engine via API
class InventingLLM(MockLLM):
    """Polishes messages by adding a made-up number, and answers with invented figures."""

    provider = "test"

    def phrase(self, draft: str, facts: dict[str, Any]) -> str:
        return draft + "\n\nThis should save roughly $123,456 in taxes."

    def answer_question(self, question: str, tools: Any, context: str) -> tuple[str, list[Any]]:
        return "TE would be 1.23%.", []


@pytest.fixture()
def api(market: SyntheticMarket, provider: RandomAnalyticsProvider) -> Iterator[TestClient]:
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


class Chat:
    def __init__(self, c: TestClient, client_id: str, account_id: str) -> None:
        self.c = c
        r = c.post(f"{API}/transitions", json={"client_id": client_id, "account_id": account_id})
        self.tid = r.json()["transition_id"]

    def __call__(self, **body: Any) -> dict[str, Any]:
        r = self.c.post(f"{API}/transitions/{self.tid}/chat", json=body)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]


def test_full_guided_flow(api: TestClient) -> None:
    chat = Chat(api, "cli_009", "acc_017")
    t = chat()
    assert t["state"] == "INGEST_CHOICE" and t["progress"] == {
        "step": 1,
        "total": 6,
        "label": "Holdings",
    }
    assert "use_existing" in [q["id"] for q in t["quick_replies"]]
    assert t["ui_payload"]["type"] == "ingest_choice" and t["llm_provider"] == "mock"

    t = chat(quick_reply="use_existing")
    # the guide reviews the account first: findings, fixes as chips, then the target
    assert t["state"] == "ACCOUNT_REVIEW" and t["ui_payload"]["type"] == "account_review"
    d = t["ui_payload"]["data"]
    assert d["benchmark_kind"] == "blend" and d["findings"]
    assert "I took a look at this account" in t["assistant_message"]
    ids = [q["id"] for q in t["quick_replies"]]
    assert ids[-1] == "continue" and any(i.startswith("fix:") for i in ids)
    t = chat(message="the client is worried about having too much in one stock")
    assert t["interpretation"]["intent"] == "apply_fix" and t["state"] == "ACCOUNT_REVIEW"
    assert t["ui_payload"]["data"]["applied"] == ["cap_stocks"]
    t = chat(quick_reply="fix:harvest")
    t = chat(quick_reply="fix:spread_gains")  # replaces harvest (one budget preference)
    assert t["ui_payload"]["data"]["applied"] == ["cap_stocks", "spread_gains"]
    t = chat(quick_reply="continue")
    assert t["state"] == "TARGET_KNOWLEDGE" and "cap single stocks" in t["assistant_message"]
    t = chat(message="I'm not sure, help me choose")
    assert t["state"] == "Q_OBJECTIVE" and t["interpretation"]["intent"] == "help"
    t = chat(quick_reply="objective:total_return")
    if t["state"] == "Q_CONSTRUCTION":  # the catalog has several total-return styles
        t = chat(quick_reply="construction:market_cap")
    assert t["state"] == "TARGET_COMPARE" and t["ui_payload"]["type"] == "model_comparison"
    ids = [c["model"]["id"] for c in t["ui_payload"]["data"]["comparisons"]]
    # closest market-cap (Core) models to today's holdings come first
    assert ids[0].startswith("TR-CORE-") and 2 <= len(ids) <= 3
    assert "Not tax or investment advice" in t["assistant_message"]

    t = chat(quick_reply="choose:TR-CORE-96-04")
    assert t["state"] == "TARGET_CONFIRM"
    t = chat(message="yes")
    assert t["state"] == "TRANSITION_SETUP" and t["ui_payload"]["type"] == "transition_setup"
    assert t["progress"]["step"] == 4
    # review preferences: the recommended budget comes first, the cap is announced
    assert "(recommended)" in t["quick_replies"][0]["label"]
    assert "cap single stocks at 5%" in t["assistant_message"]

    t = chat(message="I'd rather not pay more than 20k in taxes")
    assert t["interpretation"]["slots"] == {"budget_mode": "tax", "budget_value": 20000.0}
    assert t["state"] == "TRANSITION_RESULTS"
    opt = t["ui_payload"]["data"]["optimization"]
    assert opt["realized"]["est_tax"] <= 20_001 and opt["budget_value"] == 20000
    assert t["ui_payload"]["data"]["frontier"]["points"]
    assert "approve" in t["allowed_actions"]

    # questions are answered from tools and don't change the state
    q = chat(message="Why isn't the tracking error zero?")
    assert q["state"] == "TRANSITION_RESULTS" and "residual TE" in q["assistant_message"]

    # back invalidates downstream results
    r = api.post(f"{API}/transitions/{chat.tid}/back", json={"to_state": "TRANSITION_SETUP"})
    assert r.status_code == 200 and r.json()["state"] == "TRANSITION_SETUP"
    assert not api.get(f"{API}/transitions/{chat.tid}").json()["has_optimization"]
    assert (
        api.post(
            f"{API}/transitions/{chat.tid}/back", json={"to_state": "TRANSITION_RESULTS"}
        ).status_code
        == 422
    )

    t = chat(quick_reply="budget:tax:30000")
    assert t["state"] == "TRANSITION_RESULTS"
    te_after = t["ui_payload"]["data"]["optimization"]["post"]["te"]
    t = chat(quick_reply="approve")
    assert t["state"] == "TRANSITION_APPROVE"
    assert t["ui_payload"]["data"]["exports"]["trades_csv"].endswith("trades.csv")
    t = chat(action="approve")
    assert t["state"] == "DONE" and t["allowed_actions"] == ["restart"]
    event_id = t["ui_payload"]["data"]["event_id"]

    ev = api.get(f"{API}/events/{event_id}").json()
    assert ev["type"] == "transition" and ev["n_trades"] == len(ev["trades"]) > 0
    acct = api.get(f"{API}/accounts/acc_017").json()["account"]
    assert acct["target_model_id"] == "TR-CORE-96-04"
    assert acct["ex_ante_te"] == pytest.approx(te_after, abs=1e-4)
    assert (
        api.post(
            f"{API}/transitions/{chat.tid}/back", json={"to_state": "TRANSITION_SETUP"}
        ).status_code
        == 409
    )
    hist = api.get(f"{API}/transitions/{chat.tid}/history").json()
    assert len(hist["items"]) > 10 and {h["role"] for h in hist["items"]} == {"user", "assistant"}


def test_ingest_through_chat_and_confirmation(api: TestClient) -> None:
    acct = api.post(
        f"{API}/clients/cli_009/accounts",
        json={"account_type": "individual_taxable", "custodian": "Schwab"},
    ).json()
    chat = Chat(api, "cli_009", acct["id"])
    t = chat()
    assert "use_existing" not in [q["id"] for q in t["quick_replies"]]
    t = chat(message="connect via plaid")
    assert t["state"] == "INGEST_REVIEW" and t["ui_payload"]["type"] == "parse_preview"
    assert "assume_average_cost" in [q["id"] for q in t["quick_replies"]]
    assert "save_valid_only" in [q["id"] for q in t["quick_replies"]]
    t = chat(quick_reply="confirm")  # blocked: rows would be silently left out
    assert t["state"] == "INGEST_REVIEW" and "couldn't save" in t["assistant_message"]
    t = chat(message="ok, assume average cost")
    assert t["state"] == "ACCOUNT_REVIEW" and "Assumptions" in t["assistant_message"]
    t = chat(message="looks fine, continue")
    assert t["state"] == "TARGET_KNOWLEDGE"
    t = chat(message="I want INC-60-40")
    assert t["state"] == "TARGET_CONFIRM"
    t = chat(message="yes")
    t = chat(message="15k")  # ambiguous: asks to confirm
    assert t["interpretation"]["needs_confirmation"]
    assert [q["id"] for q in t["quick_replies"]] == ["confirm_pending", "cancel_pending"]
    t = chat(quick_reply="cancel_pending")
    assert t["state"] == "TRANSITION_SETUP"
    t = chat(message="restart")
    assert t["state"] == "INGEST_CHOICE" and "use_existing" in [q["id"] for q in t["quick_replies"]]


def test_number_guard_in_engine(api: TestClient) -> None:
    api.app.dependency_overrides[get_llm] = InventingLLM  # type: ignore[attr-defined]
    chat = Chat(api, "cli_009", "acc_017")
    chat(quick_reply="use_existing")
    chat(quick_reply="knows")
    t = chat(quick_reply="choose:TR-CORE-96-04")
    t = chat(quick_reply="yes")
    assert "123,456" not in t["assistant_message"]  # invented number rejected, template kept
    q = chat(message="what would the TE be?")
    assert "1.23%" not in q["assistant_message"] and "couldn't verify" in q["assistant_message"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("hey are you here?", "greeting"),
        ("Good morning", "greeting"),
        ("you there?", "greeting"),
        ("how are you", "how_are_you"),
        ("thank you", "thanks"),
        ("who are you?", "capabilities"),
        ("what is the tracking error of TR-CORE-96-04?", None),
    ],
)
def test_smalltalk_kind(text: str, kind: str | None) -> None:
    assert smalltalk_kind(text) == kind


def test_smalltalk_in_engine(api: TestClient) -> None:
    """'hey are you here?' gets a friendly answer, keeps the step and its buttons."""
    chat = Chat(api, "cli_009", "acc_017")
    first = chat()
    r = chat(message="hey are you here?")
    assert r["assistant_message"].startswith("Yes, I'm here! How can I help?")
    assert "step 1 of 6" in r["assistant_message"]
    assert r["state"] == first["state"]
    assert [q["id"] for q in r["quick_replies"]] == [q["id"] for q in first["quick_replies"]]
    assert r["interpretation"]["intent"] == "smalltalk"
    thanks = chat(message="thanks")
    assert thanks["assistant_message"].startswith("You're welcome!")
    lost = chat(message="blorp")
    assert lost["assistant_message"].startswith("Sorry, I didn't catch that. We're on step 1 of 6")
