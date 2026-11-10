"""Pure roll-up helpers: combine per-account analytics into client- and book-level views.

Book figures are always built from the same per-account numbers the client pages show, so the
book ≈ sum / AUM-weighted average of its clients by construction.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.analytics.types import DatedValue, TaxPeriod


@dataclass(frozen=True, slots=True)
class WeightedTEPoint:
    d: date
    avg_te: float
    p10: float
    p90: float
    n_accounts: int


def value_weighted(values: Sequence[float], weights: Sequence[float]) -> float | None:
    """Weighted mean; None when there is nothing to average."""
    if not values:
        return None
    w = np.asarray(weights, dtype=float)
    v = np.asarray(values, dtype=float)
    total = float(w.sum())
    if total <= 0:
        return float(v.mean())
    return float((v * w).sum() / total)


def _asof_lookup(series: Sequence[DatedValue]) -> tuple[list[date], list[float]]:
    return [p.d for p in series], [p.value for p in series]


def value_at(dates: list[date], values: list[float], d: date) -> float:
    """Last value on or before ``d`` (0 before the series starts)."""
    i = bisect.bisect_right(dates, d) - 1
    return values[i] if i >= 0 else 0.0


def weighted_te_series(
    te_by_account: Mapping[str, Sequence[DatedValue]],
    aum_by_account: Mapping[str, Sequence[DatedValue]],
) -> list[WeightedTEPoint]:
    """Per-date AUM-weighted average TE across accounts, with a 10th–90th percentile band."""
    aum_lookup = {k: _asof_lookup(v) for k, v in aum_by_account.items()}
    by_date: dict[date, list[tuple[float, float]]] = {}
    for acct, series in te_by_account.items():
        dates, vals = aum_lookup.get(acct, ([], []))
        for p in series:
            w = value_at(dates, vals, p.d) if dates else 1.0
            by_date.setdefault(p.d, []).append((p.value, w))
    out: list[WeightedTEPoint] = []
    for d in sorted(by_date):
        pts = by_date[d]
        tes = [t for t, _ in pts]
        avg = value_weighted(tes, [w for _, w in pts])
        out.append(
            WeightedTEPoint(
                d=d,
                avg_te=round(avg if avg is not None else 0.0, 5),
                p10=round(float(np.percentile(tes, 10)), 5),
                p90=round(float(np.percentile(tes, 90)), 5),
                n_accounts=len(pts),
            )
        )
    return out


def sum_tax_periods(histories: Iterable[Sequence[TaxPeriod]]) -> list[TaxPeriod]:
    """Sum several accounts' tax histories period-by-period (union of periods, sorted)."""
    acc: dict[str, list[float]] = {}
    for hist in histories:
        for p in hist:
            a = acc.setdefault(p.period, [0.0] * 7)
            a[0] += p.realized_st_gain
            a[1] += p.realized_lt_gain
            a[2] += p.losses_harvested
            a[3] += p.est_tax_paid
            a[4] += p.est_taxes_saved
            a[5] += p.realized_st_loss
            a[6] += p.realized_lt_loss
    return [TaxPeriod(k, *(round(x, 2) for x in a)) for k, a in sorted(acc.items())]


def sum_aum(
    aum_by_account: Mapping[str, Sequence[DatedValue]], dates: Sequence[date]
) -> list[float]:
    """Total AUM across accounts on each of ``dates`` (as-of lookup per account)."""
    lookups = [_asof_lookup(v) for v in aum_by_account.values() if v]
    return [round(sum(value_at(ds, vs, d) for ds, vs in lookups), 2) for d in dates]


def month_ends(series: Sequence[DatedValue]) -> list[DatedValue]:
    """Keep the last observation of each calendar month (plus the final point)."""
    out: dict[tuple[int, int], DatedValue] = {}
    for p in series:
        out[(p.d.year, p.d.month)] = p
    return [out[k] for k in sorted(out)]
