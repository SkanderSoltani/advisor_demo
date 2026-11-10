"""Deterministic conversation engine for the guided transition.

The state machine owns the flow. The LLM (or the offline mock) only:
  1. interprets free text into a structured :class:`Intent` (confirmed with the user when unsure),
  2. polishes templated messages — rejected if it introduces any number not from a tool,
  3. answers free-text questions using read-only tools — rejected on the same guard.
Every figure comes from :class:`AgentTools`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from app.agent.guard import unverified_numbers
from app.agent.intents import (
    CONFIRM_BELOW,
    Intent,
    ModelRef,
    allowed_intents,
    smalltalk_kind,
    step_hints,
)
from app.agent.llm import InterpretContext, LLMClient, LLMError
from app.agent.states import PROGRESS, RANK, TOTAL_STEPS, State, keys_after
from app.agent.tools import AgentTools
from app.core.config import get_settings
from app.db import models as m
from app.ingest.plaid_client import MOCK_PUBLIC_TOKEN, PlaidError, PlaidGateway
from app.schemas.chat import (
    ChatRequest,
    ChatTurn,
    Interpretation,
    Progress,
    QuickReply,
    UiPayload,
)
from app.schemas.common import DISCLAIMER
from app.schemas.ingest import ConfirmRequest, ConfirmRow, ParsePreview
from app.services.approval import approve_transition
from app.services.ingest import IngestService
from app.services.transitions import TransitionService

API = "/api/v1"
HISTORY_LIMIT = 60
# Settings the guided (chat) optimization runs with unless the advisor changes them in the chat
# (e.g. "set the cash buffer to 1%"). Product decision B5 (docs/backend_issues.md): a reasonable
# default set until the workspace exposes advanced constraints. Same fields as `Constraints`.
DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "min_cash_buffer": 0.005,  # keep 0.5% in cash
    "transaction_cost_bps": 5.0,  # estimated trading cost per side
    "turnover_penalty": 0.0,
    "min_trade_value": 250.0,  # skip dust trades under $250
    "round_shares": True,  # whole shares only
    "lot_relief": "optimizer",  # the optimizer picks lots tax-aware
}
CONSTRUCTION_LABELS = {
    "market_cap": "Market cap",
    "market_cap_fundamental": "Market cap + Fundamental",
    "market_cap_fundamental_active": "Market cap + Fundamental + Active",
}
OBJECTIVE_LABELS = {"income": "Income", "total_return": "Total return"}


@dataclass(slots=True)
class Render:
    message: str
    quick_replies: list[QuickReply] = field(default_factory=list)
    ui: UiPayload = field(default_factory=UiPayload)
    actions: list[str] = field(default_factory=lambda: ["back", "restart"])
    facts: dict[str, Any] = field(default_factory=dict)


def qr(id_: str, label: str) -> QuickReply:
    return QuickReply(id=id_, label=label)


def money(x: float | None) -> str:
    return "n/a" if x is None else (f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}")


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2%}"


class ConversationEngine:
    def __init__(self, ts: TransitionService, llm: LLMClient, plaid: PlaidGateway) -> None:
        self.ts = ts
        self.llm = llm
        self.plaid = plaid

    # ================================================================== public API
    def turn(self, t: m.Transition, req: ChatRequest) -> ChatTurn:
        self.t = t
        self.tools = AgentTools(self.ts, t)
        prefix = ""
        interp: Interpretation | None = None
        if req.action == "restart":
            return self._finish(self._restart())
        if req.action == "back":
            return self._finish(self._go_back(None))
        if req.action == "approve":
            req = ChatRequest(quick_reply="approve")

        if req.quick_reply:
            self._log("user", f"[{req.quick_reply}]")
            name, _, arg = req.quick_reply.partition(":")
            if name == "confirm_pending":
                pending = self.data.get("pending")
                self._save(drop=("pending",))
                if pending:
                    prefix = self._dispatch(Intent.model_validate(pending))
            elif name == "cancel_pending":
                self._save(drop=("pending",))
                prefix = "No problem — tell me what you'd like instead."
            else:
                prefix = self._dispatch(self._quick_reply_intent(name, arg))
        elif req.message and req.message.strip():
            text = req.message.strip()
            self._log("user", text)
            intent = self.llm.interpret(self._interp_ctx(), text)
            confirm = intent.confidence < CONFIRM_BELOW and intent.intent not in (
                "question",
                "smalltalk",
                "unknown",
            )
            interp = Interpretation(
                intent=intent.intent,
                confidence=round(intent.confidence, 2),
                slots=intent.model_dump(exclude={"intent", "confidence"}, exclude_none=True),
                needs_confirmation=confirm,
            )
            if intent.intent == "question":
                return self._finish(self._answer(intent.question or text), interp)
            if intent.intent == "smalltalk":
                return self._finish(self._smalltalk(text), interp)
            if confirm:
                self._save(pending=intent.model_dump())
                return self._finish(self._confirm_render(intent), interp)
            prefix = self._dispatch(intent)
        out = self._render()
        if prefix:
            out.message = f"{prefix}\n\n{out.message}"
        return self._finish(out, interp)

    def back(self, t: m.Transition, to_state: str) -> ChatTurn:
        self.t = t
        self.tools = AgentTools(self.ts, t)
        return self._finish(self._go_back(to_state))

    # ================================================================== plumbing
    @property
    def data(self) -> dict[str, Any]:
        return self.t.data or {}

    @property
    def state(self) -> State:
        try:
            return State(self.t.state)
        except ValueError:
            return State.INGEST_CHOICE

    def _save(self, drop: tuple[str, ...] = (), **kw: Any) -> None:
        self.ts._save(self.t, drop=drop, **kw)

    def _log(self, role: str, text: str) -> None:
        hist = list(self.data.get("history", []))
        hist.append({"role": role, "text": text, "state": self.t.state})
        self._save(history=hist[-HISTORY_LIMIT:])

    def _goto(self, s: State) -> None:
        path = [p for p in self.data.get("path", []) if p in State.__members__]
        if s.value in path:
            path = path[: path.index(s.value) + 1]
        else:
            path.append(s.value)
        self.t.state = s.value
        self._save(path=path)

    def _target(self) -> str:
        target = self.data.get("target_model_id")
        if not target:
            raise HTTPException(409, "Choose a target model first")
        return str(target)

    def _models(self) -> list[ModelRef]:
        return [
            ModelRef(x["model_id"], x["name"], x["objective"], x["construction"])
            for x in self.tools.list_models()
        ]

    def _interp_ctx(self) -> InterpretContext:
        hist = [h for h in self.data.get("history", []) if h["role"] == "assistant"]
        return InterpretContext(
            state=self.state,
            allowed=allowed_intents(self.state),
            models=self._models(),
            tradable={lot.ticker for lot in self.tools.account.lots},
            last_assistant=hist[-1]["text"] if hist else "",
        )

    def _finish(self, r: Render, interp: Interpretation | None = None) -> ChatTurn:
        msg = r.message
        if r.facts:
            polished = self.llm.phrase(msg, r.facts)
            if polished != msg and not unverified_numbers(polished, msg, r.facts):
                msg = polished
        self._log("assistant", msg)
        step, label = PROGRESS[self.state]
        return ChatTurn(
            transition_id=self.t.id,
            state=self.state.value,
            assistant_message=msg,
            quick_replies=r.quick_replies,
            ui_payload=r.ui,
            allowed_actions=r.actions,
            progress=Progress(step=step, total=TOTAL_STEPS, label=label),
            interpretation=interp,
            llm_provider=self.llm.provider,
        )

    @staticmethod
    def _quick_reply_intent(name: str, arg: str) -> Intent:
        if name == "choose":
            return Intent(intent="choose_model", confidence=1, model_id=arg)
        if name == "objective":
            return Intent(intent="set_objective", confidence=1, objective=arg)
        if name == "construction":
            return Intent(intent="set_construction", confidence=1, construction=arg)
        if name == "budget":
            mode, _, val = arg.partition(":")
            return Intent(
                intent="set_budget",
                confidence=1,
                budget_mode=mode,
                budget_value=float(val) if val else None,
            )
        return Intent(intent=name, confidence=1)

    # ================================================================== navigation
    def _restart(self) -> Render:
        keep = {"history": self.data.get("history", [])}
        self.t.data = keep
        self.ts._save(self.t)
        self.t.state = State.INGEST_CHOICE.value
        self._save(path=[State.INGEST_CHOICE.value])
        out = self._render()
        out.message = "Starting over.\n\n" + out.message
        return out

    def _go_back(self, to_state: str | None) -> Render:
        path = [State(p) for p in self.data.get("path", []) if p in State.__members__]
        if to_state is None:
            target = path[-2] if len(path) >= 2 else State.INGEST_CHOICE
        else:
            try:
                target = State(to_state)
            except ValueError as exc:
                raise HTTPException(422, f"Unknown state {to_state}") from exc
            if target not in path or RANK[target] > RANK[self.state]:
                raise HTTPException(422, f"Can only go back to a visited earlier step: {to_state}")
        if target is State.DONE or self.data.get("approved_event_id"):
            raise HTTPException(409, "This transition was approved; restart to begin a new one")
        self._save(drop=(*keys_after(target), "pending"))
        if RANK[target] < RANK[State.TARGET_CONFIRM]:
            self._save(drop=("target_confirmed",))
        self._goto(target)
        out = self._render()
        out.message = "Going back — later results were cleared.\n\n" + out.message
        return out

    # ================================================================== dispatch
    def _dispatch(self, it: Intent) -> str:
        s, name = self.state, it.intent
        if name == "restart":
            self._restart()
            return "Starting over."
        if name == "back":
            self._go_back(None)
            return "Going back."
        if name == "unknown":
            return "Sorry, I didn't catch that. " + self._where_we_are()

        if s in (State.START, State.INGEST_CHOICE):
            return self._on_ingest_choice(name)
        if s is State.INGEST_REVIEW:
            return self._on_ingest_review(name)
        if s is State.TARGET_KNOWLEDGE:
            if name == "knows":
                self._goto(State.TARGET_PICK_LIST)
            elif name == "help":
                self._goto(State.Q_OBJECTIVE)
            elif name == "choose_model":
                return self._choose(it.model_id)
            return ""
        if s in (State.TARGET_PICK_LIST, State.TARGET_COMPARE) and name == "choose_model":
            return self._choose(it.model_id)
        if s is State.Q_OBJECTIVE and name == "set_objective":
            if it.objective not in OBJECTIVE_LABELS:
                return "Please pick income or total return."
            self._save(objective=it.objective, drop=("construction", "candidates", "comparison"))
            options = self._constructions(it.objective)
            if len(options) > 1:
                self._goto(State.Q_CONSTRUCTION)
                return ""
            self._save(construction=options[0] if options else None)
            self._goto(State.TARGET_COMPARE)
            only = CONSTRUCTION_LABELS.get(options[0], options[0]) if options else "none"
            return (
                f"The current catalog has one {OBJECTIVE_LABELS[it.objective].lower()} "
                f"construction ({only}), so I'll skip that question."
            )
        if s is State.Q_CONSTRUCTION and name == "set_construction":
            self._save(construction=it.construction, drop=("candidates", "comparison"))
            self._goto(State.TARGET_COMPARE)
            return ""
        if s is State.TARGET_CONFIRM:
            if name == "yes":
                self._save(target_confirmed=True)
                self._goto(State.TRANSITION_SETUP)
            elif name == "no":
                self._save(drop=("target_confirmed",), target_model_id=None)
                self._goto(State.TARGET_KNOWLEDGE)
            return ""
        if s in (State.TRANSITION_SETUP, State.TRANSITION_RESULTS):
            return self._on_setup_or_results(it)
        if s is State.TRANSITION_APPROVE:
            if name == "approve":
                return self._approve()
            if name == "adjust":
                self._goto(State.TRANSITION_SETUP)
            return ""
        if s is State.DONE and name in ("restart", "start_over"):
            self._restart()
            return ""
        return "That option isn't available at this step."

    # ------------------------------------------------------------------ ingest
    def _on_ingest_choice(self, name: str) -> str:
        if name == "use_existing":
            if not self.tools.account.lots:
                return "This account has no holdings yet — upload a statement or connect Plaid."
            self._goto(State.TARGET_KNOWLEDGE)
            return "Using the holdings already on the account."
        if name == "upload_pdf":
            self._save(ingest_mode="pdf")
            return ""
        if name == "upload_sample":
            path = get_settings().DATA_DIR / "sample_statement_messy.pdf"
            if not path.exists():
                return "The sample statement isn't available; run scripts/seed_demo.py."
            IngestService(self.ts).preview_pdf(self.t, path.read_bytes(), self.llm)
            self._goto(State.INGEST_REVIEW)
            return "Parsed the sample statement (SAMPLE — SYNTHETIC DATA)."
        if name == "connect_plaid":
            if self.plaid.mode == "mock":
                try:
                    IngestService(self.ts).preview_plaid(self.t, self.plaid, MOCK_PUBLIC_TOKEN)
                except (PlaidError, HTTPException) as exc:
                    return f"Plaid connection failed: {getattr(exc, 'detail', exc)}"
                self._goto(State.INGEST_REVIEW)
                return "Connected the demo brokerage (mock Plaid)."
            self._save(ingest_mode="plaid")
            return ""
        return "Choose how to bring in the holdings."

    def _on_ingest_review(self, name: str) -> str:
        raw = self.data.get("ingest_preview")
        if name == "upload_again" or not raw:
            self._save(drop=("ingest_preview",))
            self._goto(State.INGEST_CHOICE)
            return ""
        pv = ParsePreview.model_validate(raw)
        excluded = sum(not r.include for r in pv.rows)
        if name == "confirm" and excluded:
            return (
                f"I couldn't save yet: {excluded} rows have problems and would be left out. "
                "Fix them in the table, accept the suggestions or the average-cost "
                "assumption, or choose “Save only the valid rows”."
            )
        if name == "save_valid_only":
            name = "confirm_valid"
        rows = []
        for r in pv.rows:
            ticker = r.ticker or ""
            if name == "accept_suggestions" and r.suggested_ticker:
                ticker = r.suggested_ticker
            include = r.include or (name == "accept_suggestions" and bool(r.suggested_ticker))
            if name == "assume_average_cost":
                fatal = {
                    "unknown_ticker",
                    "missing_ticker",
                    "negative_quantity",
                    "zero_quantity",
                    "missing_quantity",
                    "future_date",
                }
                include = not any(i.code in fatal for i in r.issues)
            if not ticker or r.quantity is None:
                include = False
            rows.append(
                ConfirmRow(
                    row_id=r.row_id,
                    lot_ref=r.lot_ref,
                    ticker=ticker or "?",
                    quantity=r.quantity or 0.0,
                    acquired_date=r.acquired_date,
                    cost_basis_total=r.cost_basis_total,
                    include=include,
                )
            )
        if name not in ("confirm", "confirm_valid", "accept_suggestions", "assume_average_cost"):
            return "Confirm the holdings, accept the suggestions, or upload again."
        try:
            res = IngestService(self.ts).confirm(
                self.t,
                ConfirmRequest(rows=rows, assume_average_cost=name == "assume_average_cost"),
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
            n = len(detail.get("rows", []))
            return f"I couldn't save yet: {detail.get('message')}" + (
                f" ({n} rows need attention)." if n else "."
            )
        self.t.state = State.TARGET_KNOWLEDGE.value
        self._goto(State.TARGET_KNOWLEDGE)
        extra = f" Assumptions: {'; '.join(res.assumptions)}." if res.assumptions else ""
        skipped = f" {res.n_excluded} rows were left out." if res.n_excluded else ""
        return f"Saved {res.n_committed} lots ({money(res.total_market_value)}).{skipped}{extra}"

    # ------------------------------------------------------------------ target
    def _constructions(self, objective: str) -> list[str]:
        return sorted({x.construction for x in self._models() if x.objective == objective})

    def _choose(self, model_id: str | None) -> str:
        ids = {x.model_id for x in self._models()}
        if model_id not in ids:
            return f"I don't know a model called {model_id}. Pick one from the list."
        self._save(target_model_id=model_id, drop=("target_confirmed",))
        self._goto(State.TARGET_CONFIRM)
        return ""

    def _candidates(self) -> list[str]:
        models = self._models()
        obj, cons = self.data.get("objective"), self.data.get("construction")
        primary = [
            x.model_id
            for x in models
            if x.objective == obj and (cons is None or x.construction == cons)
        ]
        others = [x.model_id for x in models if x.model_id not in primary]
        if self.tools.account.lots and others:
            cmp = self.tools.compare_models(others)
            te = {c["model"]["id"]: c["te_from_current"] or 9.0 for c in cmp["comparisons"]}
            others.sort(key=lambda i: te.get(i, 9.0))
        return (primary + others)[: max(2, min(3, len(models)))]

    # ------------------------------------------------------------------ setup / results
    def _setup(self) -> dict[str, Any]:
        return dict(
            self.data.get("setup") or {"budget_mode": None, "budget_value": None, "constraints": {}}
        )

    def _on_setup_or_results(self, it: Intent) -> str:
        setup = self._setup()
        name = it.intent
        if name == "lock":
            ids = self.tools.lock_lots(it.tickers or [])
            msg = (
                f"Locked {len(ids)} lots of {', '.join(it.tickers or [])}; they won't be sold."
                if ids
                else "I couldn't find those tickers in the account."
            )
            if ids and self.state is State.TRANSITION_RESULTS:
                return msg + " " + self._run(setup)
            return msg
        if name == "set_cash":
            if it.cash_buffer is None or not 0 <= it.cash_buffer <= 0.2:
                return "The cash buffer must be between 0% and 20%."
            setup["constraints"] = {
                **setup.get("constraints", {}),
                "min_cash_buffer": it.cash_buffer,
            }
            self._save(setup=setup)
            return f"Cash buffer set to {it.cash_buffer:.1%}."
        if name == "set_budget":
            mode = it.budget_mode if it.budget_mode in ("tax", "net_gain", "none") else "tax"
            if mode != "none" and (it.budget_value is None or it.budget_value < 0):
                return "Tell me the budget in dollars, e.g. “keep taxes under $20k”."
            setup.update(budget_mode=mode, budget_value=None if mode == "none" else it.budget_value)
            self._save(setup=setup)
            return self._run(setup)
        if name == "run":
            if not setup.get("budget_mode"):
                return "First choose a tax budget (or no limit)."
            return self._run(setup)
        if self.state is State.TRANSITION_RESULTS:
            if name == "approve":
                self._goto(State.TRANSITION_APPROVE)
                return ""
            if name == "adjust":
                self._goto(State.TRANSITION_SETUP)
                return ""
        return "You can set a tax budget, lock positions, or change the cash buffer."

    def _run(self, setup: dict[str, Any]) -> str:
        target = self._target()
        mode = setup.get("budget_mode") or "tax"
        try:
            opt = self.tools.run_optimization(
                mode,
                setup.get("budget_value"),
                target,
                {**DEFAULT_CONSTRAINTS, **(setup.get("constraints") or {})},
            )
            self.tools.run_frontier(target, mode if mode != "none" else "tax")
        except HTTPException as exc:
            return f"The optimizer couldn't run: {exc.detail}"
        self._goto(State.TRANSITION_RESULTS)
        b = (
            "no budget"
            if opt.budget_value is None
            else f"a {money(opt.budget_value)} "
            + ("tax budget" if opt.budget_mode == "tax" else "net-gain budget")
        )
        return f"Ran the optimizer with {b}."

    def _approve(self) -> str:
        naive = self.tools.estimate_transition_tax(self._target())
        naive_tax = naive.get("full_transition", {}).get("est_tax")
        event_id = approve_transition(self.ts, self.t, naive_tax)
        self._goto(State.DONE)
        return (
            f"Traded. The account's holdings are updated and the transition is recorded as event "
            f"**{event_id}** in the account history."
        )

    # ================================================================== questions
    def _where_we_are(self) -> str:
        step, label = PROGRESS[self.state]
        hints = step_hints(self.state)
        text = f"We're on step {step} of {TOTAL_STEPS} ({label.lower()})."
        if hints:
            text += " Here you can:\n" + "\n".join(f"- {h}" for h in hints)
        return text + "\n\nUse the buttons, type what you'd like, or ask me a question."

    def _smalltalk(self, text: str) -> Render:
        """Greetings, thanks, 'are you there?', 'what can you do?' — friendly, no numbers."""
        kind = smalltalk_kind(text) or "greeting"
        opener = {
            "greeting": "Yes, I'm here! How can I help?",
            "how_are_you": "Doing well, thanks, and ready when you are. How can I help?",
            "thanks": "You're welcome!",
            "capabilities": (
                "I'm the transition guide. I walk you through importing the holdings, choosing a "
                "target model, and finding the best trade-off between tracking error and taxes, "
                "then I prepare the trades for your approval. You can also ask me about the "
                "account, the models or the results."
            ),
        }[kind]
        base = self._render()
        return Render(
            message=f"{opener}\n\n{self._where_we_are()}",
            quick_replies=base.quick_replies,
            ui=base.ui,
            actions=base.actions,
        )

    def _answer(self, question: str) -> Render:
        base = self._render()
        try:
            answer, outputs = self.llm.answer_question(
                question,
                self.tools,
                context=f"step={self.state.value}; target={self.data.get('target_model_id')}",
            )
        except LLMError as exc:
            answer, outputs = f"I couldn't answer that right now ({exc}).", []
        if unverified_numbers(answer, outputs, question):
            answer = (
                "I couldn't verify every figure in my answer against the analytics, so I "
                "won't show it. Try the comparison or results panel instead."
            )
        return Render(
            message=f"{answer}\n\n_{DISCLAIMER}_",
            quick_replies=base.quick_replies,
            ui=base.ui,
            actions=base.actions,
        )

    def _confirm_render(self, it: Intent) -> Render:
        if it.intent == "set_budget" and it.budget_mode == "tax":
            what = f"a maximum **tax** bill of {money(it.budget_value)}"
        elif it.intent == "set_budget" and it.budget_mode == "net_gain":
            what = f"a maximum **net realized gain** of {money(it.budget_value)}"
        else:
            slots = it.model_dump(exclude={"intent", "confidence"}, exclude_none=True)
            what = f"**{it.intent.replace('_', ' ')}** {slots or ''}".strip()
        base = self._render()
        return Render(
            message=f"Just to confirm — did you mean {what}?",
            quick_replies=[qr("confirm_pending", "Yes"), qr("cancel_pending", "No")],
            ui=base.ui,
            actions=base.actions,
        )

    # ================================================================== rendering
    def _render(self) -> Render:
        s = self.state
        a = self.tools.account
        if s in (State.START, State.INGEST_CHOICE):
            if s is State.START:
                self._goto(State.INGEST_CHOICE)
            has = bool(a.lots)
            replies = []
            if has:
                replies.append(qr("use_existing", "Use current holdings"))
            replies += [
                qr("upload_pdf", "Upload tax-lot PDF"),
                qr("connect_plaid", "Connect via Plaid"),
            ]
            if get_settings().DEMO_MODE:
                replies.append(qr("upload_sample", "Use sample statement (demo)"))
            mode = self.data.get("ingest_mode")
            data: dict[str, Any] = {
                "transition_id": self.t.id,
                "account_id": a.id,
                "has_holdings": has,
                "pdf_upload_url": f"{API}/ingest/pdf",
            }
            if mode == "plaid":
                token, exp = self.plaid.create_link_token(self.ts.ps.advisor_id)
                data["plaid"] = {
                    "link_token": token,
                    "expiration": exp,
                    "mode": self.plaid.mode,
                    "exchange_url": f"{API}/ingest/plaid/exchange",
                }
            msg = (
                "Let's set up the transition. "
                + (
                    f"This account already holds {len({x.ticker for x in a.lots})} positions. "
                    if has
                    else "This account has no holdings yet. "
                )
                + "How should I get the tax lots?"
            )
            if mode == "pdf":
                msg = "Upload the tax-lot statement (PDF, up to 10 MB) and I'll show a preview."
            elif mode == "plaid":
                msg = "Open Plaid Link to connect the brokerage; I'll preview the holdings next."
            return Render(msg, replies, UiPayload(type="ingest_choice", data=data))

        if s is State.INGEST_REVIEW:
            raw = self.data.get("ingest_preview")
            if not raw:
                self._goto(State.INGEST_CHOICE)
                return self._render()
            pv = ParsePreview.model_validate(raw)
            sm = pv.summary
            via = {
                "table": "the statement's tables",
                "plaid": "Plaid",
                "llm": "an extraction pass"
                + (" (offline demo parser)" if pv.llm_provider == "mock" else ""),
            }[pv.method]
            lines = [
                f"I read **{sm.n_rows} lots** via {via} "
                f"(confidence {pv.confidence:.0%}), worth {money(sm.total_market_value)}."
            ]
            if sm.n_error_rows:
                lines.append(f"- {sm.n_error_rows} rows have errors and are excluded unless fixed.")
            if any(r.suggested_ticker for r in pv.rows):
                lines.append("- Some tickers look mistyped; I have suggestions.")
            if pv.requires_basis_decision:
                lines.append(f"- {sm.n_basis_unknown} lots lack lot-level basis or dates.")
            replies = [qr("confirm", "Looks right — save")]
            if any(r.suggested_ticker for r in pv.rows):
                replies.insert(0, qr("accept_suggestions", "Accept suggestions & save"))
            if pv.requires_basis_decision:
                replies.insert(0, qr("assume_average_cost", "Accept average-cost assumption"))
            if sm.n_error_rows:
                replies.append(
                    qr("save_valid_only", f"Save only the {sm.n_rows - sm.n_error_rows} valid rows")
                )
            replies.append(qr("upload_again", "Upload a different file"))
            return Render(
                "\n".join(lines),
                replies,
                UiPayload(type="parse_preview", data=pv.model_dump(mode="json")),
                facts=pv.summary.model_dump(),
            )

        if s is State.TARGET_KNOWLEDGE:
            return Render(
                "Do you already know the target model, or would you like help choosing?",
                [qr("knows", "I know the target"), qr("help", "Help me choose")],
            )

        if s is State.TARGET_PICK_LIST:
            models = self.tools.list_models()
            return Render(
                "Here is the model catalog. Which one is the target?",
                [qr(f"choose:{x['model_id']}", x["name"]) for x in models],
                UiPayload(type="model_list", data={"models": models}),
            )

        if s is State.Q_OBJECTIVE:
            return Render(
                "Is the goal **income** or **total return**?",
                [qr("objective:income", "Income"), qr("objective:total_return", "Total return")],
            )

        if s is State.Q_CONSTRUCTION:
            obj = self.data.get("objective", "total_return")
            return Render(
                "Which construction style?",
                [
                    qr(f"construction:{c}", CONSTRUCTION_LABELS.get(c, c))
                    for c in self._constructions(obj)
                ],
            )

        if s is State.TARGET_COMPARE:
            cands = self.data.get("candidates") or self._candidates()
            cmp = self.data.get("comparison")
            if not cmp or [c["model"]["id"] for c in cmp["comparisons"]] != cands:
                cmp = self.tools.compare_models(cands)
                self._save(candidates=cands, comparison=cmp)
            lines = ["Here are the closest options for this account (illustrative):"]
            for c in cmp["comparisons"]:
                ft = c["full_transition"]
                te = "n/a" if c["te_from_current"] is None else pct(c["te_from_current"])
                lines.append(
                    f"- **{c['model']['id']}** — yield {pct(c['model']['target_yield'])}, "
                    f"TE from today {te}, full-transition tax {money(ft['est_tax'])}"
                )
            lines.append(f"\n_{DISCLAIMER}_")
            return Render(
                "\n".join(lines),
                [
                    qr(f"choose:{c['model']['id']}", f"Choose {c['model']['id']}")
                    for c in cmp["comparisons"]
                ],
                UiPayload(type="model_comparison", data=cmp),
                facts=cmp,
            )

        if s is State.TARGET_CONFIRM:
            mid = self.data.get("target_model_id")
            mdl = next((x for x in self.tools.list_models() if x["model_id"] == mid), None)
            name = f" ({mdl['name']})" if mdl else ""
            return Render(
                f"Use **{mid}**{name} as the target for this account?",
                [qr("yes", "Yes, confirm"), qr("no", "Choose another")],
                UiPayload(type="model_list", data={"models": [mdl] if mdl else []}),
            )

        if s is State.TRANSITION_SETUP:
            mid = self._target()
            est = self.tools.estimate_transition_tax(mid)
            ft = est["full_transition"]
            summary = self.tools.get_account_summary()
            setup = self._setup()
            full = float(ft["est_tax"])
            replies = [qr("budget:tax:0", "$0 tax (harvest only)")]
            if est["taxable"] and full > 0:
                for frac in (0.25, 0.5):
                    v = round(full * frac / 1000) * 1000
                    if v > 0:
                        replies.append(qr(f"budget:tax:{v:.0f}", f"Up to {money(v)} tax"))
            replies.append(qr("budget:none", "No limit (full transition)"))
            if setup.get("budget_mode"):
                replies.append(qr("run", "Run again"))
            lines = [
                f"Moving fully into **{mid}** today would cost about **{money(full)}** in tax "
                f"(net gain {money(ft['net_realized_gain'])}).",
                "How much tax are you willing to pay this year? You can also lock positions "
                "(e.g. “don't sell JUP”) or change the cash buffer.",
            ]
            if not est["taxable"]:
                lines[0] = (
                    f"This is a tax-deferred account, so moving into **{mid}** has no tax cost."
                )
            if summary["locked_value"]:
                lines.append(f"Locked positions: {money(summary['locked_value'])} won't be sold.")
            return Render(
                "\n\n".join(lines),
                replies,
                UiPayload(
                    type="transition_setup",
                    data={
                        "target_model_id": mid,
                        "setup": setup,
                        "full_transition": ft,
                        "taxable": est["taxable"],
                        "account": summary,
                        "locked_lot_ids": self.data.get("locks", []),
                        "locks_url": f"{API}/transitions/{self.t.id}/locks",
                    },
                ),
                facts={"ft": ft, "summary": summary},
            )

        if s is State.TRANSITION_RESULTS:
            opt, fr = self.data.get("optimization"), self.data.get("frontier")
            if not opt:
                self._goto(State.TRANSITION_SETUP)
                return self._render()
            r, pre, post = opt["realized"], opt["pre"], opt["post"]
            lines = [
                f"Tracking error falls from **{pct(pre['te'])}** to **{pct(post['te'])}** "
                f"with an estimated tax of **{money(r['est_tax'])}** "
                f"(net gain {money(r['net_gain'])}, turnover {opt['summary']['turnover']:.0%}).",
                *[f"- {line}" for line in opt["diagnostics"]["explanation"]],
                f"\n_{DISCLAIMER}_",
            ]
            replies = [qr("approve", "Approve trades")]
            b = opt.get("budget_value")
            if opt["budget_mode"] == "tax" and b is not None:
                more = round(max(b * 2, 10_000) / 1000) * 1000
                replies.append(qr(f"budget:tax:{more:.0f}", f"Try {money(more)} tax"))
                if b > 0:
                    replies.append(
                        qr(
                            f"budget:tax:{round(b / 2000) * 1000:.0f}",
                            f"Try {money(round(b / 2000) * 1000)} tax",
                        )
                    )
            replies.append(qr("adjust", "Change settings"))
            return Render(
                "\n".join(lines),
                replies,
                UiPayload(type="transition_results", data={"optimization": opt, "frontier": fr}),
                actions=["back", "restart", "approve"],
                facts={"opt": opt, "frontier": fr},
            )

        if s is State.TRANSITION_APPROVE:
            opt = self.data.get("optimization") or {}
            sm = opt.get("summary", {})
            msg = (
                f"Ready to trade **{sm.get('n_lot_sells', 0)} lot sales** and "
                f"**{sm.get('n_buys', 0)} buys** into {opt.get('target_model_id')} "
                f"(estimated tax {money(opt.get('realized', {}).get('est_tax'))}). "
                "Download the trade list or summary first if you like. **Trade** executes the "
                "trades: the account's holdings are updated and the transition is recorded in its "
                f"history.\n\n_{DISCLAIMER}_"
            )
            return Render(
                msg,
                [qr("approve", "Trade"), qr("adjust", "Change settings")],
                UiPayload(
                    type="transition_results",
                    data={
                        "optimization": opt,
                        "exports": {
                            "trades_csv": f"{API}/transitions/{self.t.id}/trades.csv",
                            "summary_pdf": f"{API}/transitions/{self.t.id}/summary.pdf",
                        },
                    },
                ),
                actions=["back", "restart", "approve"],
                facts={"opt": opt},
            )

        # DONE
        return Render(
            f"Done. The transition into **{self.data.get('target_model_id')}** is recorded "
            f"(event {self.data.get('approved_event_id')}); the account now targets it.",
            [qr("restart", "Start another transition")],
            UiPayload(
                type="transition_results",
                data={
                    "event_id": self.data.get("approved_event_id"),
                    "event_url": f"{API}/events/{self.data.get('approved_event_id')}",
                    "exports": {
                        "trades_csv": f"{API}/transitions/{self.t.id}/trades.csv",
                        "summary_pdf": f"{API}/transitions/{self.t.id}/summary.pdf",
                    },
                },
            ),
            actions=["restart"],
        )
