"""LLM adapter. The deterministic app logic calls these methods; the LLM never invents numbers.

* :class:`AnthropicLLM` — Claude via the official ``anthropic`` SDK (model from ``LLM_MODEL``).
* :class:`MockLLM` — offline stand-in for demo mode. For extraction it runs a rule-based line
  parser over the statement text (it is *not* an AI model and says so via ``provider``).

Milestone 6 adds the conversational methods to the same interface.
"""

from __future__ import annotations

import base64
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from app.agent.intents import Intent, ModelRef, match_model, rule_interpret
from app.agent.states import State
from app.agent.tools import READ_ONLY_TOOL_SPECS
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("llm")


# --------------------------------------------------------------------------- extraction schema
class ExtractedLot(BaseModel):
    """One tax lot as printed on the statement. Use null when a value is not shown."""

    ticker: str | None = Field(None, description="Ticker symbol exactly as printed")
    description: str | None = Field(None, description="Security name / description")
    quantity: float | None = Field(None, description="Shares in this lot")
    acquired_date: str | None = Field(None, description="Acquisition date as ISO YYYY-MM-DD")
    cost_basis_total: float | None = Field(None, description="Total cost basis of the lot, USD")
    market_value: float | None = Field(None, description="Current market value of the lot, USD")
    term: Literal["ST", "LT"] | None = None
    lot_id: str | None = Field(None, description="Lot ID / lot number exactly as printed")


class LotExtraction(BaseModel):
    rows: list[ExtractedLot]
    cash: float | None = Field(None, description="Cash / money-market balance, USD, if shown")
    statement_date: str | None = Field(None, description="Statement date as ISO YYYY-MM-DD")
    notes: str | None = Field(None, description="Anything the reader should double-check")


EXTRACTION_SYSTEM = (
    "You extract tax-lot holdings from brokerage statements into JSON. Copy values exactly as "
    "printed: one row per tax lot (not per position), ticker symbols verbatim, quantities and "
    "dollar amounts as plain numbers (parentheses mean negative), dates as YYYY-MM-DD. Skip "
    "subtotal, total, header and page-footer lines. Copy each lot's Lot ID (lot number) "
    "verbatim when the statement shows one. Never infer or compute a value that is not "
    "printed; use null instead. Report the cash or money-market balance separately in `cash`."
)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InterpretContext:
    state: State
    allowed: dict[str, str]  # intent -> description
    models: list[ModelRef]
    tradable: set[str]
    last_assistant: str = ""


INTERPRET_SYSTEM = (
    "You map an RIA advisor's message, sent during a guided portfolio-transition workflow, to "
    "exactly one allowed intent and fill only the slots the message states. Rules: never guess "
    "numbers that the advisor did not write; '20k' means 20000; when the advisor names a dollar "
    "amount without saying whether it caps taxes or gains, use budget_mode 'tax' with confidence "
    "at most 0.6; use intent 'question' for questions; 'unknown' if nothing fits. Confidence "
    "reflects how sure you are about the intent and slots."
)
PHRASE_SYSTEM = (
    "Rewrite the draft message for a financial advisor in a concise, warm, professional tone. "
    "Keep the markdown structure. Keep every number, ticker, model id and percentage exactly as "
    "written, and do not add any new numbers, facts or recommendations. Keep any disclaimer."
)
QA_SYSTEM = (
    "You answer an RIA advisor's question about a portfolio transition. Use the tools for every "
    "figure; never estimate or invent numbers. Answer in at most 4 short sentences of markdown, "
    "quote numbers exactly as the tools return them (decimals such as 0.0415 may be shown as "
    "4.15%). If the tools cannot answer, say so. This is illustrative, for advisor review, and "
    "not tax or investment advice."
)
MAX_TOOL_ROUNDS = 5


class LLMClient(ABC):
    provider: str  # "anthropic" | "mock"
    model: str

    @abstractmethod
    def extract_lots(self, pdf_bytes: bytes, text: str) -> LotExtraction:
        """Extract tax lots from a statement (PDF bytes plus its extracted text)."""

    @abstractmethod
    def interpret(self, ctx: InterpretContext, text: str) -> Intent:
        """Map free text to one of ``ctx.allowed`` intents with slots and a confidence."""

    @abstractmethod
    def phrase(self, draft: str, facts: dict[str, Any]) -> str:
        """Optionally polish a templated message. Must not add numbers (guarded by caller)."""

    @abstractmethod
    def answer_question(self, question: str, tools: Any, context: str) -> tuple[str, list[Any]]:
        """Answer a free-text question using read-only tools. Returns (answer, tool outputs)."""


# --------------------------------------------------------------------------- Anthropic
class AnthropicLLM(LLMClient):
    provider = "anthropic"

    def __init__(self, model: str, server_fallback: bool = True) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()  # credentials from env / `ant auth login` profile
        self.model = model
        self.server_fallback = server_fallback

    def extract_lots(self, pdf_bytes: bytes, text: str) -> LotExtraction:
        anthropic = self._anthropic
        doc = base64.standard_b64encode(pdf_bytes).decode("ascii")
        kwargs: dict[str, Any] = {}
        if self.server_fallback:
            # route policy declines to a fallback model inside the same call (Claude API beta)
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                output_config={"effort": "medium"},
                system=EXTRACTION_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": doc,
                                },
                            },
                            {
                                "type": "text",
                                "text": "Extract every tax lot from this statement.",
                            },
                        ],
                    }
                ],
                output_format=LotExtraction,
                **kwargs,
            )
        except anthropic.RateLimitError as exc:
            raise LLMError("LLM rate limited; try again shortly") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"LLM request failed ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("LLM unreachable") from exc
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to process this document")
        if response.stop_reason == "max_tokens":
            raise LLMError("Statement too long for one extraction pass")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("LLM returned no structured output")
        log.info("llm extraction", rows=len(parsed.rows), request_id=response._request_id)
        return parsed

    def _fallback_kwargs(self) -> dict[str, Any]:
        if not self.server_fallback:
            return {}
        return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    def interpret(self, ctx: InterpretContext, text: str) -> Intent:
        anthropic = self._anthropic
        brief = {
            "step": ctx.state.value,
            "allowed_intents": ctx.allowed,
            "models": [
                {
                    "model_id": m.model_id,
                    "name": m.name,
                    "objective": m.objective,
                    "construction": m.construction,
                }
                for m in ctx.models
            ],
            "last_assistant_message": ctx.last_assistant[-1500:],
        }
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=2000,
                output_config={"effort": "low"},
                system=INTERPRET_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": f"Context:\n{json.dumps(brief)}\n\nAdvisor message:\n{text}",
                    }
                ],
                output_format=Intent,
                **self._fallback_kwargs(),
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            log.warning("interpret failed; using rules", error=type(exc).__name__)
            return rule_interpret(ctx.state, text, ctx.models, ctx.tradable)
        intent = response.parsed_output
        if response.stop_reason != "end_turn" or intent is None or intent.intent not in ctx.allowed:
            return rule_interpret(ctx.state, text, ctx.models, ctx.tradable)
        return intent

    def phrase(self, draft: str, facts: dict[str, Any]) -> str:
        anthropic = self._anthropic
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=2000,
                output_config={"effort": "low"},
                system=PHRASE_SYSTEM,
                messages=[{"role": "user", "content": draft}],
                **self._fallback_kwargs(),
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            return draft
        if response.stop_reason != "end_turn":
            return draft
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or draft

    def answer_question(self, question: str, tools: Any, context: str) -> tuple[str, list[Any]]:
        anthropic = self._anthropic
        dispatch = tools.read_only_dispatch()
        messages: list[Any] = [
            {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"}
        ]
        outputs: list[Any] = []
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=4000,
                    output_config={"effort": "medium"},
                    system=QA_SYSTEM,
                    tools=cast(Any, READ_ONLY_TOOL_SPECS),
                    tool_choice=cast(Any, {"type": "auto"}),
                    messages=messages,
                    **self._fallback_kwargs(),
                )
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                raise LLMError("question answering unavailable") from exc
            if response.stop_reason == "refusal":
                raise LLMError("the model declined this question")
            # pass the full content back (thinking / fallback blocks must be preserved)
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                return text, outputs
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                fn = dispatch.get(block.name)
                try:
                    out = fn(**(block.input or {})) if fn else {"error": "unknown tool"}
                    is_error = fn is None
                except Exception as exc:  # tool failures are reported back to the model
                    out, is_error = {"error": type(exc).__name__}, True
                outputs.append(out)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out, default=str),
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
        raise LLMError("too many tool rounds")


# --------------------------------------------------------------------------- Mock
_DATE_PATTERNS = [
    r"\d{1,2}/\d{1,2}/\d{2,4}",
    r"\d{4}-\d{2}-\d{2}",
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}",
]
_DATE_RE = re.compile("|".join(f"({p})" for p in _DATE_PATTERNS))
_NUM_TOKEN = re.compile(r"\(?-?\$?[\d,]*\.?\d+\)?")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.]{0,5}$")
_CASH_RE = re.compile(r"(cash|money market)[^\d$(]*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
_LOT_REF_RE = re.compile(r"\bL\d+-\d+\b")  # Lot IDs on the sample statements (L017-0042)


def _num(tok: str) -> float | None:
    from app.ingest.normalizer import parse_number

    return parse_number(tok)


def _iso(s: str) -> str | None:
    from app.ingest.normalizer import parse_date

    d = parse_date(s)
    return d.isoformat() if d else None


class MockLLM(LLMClient):
    """Offline stand-in. Extraction = rule-based line parsing of the statement text."""

    provider = "mock"
    model = "mock-rule-based"

    def extract_lots(self, pdf_bytes: bytes, text: str) -> LotExtraction:
        rows: list[ExtractedLot] = []
        cash = None
        pending: ExtractedLot | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m_cash = _CASH_RE.search(line)
            if m_cash and not _DATE_RE.search(line):
                cash = _num(m_cash.group(2))
                continue
            if re.search(r"\b(sub)?total\b", line, re.IGNORECASE):
                continue
            m_ref = _LOT_REF_RE.search(line)
            lot_ref = m_ref.group(0) if m_ref else None
            if m_ref:  # remove it so its digits aren't read as amounts
                line = (line[: m_ref.start()] + line[m_ref.end() :]).strip()
            tokens = line.split()
            m_date = _DATE_RE.search(line)
            if not tokens or not _TICKER.match(tokens[0]) or m_date is None:
                # continuation line: wrapped description of the previous row
                if pending is not None and not any(c.isdigit() for c in line):
                    pending.description = f"{pending.description or ''} {line}".strip()
                continue
            ticker = tokens[0]
            before, after = line[: m_date.start()], line[m_date.end() :]
            desc_tokens = [t for t in before.split()[1:] if _num(t) is None]
            nums = [
                v
                for v in (
                    _num(t)
                    for t in _NUM_TOKEN.findall(after)
                    + _NUM_TOKEN.findall(" ".join(before.split()[1:]))
                )
                if v is not None
            ]
            qty, basis, value = self._assign(nums)
            pending = ExtractedLot(
                ticker=ticker,
                description=" ".join(desc_tokens) or None,
                quantity=qty,
                acquired_date=_iso(m_date.group(0)),
                cost_basis_total=basis,
                market_value=value,
                lot_id=lot_ref,
            )
            rows.append(pending)
        return LotExtraction(
            rows=rows,
            cash=cash,
            notes="Extracted offline by the demo rule-based parser (no AI model was called).",
        )

    def interpret(self, ctx: InterpretContext, text: str) -> Intent:
        intent = rule_interpret(ctx.state, text, ctx.models, ctx.tradable)
        return intent if intent.intent in ctx.allowed else Intent(intent="unknown", confidence=0.3)

    def phrase(self, draft: str, facts: dict[str, Any]) -> str:
        return draft  # templates are already final in demo mode

    def answer_question(self, question: str, tools: Any, context: str) -> tuple[str, list[Any]]:
        """Pattern-matched answers backed by the same tools (no AI model involved)."""
        q = question.lower()
        models = [
            ModelRef(m["model_id"], m["name"], m["objective"], m["construction"])
            for m in tools.list_models()
        ]
        mid = match_model(question, models)
        if mid and re.search(r"tracking|\bte\b|risk|close", q):
            out = tools.te_to_model(mid)
            te = out.get("te_from_current")
            ans = (
                f"Tracking error from the current holdings to **{mid}** is **{te:.2%}**."
                if te is not None
                else f"The account has no holdings to compare with {mid}."
            )
            return ans, [out]
        if mid and re.search(r"tax|cost|gain", q):
            out = tools.estimate_transition_tax(mid)
            ft = out["full_transition"]
            return (
                f"Moving fully into **{mid}** today would realize a net gain of "
                f"${ft['net_realized_gain']:,.0f} with an estimated tax of "
                f"**${ft['est_tax']:,.0f}**"
                + (" (tax-deferred account: no tax due)." if not out["taxable"] else "."),
                [out],
            )
        if re.search(r"why|explain|residual|not zero", q):
            out = tools.explain_result()
            if "error" in out:
                return "No optimization has been run yet.", [out]
            return " ".join(out["explanation"]), [out]
        if re.search(r"model|option|catalog", q):
            out = tools.list_models()
            lines = [
                f"- **{m['model_id']}** ({m['objective'].replace('_', ' ')}), yield "
                f"{m['target_yield']:.2%}, fee {m['fee_bps']:g} bps"
                for m in out
            ]
            return "Available target models:\n" + "\n".join(lines), out
        out = tools.get_account_summary()
        return (
            f"The account is worth **${out['market_value']:,.0f}** "
            f"({out['n_positions']} positions, {out['n_lots']} lots) with "
            f"${out['unrealized_gain']:,.0f} of unrealized gain. I can also answer questions "
            "about tracking error or taxes for a specific model.",
            [out],
        )

    @staticmethod
    def _assign(nums: list[float]) -> tuple[float | None, float | None, float | None]:
        """Pick quantity, cost basis and value from the numbers on a lot line.

        Uses the layout rule quantity · price ≈ value when a price column exists; otherwise
        assumes the common order quantity, cost basis, value[, gain].
        """
        if not nums:
            return None, None, None
        qty = nums[0]
        rest = nums[1:]
        for vi, v in enumerate(rest):
            for pi, p in enumerate(rest):
                if pi != vi and v > 0 and abs(qty * p - v) / v < 0.01:
                    others = [x for k, x in enumerate(rest) if k not in (vi, pi)]
                    return qty, (others[0] if others else None), v
        basis = rest[0] if rest else None
        value = rest[1] if len(rest) > 1 else None
        return qty, basis, value


@lru_cache
def get_llm() -> LLMClient:
    """Mock in DEMO_MODE or when LLM_PROVIDER=mock; otherwise Claude."""
    s = get_settings()
    if s.DEMO_MODE or s.LLM_PROVIDER == "mock":
        return MockLLM()
    return AnthropicLLM(s.LLM_MODEL, server_fallback=s.LLM_SERVER_FALLBACK)
