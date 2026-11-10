"""Gain/tax arithmetic, lot relief (tax-optimal, HIFO, locks) and the full-transition estimate."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import Lot
from app.domain.tax import RealizedGains, add_realized, pooled_tax, tax_on_realized
from app.optimizer.lots import ReliefMethod, realized_from_sales, relieve
from app.optimizer.transition_cost import estimate_full_transition

AS_OF = date(2026, 10, 30)
ST, LT = 0.5, 0.2


def lot(
    lid: str, q: float, basis_ps: float, acquired: date, locked: bool = False, t: str = "AAA"
) -> Lot:
    return Lot(lid, "acc", t, q, q * basis_ps, acquired, locked)


OLD, NEW = date(2020, 1, 2), date(2026, 6, 1)


# ---------------------------------------------------------------- tax arithmetic
@pytest.mark.parametrize(
    ("r", "expected"),
    [
        (RealizedGains(st_gain=100), 50),
        (RealizedGains(lt_gain=100), 20),
        (RealizedGains(st_gain=100, st_loss=40), 30),
        (RealizedGains(st_gain=100, lt_loss=150), 0),  # cross-bucket: LT loss wipes ST gain
        (RealizedGains(st_gain=100, lt_gain=100, lt_loss=150), 25),  # net LT −50 offsets ST
        (RealizedGains(st_loss=80, lt_gain=100), 4),  # net ST −80 offsets LT → 20 × 0.2
        (RealizedGains(st_loss=10, lt_loss=10), 0),
    ],
)
def test_tax_on_realized(r: RealizedGains, expected: float) -> None:
    assert tax_on_realized(r, ST, LT) == pytest.approx(expected)


def test_add_realized_buckets() -> None:
    acc = add_realized(add_realized(RealizedGains(), 10, "ST"), -4, "LT")
    assert acc == RealizedGains(st_gain=10, lt_loss=4)
    assert acc.net == 6


def test_pooled_tax() -> None:
    assert pooled_tax(100, 100, 150, ST, LT) == pytest.approx(50 * LT)
    assert pooled_tax(0, 0, 10, ST, LT) == 0


# ---------------------------------------------------------------- lot relief
LOTS = [
    lot("gain_lt", 10, 50, OLD),  # price 100 → +50/sh LT  → tax 10/sh
    lot("gain_st", 10, 80, NEW),  # +20/sh ST → tax 10/sh
    lot("loss_st", 10, 130, NEW),  # −30/sh ST → tax −15/sh
    lot("loss_lt", 10, 120, OLD),  # −20/sh LT → tax −4/sh
    lot("locked", 10, 10, OLD, locked=True),
]


def test_tax_optimal_order_losses_first() -> None:
    sales = relieve(LOTS, 25, 100.0, AS_OF, ReliefMethod.TAX_OPTIMAL, ST, LT)
    assert [s.lot_id for s in sales] == ["loss_st", "loss_lt", "gain_st"]
    assert sum(s.shares for s in sales) == pytest.approx(25)
    assert sales[-1].shares == pytest.approx(5)


def test_hifo_order() -> None:
    sales = relieve(LOTS, 40, 100.0, AS_OF, ReliefMethod.HIFO, ST, LT)
    assert [s.lot_id for s in sales] == ["loss_st", "loss_lt", "gain_st", "gain_lt"]


def test_locked_lots_never_sold() -> None:
    sales = relieve(LOTS, 1_000, 100.0, AS_OF, ReliefMethod.TAX_OPTIMAL, ST, LT)
    assert "locked" not in {s.lot_id for s in sales}
    assert sum(s.shares for s in sales) == pytest.approx(40)  # only unlocked shares


def test_realized_from_sales() -> None:
    sales = relieve(LOTS, 40, 100.0, AS_OF, ReliefMethod.HIFO, ST, LT)
    r = realized_from_sales(sales)
    assert r == RealizedGains(st_gain=200, st_loss=300, lt_gain=500, lt_loss=200)


# ---------------------------------------------------------------- full transition
def test_full_transition_into_new_names() -> None:
    lots = [lot("a", 100, 50, OLD, t="AAA"), lot("b", 100, 150, NEW, t="BBB")]
    prices = {"AAA": 100.0, "BBB": 100.0, "FND": 20.0}
    est = estimate_full_transition(lots, prices, 1_000.0, {"FND": 1.0}, AS_OF, ST, LT, True)
    assert est.realized == RealizedGains(lt_gain=5_000, st_loss=5_000)
    assert est.est_tax == pytest.approx(0.0)  # ST loss fully offsets the LT gain
    assert est.post_weights["FND"] == pytest.approx(1 - 0.005, abs=1e-9)
    assert est.locked_value_retained == 0


def test_full_transition_respects_locks_and_ira() -> None:
    lots = [lot("a", 100, 10, OLD, locked=True, t="AAA"), lot("b", 100, 10, OLD, t="BBB")]
    prices = {"AAA": 100.0, "BBB": 100.0, "FND": 20.0}
    taxable = estimate_full_transition(lots, prices, 0.0, {"FND": 1.0}, AS_OF, ST, LT, True)
    assert {s.lot_id for s in taxable.sales} == {"b"}
    assert taxable.locked_value_retained == pytest.approx(10_000)
    assert taxable.post_weights["AAA"] == pytest.approx(0.5)
    assert taxable.est_tax == pytest.approx(9_000 * LT)
    ira = estimate_full_transition(lots, prices, 0.0, {"FND": 1.0}, AS_OF, ST, LT, False)
    assert ira.est_tax == 0 and ira.realized == taxable.realized


def test_full_transition_already_on_target() -> None:
    lots = [lot("a", 99.5, 50, OLD, t="AAA")]
    est = estimate_full_transition(lots, {"AAA": 100.0}, 50.0, {"AAA": 1.0}, AS_OF, ST, LT, True)
    assert est.sales == () and est.est_tax == 0


def test_full_transition_empty_account() -> None:
    est = estimate_full_transition([], {"FND": 20.0}, 0.0, {"FND": 1.0}, AS_OF, ST, LT, True)
    assert est.total_value == 0 and est.post_weights == {}
