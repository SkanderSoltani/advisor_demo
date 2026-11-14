"""Model Builder analytics (demo): characteristics, exposures, risk, benchmark and a hypothetical
back-test for any set of weights over catalog products and synthetic stocks."""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.db.catalog import EQUITY_CLASSES, CatalogFile, load_catalog
from app.model_builder.reference import (
    EQ_REGIONS,
    FI_PROFILES,
    FI_REGIONS,
    FI_SECTORS,
    INTL_DEVELOPED,
    MATURITIES,
    MATURITY_MID,
    RATING_SCORE,
    RATINGS,
    SIZES,
    STYLES,
    StockReference,
)
from app.risk_analytics.security_master import ASSET_CLASSES
from app.risk_analytics.types import Portfolio, Position

NOTIONAL = 1_000_000.0  # analytics are shown per $1M invested
RISK_FREE = 0.03
FI_CLASSES = {"US Bonds", "Non-US Bonds", "Preferred"}


# --------------------------------------------------------------------------- outputs
class Weighted(BaseModel):
    name: str
    weight: float
    market_value: float = 0.0
    group: str = ""


class HoldingRow(BaseModel):
    ticker: str
    name: str
    kind: str  # fund | stock
    asset_class: str
    weight: float
    expense_ratio_bps: float
    er_contribution_bps: float
    yield_: float = Field(alias="yield")

    model_config = {"populate_by_name": True}


class CharRow(BaseModel):
    label: str
    model: str
    benchmark: str


class FactorRow(BaseModel):
    factor: str
    model_vol: float  # contribution to volatility (vol × share of variance)
    model_pct: float  # share of variance
    bench_vol: float
    bench_pct: float


class PerfPoint(BaseModel):
    d: date
    model: float
    benchmark: float


class PerfStat(BaseModel):
    label: str
    model: str
    benchmark: str


class YearReturn(BaseModel):
    year: int
    model: float
    benchmark: float


class Benchmark(BaseModel):
    name: str
    short: str  # e.g. "S&P/Agg 60/40"
    equity_pct: int
    holdings: dict[str, float]
    note: str


class BuilderReport(BaseModel):
    name: str
    as_of: date
    data_source: str = "mock"
    total_weight: float
    normalized: bool
    warnings: list[str]
    # 1. general characteristics
    n_holdings: int
    n_underlying: int
    equity_pct: float
    fixed_income_pct: float
    cash_pct: float
    avg_duration: float | None
    pe_ratio: float | None
    pb_ratio: float | None
    net_expense_ratio_bps: float
    yield_: float = Field(alias="yield")
    # 2. holdings
    holdings: list[HoldingRow]
    # 3–9. exposures
    asset_allocation: list[Weighted]
    equity_size: list[Weighted]
    equity_style: list[Weighted]
    style_box: list[list[float]]  # rows: Large/Mid/Small × cols: Value/Blend/Growth (equity = 1)
    equity_regions: list[Weighted]
    equity_sectors: list[Weighted]
    fi_rating: list[Weighted]
    fi_sectors: list[Weighted]
    fi_maturity: list[Weighted]
    fi_regions: list[Weighted]
    # 10. characteristics vs benchmark
    equity_characteristics: list[CharRow]
    fi_characteristics: list[CharRow]
    # 11–13. risk
    volatility: float
    bench_volatility: float
    tracking_error: float
    beta: float
    factors: list[FactorRow]
    tail: list[dict[str, Any]]
    return_histogram: list[dict[str, Any]]
    stress_tests: list[dict[str, Any]]
    bench_stress: dict[str, float]
    # 14. hypothetical performance
    performance: list[PerfPoint]
    perf_stats: list[PerfStat]
    calendar_years: list[YearReturn]
    benchmark: Benchmark
    methodology: list[str]

    model_config = {"populate_by_name": True}


# --------------------------------------------------------------------------- data
class BuilderData:
    """Synthetic market, catalog products, security master and mock risk provider (cached)."""

    _inst: BuilderData | None = None
    _lock = threading.Lock()

    def __init__(self, base: Any = None) -> None:
        from app.analytics.factory import get_provider
        from app.core.config import get_settings
        from app.risk_analytics.mock_provider import MockRiskProvider
        from app.risk_analytics.security_master import SecurityMaster

        s = get_settings()
        base = base if base is not None else get_provider()
        self.base = base
        self.market = base.market
        self.funds = base.funds
        self.catalog: CatalogFile = load_catalog(s.MODELS_FILE)
        self.master = SecurityMaster.load_or_create(
            s.SECURITY_MASTER_FILE, self.market.universe,
            [(p.ticker, p.name, p.asset_class, p.proxy) for p in self.catalog.products],
            s.SYNTHETIC_SEED)
        self.risk = MockRiskProvider(self.market, self.funds, self.master)
        self.ref = StockReference(self.market.universe)
        self.products = {p.ticker: p for p in self.catalog.products}
        u = self.market.universe
        self.stocks = set(map(str, u.index))
        rets = self.market.returns
        nav = self.funds.nav.pct_change().fillna(0.0)
        self.returns = pd.concat([rets, nav.reindex(rets.index).fillna(0.0)], axis=1)
        dy = u["dividend_yield"]
        self.yields: dict[str, float] = {}
        for p in self.catalog.products:
            row = self.funds.rows.get(p.ticker, {})
            tot = sum(row.values())
            self.yields[p.ticker] = (float(p.yield_) if p.yield_ is not None
                                     else sum(x * float(dy[s_]) for s_, x in row.items()) / tot
                                     if tot else 0.0)

    @classmethod
    def get(cls, base: Any = None) -> BuilderData:
        """Shared instance for the app's analytics provider (rebuilt if a different provider is
        passed, e.g. in tests)."""
        with cls._lock:
            if cls._inst is None or (base is not None and cls._inst.base is not base):
                cls._inst = BuilderData(base)
            return cls._inst

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._inst = None

    # ------------------------------------------------------------------ instruments
    def known(self, t: str) -> bool:
        return t in self.products or t in self.stocks

    def name(self, t: str) -> str:
        if t in self.products:
            return self.products[t].name
        return str(self.market.universe.at[t, "name"]) if t in self.stocks else t

    def asset_class(self, t: str) -> str:
        if t in self.products:
            return self.products[t].asset_class
        return "US Equity" if self.master.get(t).country == "United States" else "Non-US Stocks"

    def universe(self) -> list[dict[str, Any]]:
        out = [{"ticker": p.ticker, "name": p.name, "kind": "fund", "asset_class": p.asset_class,
                "expense_ratio_bps": p.expense_ratio_bps} for p in self.catalog.products]
        u = self.market.universe
        out += [{"ticker": str(t), "name": str(r["name"]), "kind": "stock",
                 "asset_class": self.asset_class(str(t)), "sector": str(r["sector"]),
                 "expense_ratio_bps": 0.0} for t, r in u.iterrows()]
        return out


# --------------------------------------------------------------------------- helpers
def _slices(d: dict[str, float], order: list[str] | None = None, keep_zero: bool = False,
            scale: float = 1.0) -> list[Weighted]:
    names = order if order else sorted(d, key=lambda k: -d[k])
    if order:
        names = names + sorted(k for k in d if k not in order)
    return [Weighted(name=k, weight=round(d.get(k, 0.0) * scale, 6),
                     market_value=round(d.get(k, 0.0) * scale * NOTIONAL, 2))
            for k in names if keep_zero or abs(d.get(k, 0.0)) > 1e-9]


def _norm(d: dict[str, float]) -> dict[str, float]:
    tot = sum(d.values())
    return {k: v / tot for k, v in d.items()} if tot > 0 else {}


def _pct(x: float | None, n: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{n}f}%"


def _num(x: float | None, n: int = 1, suffix: str = "") -> str:
    return "—" if x is None or not math.isfinite(x) else f"{x:,.{n}f}{suffix}"


def pick_benchmark(equity_pct: float, muni_share: float) -> Benchmark:
    e = round(equity_pct * 10) * 10
    fi_t, fi_name, fi_short = (("SCMB", "Bloomberg Municipal Bond", "Muni") if muni_share > 0.5
                               else ("SCHZ", "Bloomberg US Aggregate", "Agg"))
    if e >= 100:
        name, short, h = "S&P 500", "S&P 500", {"SCHX": 1.0}
    elif e <= 0:
        name, short, h = fi_name, fi_short, {fi_t: 1.0}
    else:
        name = f"S&P 500 / {fi_name} {e}/{100 - e}"
        short = f"S&P/{fi_short} {e}/{100 - e}"
        h = {"SCHX": e / 100, fi_t: 1 - e / 100}
    return Benchmark(name=name, short=short, equity_pct=e, holdings=h,
                     note=f"Closest blend by equity exposure ({equity_pct:.0%} equity), rebalanced "
                          f"daily; simulated with {' / '.join(h)} as index proxies.")


# --------------------------------------------------------------------------- core
class _Profile:
    """Exposures and characteristics of one set of weights (model or benchmark)."""

    def __init__(self, data: BuilderData, w: dict[str, float]) -> None:
        self.data, self.w = data, w
        ref, master = data.ref, data.master
        asset: dict[str, float] = defaultdict(float)
        eq_lt: dict[str, float] = defaultdict(float)
        region: dict[str, float] = defaultdict(float)
        fi: dict[str, float] = {}
        for t, x in w.items():
            ac = data.asset_class(t)
            asset[ac] += x
            if ac in EQUITY_CLASSES:
                if t in data.stocks:
                    eq_lt[t] += x
                    region[_region_of(master.get(t).region)] += x
                else:
                    row = _norm(data.funds.rows.get(t, {}))
                    for s, y in row.items():
                        eq_lt[s] += x * y
                    proxy = data.products[t].proxy
                    if ac == "US Equity":
                        region["North America"] += x
                    elif proxy == "emerging":
                        region["Emerging Markets"] += x
                    else:
                        for k, v in INTL_DEVELOPED.items():
                            region[k] += x * v
            elif ac in FI_CLASSES:
                fi[t] = x
        self.asset = dict(asset)
        self.eq = sum(v for k, v in asset.items() if k in EQUITY_CLASSES)
        self.fi_total = sum(fi.values())
        self.cash = asset.get("Cash", 0.0)
        self.eq_lt = _norm(dict(eq_lt))
        self.eq_region = _norm(dict(region))
        # equity look-through characteristics
        lt = self.eq_lt
        self.sector: dict[str, float] = defaultdict(float)
        self.size: dict[str, float] = defaultdict(float)
        self.style: dict[str, float] = defaultdict(float)
        self.box = [[0.0] * 3 for _ in range(3)]
        for s, y in lt.items():
            self.sector[str(ref.sector[s])] += y
            sz, st = str(ref.size[s]), str(ref.style[s])
            self.size[sz] += y
            self.style[st] += y
            self.box[SIZES.index(sz)][STYLES.index(st)] += y
        hm = lambda col: (1 / sum(y / float(col[s]) for s, y in lt.items())) if lt else None  # noqa: E731
        avg = lambda col: sum(y * float(col[s]) for s, y in lt.items()) if lt else None  # noqa: E731
        self.pe, self.pb = hm(ref.pe), hm(ref.pb)
        self.roe, self.div, self.beta_eq = avg(ref.roe), avg(ref.div), avg(ref.beta)
        self.mcap = avg(ref.mcap)
        # fixed income
        fw = _norm(fi)
        rating: dict[str, float] = defaultdict(float)
        sector: dict[str, float] = defaultdict(float)
        mat: dict[str, float] = defaultdict(float)
        fregion: dict[str, float] = defaultdict(float)
        dur = ytm = cpn = 0.0
        for t, y in fw.items():
            prof = FI_PROFILES.get(data.products[t].proxy, FI_PROFILES["core_bond"])
            dur += y * prof.duration
            ytm += y * prof.ytm
            cpn += y * prof.coupon
            for k, v in prof.rating.items():
                rating[k] += y * v
            for k, v in prof.sector.items():
                sector[k] += y * v
            for k, v in prof.maturity.items():
                mat[k] += y * v
            for k, v in prof.region.items():
                fregion[k] += y * v
        has_fi = bool(fw)
        self.duration = dur if has_fi else None
        self.ytm = ytm if has_fi else None
        self.coupon = cpn if has_fi else None
        self.rating, self.fi_sector, self.maturity, self.fi_region = (
            dict(rating), dict(sector), dict(mat), dict(fregion))
        score = sum(RATING_SCORE[k] * v for k, v in rating.items()) if has_fi else None
        self.avg_rating = RATINGS[min(6, max(0, round(score) - 1))] if score else None
        mids = zip(MATURITY_MID, MATURITIES, strict=True)
        self.avg_maturity = (sum(mid * mat.get(k, 0.0) for mid, k in mids)
                             if has_fi else None)
        self.muni_share = sector.get("Municipal", 0.0)
        # fees and yield
        self.er = sum(x * data.products[t].expense_ratio_bps for t, x in w.items()
                      if t in data.products)
        u = data.market.universe
        self.yld = sum(x * (data.yields[t] if t in data.products
                            else float(u.at[t, "dividend_yield"])) for t, x in w.items())


def _region_of(r: str) -> str:
    return r if r in EQ_REGIONS else "North America"


def _risk(data: BuilderData, w: dict[str, float], name: str) -> Any:
    pf = Portfolio(id=name, name=name,
                   positions=[Position(ticker=t, market_value=x * NOTIONAL) for t, x in w.items()])
    return data.risk.analyze(pf, scope="account")


def _daily(data: BuilderData, w: dict[str, float]) -> pd.Series:
    cols = [t for t in w if t in data.returns.columns]
    r = data.returns[cols].to_numpy() @ np.array([w[t] for t in cols])
    return pd.Series(r, index=data.returns.index)


def _stats(r: pd.Series) -> dict[str, float]:
    g = (1 + r).cumprod()
    years = len(r) / 252
    ann = float(g.iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    vol = float(r.std() * math.sqrt(252))
    mdd = float((1 - g / g.cummax()).max())
    roll = (1 + r).rolling(252).apply(np.prod, raw=True) - 1
    return {"total": float(g.iloc[-1] - 1), "ann": ann, "vol": vol, "mdd": mdd,
            "sharpe": (ann - RISK_FREE) / vol if vol > 0 else 0.0,
            "best": float(roll.max()), "worst": float(roll.min())}


def analyze(holdings: dict[str, float], name: str = "Draft model",
            data: BuilderData | None = None, benchmark: Benchmark | None = None) -> BuilderReport:
    """Full report for one set of weights. ``benchmark`` overrides the closest-blend pick (the
    transition view measures every portfolio against the target model)."""
    data = data or BuilderData.get()
    warnings: list[str] = []
    raw = {t.upper(): float(x) for t, x in holdings.items() if x and x > 0}
    unknown = [t for t in raw if not data.known(t)]
    if unknown:
        warnings.append(f"Not in the universe (ignored): {', '.join(sorted(unknown))}")
    raw = {t: x for t, x in raw.items() if data.known(t)}
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("Add at least one holding with a weight above 0%")
    normalized = abs(total - 1.0) > 1e-4
    if normalized:
        warnings.append(f"Weights add up to {total:.2%}; analytics use them scaled to 100%.")
    w = {t: x / total for t, x in raw.items()}

    m = _Profile(data, w)
    bench = benchmark or pick_benchmark(m.eq, m.muni_share if m.fi_total > 0 else 0.0)
    b = _Profile(data, bench.holdings)
    rm, rb = _risk(data, w, name), _risk(data, bench.holdings, "benchmark")

    # factor decomposition: model vs benchmark
    bmap = {x.factor: x for x in rb.decomposition}
    factors = [FactorRow(factor=x.factor, model_vol=round(x.vol_contribution, 6),
                         model_pct=round(x.pct_of_variance, 5),
                         bench_vol=round(bmap[x.factor].vol_contribution, 6)
                         if x.factor in bmap else 0.0,
                         bench_pct=round(bmap[x.factor].pct_of_variance, 5)
                         if x.factor in bmap else 0.0)
               for x in rm.decomposition]

    # hypothetical performance
    rmod, rben = _daily(data, w), _daily(data, bench.holdings)
    te = float((rmod - rben).std() * math.sqrt(252))
    gm, gb = 10_000 * (1 + rmod).cumprod(), 10_000 * (1 + rben).cumprod()
    monthly = pd.DataFrame({"m": gm, "b": gb}).resample("ME").last()
    perf = [PerfPoint(d=pd.Timestamp(i).date(), model=round(float(r_.m), 2),
                      benchmark=round(float(r_.b), 2)) for i, r_ in monthly.iterrows()]
    sm, sb = _stats(rmod), _stats(rben)
    perf_stats = [
        PerfStat(label="Total return", model=_pct(sm["total"]), benchmark=_pct(sb["total"])),
        PerfStat(label="Annualized return", model=_pct(sm["ann"]), benchmark=_pct(sb["ann"])),
        PerfStat(label="Annualized volatility", model=_pct(sm["vol"]), benchmark=_pct(sb["vol"])),
        PerfStat(label="Sharpe ratio (rf 3%)", model=_num(sm["sharpe"], 2),
                 benchmark=_num(sb["sharpe"], 2)),
        PerfStat(label="Max drawdown", model=_pct(-sm["mdd"]), benchmark=_pct(-sb["mdd"])),
        PerfStat(label="Best 12 months", model=_pct(sm["best"]), benchmark=_pct(sb["best"])),
        PerfStat(label="Worst 12 months", model=_pct(sm["worst"]), benchmark=_pct(sb["worst"])),
        PerfStat(label="Tracking error", model=_pct(te), benchmark="—"),
    ]
    yr = pd.DataFrame({"m": rmod, "b": rben}).groupby(rmod.index.year).apply(
        lambda d: (1 + d).prod() - 1)
    years = [YearReturn(year=int(y), model=round(float(r_.m), 5), benchmark=round(float(r_.b), 5))
             for y, r_ in yr.iterrows()]

    # holdings table
    rows = []
    u = data.market.universe
    for t, x in sorted(w.items(), key=lambda kv: -kv[1]):
        er = data.products[t].expense_ratio_bps if t in data.products else 0.0
        rows.append(HoldingRow(
            ticker=t, name=data.name(t), kind="fund" if t in data.products else "stock",
            asset_class=data.asset_class(t), weight=round(x, 6), expense_ratio_bps=er,
            er_contribution_bps=round(x * er, 3),
            yield_=round(data.yields[t] if t in data.products
                         else float(u.at[t, "dividend_yield"]), 5)))

    alloc = [Weighted(name=a, weight=round(m.asset.get(a, 0.0), 6),
                      market_value=round(m.asset.get(a, 0.0) * NOTIONAL, 2), group=g)
             for a, g in ASSET_CLASSES]

    def eq_rows(p: _Profile) -> dict[str, str]:
        return {"P/E ratio": _num(p.pe, 1, "x"), "P/B ratio": _num(p.pb, 2, "x"),
                "Return on equity": _pct(p.roe), "Dividend yield": _pct(p.div, 2),
                "Avg. market cap": "—" if p.mcap is None else f"${p.mcap / 1e9:,.0f}B",
                "Equity beta": _num(p.beta_eq, 2), "Equity share": _pct(p.eq)}

    def fi_rows(p: _Profile) -> dict[str, str]:
        return {"Effective duration": _num(p.duration, 1, " yrs"),
                "Yield to maturity": _pct(p.ytm, 2), "Average coupon": _pct(p.coupon, 2),
                "Average maturity": _num(p.avg_maturity, 1, " yrs"),
                "Average credit quality": p.avg_rating or "—",
                "Fixed income share": _pct(p.fi_total)}

    em, eb, fm, fb = eq_rows(m), eq_rows(b), fi_rows(m), fi_rows(b)
    stress_b = {x.name: x.pnl_pct for x in rb.stress_tests}

    return BuilderReport(
        name=name, as_of=data.market.as_of, total_weight=round(total, 6), normalized=normalized,
        warnings=warnings, n_holdings=len(w), n_underlying=rm.n_underlying,
        equity_pct=round(m.eq, 6), fixed_income_pct=round(m.fi_total, 6),
        cash_pct=round(m.cash, 6), avg_duration=m.duration, pe_ratio=m.pe, pb_ratio=m.pb,
        net_expense_ratio_bps=round(m.er, 3), yield_=round(m.yld, 6), holdings=rows,
        asset_allocation=alloc,
        equity_size=_slices(dict(m.size), SIZES, keep_zero=True),
        equity_style=_slices(dict(m.style), STYLES, keep_zero=True),
        style_box=[[round(v, 5) for v in r_] for r_ in m.box],
        equity_regions=_slices(m.eq_region, EQ_REGIONS),
        equity_sectors=_slices(dict(m.sector)),
        fi_rating=_slices(m.rating, RATINGS),
        fi_sectors=_slices(m.fi_sector, FI_SECTORS),
        fi_maturity=_slices(m.maturity, MATURITIES, keep_zero=bool(m.maturity)),
        fi_regions=_slices(m.fi_region, FI_REGIONS),
        equity_characteristics=[CharRow(label=k, model=em[k], benchmark=eb[k]) for k in em],
        fi_characteristics=[CharRow(label=k, model=fm[k], benchmark=fb[k]) for k in fm],
        volatility=round(rm.volatility, 6), bench_volatility=round(rb.volatility, 6),
        tracking_error=round(te, 6), beta=rm.beta, factors=factors,
        tail=[x.model_dump(mode="json") for x in rm.tail],
        return_histogram=[x.model_dump(mode="json") for x in rm.return_histogram],
        stress_tests=[x.model_dump(mode="json") for x in rm.stress_tests],
        bench_stress=stress_b,
        performance=perf, perf_stats=perf_stats, calendar_years=years, benchmark=bench,
        methodology=[
            "Simulated numbers from the synthetic market — not real data.",
            "Exposures look through funds to their simulated holdings; equity breakdowns are "
            "shares of the equity sleeve, fixed-income breakdowns shares of the bond sleeve.",
            "Bond characteristics (duration, ratings, sectors, maturities) are mock fund "
            "profiles; P/E and P/B are mock values derived from each stock's value score.",
            "Volatility: ex-ante factor model (market, sectors, styles, stock-specific). "
            "Tail risk: historical simulation over the last 2 years. Stress tests: factor shocks.",
            f"Benchmark: {bench.note}",
            "Hypothetical performance: today's weights held constant (rebalanced daily) over the "
            "simulated price history; no fees or taxes. Not a track record.",
        ],
    )
