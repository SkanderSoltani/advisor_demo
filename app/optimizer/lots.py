"""Lot relief: attribute a sale of N shares of one security to specific tax lots.

Methods
-------
* ``tax_optimal``: sell lots in ascending order of tax per share, i.e. largest losses first
  (ST losses before LT losses at equal size, since they offset higher-taxed gains), then the
  cheapest gains to realise (LT before ST; high basis before low basis).
* ``hifo``: highest cost per share first (the common custodian default for tax efficiency).

Locked lots are never sold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.domain.entities import Lot
from app.domain.tax import RealizedGains, add_realized

EPS = 1e-9


class ReliefMethod(StrEnum):
    TAX_OPTIMAL = "tax_optimal"
    HIFO = "hifo"


@dataclass(frozen=True, slots=True)
class LotSale:
    lot_id: str
    ticker: str
    shares: float
    price: float
    proceeds: float
    cost_basis: float
    gain: float
    term: str  # "ST" | "LT"
    acquired_date: date


def order_lots(
    lots: Sequence[Lot],
    price: float,
    as_of: date,
    method: ReliefMethod,
    st_rate: float,
    lt_rate: float,
) -> list[Lot]:
    """Unlocked lots in the order they should be sold."""
    sellable = [lot for lot in lots if not lot.locked and lot.quantity > EPS]
    if method is ReliefMethod.HIFO:
        return sorted(sellable, key=lambda lot: (-lot.cost_per_share, lot.acquired_date))

    def tax_per_share(lot: Lot) -> float:
        rate = st_rate if lot.holding_period(as_of).value == "ST" else lt_rate
        return (price - lot.cost_per_share) * rate

    return sorted(sellable, key=lambda lot: (tax_per_share(lot), -lot.cost_per_share))


def relieve(
    lots: Sequence[Lot],
    shares: float,
    price: float,
    as_of: date,
    method: ReliefMethod = ReliefMethod.TAX_OPTIMAL,
    st_rate: float = 0.37,
    lt_rate: float = 0.2,
) -> list[LotSale]:
    """Sell up to ``shares`` across ``lots`` (one ticker). Returns the per-lot sales.

    Sells less than requested if unlocked lots run out.
    """
    remaining = shares
    out: list[LotSale] = []
    for lot in order_lots(lots, price, as_of, method, st_rate, lt_rate):
        if remaining <= EPS:
            break
        q = min(lot.quantity, remaining)
        cost = lot.cost_per_share * q
        out.append(
            LotSale(
                lot_id=lot.lot_id,
                ticker=lot.ticker,
                shares=q,
                price=price,
                proceeds=q * price,
                cost_basis=cost,
                gain=q * price - cost,
                term=lot.holding_period(as_of).value,
                acquired_date=lot.acquired_date,
            )
        )
        remaining -= q
    return out


def realized_from_sales(sales: Sequence[LotSale]) -> RealizedGains:
    """Bucket a set of lot sales into ST/LT gains and losses."""
    acc = RealizedGains()
    for s in sales:
        acc = add_realized(acc, s.gain, s.term)
    return acc
