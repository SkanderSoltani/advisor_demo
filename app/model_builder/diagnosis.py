"""Account diagnosis: rule-based checks over an account's holdings and its analytics.

The checks compute every number; the AI guide only words them (and, with a Claude key, polishes
the wording under the number guard). Each finding offers fixes that become real settings:
optimizer constraints (applied when the transition is optimized) or preferences (which targets to
suggest, which tax budget to recommend).

Benchmark: the target model when there is one, otherwise the closest S&P 500 / Bloomberg Agg
blend by the account's equity share (as in the Model Builder).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.catalog import EQUITY_CLASSES
from app.model_builder.analytics import Benchmark, BuilderData, BuilderReport, analyze

Severity = Literal["high", "medium", "low", "info"]

# thresholds (share of the account unless noted)
CONC_HIGH, CONC_MED = 0.10, 0.05  # one company, look-through
SECTOR_HIGH, SECTOR_MED = 0.10, 0.05  # sector share of the equity sleeve vs benchmark (points)
HOME_BIAS = 0.10  # non-US share of the equity sleeve below this is flagged
VOL_HIGH, VOL_MED = 1.25, 1.10  # volatility vs the benchmark's
TE_MED = 0.04
GAIN_HIGH, GAIN_MED = 0.30, 0.15  # unrealized gain as a share of market value
LOSS_MIN_SHARE, LOSS_MIN_USD = 0.005, 2_000.0
CASH_MED = 0.03
WASH_DAYS = 30


class Fix(BaseModel):
    id: str
    label: str  # chip text
    description: str  # what it does, in one sentence
    kind: Literal["constraint", "preference"]
    setting: dict[str, Any] = Field(default_factory=dict)


FIXES: dict[str, Fix] = {f.id: f for f in [
    Fix(id="cap_stocks", label="Cap single stocks at 5%", kind="constraint",
        setting={"max_stock_weight": 0.05},
        description="No single stock above 5% of the account after the transition "
                    "(locked lots excepted)."),
    Fix(id="sector_band", label="Keep sectors near the target", kind="constraint",
        setting={"sector_band": 0.05},
        description="Every sector within ±5 points of the target model's weight."),
    Fix(id="lower_risk", label="Look at lower-risk targets", kind="preference",
        setting={"risk": "lower"},
        description="When suggesting targets, favor models with less equity than the account "
                    "holds today."),
    Fix(id="more_intl", label="Add international stocks", kind="preference",
        setting={"international": "more"},
        description="When suggesting targets, favor models with a meaningful international "
                    "stock allocation."),
    Fix(id="spread_gains", label="Spread gains over ~3 years", kind="preference",
        setting={"budget": "spread"},
        description="Recommend a tax budget of about a third of the full-transition tax this "
                    "year, and move the rest over the next two years."),
    Fix(id="harvest", label="Harvest losses first", kind="preference",
        setting={"budget": "harvest"},
        description="Recommend a $0 tax budget: sell losing lots to offset gains and move what "
                    "that pays for."),
    Fix(id="invest_cash", label="Invest the idle cash", kind="constraint",
        setting={"min_cash_buffer": 0.005},
        description="Keep only a 0.5% cash buffer; invest the rest in the target."),
]}


class Finding(BaseModel):
    id: str
    check: Literal["concentration", "sector", "region", "risk", "tax", "cash"]
    severity: Severity
    title: str  # short, e.g. "Heavier Information Technology exposure"
    detail: str  # one sentence with the numbers
    metrics: dict[str, float] = Field(default_factory=dict)
    fixes: list[str] = Field(default_factory=list)


class Diagnosis(BaseModel):
    scope: str  # account id or "household"
    as_of: date
    data_source: str = "mock"
    benchmark: Benchmark
    benchmark_kind: Literal["target", "blend"]
    market_value: float
    equity_pct: float
    volatility: float
    bench_volatility: float
    taxable: bool
    findings: list[Finding]
    fixes: dict[str, Fix]  # the fixes the findings refer to
    summary: str


@dataclass(slots=True)
class LotIn:
    ticker: str
    quantity: float
    cost_basis: float
    market_value: float
    acquired: date
    taxable: bool
    basis_unknown: bool = False


SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _p(x: float, nd: int = 0) -> str:
    return f"{x * 100:.{nd}f}%"


def _pts(x: float) -> str:
    return f"{x * 100:+.0f} pts"


def _usd(x: float) -> str:
    a = abs(x)
    s = f"${a / 1e6:,.1f}M" if a >= 1e6 else f"${a / 1e3:,.0f}k" if a >= 1e4 else f"${a:,.0f}"
    return ("-" if x < 0 else "") + s


def look_through(weights: dict[str, float], data: BuilderData) -> dict[str, tuple[float, float]]:
    """Company → (total weight, of which directly held). Equity funds are opened up into their
    simulated holdings; bond and cash funds are not."""
    out: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for t, x in weights.items():
        if t in data.stocks:
            out[t][0] += x
            out[t][1] += x
        elif t in data.products and data.products[t].asset_class in EQUITY_CLASSES:
            row = data.funds.rows.get(t, {})
            tot = sum(row.values()) or 1.0
            for s, y in row.items():
                out[s][0] += x * y / tot
    return {k: (v[0], v[1]) for k, v in out.items()}


def _shares(items: list[Any]) -> dict[str, float]:
    return {x.name: x.weight for x in items}


def diagnose(weights: dict[str, float], lots: list[LotIn], data: BuilderData, *, scope: str,
             as_of: date, st_rate: float, lt_rate: float, taxable: bool,
             target: Benchmark | None = None) -> Diagnosis:
    rep: BuilderReport = analyze(weights, "Account", data, benchmark=target)
    bench = rep.benchmark
    bref = analyze(bench.holdings, bench.short, data, benchmark=bench)
    blabel = "the target model" if target else f"the {bench.short} blend"
    findings: list[Finding] = []

    # ---- concentration (look-through)
    lt = look_through(rep_weights(rep), data)
    big = sorted(((t, w, d) for t, (w, d) in lt.items() if w >= CONC_MED), key=lambda x: -x[1])
    if big:
        top = big[:3]
        t0, w0, d0 = top[0]
        via = (f" ({_p(d0, 1)} held directly, {_p(w0 - d0, 1)} through funds)"
               if d0 > 0 and w0 - d0 > 0.002 else "")
        extra = len(big) - 3
        more = (f" Also above 5%: {', '.join(t for t, _, _ in big[1:3])}"
                + (f" and {extra} more" if extra > 0 else "") + ".") if len(big) > 1 else ""
        findings.append(Finding(
            id="concentration", check="concentration",
            severity="high" if w0 >= CONC_HIGH else "medium",
            title=f"Concentrated position in {data.name(t0)}" if len(big) == 1
            else f"{len(big)} concentrated positions",
            detail=f"{t0} is {_p(w0, 1)} of the account{via}.{more}" if len(big) > 1
            else f"{t0} is {_p(w0, 1)} of the account{via}.",
            metrics={"top_weight": round(w0, 4), "n_over_5pct": len(big),
                     **{f"w_{t}": round(w, 4) for t, w, _ in top}},
            fixes=["cap_stocks"]))

    # ---- sector tilts (shares of the equity sleeve)
    if rep.equity_pct > 0.05:
        mine, ref = _shares(rep.equity_sectors), _shares(bref.equity_sectors)
        diffs = sorted(((s, mine.get(s, 0.0) - ref.get(s, 0.0)) for s in set(mine) | set(ref)
                        if s and s != "Bonds & other"), key=lambda x: -abs(x[1]))
        tilts = [(s, d) for s, d in diffs if abs(d) >= SECTOR_MED]
        if tilts:
            s0, d0 = tilts[0]
            word = "Heavier" if d0 > 0 else "Lighter"
            others = "; ".join(f"{s} {_pts(d)}" for s, d in tilts[1:3])
            findings.append(Finding(
                id="sector", check="sector",
                severity="high" if abs(d0) >= SECTOR_HIGH else "medium",
                title=f"{word} {s0} exposure",
                detail=f"{s0} is {_p(mine.get(s0, 0.0))} of the stocks vs "
                       f"{_p(ref.get(s0, 0.0))} in {blabel} ({_pts(d0)})."
                       + (f" Other tilts: {others}." if others else ""),
                metrics={"sector_diff": round(d0, 4), "sector_weight": round(mine.get(s0, 0), 4),
                         "bench_weight": round(ref.get(s0, 0), 4)},
                fixes=["sector_band"]))

        # ---- region (home bias)
        reg, rreg = _shares(rep.equity_regions), _shares(bref.equity_regions)
        non_us = 1 - reg.get("North America", 0.0)
        ref_non_us = 1 - rreg.get("North America", 0.0)
        if target is not None and ref_non_us - non_us >= SECTOR_MED:
            findings.append(Finding(
                id="region", check="region", severity="medium",
                title="Less international than the target",
                detail=f"International stocks are {_p(non_us)} of the stocks vs "
                       f"{_p(ref_non_us)} in the target ({_pts(non_us - ref_non_us)}).",
                metrics={"non_us": round(non_us, 4), "bench_non_us": round(ref_non_us, 4)},
                fixes=["more_intl"]))
        elif target is None and non_us < HOME_BIAS:
            findings.append(Finding(
                id="region", check="region", severity="low",
                title="Almost all US stocks",
                detail=f"{_p(1 - non_us)} of the stocks are US or Canadian companies; diversified "
                       "models usually hold 20–35% international.",
                metrics={"non_us": round(non_us, 4)}, fixes=["more_intl"]))

    # ---- risk vs benchmark
    ratio = rep.volatility / rep.bench_volatility if rep.bench_volatility else 1.0
    worst = min(rep.stress_tests, key=lambda x: x["pnl_pct"]) if rep.stress_tests else None
    if ratio >= VOL_MED or rep.tracking_error >= TE_MED:
        stress = ""
        b = rep.bench_stress.get(worst["name"]) if worst else None
        if worst and (b is None or abs(worst["pnl_pct"] - b) >= 0.02):
            stress = (f" In a {worst['name']} scenario it would lose about "
                      f"{_p(-worst['pnl_pct'])}" + (f" vs {_p(-b)} for {blabel}." if b is not None
                                                    else "."))
        findings.append(Finding(
            id="risk", check="risk", severity="high" if ratio >= VOL_HIGH else "medium",
            title="More risk than the benchmark" if ratio >= VOL_MED
            else "Far from the benchmark",
            detail=f"Volatility is {_p(rep.volatility, 1)} vs {_p(rep.bench_volatility, 1)} for "
                   f"{blabel} (beta {rep.beta:.2f}, tracking error "
                   f"{_p(rep.tracking_error, 1)}).{stress}",
            metrics={"volatility": round(rep.volatility, 4),
                     "bench_volatility": round(rep.bench_volatility, 4),
                     "tracking_error": round(rep.tracking_error, 4), "beta": round(rep.beta, 3)},
            fixes=(["lower_risk"] if ratio >= VOL_MED and target is None else [])
            + ["sector_band"]))

    # ---- tax: embedded gains, losses to harvest, wash-sale risk, missing basis
    tlots = [x for x in lots if x.taxable]
    if tlots:
        tmv = sum(x.market_value for x in tlots) or 1.0
        st_cut = as_of - timedelta(days=365)
        g_st = sum(max(x.market_value - x.cost_basis, 0) for x in tlots if x.acquired > st_cut)
        g_lt = sum(max(x.market_value - x.cost_basis, 0) for x in tlots if x.acquired <= st_cut)
        losses = sum(min(x.market_value - x.cost_basis, 0) for x in tlots)
        net = g_st + g_lt + losses
        if net / tmv >= GAIN_MED:
            tax_all = max(g_st * st_rate + g_lt * lt_rate + losses * lt_rate, 0.0)
            findings.append(Finding(
                id="gains", check="tax", severity="high" if net / tmv >= GAIN_HIGH else "medium",
                title="Large embedded gains",
                detail=f"Unrealized gains net of losses are {_usd(net)} ({_p(net / tmv)} of the "
                       f"taxable value); selling everything today would cost roughly "
                       f"{_usd(tax_all)} in tax.",
                metrics={"net_gain": round(net, 2), "gain_share": round(net / tmv, 4),
                         "tax_if_sold": round(tax_all, 2)},
                fixes=["spread_gains"]))
        if -losses >= max(LOSS_MIN_USD, LOSS_MIN_SHARE * tmv):
            st_loss = -sum(min(x.market_value - x.cost_basis, 0) for x in tlots
                           if x.acquired > st_cut)
            findings.append(Finding(
                id="losses", check="tax", severity="medium",
                title="Losses available to harvest",
                detail=f"{_usd(-losses)} of unrealized losses ({_usd(st_loss)} short-term) can "
                       "offset gains realized in the transition.",
                metrics={"losses": round(-losses, 2), "st_losses": round(st_loss, 2)},
                fixes=["harvest"]))
        recent = {x.ticker for x in tlots if (as_of - x.acquired).days <= WASH_DAYS}
        loss_t = {x.ticker for x in tlots if x.market_value < x.cost_basis}
        wash = sorted(recent & loss_t)
        if wash:
            findings.append(Finding(
                id="wash", check="tax", severity="info",
                title="Wash-sale risk on recent purchases",
                detail=f"{', '.join(wash[:4])} {'was' if len(wash) == 1 else 'were'} bought in the "
                       f"last 30 days and also {'has' if len(wash) == 1 else 'have'} losing lots; "
                       "selling those at a loss now would be a wash sale, so the optimizer holds "
                       "them back.",
                metrics={"n_tickers": len(wash)}))
        unknown = sum(1 for x in tlots if x.basis_unknown)
        if unknown:
            findings.append(Finding(
                id="basis", check="tax", severity="info", title="Missing cost basis",
                detail=f"{unknown} lots have no cost basis on file; their tax figures are "
                       "estimates (average cost).", metrics={"n_lots": unknown}))

    # ---- idle cash
    cash = weights.get("CASH", 0.0) / (sum(weights.values()) or 1.0)
    if cash >= CASH_MED:
        findings.append(Finding(
            id="cash", check="cash", severity="low", title="Idle cash",
            detail=f"{_p(cash, 1)} of the account is in cash, above the 0.5% buffer the "
                   "transition keeps.", metrics={"cash": round(cash, 4)}, fixes=["invest_cash"]))

    findings.sort(key=lambda f: SEV_ORDER[f.severity])
    used = {fx for f in findings for fx in f.fixes}
    mv = sum(x.market_value for x in lots) + cash_value(weights, lots)
    return Diagnosis(scope=scope, as_of=as_of, benchmark=bench,
                     benchmark_kind="target" if target else "blend", market_value=round(mv, 2),
                     equity_pct=round(rep.equity_pct, 4), volatility=round(rep.volatility, 4),
                     bench_volatility=round(rep.bench_volatility, 4), taxable=bool(tlots),
                     findings=findings, fixes={k: FIXES[k] for k in FIXES if k in used},
                     summary=summary(findings))


def rep_weights(rep: BuilderReport) -> dict[str, float]:
    return {h.ticker: h.weight for h in rep.holdings}


def cash_value(weights: dict[str, float], lots: list[LotIn]) -> float:
    """Cash in dollars, from its weight and the lots' value."""
    c = weights.get("CASH", 0.0)
    tot = sum(weights.values()) or 1.0
    invested = sum(x.market_value for x in lots)
    share = c / tot
    return invested * share / (1 - share) if share < 1 else 0.0


def summary(findings: list[Finding]) -> str:
    serious = [f for f in findings if f.severity in ("high", "medium")]
    if not findings:
        return "Nothing stands out: the account is close to its benchmark and has no tax flags."
    if not serious:
        return f"A few minor notes ({len(findings)}); nothing urgent."
    return (f"{len(serious)} thing{'s' if len(serious) > 1 else ''} worth a look: "
            + "; ".join(f.title.lower() for f in serious[:4]) + ".")


def message(d: Diagnosis, applied: list[str], limit: int = 4) -> str:
    """The guide's opening (rule-based wording; every number comes from the findings)."""
    if not d.findings:
        return ("I took a look at this account and nothing stands out: it's close to "
                f"{'the target' if d.benchmark_kind == 'target' else d.benchmark.short} and "
                "there are no tax flags. Shall we pick the target?")
    serious = [f for f in d.findings if f.severity in ("high", "medium")]
    lead = ("I took a look at this account. A few things stand out:" if serious
            else "I took a look at this account. Nothing urgent, but a couple of notes:")
    lines = [lead]
    for f in d.findings[:limit]:
        lines.append(f"- **{f.title}.** {f.detail}")
    if len(d.findings) > limit:
        lines.append(f"- …and {len(d.findings) - limit} more on the right.")
    if applied:
        lines.append("\nAlready applied: " + ", ".join(FIXES[a].label.lower() for a in applied
                                                       if a in FIXES) + ".")
    lines.append("\nIs any of this a concern for the client? Pick a fix below, tell me in your "
                 "own words, or continue.")
    return "\n".join(lines)


def facts(d: Diagnosis) -> dict[str, Any]:
    """Numbers the wording may use (for the LLM number guard)."""
    return {"benchmark": d.benchmark.short, "volatility": d.volatility,
            "bench_volatility": d.bench_volatility, "equity_pct": d.equity_pct,
            "findings": [f.model_dump() for f in d.findings]}


# free-text concerns → fixes (offline interpreter)
CONCERN_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("concentrat", "single stock", "one stock", "too much in", "position size", "cap "),
     "cap_stocks"),
    (("tech", "sector", "tilt", "overweight", "underweight"), "sector_band"),
    (("international", "global", "home bias", "foreign", "non-us", "overseas"), "more_intl"),
    (("risk", "volatil", "drawdown", "safer", "conservative", "aggressive", "stress"),
     "lower_risk"),
    (("harvest", "loss"), "harvest"),
    (("tax", "gain", "spread", "over time", "years", "capital gain"), "spread_gains"),
    (("cash", "idle"), "invest_cash"),
]


def concern_to_fix(text: str, offered: list[str]) -> str | None:
    t = text.lower()
    for words, fix in CONCERN_WORDS:
        if fix in offered and any(w in t for w in words):
            return fix
    return None
