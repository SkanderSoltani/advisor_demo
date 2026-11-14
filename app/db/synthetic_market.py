"""Deterministic synthetic market: a ~300-name large/mid-cap universe labelled with real company
names (app.db.real_universe; prices and fundamentals stay simulated) and 5 years of daily
prices simulated from a multi-factor model (market + sector + style factors + idiosyncratic noise).

Everything is driven by a single seed so the demo is reproducible. Nothing here is real data.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from app.db.real_universe import assign

TRADING_DAYS = 252
MARKET_GEOMETRIC_RETURN = 0.12

# sector -> (share of names, mean dividend yield, beta offset, share of non-payers)
SECTORS: dict[str, tuple[float, float, float, float]] = {
    "Information Technology": (0.14, 0.008, 0.20, 0.35),
    "Health Care": (0.12, 0.015, -0.05, 0.25),
    "Financials": (0.13, 0.025, 0.05, 0.05),
    "Consumer Discretionary": (0.11, 0.010, 0.15, 0.35),
    "Communication Services": (0.06, 0.010, 0.05, 0.40),
    "Industrials": (0.13, 0.016, 0.05, 0.10),
    "Consumer Staples": (0.07, 0.028, -0.35, 0.02),
    "Energy": (0.05, 0.035, 0.10, 0.05),
    "Utilities": (0.06, 0.036, -0.45, 0.00),
    "Real Estate": (0.06, 0.038, -0.10, 0.00),
    "Materials": (0.07, 0.020, 0.05, 0.08),
}

STYLE_FACTORS = ["value", "quality", "profitability", "momentum", "size"]

_NAME_STEMS = [
    "Aster",
    "Bryn",
    "Cobalt",
    "Drover",
    "Ember",
    "Fenwick",
    "Galen",
    "Harrow",
    "Ionic",
    "Juniper",
    "Kestrel",
    "Lumen",
    "Meridian",
    "Northgate",
    "Orrin",
    "Pellucid",
    "Quarry",
    "Redfern",
    "Solace",
    "Tamsin",
    "Umber",
    "Vantor",
    "Willow",
    "Xeno",
    "Yarrow",
    "Zephyr",
    "Alder",
    "Brightwater",
    "Calder",
    "Dunmore",
    "Eastlake",
    "Foxglove",
    "Granite",
    "Halcyon",
    "Ironwood",
    "Jasper",
    "Keystone",
    "Larkspur",
    "Marlow",
    "Nimbus",
    "Oakhaven",
    "Pinecrest",
    "Quill",
    "Rowan",
    "Silverline",
    "Thistle",
    "Upland",
    "Verdant",
    "Westmark",
    "Ashby",
    "Beacon",
    "Corvid",
]

_SECTOR_SUFFIX: dict[str, list[str]] = {
    "Information Technology": ["Systems", "Software", "Semiconductor", "Networks", "Digital"],
    "Health Care": ["Therapeutics", "Health", "Biosciences", "Medical", "Pharma"],
    "Financials": ["Bancorp", "Financial", "Capital", "Insurance Group", "Trust"],
    "Consumer Discretionary": ["Brands", "Retail", "Motors", "Leisure", "Apparel"],
    "Communication Services": ["Media", "Communications", "Interactive", "Broadcasting"],
    "Industrials": ["Industries", "Aerospace", "Logistics", "Machinery", "Rail"],
    "Consumer Staples": ["Foods", "Beverage", "Household", "Grocers"],
    "Energy": ["Energy", "Petroleum", "Resources", "Midstream"],
    "Utilities": ["Power", "Utilities", "Electric", "Water"],
    "Real Estate": ["Realty", "Properties", "REIT", "Land Trust"],
    "Materials": ["Materials", "Chemicals", "Metals", "Packaging"],
}


@dataclass(slots=True)
class SyntheticMarket:
    """Universe reference data plus simulated price / factor history."""

    universe: pd.DataFrame  # index=ticker
    prices: pd.DataFrame  # index=date, columns=ticker
    factor_returns: pd.DataFrame  # index=date, columns=factor
    loadings: pd.DataFrame  # index=ticker, columns=factor

    @property
    def returns(self) -> pd.DataFrame:
        return self.prices.pct_change().iloc[1:]

    @property
    def as_of(self) -> date:
        return pd.Timestamp(self.prices.index[-1]).date()

    def last_prices(self) -> pd.Series:
        return self.prices.iloc[-1]

    # ------------------------------------------------------------------ persistence
    def save(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.universe.to_csv(data_dir / "universe.csv")
        self.prices.round(4).to_csv(data_dir / "prices.csv.gz", compression="gzip")
        self.factor_returns.to_csv(data_dir / "factor_returns.csv.gz", compression="gzip")
        self.loadings.to_csv(data_dir / "factor_loadings.csv")

    @classmethod
    def load(cls, data_dir: Path) -> SyntheticMarket:
        universe = pd.read_csv(data_dir / "universe.csv", index_col="ticker")
        prices = pd.read_csv(data_dir / "prices.csv.gz", index_col=0, parse_dates=True)
        factors = pd.read_csv(data_dir / "factor_returns.csv.gz", index_col=0, parse_dates=True)
        loadings = pd.read_csv(data_dir / "factor_loadings.csv", index_col=0)
        return cls(universe=universe, prices=prices, factor_returns=factors, loadings=loadings)

    @classmethod
    def exists(cls, data_dir: Path) -> bool:
        return all(
            (data_dir / f).exists()
            for f in (
                "universe.csv",
                "prices.csv.gz",
                "factor_returns.csv.gz",
                "factor_loadings.csv",
            )
        )


def _make_tickers(rng: np.random.Generator, n: int) -> list[str]:
    letters = np.array(list(string.ascii_uppercase))
    out: list[str] = []
    seen: set[str] = set()
    while len(out) < n:
        k = int(rng.choice([3, 4], p=[0.45, 0.55]))
        t = "".join(rng.choice(letters, size=k))
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _make_names(rng: np.random.Generator, sectors: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sector in sectors:
        while True:
            name = f"{rng.choice(_NAME_STEMS)} {rng.choice(_SECTOR_SUFFIX[sector])}"
            if name in seen:
                name = f"{name} {rng.choice(['Corp', 'Holdings', 'Group', 'Inc'])}"
            if name not in seen:
                break
        seen.add(name)
        out.append(name)
    return out


def _zscore(x: np.ndarray) -> np.ndarray:
    return np.asarray((x - x.mean()) / (x.std() + 1e-12), dtype=np.float64)


def generate_market(
    seed: int,
    as_of: date,
    n_names: int = 300,
    years: int = 5,
) -> SyntheticMarket:
    """Simulate the full synthetic market deterministically from ``seed``."""
    rng = np.random.default_rng(seed)

    # ---------------------------------------------------------------- universe
    sector_names = list(SECTORS)
    shares = np.array([SECTORS[s][0] for s in sector_names])
    sectors = list(rng.choice(sector_names, size=n_names, p=shares / shares.sum()))
    tickers = _make_tickers(rng, n_names)
    names = _make_names(rng, sectors)

    rank = np.arange(1, n_names + 1)
    market_cap = 2.5e9 * (n_names / rank) ** 1.2 * np.exp(rng.normal(0, 0.12, n_names))
    market_cap = np.sort(market_cap)[::-1]  # rank order is random w.r.t. sector
    # label each slot with a real company of its sector, biggest first (numbers stay simulated);
    # the random tickers/names above are only drawn to keep the random stream (and prices) unchanged
    real = assign(sectors, [float(x) for x in market_cap])
    tickers = [r[0] for r in real]
    names = [r[1] for r in real]
    sectors = [r[3] for r in real]  # unchanged unless a sector ran out of real companies

    # correlated fundamental scores: value, quality, profitability
    corr = np.array([[1.0, -0.15, 0.0], [-0.15, 1.0, 0.6], [0.0, 0.6, 1.0]])
    fund = rng.multivariate_normal(np.zeros(3), corr, size=n_names).clip(-3, 3)
    value, quality, profitability = fund[:, 0], fund[:, 1], fund[:, 2]

    sec_yield = np.array([SECTORS[s][1] for s in sectors])
    non_payer = rng.random(n_names) < np.array([SECTORS[s][3] for s in sectors])
    dividend_yield = sec_yield * np.exp(rng.normal(0, 0.45, n_names) + 0.2 * value)
    dividend_yield = np.where(non_payer, 0.0, dividend_yield).clip(0, 0.08)

    beta = (1.0 + np.array([SECTORS[s][2] for s in sectors]) + rng.normal(0, 0.15, n_names)).clip(
        0.35, 1.9
    )

    # ---------------------------------------------------------------- factor model
    dates = pd.bdate_range(end=pd.Timestamp(as_of), periods=years * TRADING_DAYS + 1)
    t_len = len(dates)

    # market with volatility clustering (AR(1) log-vol) so there are drawdowns to harvest
    z = np.zeros(t_len)
    for t in range(1, t_len):
        z[t] = 0.985 * z[t - 1] + rng.normal(0, 0.08)
    mkt_vol = 0.16 / np.sqrt(TRADING_DAYS) * np.exp(0.6 * z - 0.18)
    mkt_shock = mkt_vol * rng.standard_normal(t_len)
    # Pin the realised market drift (≈ +12%/yr factor drift) so every seed gives a plausible path:
    # keep the simulated shape (drawdowns, vol clusters) but remove the luck in the mean.
    mkt = mkt_shock - mkt_shock.mean() + np.log1p(MARKET_GEOMETRIC_RETURN) / TRADING_DAYS
    mkt += 0.5 * float(mkt_shock.var())

    sector_f = rng.normal(0.0, 0.09 / np.sqrt(TRADING_DAYS), (t_len, len(sector_names)))
    style_mu = np.array([0.005, 0.01, 0.01, 0.015, -0.005]) / TRADING_DAYS
    style_f = style_mu + rng.normal(0.0, 0.045 / np.sqrt(TRADING_DAYS), (t_len, len(STYLE_FACTORS)))

    size_score = -_zscore(np.log(market_cap))
    momentum_load = rng.normal(0, 1, n_names)
    style_load = 0.35 * np.column_stack([value, quality, profitability, momentum_load, size_score])
    sector_load = np.zeros((n_names, len(sector_names)))
    for i, s in enumerate(sectors):
        sector_load[i, sector_names.index(s)] = 1.0

    factor_names = ["market", *[f"sector:{s}" for s in sector_names], *STYLE_FACTORS]
    F = np.column_stack([mkt, sector_f, style_f])  # noqa: N806
    B = np.column_stack([beta, sector_load, style_load])  # noqa: N806

    cap_pct = (np.argsort(np.argsort(-market_cap)) + 1) / n_names  # 0 = largest
    idio_vol = (0.14 + 0.12 * cap_pct) * np.exp(rng.normal(0, 0.2, n_names)) / np.sqrt(TRADING_DAYS)
    # +½σ² offsets volatility drag so the median stock doesn't decay vs the index
    eps = rng.standard_normal((t_len, n_names)) * idio_vol + 0.5 * idio_vol**2
    rets = F @ B.T + eps
    rets[0] = 0.0
    rets = rets.clip(-0.5, 0.5)

    start_px = np.exp(rng.uniform(np.log(15), np.log(300), n_names))
    px = start_px * np.cumprod(1.0 + rets, axis=0)

    prices = pd.DataFrame(px, index=dates, columns=tickers)
    prices.index.name = "date"

    # momentum score = realised 12-1 month return (z-scored), as practitioners define it
    mom = px[-21] / px[-TRADING_DAYS] - 1.0
    momentum = _zscore(mom).clip(-3, 3)

    last = px[-1]
    universe = pd.DataFrame(
        {
            "ticker": tickers,
            "name": names,
            "sector": sectors,
            "market_cap": market_cap.round(0),
            "shares_outstanding": (market_cap / last).round(0),
            "dividend_yield": dividend_yield.round(5),
            "value": value.round(4),
            "quality": quality.round(4),
            "profitability": profitability.round(4),
            "momentum": momentum.round(4),
            "beta": beta.round(4),
            "price": last.round(4),
        }
    ).set_index("ticker")

    factor_returns = pd.DataFrame(F, index=dates, columns=factor_names)
    factor_returns.index.name = "date"
    loadings = pd.DataFrame(B, index=tickers, columns=factor_names)
    loadings.index.name = "ticker"

    return SyntheticMarket(
        universe=universe, prices=prices, factor_returns=factor_returns, loadings=loadings
    )


def load_or_generate(
    data_dir: Path, seed: int, as_of: date, n_names: int, years: int
) -> SyntheticMarket:
    """Load cached market files from ``data_dir`` or generate + save them."""
    if SyntheticMarket.exists(data_dir):
        return SyntheticMarket.load(data_dir)
    market = generate_market(seed=seed, as_of=as_of, n_names=n_names, years=years)
    market.save(data_dir)
    return market
