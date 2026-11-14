"""Mock security master: asset class, GICS sector, country and region per security.

Generated once from the synthetic universe (seeded) and saved to
``data/analytics/security_master.json``; later runs read the file back. Tickers that appear later
(new catalog products, ingested statements) are added and saved too, so earlier rows never change.

* Asset classes: Equity (US Equity, Non-US Stocks), Fixed Income (US Bonds, Non-US Bonds),
  Preferred, Cash. Mock only: about 18% of the synthetic securities are tagged as bonds and 6% as
  preferreds (seeded); US vs non-US follows the country.
* Securities: GICS sector from the universe; size bucket from market-cap rank; ~80% US domicile,
  the rest spread over developed and emerging countries (seeded).
* Funds (catalog products), marked ``is_fund``: asset class from the model catalog (US Equity,
  Non-US Stocks, US Bonds, Non-US Bonds, Preferred, Cash). Non-US funds get a fund-level country
  ("Developed ex-US (fund)" / "Emerging markets (fund)"). Refreshed from the catalog on every
  load, so editing a product's asset class follows through.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from app.db.real_universe import REAL_COUNTRY
from app.risk_analytics.types import SecurityRef

COUNTRIES: list[tuple[str, str, float]] = [  # (country, region, probability)
    ("United States", "North America", 0.80),
    ("Canada", "North America", 0.025),
    ("United Kingdom", "Europe", 0.03),
    ("Germany", "Europe", 0.018),
    ("France", "Europe", 0.015),
    ("Switzerland", "Europe", 0.015),
    ("Netherlands", "Europe", 0.01),
    ("Japan", "Asia Pacific", 0.025),
    ("Australia", "Asia Pacific", 0.01),
    ("Taiwan", "Emerging Markets", 0.012),
    ("China", "Emerging Markets", 0.015),
    ("India", "Emerging Markets", 0.012),
    ("South Korea", "Emerging Markets", 0.008),
    ("Brazil", "Emerging Markets", 0.005),
    # countries of the real companies in the universe (never drawn at random)
    ("Denmark", "Europe", 0.0),
    ("Sweden", "Europe", 0.0),
    ("Belgium", "Europe", 0.0),
    ("Singapore", "Asia Pacific", 0.0),
]
EMERGING = {c for c, r, _ in COUNTRIES if r == "Emerging Markets"}
US_REGION = ("United States", "North America")


MASTER_VERSION = 3  # bump when the taxonomy changes: older files are regenerated

# Asset-class taxonomy: (asset class, group), in display order
ASSET_CLASSES: list[tuple[str, str]] = [
    ("US Equity", "Equity"),
    ("Non-US Stocks", "Equity"),
    ("US Bonds", "Fixed Income"),
    ("Non-US Bonds", "Fixed Income"),
    ("Preferred", "Preferred"),
    ("Cash", "Cash"),
]
ASSET_GROUP = dict(ASSET_CLASSES)
# Mock only: share of synthetic securities tagged as bonds / preferreds, and how much of a
# stock's simulated risk they keep (so a fixed-income tilt lowers portfolio risk).
P_BOND, P_PREFERRED = 0.18, 0.06
RISK_SCALE = {"US Bonds": 0.25, "Non-US Bonds": 0.3, "Preferred": 0.5}


def asset_class(kind: str, country: str) -> str:
    """kind: equity | bond | preferred."""
    us = country == "United States"
    if kind == "bond":
        return "US Bonds" if us else "Non-US Bonds"
    if kind == "preferred":
        return "Preferred"
    return "US Equity" if us else "Non-US Stocks"


class SecurityMaster:
    def __init__(self, path: Path, rows: dict[str, SecurityRef]) -> None:
        self.path = path
        self.rows = rows
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ build / load
    @classmethod
    def load_or_create(
        cls, path: Path, universe: pd.DataFrame, funds: Iterable[tuple[str, ...]], seed: int
    ) -> SecurityMaster:
        """Read the file if it exists; otherwise generate (seeded) and save it.

        ``funds``: (ticker, name, asset class, proxy rule) of every fund product."""
        rows: dict[str, SecurityRef] = {}
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("version") == MASTER_VERSION:
                rows = {r["ticker"]: SecurityRef(**r) for r in data["securities"]}
        sm = cls(path, rows)
        added = sm._add_universe(universe, seed) + sm._add_funds(funds)
        if added or not path.exists() or not rows:
            sm.save()
        return sm

    def _add_universe(self, universe: pd.DataFrame, seed: int) -> int:
        rng = np.random.default_rng([seed, 7_331])
        rank = universe["market_cap"].rank(ascending=False, method="first")
        n = len(universe)
        names = [c for c, _, _ in COUNTRIES]
        probs = np.array([p for _, _, p in COUNTRIES])
        countries = rng.choice(len(names), size=n, p=probs / probs.sum())  # one draw per row
        kind_u = rng.random(n)
        region_of = {c: r for c, r, _ in COUNTRIES}
        added = 0
        for i, (t, row) in enumerate(universe.iterrows()):
            t = str(t)
            if t in self.rows:
                continue
            r = rank[t] / n
            size = "Large" if r <= 0.5 else ("Mid" if r <= 0.8 else "Small")
            country = names[int(countries[i])]
            sector = str(row["sector"])
            u = kind_u[i]
            kind = "bond" if u < P_BOND else ("preferred" if u < P_BOND + P_PREFERRED else "equity")
            if t in REAL_COUNTRY:  # a real company: a stock, in its real home country
                country, kind = REAL_COUNTRY[t], "equity"
            self.rows[t] = SecurityRef(
                ticker=t,
                name=str(row["name"]),
                asset_class=asset_class(kind, country),
                sector=sector,
                country=country,
                region=region_of[country],
                size=size,
            )
            added += 1
        return added

    def _add_funds(self, funds: Iterable[tuple[str, ...]]) -> int:
        """funds: (ticker, name[, asset class[, proxy rule]]). Returns rows added or changed."""
        added = 0
        for f in funds:
            t, name = f[0], f[1]
            ac = f[2] if len(f) > 2 else "US Equity"
            proxy = f[3] if len(f) > 3 else ""
            if ac == "Non-US Stocks":
                country, region = (("Emerging markets (fund)", "Emerging Markets")
                                   if proxy == "emerging" else
                                   ("Developed ex-US (fund)", "Developed ex-US"))
            elif ac == "Non-US Bonds":
                country, region = "Developed ex-US (fund)", "Developed ex-US"
            else:
                country, region = US_REGION
            ref = SecurityRef(ticker=t, name=name, asset_class=ac, sector="Fund",
                              country=country, region=region, is_fund=True)
            if self.rows.get(t) != ref:
                self.rows[t] = ref
                added += 1
        return added

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "_about": "Mock security master (synthetic). Generated once; edit freely. "
                "Replace with Aladdin / Bloomberg reference data when connected.",
                "version": MASTER_VERSION,
                "asset_classes": [{"asset_class": a, "group": g} for a, g in ASSET_CLASSES],
                "securities": [r.model_dump() for r in sorted(self.rows.values(),
                                                               key=lambda r: r.ticker)],
            }
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(body, indent=1))
            tmp.replace(self.path)

    def get(self, ticker: str) -> SecurityRef:
        """Reference row; unknown tickers get an 'Other' row (saved, so it stays stable)."""
        ref = self.rows.get(ticker)
        if ref is None:
            ref = SecurityRef(ticker=ticker, name=ticker, asset_class="Other",
                              sector="Unclassified", country=US_REGION[0], region=US_REGION[1])
            self.rows[ticker] = ref
            self.save()
        return ref
