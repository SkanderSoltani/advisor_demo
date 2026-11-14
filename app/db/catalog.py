"""Target-model catalog loaded from ``data/models/target_models.json`` (editable by the team).

The JSON lists *products* (e.g. ETFs), *lines* of models (each in a category: total return or
income) and *models* (weights over products; each belongs to a line and has a risk
profile). The file is the master copy: the Model management page edits it through
``save_catalog``.

Because only synthetic market data exists, every product is simulated by a *proxy rule* over
the synthetic stock universe (see :func:`build_fund_proxies`); analytics then work on the
look-through stock weights.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.db.synthetic_market import SyntheticMarket
from app.domain import model_construction as mc

ProxyRule = Literal[
    "broad_market", "large_cap", "mid_cap", "small_cap", "large_growth", "large_value", "dividend",
    "intl_developed", "intl_small", "emerging", "reit", "real_assets",
    "core_bond", "core_plus_bond", "short_treasury", "interm_treasury", "long_treasury", "tips",
    "corporate", "short_corporate", "high_yield", "senior_loan", "global_bond", "preferred",
    "muni", "short_muni", "cash",
]
FALLBACK_PROXY: ProxyRule = "broad_market"
NAV_START = 20.0
CASH_NAV = 1.0
# Non-US equity, real assets and bond products are simulated as a *fraction* of a synthetic
# stock basket (the rest behaves like cash), so their simulated risk is lower: e.g. an aggregate
# bond ETF moves like 25% of the large-value basket. Mock only — replaced by real data later.
BLENDS: dict[str, list[tuple[str, float]]] = {
    "intl_developed": [("large_value", 0.55), ("dividend", 0.40)],
    "intl_small": [("small_cap", 0.90)],
    "emerging": [("small_cap", 0.60), ("large_growth", 0.50)],
    "reit": [("dividend", 0.90)],
    "real_assets": [("dividend", 0.50), ("large_value", 0.40)],
    "core_bond": [("large_value", 0.25)],
    "core_plus_bond": [("large_value", 0.30)],
    "short_treasury": [("broad_market", 0.05)],
    "interm_treasury": [("broad_market", 0.20)],
    "long_treasury": [("broad_market", 0.45)],
    "tips": [("broad_market", 0.20)],
    "corporate": [("large_value", 0.30)],
    "short_corporate": [("large_value", 0.12)],
    "high_yield": [("dividend", 0.45)],
    "senior_loan": [("dividend", 0.25)],
    "global_bond": [("large_value", 0.28)],
    "preferred": [("dividend", 0.50)],
    "muni": [("dividend", 0.20)],
    "short_muni": [("dividend", 0.06)],
    "cash": [],
}


class ProductSpec(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z0-9.\-]{1,12}$")
    name: str
    issuer: str = ""
    asset_class: str = "US Equity"
    expense_ratio_bps: float = Field(0.0, ge=0)
    proxy: str = FALLBACK_PROXY  # unknown rules fall back to broad_market (with a warning)
    # distribution / SEC-style yield (decimal); when absent the look-through dividend yield is used
    yield_: float | None = Field(None, alias="yield", ge=0, le=1)

    model_config = {"populate_by_name": True}


class ModelHoldingSpec(BaseModel):
    ticker: str
    weight: float = Field(gt=0, le=1)


CATEGORIES: dict[str, str] = {
    "total_return": "Total Return",
    "income": "Income",
    "tax_efficient": "Tax Efficient",
}
Objective = Literal["total_return", "income", "tax_efficient"]
# asset classes that count as equity (the rest: fixed income, preferred, cash)
EQUITY_CLASSES = {"US Equity", "Non-US Stocks"}
RISK_PROFILES = [
    "Conservative",
    "Moderately conservative",
    "Moderate",
    "Moderately aggressive",
    "Aggressive",
]


class ModelLineSpec(BaseModel):
    """A family of models (e.g. "Core Models") within one category, one model per risk level."""

    id: str = Field(pattern=r"^[A-Za-z0-9\-_]{1,20}$")
    name: str = Field(min_length=1)
    objective: Objective
    description: str = ""
    provider: str = "Charles Schwab"  # "Custom" for lines made in the Model Builder


class TargetModelSpec(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9\-_]{1,20}$")
    name: str
    provider: str = ""
    objective: Objective
    construction: str = "market_cap"
    benchmark: str
    advisory_fee_bps: float = Field(0.0, ge=0)
    description: str = ""
    rationale: str = ""
    regime_overlay: bool = False
    line_id: str | None = None
    risk_profile: str = ""
    holdings: list[ModelHoldingSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> TargetModelSpec:
        total = sum(h.weight for h in self.holdings)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"model {self.id}: weights sum to {total:.6f}, expected 1.0")
        if len({h.ticker for h in self.holdings}) != len(self.holdings):
            raise ValueError(f"model {self.id}: duplicate tickers")
        return self


class CatalogFile(BaseModel):
    version: int = 1
    notice: str = ""
    products: list[ProductSpec]
    # single stocks (synthetic universe) that models hold directly — added by the Model Builder
    stocks: list[str] = Field(default_factory=list)
    lines: list[ModelLineSpec] = Field(default_factory=list)
    models: list[TargetModelSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_refs(self) -> CatalogFile:
        known = {p.ticker for p in self.products}
        if len(known) != len(self.products):
            raise ValueError("duplicate product tickers")
        if known & set(self.stocks):
            raise ValueError("a ticker is listed both as a product and as a stock")
        known |= set(self.stocks)
        for m in self.models:
            missing = {h.ticker for h in m.holdings} - known
            if missing:
                raise ValueError(f"model {m.id} references unknown products {sorted(missing)}")
        if len({m.id for m in self.models}) != len(self.models):
            raise ValueError("duplicate model ids")
        lines = {ln.id: ln for ln in self.lines}
        if len(lines) != len(self.lines):
            raise ValueError("duplicate line ids")
        for m in self.models:
            if m.line_id is None:
                continue
            ln = lines.get(m.line_id)
            if ln is None:
                raise ValueError(f"model {m.id} references unknown line {m.line_id}")
            if ln.objective != m.objective:
                raise ValueError(f"model {m.id}: objective differs from its line {ln.id}")
        return self

    def product(self, ticker: str) -> ProductSpec:
        return next(p for p in self.products if p.ticker == ticker)

    def asset_class(self, ticker: str) -> str:
        """Product asset class; declared single stocks count as US Equity."""
        p = next((p for p in self.products if p.ticker == ticker), None)
        return p.asset_class if p else "US Equity"

    def expense_ratio_bps(self, ticker: str) -> float:
        p = next((p for p in self.products if p.ticker == ticker), None)
        return p.expense_ratio_bps if p else 0.0


def load_catalog(path: Path) -> CatalogFile:
    """Read and validate the catalog JSON."""
    return CatalogFile.model_validate(json.loads(path.read_text()))


def dump_catalog(catalog: CatalogFile) -> str:
    """Readable JSON: one object per product / line / model, holdings on one line each."""
    d = catalog.model_dump(mode="json", by_alias=True)
    for p in d["products"]:
        if p.get("yield") is None:
            p.pop("yield", None)
    one = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731
    out = ["{"]
    for key in ("version", "notice", "proxy_rules"):
        if key in d or key == "proxy_rules":
            val = d.get(key, list(ProxyRule.__args__))  # type: ignore[attr-defined]
            out.append(f'  "{key}": {one(val)},')
    out.append('  "products": [')
    out.append(",\n".join(f"    {one(p)}" for p in d["products"]))
    out.append("  ],")
    if d.get("stocks"):
        out.append(f'  "stocks": {one(d["stocks"])},')
    out.append('  "lines": [')
    out.append(",\n".join(f"    {one(ln)}" for ln in d["lines"]))
    out.append("  ],")
    out.append('  "models": [')
    models = []
    for m in d["models"]:
        fields = [f'      "{k}": {one(v)}' for k, v in m.items()]
        models.append("    {\n" + ",\n".join(fields) + "\n    }")
    out.append(",\n".join(models))
    out.append("  ]")
    out.append("}")
    return "\n".join(out) + "\n"


def save_catalog(path: Path, catalog: CatalogFile) -> None:
    """Validate and write the catalog atomically (temp file + rename)."""
    CatalogFile.model_validate(catalog.model_dump(by_alias=True))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(dump_catalog(catalog))
    tmp.replace(path)


def catalog_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# --------------------------------------------------------------------------- proxies
@dataclass(slots=True)
class FundProxies:
    """Look-through weights (product × stock) and simulated NAV history (date × product)."""

    weights: pd.DataFrame
    nav: pd.DataFrame
    rules: dict[str, str]  # ticker -> rule actually applied
    rows: dict[str, dict[str, float]] = field(default_factory=dict)  # sparse look-through

    def __post_init__(self) -> None:
        cols = [str(c) for c in self.weights.columns]
        for fund in self.weights.index:
            vals = self.weights.loc[fund].to_numpy(dtype=float)
            self.rows[str(fund)] = {cols[i]: float(vals[i]) for i in np.flatnonzero(vals > 0)}

    def look_through(self, weights: dict[str, float]) -> dict[str, float]:
        """Replace product weights by their constituent stock weights (stocks pass through)."""
        out: dict[str, float] = {}
        for t, w in weights.items():
            row = self.rows.get(t)
            if row is None:
                out[t] = out.get(t, 0.0) + w
                continue
            for s, x in row.items():
                out[s] = out.get(s, 0.0) + w * x
        return out


def universe_arrays(market: SyntheticMarket) -> mc.UniverseArrays:
    """Universe reference data as aligned numpy arrays."""
    u = market.universe
    return mc.UniverseArrays(
        tickers=list(u.index),
        sectors=list(u["sector"]),
        market_cap=u["market_cap"].to_numpy(dtype=float),
        dividend_yield=u["dividend_yield"].to_numpy(dtype=float),
        value=u["value"].to_numpy(dtype=float),
        quality=u["quality"].to_numpy(dtype=float),
        profitability=u["profitability"].to_numpy(dtype=float),
        momentum=u["momentum"].to_numpy(dtype=float),
    )


def _proxy_weights(rule: str, u: mc.UniverseArrays) -> np.ndarray:
    n = len(u.tickers)
    allm = np.ones(n, dtype=bool)
    rank = np.argsort(np.argsort(-u.market_cap))  # 0 = largest
    large = rank < 150
    growth = mc.zscore(mc.zscore(u.momentum) + mc.zscore(u.quality) - mc.zscore(u.value))
    if rule == "large_cap":
        return mc.cap_weights(u.market_cap, large)
    if rule == "mid_cap":
        return mc.cap_weights(u.market_cap, rank >= 100)
    if rule == "small_cap":
        return mc.cap_weights(u.market_cap, rank >= 200)
    if rule in ("large_growth", "large_value"):
        med = float(np.median(growth[large]))
        side = growth >= med if rule == "large_growth" else growth < med
        return mc.cap_weights(u.market_cap, large & side)
    if rule in BLENDS:
        out = np.zeros(n)
        for base, share in BLENDS[rule]:
            out += share * _proxy_weights(base, u)
        return out
    if rule == "dividend":
        eligible = mc.income_eligible(u)
        score = mc.zscore(mc.zscore(u.dividend_yield) + mc.zscore(u.quality))
        pick = eligible & (score >= np.median(score[eligible]))
        return mc.apply_sector_cap(mc.cap_weights(u.market_cap, pick), u.sectors, 0.25)
    return mc.cap_weights(u.market_cap, allm)  # broad_market / fallback


def build_fund_proxies(market: SyntheticMarket, catalog: CatalogFile) -> FundProxies:
    """Simulate every catalog product from the synthetic universe."""
    u = universe_arrays(market)
    known = set(ProxyRule.__args__)  # type: ignore[attr-defined]
    rows, rules = {}, {}
    for p in catalog.products:
        rule = p.proxy if p.proxy in known else FALLBACK_PROXY
        rules[p.ticker] = rule
        rows[p.ticker] = _proxy_weights(rule, u)
    weights = pd.DataFrame(rows, index=list(u.tickers)).T
    rets = market.returns
    fund_rets = rets.to_numpy() @ weights.to_numpy().T  # daily-rebalanced proxy returns
    nav = NAV_START * np.cumprod(np.vstack([np.ones(len(weights)), 1 + fund_rets]), axis=0)
    for j, t in enumerate(weights.index):
        if rules[t] == "cash":
            nav[:, j] = CASH_NAV  # cash equivalents: constant $1 NAV
    nav_df = pd.DataFrame(nav, index=market.prices.index, columns=list(weights.index))
    return FundProxies(weights=weights, nav=nav_df, rules=rules)
