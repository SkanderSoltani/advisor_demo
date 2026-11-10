"""Portfolio-construction primitives over the synthetic universe.

Used to build the synthetic benchmarks and the product (ETF) proxies behind the target-model
catalog: cap weighting, top-N screens, bounded tilts, sector caps and tracking error.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Vec = npt.NDArray[np.float64]
Mat = npt.NDArray[np.float64]

TILT_BOUND = 0.5
INCOME_SECTOR_CAP = 0.25
INCOME_ELIGIBLE_TOP = 200
TR_BENCHMARK = "SYN-LMC"
INC_BENCHMARK = "SYN-DIV"
BENCHMARK_NAMES = {
    TR_BENCHMARK: "Synthetic US Large/Mid Cap Index",
    INC_BENCHMARK: "Synthetic US Dividend Index",
}


@dataclass(frozen=True, slots=True)
class UniverseArrays:
    """Universe reference data as aligned arrays (index i ↔ tickers[i])."""

    tickers: Sequence[str]
    sectors: Sequence[str]
    market_cap: Vec
    dividend_yield: Vec
    value: Vec
    quality: Vec
    profitability: Vec
    momentum: Vec


# --------------------------------------------------------------------------- primitives
def zscore(x: Vec) -> Vec:
    """Cross-sectional z-score."""
    sd = float(x.std())
    return np.asarray((x - x.mean()) / (sd if sd > 0 else 1.0), dtype=np.float64)


def normalize(w: Vec) -> Vec:
    """Clip negatives and rescale to sum to one."""
    w = np.clip(w, 0.0, None)
    total = float(w.sum())
    if total <= 0:
        raise ValueError("cannot normalise an all-zero weight vector")
    return w / total


def tracking_error(w: Vec, benchmark: Vec, cov: Mat) -> float:
    """Annualised ex-ante tracking error sqrt((w-b)ᵀ Σ (w-b)); ``cov`` must be annualised."""
    d = w - benchmark
    return float(np.sqrt(max(float(d @ cov @ d), 0.0)))


def shrunk_sample_covariance(returns: Mat, delta: float = 0.2, periods: int = 252) -> Mat:
    """Annualised sample covariance shrunk toward its diagonal: (1-δ)·S + δ·diag(S)."""
    s = np.cov(returns, rowvar=False) * periods
    return np.asarray((1.0 - delta) * s + delta * np.diag(np.diag(s)), dtype=np.float64)


def cap_weights(market_cap: Vec, mask: npt.NDArray[np.bool_]) -> Vec:
    """Cap weights over the names selected by ``mask``."""
    return normalize(np.where(mask, market_cap, 0.0))


def top_n_mask(market_cap: Vec, eligible: npt.NDArray[np.bool_], n: int) -> npt.NDArray[np.bool_]:
    """Mask of the ``n`` largest eligible names."""
    caps = np.where(eligible, market_cap, -np.inf)
    idx = np.argsort(-caps)[:n]
    mask = np.zeros(len(market_cap), dtype=bool)
    mask[idx] = True
    return mask & eligible


def apply_tilt(base: Vec, score: Vec, bound: float = TILT_BOUND) -> Vec:
    """Multiply each base weight by (1 + bound·tanh(score)) and renormalise."""
    return normalize(base * (1.0 + bound * np.tanh(score)))


def apply_sector_cap(w: Vec, sectors: Sequence[str], cap: float, max_iter: int = 50) -> Vec:
    """Cap each sector's total weight at ``cap``, redistributing excess pro-rata to the others."""
    w = normalize(w.copy())
    sec = np.asarray(sectors)
    names = np.unique(sec)
    capped: set[str] = set()
    for _ in range(max_iter):
        totals = {s: float(w[sec == s].sum()) for s in names}
        over = [s for s in names if totals[s] > cap + 1e-12]
        if not over:
            break
        for s in over:
            w[sec == s] *= cap / totals[s]
            capped.add(s)
        free = ~np.isin(sec, list(capped))
        room = 1.0 - float(w[~free].sum())
        free_total = float(w[free].sum())
        if free_total <= 0:
            break
        w[free] *= room / free_total
    return w


# --------------------------------------------------------------------------- benchmarks
def income_eligible(u: UniverseArrays) -> npt.NDArray[np.bool_]:
    """Income screen: among the largest INCOME_ELIGIBLE_TOP names, payers with yield ≥ median."""
    top = top_n_mask(u.market_cap, np.ones(len(u.tickers), dtype=bool), INCOME_ELIGIBLE_TOP)
    med_yield = float(np.median(u.dividend_yield[top]))
    return top & (u.dividend_yield >= med_yield) & (u.dividend_yield > 0)


def build_benchmarks(u: UniverseArrays) -> dict[str, Vec]:
    """Benchmark weight vectors keyed by benchmark code ("SYN-LMC", "SYN-DIV").

    SYN-LMC = cap-weighted full universe; SYN-DIV = cap-weighted income-eligible names with the
    same 25% sector cap the income models use (like most published dividend indices).
    """
    return {
        TR_BENCHMARK: cap_weights(u.market_cap, np.ones(len(u.tickers), dtype=bool)),
        INC_BENCHMARK: apply_sector_cap(
            cap_weights(u.market_cap, income_eligible(u)), u.sectors, INCOME_SECTOR_CAP
        ),
    }
