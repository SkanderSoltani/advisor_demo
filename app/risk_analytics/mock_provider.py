"""Simulated point-in-time analytics over the synthetic market (``data_source = "mock"``).

Nothing here is random at report time: every number is computed from the synthetic price and
factor history and the (seeded, saved) mock security master, so the same holdings always give the
same report.

* Look-through: funds are replaced by their proxy stock weights; cash carries no risk.
* Exposures: asset class, GICS sector, country and region from the security master.
* Volatility: ex-ante factor model σ² = xᵀFx + Σ wᵢ² dᵢ, with x = Bᵀw (loadings from the
  generator; factor covariance F and specific variance d over the last two years).
* Decomposition: Euler split of variance into market, sector, style factors and stock-specific.
* VaR / CVaR: historical simulation of today's weights over the last 504 days (1-day), scaled by
  √21 for 1 month.
* Stress tests: hypothetical factor shocks applied to the portfolio's factor exposures.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

import numpy as np
import pandas as pd

from app.db.catalog import FundProxies
from app.db.synthetic_market import SyntheticMarket
from app.risk_analytics.provider import RiskAnalyticsProvider
from app.risk_analytics.security_master import (
    ASSET_CLASSES,
    ASSET_GROUP,
    RISK_SCALE,
    SecurityMaster,
)
from app.risk_analytics.types import (
    CountrySlice,
    FactorContribution,
    HistBin,
    Portfolio,
    RiskContributor,
    RiskReport,
    SecurityRef,
    Slice,
    StressResult,
    TailRisk,
)

LOOKBACK = 504
MONTH_DAYS = 21
STYLE = ("value", "quality", "profitability", "momentum", "size")
STYLE_LABELS = {"value": "Value", "quality": "Quality", "profitability": "Profitability",
                "momentum": "Momentum", "size": "Size (small cap)"}

# (name, description, factor shocks). Sector shocks are on top of the market move.
SCENARIOS: list[tuple[str, str, dict[str, float]]] = [
    ("Equity market −20%", "Broad market falls 20%; no other factor moves",
     {"market": -0.20}),
    ("2008-style credit crisis", "Market −35%, financials and real estate hit hardest",
     {"market": -0.35, "sector:Financials": -0.20, "sector:Real Estate": -0.15,
      "sector:Consumer Staples": 0.08, "sector:Health Care": 0.06, "quality": 0.04,
      "size": -0.03}),
    ("COVID-19 shock (Feb–Mar 2020)", "Market −30%, energy collapses, tech holds up",
     {"market": -0.30, "sector:Energy": -0.25, "sector:Financials": -0.08,
      "sector:Real Estate": -0.08, "sector:Information Technology": 0.06,
      "sector:Health Care": 0.04, "momentum": 0.03, "size": -0.04}),
    ("Rates +200 bp", "Rates rise sharply; rate-sensitive sectors fall",
     {"market": -0.07, "sector:Real Estate": -0.10, "sector:Utilities": -0.08,
      "sector:Consumer Staples": -0.03, "sector:Financials": 0.04, "value": 0.02,
      "momentum": -0.02}),
    ("Tech sell-off", "Technology and communication services fall; value outperforms",
     {"market": -0.06, "sector:Information Technology": -0.15,
      "sector:Communication Services": -0.10, "sector:Consumer Discretionary": -0.05,
      "momentum": -0.05, "value": 0.04}),
    ("Oil price spike", "Energy rallies; consumers and industrials lag",
     {"market": -0.04, "sector:Energy": 0.18, "sector:Consumer Discretionary": -0.05,
      "sector:Industrials": -0.03, "sector:Materials": 0.03}),
    ("Equity rally +15%", "Broad market rises 15%",
     {"market": 0.15, "size": 0.02, "momentum": 0.01}),
]

METHODOLOGY = [
    "Simulated numbers from the synthetic market — not real data.",
    "Funds are looked through to their holdings; cash carries no risk.",
    "Volatility: ex-ante factor model (market, 11 GICS sectors, 5 styles, stock-specific), "
    "2-year estimation window, annualised.",
    "VaR / CVaR: historical simulation of today's weights over the last 504 trading days; "
    "1-month figures scaled by √21.",
    "Stress tests: hypothetical factor shocks applied to today's factor exposures.",
    "Asset classes come from the mock security master: some synthetic securities are tagged as "
    "bonds or preferreds and keep only part of their simulated stock risk.",
]


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


class MockRiskProvider(RiskAnalyticsProvider):
    data_source = "mock"
    source_label = "Simulated (mock data)"

    def __init__(self, market: SyntheticMarket, funds: FundProxies, master: SecurityMaster) -> None:
        self.master = master
        self.as_of = market.as_of
        rets = market.returns.iloc[-LOOKBACK:]
        self.tickers = [str(t) for t in rets.columns]
        self.idx = {t: i for i, t in enumerate(self.tickers)}
        fr = market.factor_returns.reindex(rets.index).fillna(0.0)
        self.factors = [str(f) for f in fr.columns]
        self.B = market.loadings.reindex(index=self.tickers, columns=self.factors).fillna(0.0)
        self.B = self.B.to_numpy(dtype=float)
        self.R = rets.fillna(0.0).to_numpy(dtype=float)
        fmat = fr.to_numpy(dtype=float)
        self.F = np.cov(fmat, rowvar=False) * 252
        resid = self.R - fmat @ self.B.T
        self.D = resid.var(axis=0, ddof=1) * 252
        cap = market.universe["market_cap"].reindex(self.tickers).fillna(0.0).to_numpy(dtype=float)
        self.mkt = self.R @ (cap / cap.sum())
        self.look = funds.rows
        # mock: bond / preferred-tagged securities keep only part of their simulated stock risk
        self.scale = np.array([RISK_SCALE.get(master.get(t).asset_class, 1.0)
                               for t in self.tickers])
        self._broad = funds.rows.get("SCHB") or {
            t: c / cap.sum() for t, c in zip(self.tickers, cap, strict=True)
        }
        self._px = pd.concat([market.prices.iloc[-1], funds.nav.iloc[-1]])

    # ------------------------------------------------------------------ interface
    def prices(self, tickers: Sequence[str]) -> dict[str, float]:
        return {t: float(self._px[t]) for t in tickers if t in self._px.index}

    def security_reference(self, tickers: Sequence[str]) -> dict[str, SecurityRef]:
        return {t: self.master.get(t) for t in tickers}

    def analyze(self, portfolio: Portfolio, scope: str = "client") -> RiskReport:
        total = portfolio.market_value
        n = len(self.tickers)
        w = np.zeros(n)
        units: list[tuple[str, float, dict[str, float]]] = []  # (ticker, weight, look-through)
        asset: dict[str, float] = defaultdict(float)
        sector: dict[str, float] = defaultdict(float)
        country: dict[str, float] = defaultdict(float)
        region_of: dict[str, str] = {}
        tot = total if total > 0 else 1.0

        def classify(ref: SecurityRef, wt: float) -> None:
            asset[ref.asset_class] += wt
            sector[ref.sector] += wt
            country[ref.country] += wt
            region_of[ref.country] = ref.region

        def classify_fund(ref: SecurityRef, wt: float, unit: dict[str, float]) -> None:
            """Asset class and country from the fund; GICS sectors from its equity holdings
            (bond, preferred and cash funds have no GICS sector, like cash)."""
            asset[ref.asset_class] += wt
            country[ref.country] += wt
            region_of[ref.country] = ref.region
            if ASSET_GROUP.get(ref.asset_class) != "Equity":
                return
            tot_x = sum(unit.values())
            for s, x in unit.items():
                if tot_x > 0:
                    sector[self.master.get(s).sector] += wt * x / tot_x

        for p in portfolio.positions:
            if p.market_value == 0:
                continue
            wp = p.market_value / tot
            ref = self.master.get(p.ticker)
            if p.ticker in self.idx:
                unit = {p.ticker: 1.0}
                classify(ref, wp)
            elif p.ticker in self.look:
                unit = self.look[p.ticker]
                classify_fund(ref, wp, unit)
            else:  # unknown security: classify as "Other", risk like the broad market
                unit = self._broad
                classify(ref, wp)
            units.append((p.ticker, wp, unit))
            for s, x in unit.items():
                i = self.idx.get(s)
                if i is not None:
                    w[i] += wp * x
        cash_w = portfolio.cash / tot if total > 0 else 0.0
        if portfolio.cash:
            asset["Cash"] += cash_w

        w_val = w  # value weights (exposures); w = risk-equivalent weights below
        w = w_val * self.scale

        # ---- factor model risk
        x = self.B.T @ w
        fx = self.F @ x
        fvar = float(x @ fx)
        svar = float((w**2) @ self.D)
        var = fvar + svar
        vol = math.sqrt(max(var, 0.0))
        c = x * fx  # Euler contribution per factor (sums to fvar)

        def share(v: float) -> float:
            return v / var if var > 0 else 0.0

        fi = {f: i for i, f in enumerate(self.factors)}
        sec_idx = [i for f, i in fi.items() if f.startswith("sector:")]
        rows = [FactorContribution(factor="Market", exposure=_r(x[fi["market"]], 4),
                                   pct_of_variance=_r(share(c[fi["market"]]), 5),
                                   vol_contribution=_r(share(c[fi["market"]]) * vol))]
        sec_c = float(c[sec_idx].sum()) if sec_idx else 0.0
        rows.append(FactorContribution(factor="Sector / industry", exposure=None,
                                       pct_of_variance=_r(share(sec_c), 5),
                                       vol_contribution=_r(share(sec_c) * vol)))
        for f in STYLE:
            if f in fi:
                k = fi[f]
                rows.append(FactorContribution(factor=STYLE_LABELS[f], exposure=_r(x[k], 4),
                                               pct_of_variance=_r(share(c[k]), 5),
                                               vol_contribution=_r(share(c[k]) * vol)))
        rows.append(FactorContribution(factor="Stock-specific", exposure=None,
                                       pct_of_variance=_r(share(svar), 5),
                                       vol_contribution=_r(share(svar) * vol)))
        sec_detail = sorted(
            (FactorContribution(factor=self.factors[i].split(":", 1)[1], exposure=_r(x[i], 4),
                                pct_of_variance=_r(share(c[i]), 5),
                                vol_contribution=_r(share(c[i]) * vol)) for i in sec_idx),
            key=lambda r: -abs(r.pct_of_variance),
        )

        # ---- historical simulation
        rp = self.R @ w
        realized = float(rp.std(ddof=1) * math.sqrt(252)) if total > 0 else 0.0
        mv = float(np.var(self.mkt, ddof=1))
        beta = float(np.cov(rp, self.mkt, ddof=1)[0, 1] / mv) if mv > 0 else 0.0
        tail = []
        for horizon, days in (("1 day", 1), ("1 month", MONTH_DAYS)):
            for conf in (0.95, 0.99):
                q = float(np.quantile(rp, 1 - conf))
                v1 = max(-q, 0.0)
                cv1 = max(-float(rp[rp <= q].mean()), 0.0) if total > 0 else 0.0
                k = math.sqrt(days)
                tail.append(TailRisk(horizon=horizon, days=days, confidence=conf,
                                     var=_r(v1 * k), cvar=_r(cv1 * k),
                                     var_usd=round(v1 * k * total, 2),
                                     cvar_usd=round(cv1 * k * total, 2)))
        counts, edges = np.histogram(rp, bins=40)
        hist = [HistBin(x0=_r(edges[i]), x1=_r(edges[i + 1]), count=int(counts[i]))
                for i in range(len(counts))]

        # ---- stress tests
        stress = []
        for name, desc, shocks in SCENARIOS:
            pnl = sum(x[fi[f]] * s for f, s in shocks.items() if f in fi)
            stress.append(StressResult(name=name, description=desc, pnl_pct=_r(pnl),
                                       pnl_usd=round(pnl * total, 2)))

        # ---- contributors and concentration (by position)
        g = self.B @ fx + self.D * w  # Σw
        contrib: dict[str, list[float]] = {}
        for t, wp, unit in units:
            cg = sum(x_ * self.scale[self.idx[s]] * g[self.idx[s]]
                     for s, x_ in unit.items() if s in self.idx)
            acc = contrib.setdefault(t, [0.0, 0.0])
            acc[0] += wp
            acc[1] += wp * cg
        top = sorted(contrib.items(), key=lambda kv: -kv[1][1])[:10]
        contributors = [RiskContributor(ticker=t, name=self.master.get(t).name, weight=_r(v[0]),
                                        pct_of_risk=_r(share(v[1]), 5)) for t, v in top]
        pw = np.array([v[0] for v in contrib.values()])
        invested = pw.sum()
        top10 = float(np.sort(pw)[::-1][:10].sum()) if len(pw) else 0.0
        eff_n = float(1 / ((pw / invested) ** 2).sum()) if invested > 0 else 0.0

        def slices(d: dict[str, float]) -> list[Slice]:
            return [Slice(name=k, weight=_r(v), market_value=round(v * total, 2))
                    for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if abs(v) > 1e-9]

        def allocation(d: dict[str, float]) -> list[Slice]:
            """Fixed taxonomy and order (zero rows kept), then anything unexpected."""
            names = [a for a, _ in ASSET_CLASSES] + sorted(set(d) - set(ASSET_GROUP))
            return [Slice(name=k, weight=_r(d.get(k, 0.0)),
                          market_value=round(d.get(k, 0.0) * total, 2),
                          group=ASSET_GROUP.get(k, "Other")) for k in names]

        regions: dict[str, float] = defaultdict(float)
        for ctry, v in country.items():
            regions[region_of[ctry]] += v
        # geography covers securities only: cash has no country

        return RiskReport(
            scope=scope,  # type: ignore[arg-type]
            scope_id=portfolio.id,
            name=portfolio.name,
            as_of=self.as_of,
            generated_at=datetime.now().replace(microsecond=0),
            data_source=self.data_source,
            source_label=self.source_label,
            methodology=METHODOLOGY,
            market_value=round(total, 2),
            cash_weight=_r(cash_w),
            n_positions=len(contrib),
            n_underlying=int((w_val > 1e-9).sum()),
            asset_allocation=allocation(asset),
            sectors=slices(sector),
            regions=slices(regions),
            countries=[CountrySlice(region=region_of[s.name], **s.model_dump())
                       for s in slices(country)],
            volatility=_r(vol),
            realized_volatility=_r(realized),
            beta=_r(beta, 4),
            systematic_pct=_r(share(fvar), 5),
            specific_pct=_r(share(svar), 5),
            decomposition=rows,
            sector_factor_detail=sec_detail,
            tail=tail,
            return_histogram=hist,
            stress_tests=stress,
            top_contributors=contributors,
            top10_weight=_r(top10),
            effective_n=round(eff_n, 1),
        )
