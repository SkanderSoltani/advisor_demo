"""Model Builder guide: a deterministic, rule-based assistant (offline demo mode, like the
transition guide's mock interpreter). It reads a message or a quick reply, edits the draft and
answers questions from the analytics. The frontend owns the draft and sends it with each turn.

Steps: build → analyze (and refine) → scale → save → done.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from app.db.catalog import EQUITY_CLASSES
from app.db.real_universe import WORD_TICKERS
from app.model_builder.scaling import scale_line, targets

OBJECTIVES = {"total_return": "Total Return", "income": "Income", "tax_efficient": "Tax Efficient"}
STEP_ORDER = ["build", "analyze", "scale", "save", "done"]


class Draft(BaseModel):
    name: str = "My model"
    objective: str = "total_return"
    holdings: dict[str, float] = Field(default_factory=dict)  # fractions
    step: str = "build"
    scale_n: int = 10
    scale_lo: int = 10
    scale_hi: int = 100
    line_name: str = ""
    saved_line_id: str | None = None
    saved_model_ids: list[str] = Field(default_factory=list)


class QuickReply(BaseModel):
    id: str
    label: str


class AssistTurn(BaseModel):
    draft: Draft
    message: str
    quick_replies: list[QuickReply]
    refresh_analytics: bool = False


class Tools:
    """What the guide can use (wired to the builder data and the catalog by the API)."""

    def __init__(self, known: Callable[[str], bool], asset_class: Callable[[str], str],
                 models: list[dict[str, Any]], analyze: Callable[[dict[str, float], str], Any],
                 save: Callable[[Draft], tuple[str, list[str]]]) -> None:
        self.known, self.asset_class, self.models = known, asset_class, models
        self.analyze, self.save = analyze, save


def _pct(x: float, n: int = 1) -> str:
    return f"{x * 100:.{n}f}%"


def _qr(*pairs: tuple[str, str]) -> list[QuickReply]:
    return [QuickReply(id=i, label=lbl) for i, lbl in pairs]


def _equity(d: Draft, t: Tools) -> float:
    tot = sum(d.holdings.values()) or 1.0
    return sum(x for k, x in d.holdings.items() if t.asset_class(k) in EQUITY_CLASSES) / tot


def _tickers(text: str, t: Tools) -> list[str]:
    return [w for w in re.findall(r"\b[A-Za-z][A-Za-z0-9.\-]{0,9}\b", text)
            if w.upper() == w and t.known(w)] or \
           [w.upper() for w in re.findall(r"\b[A-Za-z]{2,6}\b", text) if t.known(w.upper())
            and w.lower() not in STOP]


STOP = {"add", "set", "to", "and", "the", "with", "for", "from", "remove", "drop", "of", "in",
        "a", "an", "it", "as", "my", "me", "save", "call", "name", "line", "model", "models",
        "more", "less", "risk", "equity", "bond", "bonds", "show", "run", "use", "start",
        "scale", "into", "by", "at", "is", "be", "put", "make", "swap", "replace", "what", "why",
        *WORD_TICKERS}


def _summary(rep: Any) -> str:
    return (f"**{rep.name}**: {_pct(rep.equity_pct, 0)} equity / {_pct(rep.fixed_income_pct, 0)} "
            f"fixed income / {_pct(rep.cash_pct, 0)} cash · {rep.n_holdings} holdings. "
            f"Volatility **{_pct(rep.volatility)}** vs {_pct(rep.bench_volatility)} for the "
            f"benchmark **{rep.benchmark.short}** (tracking error {_pct(rep.tracking_error)}). "
            f"Yield {_pct(rep.yield_, 2)}, net expense ratio {rep.net_expense_ratio_bps:.1f} bps.")


def _shift(d: Draft, t: Tools, target: float) -> dict[str, float]:
    e = max(0, min(100, round(target * 100)))
    return scale_line(d.holdings, 1, e, e, t.asset_class)[0].holdings


def _line_text(d: Draft) -> str:
    labs = [f"{e}/{100 - e}" for e in targets(d.scale_n, d.scale_lo, d.scale_hi)]
    return f"{len(labs)} models: " + ", ".join(labs)


def _replies(d: Draft) -> list[QuickReply]:
    if not d.holdings:
        return _qr(("import", "Import a PDF / Excel file"), ("start:TR-CORE-56-44",
                   "Start from Core 56/44"), ("start:INC-42-58", "Start from Income 42/58"),
                   ("help", "What can you do?"))
    if d.step in ("build", "analyze"):
        out = [("analyze", "Run analytics")] if d.step == "build" else []
        out += [("less_risk", "Less risk (−10% equity)"), ("more_risk", "More risk (+10% equity)")]
        if d.step == "analyze":
            out += [("explain:benchmark", "Which benchmark?"), ("go_scale", "Scale into a line")]
        return _qr(*out)
    if d.step == "scale":
        return _qr(("scale:10:10:100", "10 models · 10/90 → 100/0"),
                   ("scale:5:20:100", "5 models · 20/80 → 100/0"),
                   ("scale:9:10:90", "9 models · 10/90 → 90/10"), ("go_save", "Save this line"))
    if d.step == "save":
        return _qr(*[(f"objective:{k}", v) for k, v in OBJECTIVES.items()])
    return _qr(("restart", "Build another model"))


def assist(d: Draft, message: str | None, reply: str | None, t: Tools) -> AssistTurn:
    msg = (message or "").strip()
    low = msg.lower()
    rid = (reply or "").strip()
    refresh = False

    def turn(text: str) -> AssistTurn:
        return AssistTurn(draft=d, message=text, quick_replies=_replies(d),
                          refresh_analytics=refresh)

    # ---------------------------------------------------------------- start / help / restart
    if not msg and not rid:
        return turn("Hi! Let's build a model. **Import** a PDF or Excel file with tickers and "
                    "weights, **start from** an existing model, or add holdings yourself — e.g. "
                    "*add SCHX 40%, SCHF 15%, SCHZ 40%, CASH 5%*. I'll run the analytics, help you "
                    "refine it and scale it into a line of models.")
    if rid == "restart" or re.search(r"\b(start over|clear( all)?|reset)\b", low):
        d = Draft()
        return turn("Cleared. Add holdings, import a file or start from an existing model.")
    if rid == "help" or low in ("help", "?") or "what can you do" in low:
        return turn("I can:\n- **build**: *add SCHX 30%*, *set SCHZ to 25%*, *remove FNDX*, "
                    "*replace SCHF with FNDF*, *normalize* (scale weights to 100%), *start from "
                    "Core 60/40*\n- **analyze**: *run analytics*, *which benchmark?*, *what's the "
                    "duration?*, *how did it perform?*\n- **refine**: *less risk*, *more risk*, "
                    "*set equity to 65%*\n- **scale**: *scale to 10 models from 10/90 to 100/0*\n"
                    "- **save**: *save as Growth & Income Models* (then pick the category).")
    if rid == "import":
        return turn("Use **Import file** on the right (Excel, CSV or PDF with a ticker column "
                    "and a weight column). A sample file is linked there too.")

    # ---------------------------------------------------------------- start from a model
    start_id = rid.split(":", 1)[1] if rid.startswith("start:") else None
    if start_id is None and re.search(r"\b(start|begin|copy|use|load)\b.*\b(from|with)?\b", low):
        for m in sorted(t.models, key=lambda m: -len(m["name"])):
            if m["name"].lower() in low or m["id"].lower() in low:
                start_id = m["id"]
                break
    if start_id:
        m = next((x for x in t.models if x["id"] == start_id), None)
        if m is None:
            return turn(f"I couldn't find the model {start_id}.")
        d.holdings = {h["ticker"]: h["weight"] for h in m["holdings"]}
        d.name = f"My {m['name']}"
        d.step, refresh = "analyze", True
        return turn(f"Started from **{m['name']}** ({len(d.holdings)} holdings). The analytics are "
                    "on the right — change any weight, or tell me what to adjust.")

    # ---------------------------------------------------------------- naming
    mname = re.search(r"\b(?:name|call|rename)\s+(?:it|the model|this)?\s*(?:as|to)?\s*[\"“]?"
                      r"(.+?)[\"”]?$", msg, re.I)
    if mname and "line" not in low:
        d.name = mname.group(1).strip()[:80]
        return turn(f"Renamed the model to **{d.name}**.")

    # ---------------------------------------------------------------- save
    if d.step == "save" and not d.line_name and msg and not rid and not re.search(
            r"\bsave\b", low):
        d.line_name = msg.strip().strip('"“”')[:100]
        return turn(f"Line name: **{d.line_name}** ({_line_text(d)}). Which category should it "
                    "go under?")
    if d.step in ("scale", "save") or rid in ("go_save",) or re.search(r"\bsave\b", low):
        ms = re.search(r"\bsave\b(?:\s+(?:it|this|the line))?\s+as\s+[\"“]?(.+?)[\"”]?$", msg, re.I)
        if ms:
            d.line_name = ms.group(1).strip()[:100]
        if rid.startswith("objective:"):
            d.objective = rid.split(":", 1)[1]
        elif "income" in low:
            d.objective = "income"
        elif "tax" in low:
            d.objective = "tax_efficient"
        elif "total return" in low or "growth" in low:
            d.objective = "total_return"
        wants_save = (rid in ("go_save",) or rid.startswith("objective:") or ms is not None
                      or re.search(r"\bsave\b", low) is not None)
        if wants_save:
            if not d.holdings:
                return turn("There's nothing to save yet — add some holdings first.")
            if not d.line_name:
                d.step = "save"
                return turn("What should the line be called? Type *save as <name>* (e.g. "
                            "*save as Growth & Income Models*), then pick the category.")
            if not rid.startswith("objective:") and d.step != "save":
                d.step = "save"
                return turn(f"Saving **{d.line_name}** ({_line_text(d)}). Which category should "
                            "it go under?")
            try:
                lid, ids = t.save(d)
            except ValueError as exc:
                return turn(f"I couldn't save it: {exc}")
            d.saved_line_id, d.saved_model_ids, d.step = lid, ids, "done"
            return turn(f"Saved **{d.line_name}** under Custom Models → {OBJECTIVES[d.objective]} "
                        f"with {len(ids)} models ({ids[0]} … {ids[-1]}). They're in "
                        "[Model management](/models) and can be used as transition targets now.")

    # ---------------------------------------------------------------- scale
    sm = re.match(r"scale:(\d+):(\d+):(\d+)$", rid)
    if sm or rid == "go_scale" or re.search(r"\b(scale|line of|\d+\s+models)\b", low):
        if not d.holdings:
            return turn("Build the model first, then I'll scale it.")
        if sm:
            d.scale_n, d.scale_lo, d.scale_hi = map(int, sm.groups())
        else:
            n = re.search(r"(\d+)\s+models", low)
            if n:
                d.scale_n = int(n.group(1))
            rng = re.search(r"from\s+(\d+)\s*(?:/\s*\d+|%)?\s+to\s+(\d+)", low) or \
                re.search(r"between\s+(\d+)\s*%?\s+and\s+(\d+)", low)
            if rng:
                d.scale_lo, d.scale_hi = int(rng.group(1)), int(rng.group(2))
        d.step = "scale"
        return turn(f"Here's the line: {_line_text(d)}. Each keeps your equity mix and bond mix "
                    "and only resizes the two sleeves (cash stays as in your model). Adjust the "
                    "count or range on the right, or say *save as <name>*.")

    # ---------------------------------------------------------------- refine risk
    e_now = _equity(d, t) if d.holdings else 0.0
    by = re.search(r"by\s+(\d+)", low)
    step = (int(by.group(1)) if by else 10) / 100
    set_eq = re.search(r"\b(?:set|make|target)\s+equity\s+(?:to|at)\s+(\d+)", low)
    if d.holdings and (set_eq or rid in ("less_risk", "more_risk") or re.search(
            r"\b(less risk|more conservative|reduce (risk|equity)|safer|more aggressive|more risk|"
            r"more equity|increase equity)\b", low)):
        if set_eq:
            target = int(set_eq.group(1)) / 100
        elif rid == "less_risk" or re.search(r"less risk|conservative|reduce|safer", low):
            target = e_now - step
        else:
            target = e_now + step
        d.holdings = _shift(d, t, target)
        d.step, refresh = "analyze", True
        return turn(f"Moved equity from {_pct(e_now, 0)} to **{_pct(_equity(d, t), 0)}**, keeping "
                    "the mix inside each sleeve. Analytics updated on the right.")

    # ---------------------------------------------------------------- edits
    changed: list[str] = []
    if re.search(r"\b(normali[sz]e|rescale|add up|to 100)\b", low):
        tot = sum(d.holdings.values())
        if tot > 0:
            d.holdings = {k: round(v / tot, 6) for k, v in d.holdings.items()}
            changed.append(f"scaled the weights from {_pct(tot)} to 100%")
    rep_m = re.search(r"\b(?:replace|swap)\s+([A-Za-z.\-]+)\s+(?:with|for|by)\s+([A-Za-z.\-]+)",
                      msg, re.I)
    if rep_m:
        a, b = rep_m.group(1).upper(), rep_m.group(2).upper()
        if a in d.holdings and t.known(b):
            d.holdings[b] = round(d.holdings.get(b, 0.0) + d.holdings.pop(a), 6)
            changed.append(f"replaced {a} with {b}")
        else:
            return turn(f"I can only replace a holding with a ticker from the universe "
                        f"({a} → {b}).")
    if re.search(r"\b(remove|drop|delete|sell)\b", low) and not rep_m:
        gone = [x for x in _tickers(msg, t) if x in d.holdings]
        for x in gone:
            d.holdings.pop(x)
        if gone:
            changed.append(f"removed {', '.join(gone)}")
    elif not rep_m:
        tick_w = r"\b([A-Za-z][A-Za-z0-9.\-]{0,9})\s*(?:to|at|=|:)?\s*(\d+(?:\.\d+)?)\s*%"
        w_tick = r"(\d+(?:\.\d+)?)\s*%\s*(?:in|of|to)?\s*([A-Za-z][A-Za-z0-9.\-]{0,9})"
        pairs = re.findall(tick_w, msg) + [(b, a) for a, b in re.findall(w_tick, msg)]
        bad = []
        for raw, w in pairs:
            tk = raw.upper()
            # stop words are skipped unless typed in capitals as a known ticker ("NOW 5%")
            if tk.lower() in STOP and not (raw.isupper() and t.known(tk)):
                continue
            if t.known(tk):
                d.holdings[tk] = round(float(w) / 100, 6)
                changed.append(f"{tk} {float(w):g}%")
            else:
                bad.append(tk)
        if bad and not changed:
            return turn(f"{', '.join(bad)} isn't in the universe. Search tickers on the right to "
                        "see what's available.")
    if changed:
        tot = sum(d.holdings.values())
        d.step = "analyze" if d.step != "build" else d.step
        refresh = d.step == "analyze"
        note = "" if abs(tot - 1) < 1e-4 else (f" Weights now add up to **{_pct(tot)}** — say "
                                               "*normalize* to scale them to 100%.")
        return turn("Done: " + "; ".join(changed) + "." + note)

    # ---------------------------------------------------------------- analyze / questions
    asks = re.search(r"\b(benchmark|volatil|risk|fee|expense|duration|bond|yield|perform|return|"
                     r"drawdown|how)\b", low) or rid.startswith("explain:")
    if rid == "analyze" or re.search(r"\b(analy[sz]e|analytics|run|check)\b", low) or asks:
        if not d.holdings:
            return turn("Add some holdings first.")
        if sum(d.holdings.values()) <= 0:
            return turn("The weights are all zero.")
        rep = t.analyze(d.holdings, d.name)
        if d.step == "build":
            d.step = "analyze"
        refresh = True
        topic = rid.split(":", 1)[1] if rid.startswith("explain:") else low
        if "benchmark" in topic:
            return turn(f"I compared it with **{rep.benchmark.name}** — the closest blend to its "
                        f"{_pct(rep.equity_pct, 0)} equity exposure. {rep.benchmark.note}")
        if re.search(r"fee|expense", topic):
            top = max(rep.holdings, key=lambda h: h.er_contribution_bps)
            return turn(f"Net expense ratio **{rep.net_expense_ratio_bps:.1f} bps**. The biggest "
                        f"contributor is {top.ticker} ({top.expense_ratio_bps:.0f} bps × "
                        f"{_pct(top.weight)} = {top.er_contribution_bps:.1f} bps).")
        if re.search(r"duration|bond", topic):
            if rep.avg_duration is None:
                return turn("This model has no bonds, so there's no duration.")
            fi = {c.label: c.model for c in rep.fi_characteristics}
            return turn(f"Bond sleeve ({_pct(rep.fixed_income_pct, 0)} of the model): duration "
                        f"**{fi['Effective duration']}**, yield to maturity "
                        f"{fi['Yield to maturity']}, average quality "
                        f"{fi['Average credit quality']}.")
        if re.search(r"perform|return|drawdown", topic):
            s = {p.label: p for p in rep.perf_stats}
            a, dd = s["Annualized return"], s["Max drawdown"]
            return turn(f"Hypothetically (today's weights over the simulated history): "
                        f"**{a.model}** a year vs {a.benchmark} for {rep.benchmark.short}, max "
                        f"drawdown {dd.model} vs {dd.benchmark}. Not a track record.")
        if re.search(r"volatil|risk", topic):
            f = sorted(rep.factors, key=lambda x: -x.model_vol)[:2]
            return turn(f"Volatility **{_pct(rep.volatility)}** ({rep.benchmark.short}: "
                        f"{_pct(rep.bench_volatility)}). Most of it comes from "
                        f"{f[0].factor.lower()} ({_pct(f[0].model_pct, 0)} of variance)"
                        + (f" and {f[1].factor.lower()} ({_pct(f[1].model_pct, 0)})." if len(f) > 1
                           else "."))
        return turn(_summary(rep) + " Want to refine it, or *scale it into a line*?")

    return turn("I didn't catch that. Try *add SCHX 30%*, *remove FNDX*, *less risk*, *run "
                "analytics*, *scale to 10 models* or *save as <name>* — or say *help*.")
