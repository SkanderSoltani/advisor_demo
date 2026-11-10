"""Target-model catalog loaded from ``data/models/target_models.json`` (editable by the team).

The JSON lists *products* (e.g. ETFs) and *models* (weights over products). Because only synthetic
market data exists, every product is simulated by a *proxy rule* over the synthetic stock universe
(see :func:`build_fund_proxies`); analytics then work on the look-through stock weights.
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
    "broad_market", "large_cap", "mid_cap", "small_cap", "large_growth", "large_value", "dividend"
]
FALLBACK_PROXY: ProxyRule = "broad_market"
NAV_START = 20.0


class ProductSpec(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z0-9.\-]{1,12}$")
    name: str
    issuer: str = ""
    asset_class: str = "US Equity"
    expense_ratio_bps: float = Field(0.0, ge=0)
    proxy: str = FALLBACK_PROXY  # unknown rules fall back to broad_market (with a warning)


class ModelHoldingSpec(BaseModel):
    ticker: str
    weight: float = Field(gt=0, le=1)


class TargetModelSpec(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9\-_]{1,20}$")
    name: str
    provider: str = ""
    objective: Literal["total_return", "income"]
    construction: str = "market_cap"
    benchmark: str
    advisory_fee_bps: float = Field(0.0, ge=0)
    description: str = ""
    rationale: str = ""
    regime_overlay: bool = False
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
    models: list[TargetModelSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_refs(self) -> CatalogFile:
        known = {p.ticker for p in self.products}
        if len(known) != len(self.products):
            raise ValueError("duplicate product tickers")
        for m in self.models:
            missing = {h.ticker for h in m.holdings} - known
            if missing:
                raise ValueError(f"model {m.id} references unknown products {sorted(missing)}")
        if len({m.id for m in self.models}) != len(self.models):
            raise ValueError("duplicate model ids")
        return self

    def product(self, ticker: str) -> ProductSpec:
        return next(p for p in self.products if p.ticker == ticker)


def load_catalog(path: Path) -> CatalogFile:
    """Read and validate the catalog JSON."""
    return CatalogFile.model_validate(json.loads(path.read_text()))


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
    nav_df = pd.DataFrame(nav, index=market.prices.index, columns=list(weights.index))
    return FundProxies(weights=weights, nav=nav_df, rules=rules)
