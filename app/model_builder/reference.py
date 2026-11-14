"""Mock reference data for the Model Builder (demo only).

* Stocks (synthetic universe): size bucket from market-cap rank, style (value / blend / growth)
  from the value and growth scores, P/E and P/B derived from the value score, country / region
  from the mock security master.
* Equity funds: look-through to their simulated stock basket; non-US funds get a fund-level
  region split.
* Bond, preferred and cash funds: a profile per proxy rule (duration, yield, rating, sector,
  maturity and region mixes) typical of that kind of fund.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "Below B / NR"]
MATURITIES = ["0–1 yr", "1–3 yrs", "3–5 yrs", "5–7 yrs", "7–10 yrs", "10–20 yrs", "20+ yrs"]
FI_SECTORS = ["Treasury", "TIPS", "Agency MBS", "Securitized", "Corporate (IG)", "High yield",
              "Bank loans", "Municipal", "Non-US government", "Preferred", "Cash equivalents"]
FI_REGIONS = ["United States", "Developed ex-US", "Emerging Markets"]
EQ_REGIONS = ["North America", "Europe", "Asia Pacific", "Emerging Markets"]
SIZES = ["Large", "Mid", "Small"]
STYLES = ["Value", "Blend", "Growth"]
RATING_SCORE = {r: i + 1 for i, r in enumerate(RATINGS)}  # AAA = 1 … Below B = 7
MATURITY_MID = [0.5, 2.0, 4.0, 6.0, 8.5, 15.0, 25.0]


@dataclass(frozen=True)
class FIProfile:
    duration: float
    ytm: float
    coupon: float
    rating: dict[str, float]
    sector: dict[str, float]
    maturity: dict[str, float]  # keys: MATURITIES
    region: dict[str, float] = field(default_factory=lambda: {"United States": 1.0})


def _m(*w: float) -> dict[str, float]:
    return {k: v for k, v in zip(MATURITIES, w, strict=True) if v}


FI_PROFILES: dict[str, FIProfile] = {
    "core_bond": FIProfile(6.0, 0.046, 0.036, {"AAA": .72, "AA": .03, "A": .12, "BBB": .13},
                           {"Treasury": .44, "Agency MBS": .26, "Corporate (IG)": .25,
                            "Securitized": .03, "Non-US government": .02},
                           _m(.01, .21, .19, .14, .22, .06, .17),
                           {"United States": .95, "Developed ex-US": .04, "Emerging Markets": .01}),
    "core_plus_bond": FIProfile(6.1, 0.053, 0.042,
                                {"AAA": .55, "AA": .03, "A": .10, "BBB": .17, "BB": .08, "B": .05,
                                 "Below B / NR": .02},
                                {"Treasury": .25, "Agency MBS": .30, "Corporate (IG)": .25,
                                 "High yield": .10, "Securitized": .07, "Non-US government": .03},
                                _m(.02, .20, .20, .14, .20, .07, .17),
                                {"United States": .88, "Developed ex-US": .08,
                                 "Emerging Markets": .04}),
    "short_treasury": FIProfile(1.9, 0.039, 0.031, {"AAA": 1.0}, {"Treasury": 1.0},
                                _m(.05, .95, 0, 0, 0, 0, 0)),
    "interm_treasury": FIProfile(5.1, 0.040, 0.033, {"AAA": 1.0}, {"Treasury": 1.0},
                                 _m(0, 0, .45, .30, .25, 0, 0)),
    "long_treasury": FIProfile(15.5, 0.047, 0.035, {"AAA": 1.0}, {"Treasury": 1.0},
                               _m(0, 0, 0, 0, 0, .35, .65)),
    "tips": FIProfile(6.6, 0.042, 0.011, {"AAA": 1.0}, {"TIPS": 1.0},
                      _m(.03, .22, .22, .17, .20, .06, .10)),
    "corporate": FIProfile(6.2, 0.052, 0.044, {"AAA": .02, "AA": .05, "A": .45, "BBB": .48},
                           {"Corporate (IG)": 1.0}, _m(0, 0, 0, .50, .50, 0, 0),
                           {"United States": .90, "Developed ex-US": .10}),
    "short_corporate": FIProfile(2.6, 0.047, 0.040, {"AAA": .02, "AA": .07, "A": .42, "BBB": .49},
                                 {"Corporate (IG)": 1.0}, _m(0, .55, .45, 0, 0, 0, 0),
                                 {"United States": .90, "Developed ex-US": .10}),
    "high_yield": FIProfile(3.2, 0.073, 0.062, {"BB": .50, "B": .38, "Below B / NR": .12},
                            {"High yield": 1.0}, _m(0, .20, .45, .25, .10, 0, 0),
                            {"United States": .92, "Developed ex-US": .07,
                             "Emerging Markets": .01}),
    "senior_loan": FIProfile(0.3, 0.082, 0.081, {"BB": .20, "B": .65, "Below B / NR": .15},
                             {"Bank loans": 1.0}, _m(.10, .15, .45, .30, 0, 0, 0),
                             {"United States": .95, "Developed ex-US": .05}),
    "global_bond": FIProfile(7.0, 0.036, 0.028, {"AAA": .30, "AA": .30, "A": .25, "BBB": .15},
                             {"Non-US government": .70, "Corporate (IG)": .20,
                              "Securitized": .10},
                             _m(.02, .20, .20, .18, .20, .10, .10),
                             {"Developed ex-US": .85, "Emerging Markets": .15}),
    "preferred": FIProfile(4.5, 0.063, 0.058, {"BBB": .60, "BB": .35, "Below B / NR": .05},
                           {"Preferred": 1.0}, _m(0, 0, 0, .10, 0, .20, .70),
                           {"United States": .90, "Developed ex-US": .10}),
    "muni": FIProfile(5.5, 0.034, 0.045, {"AAA": .20, "AA": .55, "A": .20, "BBB": .05},
                      {"Municipal": 1.0}, _m(0, .12, .20, .20, .25, .18, .05)),
    "short_muni": FIProfile(2.0, 0.029, 0.042, {"AAA": .25, "AA": .55, "A": .17, "BBB": .03},
                            {"Municipal": 1.0}, _m(.20, .60, .20, 0, 0, 0, 0)),
    "cash": FIProfile(0.1, 0.038, 0.038, {"AAA": 1.0}, {"Cash equivalents": 1.0},
                      _m(1, 0, 0, 0, 0, 0, 0)),
}
# non-US equity funds: fund-level region split
INTL_DEVELOPED = {"Europe": .62, "Asia Pacific": .30, "North America": .08}
REGION_OF_MASTER = {"North America": "North America", "Europe": "Europe",
                    "Asia Pacific": "Asia Pacific", "Emerging Markets": "Emerging Markets"}


class StockReference:
    """Size, style, P/E and P/B for every synthetic stock (deterministic)."""

    def __init__(self, universe: pd.DataFrame, seed: int = 11) -> None:
        u = universe
        n = len(u)
        rank = u["market_cap"].rank(ascending=False, method="first") / n
        self.size = pd.Series(np.where(rank <= 0.5, "Large", np.where(rank <= 0.8, "Mid", "Small")),
                              index=u.index)
        z = lambda s: (s - s.mean()) / (s.std() or 1.0)  # noqa: E731
        growth = z(z(u["momentum"]) + z(u["quality"]) - z(u["value"]))
        lo, hi = growth.quantile([1 / 3, 2 / 3])
        self.style = pd.Series(np.where(growth <= lo, "Value",
                                        np.where(growth >= hi, "Growth", "Blend")), index=u.index)
        rng = np.random.default_rng(seed)
        noise = rng.normal(0, 1, size=(2, n))
        v = z(u["value"]).to_numpy()
        self.pe = pd.Series(np.clip(21 - 5.5 * v + 3 * noise[0], 6, 60), index=u.index)
        self.pb = pd.Series(np.clip(3.4 - 1.1 * v + 0.6 * noise[1], 0.6, 15), index=u.index)
        self.roe = (self.pb / self.pe).clip(0.02, 0.6)
        self.mcap = u["market_cap"]
        self.div = u["dividend_yield"]
        self.beta = u["beta"]
        self.sector = u["sector"]
