"""Full-transition estimate: what it costs (in tax) to move an account entirely into a model.

Procedure (no optimisation — this is the "do it all today" reference point):

1. Investable value  V_inv = (Σ market value + cash) · (1 − cash_buffer).
2. Target shares     t_i = w*_i · V_inv / p_i.
3. Sell              max(q_i − t_i, 0) shares of each holding, lots chosen by tax-optimal relief;
                     locked lots are never sold, so a locked excess stays in the portfolio.
4. Buy               underweights pro-rata with the cash available after sales, keeping the buffer.
5. Tax               netted ST/LT realized gains × the household's rates (0 for IRAs).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.entities import Lot
from app.domain.tax import RealizedGains, tax_on_realized
from app.optimizer.lots import LotSale, ReliefMethod, realized_from_sales, relieve

DEFAULT_CASH_BUFFER = 0.005


@dataclass(frozen=True, slots=True)
class FullTransitionEstimate:
    sales: tuple[LotSale, ...]
    buys: dict[str, float]  # ticker -> shares
    realized: RealizedGains
    est_tax: float
    total_value: float
    traded_value: float  # sells + buys
    turnover: float  # (sells + buys) / 2 / total value
    locked_value_retained: float  # value of locked shares above target that could not be sold
    post_weights: dict[str, float]  # ticker -> weight of total value
    post_cash: float


def estimate_full_transition(
    lots: Sequence[Lot],
    prices: Mapping[str, float],
    cash: float,
    target_weights: Mapping[str, float],
    as_of: date,
    st_rate: float,
    lt_rate: float,
    taxable: bool,
    cash_buffer: float = DEFAULT_CASH_BUFFER,
    method: ReliefMethod = ReliefMethod.TAX_OPTIMAL,
) -> FullTransitionEstimate:
    """Estimate trades, realized gains and tax for a complete move into ``target_weights``."""
    by_ticker: dict[str, list[Lot]] = {}
    for lot in lots:
        by_ticker.setdefault(lot.ticker, []).append(lot)
    held = {t: sum(lot.quantity for lot in ls) for t, ls in by_ticker.items()}
    total = cash + sum(q * prices[t] for t, q in held.items())
    if total <= 0:
        return FullTransitionEstimate((), {}, RealizedGains(), 0.0, 0.0, 0.0, 0.0, 0.0, {}, 0.0)

    investable = total * (1.0 - cash_buffer)
    target_sh = {t: w * investable / prices[t] for t, w in target_weights.items() if w > 0}

    sales: list[LotSale] = []
    locked_retained = 0.0
    remaining = dict(held)
    for t, q in held.items():
        excess = q - target_sh.get(t, 0.0)
        if excess <= 1e-9:
            continue
        s = relieve(by_ticker[t], excess, prices[t], as_of, method, st_rate, lt_rate)
        sold = sum(x.shares for x in s)
        remaining[t] = q - sold
        locked_retained += max(excess - sold, 0.0) * prices[t]
        sales.extend(s)

    proceeds = sum(s.proceeds for s in sales)
    available = cash + proceeds - total * cash_buffer
    need = {
        t: (sh - remaining.get(t, 0.0)) * prices[t]
        for t, sh in target_sh.items()
        if sh - remaining.get(t, 0.0) > 1e-9
    }
    need_total = sum(need.values())
    scale = min(1.0, max(available, 0.0) / need_total) if need_total > 0 else 0.0
    buys = {t: v * scale / prices[t] for t, v in need.items()}
    bought = sum(v * scale for v in need.values())

    post_shares = dict(remaining)
    for t, b in buys.items():
        post_shares[t] = post_shares.get(t, 0.0) + b
    post_cash = cash + proceeds - bought
    post_w = {t: q * prices[t] / total for t, q in post_shares.items() if q > 1e-9}

    realized = realized_from_sales(sales)
    tax = tax_on_realized(realized, st_rate, lt_rate) if taxable else 0.0
    traded = proceeds + bought
    return FullTransitionEstimate(
        sales=tuple(sales),
        buys=buys,
        realized=realized,
        est_tax=round(tax, 2),
        total_value=total,
        traded_value=traded,
        turnover=traded / 2.0 / total,
        locked_value_retained=locked_retained,
        post_weights=post_w,
        post_cash=post_cash,
    )
