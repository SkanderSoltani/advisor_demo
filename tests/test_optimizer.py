"""Transition optimizer: budgets, locks, wash sales, cash, frontier, glide path, performance."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.analytics.random_provider import RandomAnalyticsProvider
from app.db import models as m
from app.domain.tax import tax_on_realized
from app.optimizer.problem import (
    BudgetMode,
    LotRelief,
    OptimizationProblem,
    OptimizerSettings,
    OptLot,
    TransitionOptimizer,
    glide_path,
    risk_factors_from_model,
)
from tests.conftest import TEST_AS_OF

TR_MODEL = {"SCHX": 0.55, "SCHG": 0.15, "SCHV": 0.15, "SCHM": 0.15}


def build(
    db: Session, provider: RandomAnalyticsProvider, account_id: str, target: dict[str, float]
) -> OptimizationProblem:
    a = db.get(m.Account, account_id)
    assert a is not None
    tickers = sorted({lot.ticker for lot in a.lots} | set(target))
    idx = {t: i for i, t in enumerate(tickers)}
    rm = provider.get_risk_model(tickers)
    px = provider.get_prices(tickers)
    sec = [k for k, f in enumerate(rm.factor_names) if f.startswith("sector:")]
    c = a.client
    return OptimizationProblem(
        tickers=tuple(tickers),
        prices=np.array([px[t] for t in tickers]),
        cov=rm.covariance,
        target=np.array([target.get(t, 0.0) for t in tickers]),
        buyable=np.array([target.get(t, 0.0) > 0 for t in tickers]),
        lots=tuple(
            OptLot(
                lot.id,
                idx[lot.ticker],
                lot.quantity,
                lot.cost_basis_total / lot.quantity,
                lot.acquired_date,
                lot.locked,
            )
            for lot in a.lots
        ),
        cash=a.cash,
        as_of=TEST_AS_OF,
        st_rate=c.federal_st_rate + c.state_rate,
        lt_rate=c.federal_lt_rate + c.state_rate,
        taxable=a.account_type not in ("ira", "roth_ira"),
        sector_names=tuple(rm.factor_names[k] for k in sec),
        sector_loadings=rm.loadings[:, sec],
        cov_factors=factors(rm),
    )


def factors(rm):  # type: ignore[no-untyped-def]
    return risk_factors_from_model(
        rm.exposure, rm.base_loadings, rm.factor_covariance, rm.base_specific_variance
    )


@pytest.fixture(scope="module")
def legacy(db_module: Session, provider: RandomAnalyticsProvider) -> OptimizationProblem:
    acct = db_module.query(m.Account).filter(m.Account.target_model_id.is_(None)).one()
    return build(db_module, provider, acct.id, TR_MODEL)


@pytest.fixture(scope="module")
def db_module(engine, seeded):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=engine)() as s:
        yield s


# ---------------------------------------------------------------- budgets
@pytest.mark.parametrize("budget", [0.0, 10_000.0, 40_000.0, 90_000.0])
def test_tax_never_exceeds_budget(legacy: OptimizationProblem, budget: float) -> None:
    sol = TransitionOptimizer(legacy, OptimizerSettings()).solve(BudgetMode.TAX, budget)
    assert sol.status == "optimal"
    exact = tax_on_realized(sol.realized, legacy.st_rate, legacy.lt_rate)
    assert exact == pytest.approx(sol.est_tax, abs=0.01)
    assert exact <= budget + 1.0
    assert sol.te_after < sol.te_before


def test_net_gain_budget(legacy: OptimizationProblem) -> None:
    sol = TransitionOptimizer(legacy, OptimizerSettings()).solve(BudgetMode.NET_GAIN, 50_000)
    assert sol.realized.net <= 50_000 + 1.0
    assert "net_gain budget" in sol.binding


def test_zero_budget_still_improves_by_harvesting(legacy: OptimizationProblem) -> None:
    sol = TransitionOptimizer(legacy, OptimizerSettings()).solve(BudgetMode.TAX, 0)
    assert sol.est_tax <= 1.0
    assert sol.realized.st_loss + sol.realized.lt_loss > 0
    assert sol.te_after < 0.8 * sol.te_before


# ---------------------------------------------------------------- locks, cash, long-only
def test_locked_lots_never_sold(legacy: OptimizationProblem) -> None:
    locked = {lot.lot_id for lot in legacy.lots if lot.locked}
    assert locked
    sol = TransitionOptimizer(legacy, OptimizerSettings()).solve(BudgetMode.NONE, None)
    assert not locked & {s.lot_id for s in sol.sells}
    assert any(c.reason == "locked" for c in sol.contributions)


def test_extra_locks(legacy: OptimizationProblem) -> None:
    big = max(legacy.lots, key=lambda lot: lot.quantity * legacy.prices[lot.sec])
    prob = replace(
        legacy,
        lots=tuple(replace(lot, locked=True) if lot is big else lot for lot in legacy.lots),
    )
    sol = TransitionOptimizer(prob, OptimizerSettings()).solve(BudgetMode.NONE, None)
    assert big.lot_id not in {s.lot_id for s in sol.sells}


def test_cash_and_long_only(legacy: OptimizationProblem) -> None:
    s = OptimizerSettings(min_cash_buffer=0.01)
    sol = TransitionOptimizer(legacy, s).solve(BudgetMode.TAX, 30_000)
    assert sol.post_cash >= 0.01 * sol.total_value - 1.0
    assert (sol.post_weights >= -1e-9).all()
    assert sol.post_weights.sum() + sol.post_cash / sol.total_value == pytest.approx(1, abs=1e-6)
    for sl in sol.sells:
        lot = next(x for x in legacy.lots if x.lot_id == sl.lot_id)
        assert sl.shares <= lot.quantity + 1e-9
    assert all(b.shares == int(b.shares) for b in sol.buys)  # whole shares


def test_ira_ignores_budget(db_module: Session, provider: RandomAnalyticsProvider) -> None:
    ira = db_module.query(m.Account).filter_by(account_type="ira").first()
    assert ira is not None
    prob = build(db_module, provider, ira.id, TR_MODEL)
    sol = TransitionOptimizer(prob, OptimizerSettings()).solve(BudgetMode.TAX, 0)
    assert sol.est_tax == 0 and sol.te_after < 0.005  # nothing locked → near-full transition
    assert any("Tax-deferred" in n for n in sol.notes)


# ---------------------------------------------------------------- wash sale
def _toy(lots: tuple[OptLot, ...], buyable: bool, taxable: bool = True) -> OptimizationProblem:
    cov = np.array([[0.04, 0.03], [0.03, 0.04]])
    return OptimizationProblem(
        tickers=("AAA", "FND"),
        prices=np.array([100.0, 50.0]),
        cov=cov,
        target=np.array([0.0, 1.0]) if not buyable else np.array([0.5, 0.5]),
        buyable=np.array([buyable, True]),
        lots=lots,
        cash=1_000.0,
        as_of=TEST_AS_OF,
        st_rate=0.4,
        lt_rate=0.2,
        taxable=taxable,
    )


def test_wash_sale_blocks_loss_sale_of_bought_security() -> None:
    loss = OptLot("loss", 0, 100, 150.0, date(2020, 1, 2), False)
    prob = _toy((loss,), buyable=True)
    opt = TransitionOptimizer(prob, OptimizerSettings())
    sol = opt.solve(BudgetMode.NONE, None)
    assert "loss" in sol.wash_blocked_lots and not sol.sells
    assert any("Wash-sale" in n for n in sol.notes)


def test_wash_sale_recent_purchase() -> None:
    old_loss = OptLot("old", 0, 100, 150.0, date(2020, 1, 2), False)
    recent = OptLot("recent", 0, 10, 90.0, TEST_AS_OF - timedelta(days=10), False)
    sol = TransitionOptimizer(_toy((old_loss, recent), buyable=False), OptimizerSettings()).solve(
        BudgetMode.NONE, None
    )
    assert "old" not in {s.lot_id for s in sol.sells}
    assert "recent" in {s.lot_id for s in sol.sells}  # a gain lot may still be sold
    # no guard in tax-deferred accounts
    sol_ira = TransitionOptimizer(
        _toy((old_loss, recent), buyable=False, taxable=False), OptimizerSettings()
    ).solve(BudgetMode.NONE, None)
    assert "old" in {s.lot_id for s in sol_ira.sells}


# ---------------------------------------------------------------- frontier & glide path
def test_frontier_monotone(legacy: OptimizationProblem) -> None:
    pts, top = TransitionOptimizer(legacy, OptimizerSettings()).frontier(BudgetMode.TAX, 12)
    assert len(pts) == 12 and top > 0
    tes = [p.te for p in pts]
    taxes = [p.est_tax for p in pts]
    assert all(b <= a + 1e-5 for a, b in pairwise(tes))  # TE falls
    assert all(b >= a - 1.0 for a, b in pairwise(taxes))  # tax rises
    assert all(p.est_tax <= p.budget + 1.0 for p in pts)
    assert tes[-1] < tes[0]


def test_glide_path(legacy: OptimizationProblem) -> None:
    years, _ = glide_path(legacy, OptimizerSettings(), BudgetMode.TAX, [20_000, 20_000, 20_000])
    assert [y.year for y in years] == [1, 2, 3]
    tes = [y.te_after for y in years]
    assert tes == sorted(tes, reverse=True)
    assert all(y.est_tax <= y.budget + 1.0 for y in years)


# ---------------------------------------------------------------- post-processing
def test_min_trade_and_max_weight(legacy: OptimizationProblem) -> None:
    s = OptimizerSettings(min_trade_value=2_500, max_weight=0.5)
    sol = TransitionOptimizer(legacy, s).solve(BudgetMode.TAX, 50_000)
    by_ticker: dict[str, float] = {}
    for x in sol.sells:
        by_ticker[x.ticker] = by_ticker.get(x.ticker, 0.0) + x.proceeds
    assert all(v >= 2_500 - 1 for v in by_ticker.values())
    assert all(b.value >= 2_500 - 1 for b in sol.buys)
    assert sol.post_weights.max() <= 0.5 + 1e-3


def test_hifo_reattribution_conserves_shares(legacy: OptimizationProblem) -> None:
    base = TransitionOptimizer(legacy, OptimizerSettings()).solve(BudgetMode.TAX, 40_000)
    hifo = TransitionOptimizer(legacy, OptimizerSettings(lot_relief=LotRelief.HIFO)).solve(
        BudgetMode.TAX, 40_000
    )

    def per_ticker(sol) -> dict[str, float]:  # type: ignore[no-untyped-def]
        out: dict[str, float] = {}
        for s in sol.sells:
            out[s.ticker] = out.get(s.ticker, 0.0) + s.shares
        return out

    a, b = per_ticker(base), per_ticker(hifo)
    assert a.keys() == b.keys()
    for t in a:
        assert b[t] == pytest.approx(a[t], abs=0.01)
    assert "hifo_tax" in hifo.lot_relief_check


def test_infeasible_sector_band_is_relaxed(legacy: OptimizationProblem) -> None:
    sol = TransitionOptimizer(legacy, OptimizerSettings(sector_band=0.001)).solve(BudgetMode.TAX, 0)
    assert sol.status == "optimal" and "sector bounds" in sol.relaxations


def test_dense_and_factor_forms_agree(legacy: OptimizationProblem) -> None:
    dense = replace(legacy, cov_factors=())
    a = TransitionOptimizer(legacy, OptimizerSettings()).solve(BudgetMode.TAX, 30_000)
    b = TransitionOptimizer(dense, OptimizerSettings()).solve(BudgetMode.TAX, 30_000)
    assert a.te_after == pytest.approx(b.te_after, abs=2e-4)
    assert a.est_tax == pytest.approx(b.est_tax, abs=50)


def test_empty_account() -> None:
    prob = OptimizationProblem(
        tickers=("FND",),
        prices=np.array([50.0]),
        cov=np.array([[0.04]]),
        target=np.array([1.0]),
        buyable=np.array([True]),
        lots=(),
        cash=0.0,
        as_of=TEST_AS_OF,
        st_rate=0.4,
        lt_rate=0.2,
        taxable=True,
    )
    sol = TransitionOptimizer(prob, OptimizerSettings()).solve(BudgetMode.TAX, 1000)
    assert sol.status == "empty" and not sol.sells and not sol.buys


# ---------------------------------------------------------------- performance
def test_300_names_1000_lots_under_two_seconds(provider: RandomAnalyticsProvider) -> None:
    rng = np.random.default_rng(7)
    stocks = list(provider.market.universe.index)
    tickers = sorted(stocks + list(TR_MODEL))
    idx = {t: i for i, t in enumerate(tickers)}
    px = provider.get_prices(tickers)
    lots = []
    for k in range(1000):
        t = stocks[k % 300]
        acquired = TEST_AS_OF - timedelta(days=int(rng.integers(5, 3000)))
        lots.append(
            OptLot(
                f"L{k}",
                idx[t],
                float(rng.uniform(5, 200)),
                px[t] * float(rng.uniform(0.5, 1.4)),
                acquired,
                bool(k % 97 == 0),
            )
        )
    rm = provider.get_risk_model(tickers)
    prob = OptimizationProblem(
        tickers=tuple(tickers),
        prices=np.array([px[t] for t in tickers]),
        cov=rm.covariance,
        target=np.array([TR_MODEL.get(t, 0.0) for t in tickers]),
        buyable=np.array([t in TR_MODEL for t in tickers]),
        lots=tuple(lots),
        cash=10_000.0,
        as_of=TEST_AS_OF,
        st_rate=0.45,
        lt_rate=0.28,
        taxable=True,
        cov_factors=factors(rm),
    )
    t0 = time.perf_counter()
    sol = TransitionOptimizer(prob, OptimizerSettings()).solve(BudgetMode.TAX, 50_000)
    elapsed = time.perf_counter() - t0
    assert sol.status == "optimal" and sol.est_tax <= 50_001
    assert elapsed < 2.0, f"solve took {elapsed:.2f}s"
