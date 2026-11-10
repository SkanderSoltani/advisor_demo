"""Intent schema (what free text may map to, per state) and the offline rule-based interpreter."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agent.states import State

CONFIRM_BELOW = 0.75  # interpretations below this confidence are confirmed with the user


class Intent(BaseModel):
    """Structured reading of one advisor message. Unused slots stay null."""

    intent: str = Field(description="One of the allowed intent names for the current step")
    confidence: float = Field(ge=0, le=1)
    model_id: str | None = None
    objective: str | None = Field(None, description="income | total_return")
    construction: str | None = Field(
        None, description="market_cap | market_cap_fundamental | market_cap_fundamental_active"
    )
    budget_mode: str | None = Field(None, description="tax | net_gain | none")
    budget_value: float | None = Field(None, description="USD")
    tickers: list[str] | None = None
    cash_buffer: float | None = Field(None, description="decimal, e.g. 0.02 for 2%")
    question: str | None = None


GLOBAL_INTENTS: dict[str, str] = {
    "back": "go back to the previous step",
    "restart": "start the whole flow over",
    "question": "asks a question about the account, models, taxes or results",
    "smalltalk": "a greeting, thanks, checking the assistant is there, or asking what it can do",
    "unknown": "none of the above",
}

STATE_INTENTS: dict[State, dict[str, str]] = {
    State.INGEST_CHOICE: {
        "upload_pdf": "upload a tax-lot statement PDF",
        "connect_plaid": "connect the brokerage via Plaid",
        "use_existing": "keep the holdings already on the account",
    },
    State.INGEST_REVIEW: {
        "confirm": "the parsed holdings look right; save them",
        "accept_suggestions": "apply the suggested ticker corrections, then save",
        "assume_average_cost": "accept average-cost basis / assumed dates for unknown lots",
        "upload_again": "upload a different file",
        "save_valid_only": "save only the rows without errors",
    },
    State.TARGET_KNOWLEDGE: {
        "knows": "already knows which target model to use",
        "help": "wants help choosing a target",
        "choose_model": "names a specific model (model_id)",
    },
    State.TARGET_PICK_LIST: {"choose_model": "picks a model (model_id)"},
    State.Q_OBJECTIVE: {"set_objective": "income or total return (objective)"},
    State.Q_CONSTRUCTION: {"set_construction": "construction style (construction)"},
    State.TARGET_COMPARE: {"choose_model": "picks one of the compared models (model_id)"},
    State.TARGET_CONFIRM: {"yes": "confirms the target", "no": "wants a different target"},
    State.TRANSITION_SETUP: {
        "set_budget": "sets a tax or gain budget (budget_mode, budget_value)",
        "lock": "keep / don't sell some securities (tickers)",
        "set_cash": "change the cash buffer (cash_buffer)",
        "run": "run the optimization with the current settings",
    },
    State.TRANSITION_RESULTS: {
        "set_budget": "try a different budget (budget_mode, budget_value)",
        "lock": "keep / don't sell some securities (tickers)",
        "approve": "happy with the result; move to approval",
        "adjust": "go back to change the settings",
    },
    State.TRANSITION_APPROVE: {"approve": "approve the trades", "adjust": "change something"},
    State.DONE: {"restart": "start a new transition"},
}


def allowed_intents(state: State) -> dict[str, str]:
    return {**STATE_INTENTS.get(state, {}), **GLOBAL_INTENTS}


def step_hints(state: State, limit: int = 4) -> list[str]:
    """Plain-language list of what the advisor can do at this step (for help / fallback replies)."""
    out = []
    for desc in STATE_INTENTS.get(state, {}).values():
        text = re.sub(r"\s*\([^)]*\)", "", desc).strip()
        out.append(text[0].upper() + text[1:])
    return out[:limit]


# --------------------------------------------------------------------------- small talk
_SMALLTALK: list[tuple[str, re.Pattern[str]]] = [
    (
        "capabilities",
        re.compile(
            r"\b(who are you|what are you|what can you do|what do you do|how can you help"
            r"|what can i (do|ask))\b",
            re.IGNORECASE,
        ),
    ),
    ("how_are_you", re.compile(r"\b(how are you|how's it going|how is it going)\b", re.IGNORECASE)),
    ("thanks", re.compile(r"\b(thanks|thank you|thx|cheers|appreciate it)\b", re.IGNORECASE)),
    (
        "greeting",
        re.compile(
            r"^(hi|hello|hey|hiya|yo|howdy|good (morning|afternoon|evening))\b"
            r"|\b(are you|you) (there|here|around|awake|online|alive)\b",
            re.IGNORECASE,
        ),
    ),
]


def smalltalk_kind(text: str) -> str | None:
    """'greeting' | 'how_are_you' | 'thanks' | 'capabilities', or None if it isn't small talk."""
    t = text.strip()
    if len(t.split()) > 12:  # long messages carry a real request
        return None
    for kind, pattern in _SMALLTALK:
        if pattern.search(t):
            return kind
    return None


# --------------------------------------------------------------------------- rule-based
@dataclass(frozen=True, slots=True)
class ModelRef:
    model_id: str
    name: str
    objective: str
    construction: str


_AMOUNT = re.compile(
    r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|mm|million)?\b(?!\s*%)", re.IGNORECASE
)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_TICKER_TOKEN = re.compile(r"\b[A-Z]{2,5}\b")
_QUESTION_START = re.compile(
    r"^(what|how|why|which|who|when|where|can|could|is|are|does|do)\b", re.IGNORECASE
)


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}\b", text) for w in words)


def parse_amount(text: str) -> float | None:
    m = _AMOUNT.search(text.replace("$ ", "$"))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if unit in {"k", "thousand"}:
        v *= 1_000
    elif unit in {"m", "mm", "million"}:
        v *= 1_000_000
    return v


def match_model(text: str, models: Sequence[ModelRef]) -> str | None:
    t = text.lower()
    for mdl in models:
        if mdl.model_id.lower() in t or mdl.name.lower() in t:
            return mdl.model_id
    wants_income = _has(t, "income", "dividend", "dividends", "yield")
    wants_tr = _has(t, "total return", "growth", "core", "equity")
    hits = [
        mdl.model_id
        for mdl in models
        if (wants_income and mdl.objective == "income")
        or (wants_tr and not wants_income and mdl.objective == "total_return")
    ]
    return hits[0] if len(hits) == 1 else None


def rule_interpret(
    state: State, text: str, models: Sequence[ModelRef], tradable: set[str]
) -> Intent:
    """Deterministic keyword interpreter (offline demo mode)."""
    raw = text.strip()
    t = raw.lower()
    if _has(t, "start over", "restart"):
        return Intent(intent="restart", confidence=0.95)
    if _has(t, "go back", "back", "previous step"):
        return Intent(intent="back", confidence=0.9)

    def question() -> Intent:
        return Intent(intent="question", confidence=0.85, question=raw)

    if state is State.INGEST_CHOICE:
        if _has(t, "pdf", "upload", "statement", "file"):
            return Intent(intent="upload_pdf", confidence=0.9)
        if _has(t, "plaid", "connect", "link", "brokerage login"):
            return Intent(intent="connect_plaid", confidence=0.9)
        if _has(t, "existing", "current", "keep", "these", "already"):
            return Intent(intent="use_existing", confidence=0.85)
    elif state is State.INGEST_REVIEW:
        if _has(t, "suggest", "suggestion", "suggestions", "typo", "fix"):
            return Intent(intent="accept_suggestions", confidence=0.85)
        if _has(t, "average", "assume", "assumption"):
            return Intent(intent="assume_average_cost", confidence=0.85)
        if _has(t, "again", "another", "different file", "re-upload"):
            return Intent(intent="upload_again", confidence=0.85)
        if _has(t, "confirm", "looks good", "correct", "yes", "save", "fine"):
            return Intent(intent="confirm", confidence=0.85)
    elif state in (State.TARGET_KNOWLEDGE, State.TARGET_PICK_LIST, State.TARGET_COMPARE):
        mid = match_model(raw, models)
        if mid:
            return Intent(intent="choose_model", confidence=0.85, model_id=mid)
        if state is State.TARGET_KNOWLEDGE:
            if _has(t, "help", "not sure", "unsure", "recommend", "suggest", "no", "don't know"):
                return Intent(intent="help", confidence=0.85)
            if _has(t, "yes", "i know", "list", "show", "pick"):
                return Intent(intent="knows", confidence=0.8)
    elif state is State.Q_OBJECTIVE:
        if _has(t, "income", "dividend", "dividends", "yield", "cash flow"):
            return Intent(intent="set_objective", confidence=0.9, objective="income")
        if _has(t, "total return", "growth", "appreciation", "return"):
            return Intent(intent="set_objective", confidence=0.9, objective="total_return")
    elif state is State.Q_CONSTRUCTION:
        if _has(t, "active", "momentum"):
            return Intent(
                intent="set_construction",
                confidence=0.85,
                construction="market_cap_fundamental_active",
            )
        if _has(t, "fundamental", "quality", "value", "tilt"):
            return Intent(
                intent="set_construction", confidence=0.85, construction="market_cap_fundamental"
            )
        if _has(t, "market cap", "cap weighted", "simple", "index", "passive"):
            return Intent(intent="set_construction", confidence=0.85, construction="market_cap")
    elif state is State.TARGET_CONFIRM:
        if _has(t, "no", "change", "different", "other"):
            return Intent(intent="no", confidence=0.85)
        if _has(t, "yes", "confirm", "go ahead", "ok", "okay", "sure", "correct"):
            return Intent(intent="yes", confidence=0.9)
    elif state in (State.TRANSITION_SETUP, State.TRANSITION_RESULTS, State.TRANSITION_APPROVE):
        if state is not State.TRANSITION_SETUP and _has(
            t, "approve", "looks good", "proceed", "go ahead", "accept"
        ):
            return Intent(intent="approve", confidence=0.9)
        if state is not State.TRANSITION_SETUP and _has(t, "adjust", "change settings", "tweak"):
            return Intent(intent="adjust", confidence=0.85)
        if state is not State.TRANSITION_APPROVE:
            if _has(t, "lock", "don't sell", "do not sell", "keep", "hold", "exclude"):
                tickers = [x for x in _TICKER_TOKEN.findall(raw) if x in tradable]
                if tickers:
                    return Intent(intent="lock", confidence=0.85, tickers=tickers)
            pct = _PCT.search(raw)
            if pct and _has(t, "cash", "buffer"):
                return Intent(
                    intent="set_cash", confidence=0.85, cash_buffer=float(pct.group(1)) / 100
                )
            if _has(
                t,
                "no limit",
                "no budget",
                "full transition",
                "don't care",
                "whatever",
                "all the way",
                "regardless",
            ):
                return Intent(intent="set_budget", confidence=0.85, budget_mode="none")
            amount = parse_amount(raw)
            if amount is not None and not (raw.endswith("?") and _QUESTION_START.match(raw)):
                if _has(t, "tax", "taxes", "irs", "bill"):
                    return Intent(
                        intent="set_budget", confidence=0.9, budget_mode="tax", budget_value=amount
                    )
                if _has(t, "gain", "gains", "realize", "realise", "capital"):
                    return Intent(
                        intent="set_budget",
                        confidence=0.9,
                        budget_mode="net_gain",
                        budget_value=amount,
                    )
                # an amount without saying what it caps: assume tax, but confirm
                return Intent(
                    intent="set_budget", confidence=0.6, budget_mode="tax", budget_value=amount
                )
            if _has(t, "zero tax", "no tax", "no taxes", "tax free", "tax-free", "harvest only"):
                return Intent(
                    intent="set_budget", confidence=0.85, budget_mode="tax", budget_value=0.0
                )
            if state is State.TRANSITION_SETUP and _has(t, "run", "go", "optimize", "optimise"):
                return Intent(intent="run", confidence=0.85)
    # nothing step-specific matched: small talk before treating it as a question
    if smalltalk_kind(raw):
        return Intent(intent="smalltalk", confidence=0.95, question=raw)
    if raw.endswith("?") or _QUESTION_START.match(raw):
        return question()
    return Intent(intent="unknown", confidence=0.3)
