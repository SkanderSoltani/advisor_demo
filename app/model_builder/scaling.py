"""Scale one model into a line of models by equity exposure.

The mix inside the equity sleeve and inside the fixed-income sleeve stays the same; only the
size of the two sleeves changes to hit each target equity share. Cash stays at the model's level
(less when a target leaves no room). A model with no bonds borrows SCHZ as its bond sleeve, one
with no equity borrows SCHX.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from app.db.catalog import EQUITY_CLASSES

DEFAULT_FI = "SCHZ"
DEFAULT_EQ = "SCHX"


class ScaledModel(BaseModel):
    equity_pct: int
    label: str  # "60/40"
    holdings: dict[str, float]


def targets(n: int, lo: int, hi: int) -> list[int]:
    n = max(1, min(int(n), 21))
    lo, hi = sorted((max(0, min(100, int(lo))), max(0, min(100, int(hi)))))
    if n == 1:
        return [hi]
    return sorted({round(lo + (hi - lo) * i / (n - 1)) for i in range(n)})


def scale_line(holdings: dict[str, float], n: int, lo: int, hi: int,
               asset_class: Callable[[str], str]) -> list[ScaledModel]:
    tot = sum(holdings.values()) or 1.0
    w = {t: x / tot for t, x in holdings.items() if x > 0}
    eq = {t: x for t, x in w.items() if asset_class(t) in EQUITY_CLASSES}
    cash = {t: x for t, x in w.items() if asset_class(t) == "Cash"}
    fi = {t: x for t, x in w.items() if t not in eq and t not in cash}
    eq = eq or {DEFAULT_EQ: 1.0}
    fi = fi or {DEFAULT_FI: 1.0}
    e_tot, f_tot, c_tot = sum(eq.values()), sum(fi.values()), sum(cash.values())
    out = []
    for e_pct in targets(n, lo, hi):
        e = e_pct / 100
        c = min(c_tot, 1 - e)
        f = max(0.0, 1 - e - c)
        h: dict[str, float] = {}
        for t, x in eq.items():
            h[t] = h.get(t, 0.0) + e * x / e_tot
        for t, x in fi.items():
            h[t] = h.get(t, 0.0) + f * x / f_tot
        for t, x in cash.items():
            h[t] = h.get(t, 0.0) + (c * x / c_tot if c_tot else 0.0)
        h = {t: round(x, 6) for t, x in h.items() if x >= 5e-7}
        top = max(h, key=lambda k: h[k])
        h[top] = round(h[top] + 1 - sum(h.values()), 6)
        out.append(ScaledModel(equity_pct=e_pct, label=f"{e_pct}/{100 - e_pct}", holdings=h))
    return out
