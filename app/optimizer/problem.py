"""Tax-aware transition optimizer (convex QP, cvxpy).

Notation (see docs/optimizer.md for the full write-up)
------------------------------------------------------
Securities i ∈ S = held securities ∪ target products, prices p_i, account value V (incl. cash),
target weights w*, covariance Σ over S (exact look-through: Σ_S = E Σ_stock Eᵀ).

Decision variables (scaled for numerical stability)
* u_l ∈ [0, ub_l]  fraction of lot l sold (ub_l = 0 for locked / wash-blocked lots, else 1)
* v_i ≥ 0          purchase of security i as a fraction of V (only target products are buyable)

Post-trade weights   x_i = (h_i p_i − Σ_{l∈i} u_l q_l p_i) / V + v_i
Objective            min (x − w*)ᵀ Σ (x − w*) + (c_tc + λ_turn) · (sells + buys) / V
Gain per lot         g_l = q_l (p_i − basis_l)            (realised gain if fully sold)
Budget (one of)      net gain:  Σ_l g_l u_l ≤ G_max
                     tax:       τ_ST·ST + τ_LT·LT ≤ T_max   and   τ_LT·(ST + LT) ≤ T_max
                     where ST = Σ_{l∈ST} g_l u_l and LT = Σ_{l∈LT} g_l u_l (losses net within
                     each bucket). Together these two linear constraints bound the exact
                     cross-bucket netted tax from above, so exact tax ≤ T_max always holds;
                     they are tight except when LT losses offset ST gains (then conservative).
Cash                 cash + sells ≥ buys + buffer · V
Optional             x_i ≤ max_weight;  |sector(x) − sector(w*)| ≤ band
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

import cvxpy as cp
import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from app.domain.entities import Lot
from app.domain.tax import RealizedGains, add_realized, tax_on_realized
from app.optimizer.lots import ReliefMethod, relieve

Vec = npt.NDArray[np.float64]
Mat = npt.NDArray[np.float64]
BoolVec = npt.NDArray[np.bool_]

WASH_SALE_DAYS = 30
# Trading costs are expressed in TE² (variance) units; κ keeps them "small penalties" that
# break ties and suppress pointless trades without dominating the tracking-error objective.
COST_WEIGHT = 0.02
DUST_VALUE = 1.0  # USD; smaller trades are solver noise and are dropped


class BudgetMode(StrEnum):
    NET_GAIN = "net_gain"
    TAX = "tax"
    NONE = "none"


class LotRelief(StrEnum):
    OPTIMIZER = "optimizer"
    TAX_OPTIMAL = "tax_optimal"
    HIFO = "hifo"


@dataclass(frozen=True, slots=True)
class OptLot:
    lot_id: str
    sec: int  # index into OptimizationProblem.tickers
    quantity: float
    basis_per_share: float
    acquired: date
    locked: bool


@dataclass(frozen=True, slots=True)
class OptimizationProblem:
    tickers: tuple[str, ...]
    prices: Vec
    cov: Mat  # annualised, PSD, over tickers
    target: Vec  # target weights over tickers (sum 1)
    buyable: BoolVec
    lots: tuple[OptLot, ...]
    cash: float
    as_of: date
    st_rate: float
    lt_rate: float
    taxable: bool
    sector_names: tuple[str, ...] = ()
    sector_loadings: Mat = field(default_factory=lambda: np.zeros((0, 0)))  # |S| × n_sectors
    # Optional factorisation of cov as a list of matrices M_k with Σ_k M_kᵀ M_k = cov.
    # Factor-model structure makes the QP far sparser (see risk_factors_from_model).
    cov_factors: tuple[Mat, ...] = ()
    # which securities are single stocks (for ``max_stock_weight``); None = treat all as stocks
    single_stock: BoolVec | None = None

    @property
    def held_shares(self) -> Vec:
        h = np.zeros(len(self.tickers))
        for lot in self.lots:
            h[lot.sec] += lot.quantity
        return h

    @property
    def total_value(self) -> float:
        return float(self.cash + self.held_shares @ self.prices)

    def term(self, lot: OptLot) -> str:
        return "LT" if (self.as_of - lot.acquired).days > 365 else "ST"


@dataclass(frozen=True, slots=True)
class OptimizerSettings:
    min_cash_buffer: float = 0.005
    transaction_cost_bps: float = 5.0
    turnover_penalty: float = 0.0
    min_trade_value: float = 0.0
    max_names: int | None = None
    max_weight: float | None = None
    max_stock_weight: float | None = None  # cap on single stocks only (funds are not capped)
    sector_band: float | None = None
    round_shares: bool = True
    lot_relief: LotRelief = LotRelief.OPTIMIZER


@dataclass(frozen=True, slots=True)
class LotSell:
    lot_id: str
    ticker: str
    shares: float
    price: float
    proceeds: float
    cost_basis: float
    realized_gain: float
    term: str
    acquired: date


@dataclass(frozen=True, slots=True)
class Buy:
    ticker: str
    shares: float
    price: float
    value: float


@dataclass(frozen=True, slots=True)
class TEContribution:
    ticker: str
    active_weight: float
    contribution: float  # sums to TE across securities
    reason: str  # locked | budget | buffer | target | other


@dataclass(slots=True)
class Solution:
    status: str
    solver: str
    solve_ms: float
    mode: BudgetMode
    budget: float | None
    sells: list[LotSell]
    buys: list[Buy]
    post_weights: Vec
    post_cash: float
    te_before: float
    te_after: float
    realized: RealizedGains
    est_tax: float
    linear_tax: float
    turnover: float
    total_value: float
    binding: list[str]
    relaxations: list[str]
    notes: list[str]
    contributions: list[TEContribution]
    wash_blocked_lots: list[str]
    lot_relief_check: dict[str, float]


@dataclass(frozen=True, slots=True)
class FrontierPoint:
    budget: float
    est_tax: float
    net_gain: float
    te: float
    turnover: float
    status: str


@dataclass(frozen=True, slots=True)
class GlideYear:
    year: int
    budget: float
    est_tax: float
    net_gain: float
    te_after: float
    n_trades: int


def _te(d: Vec, cov: Mat) -> float:
    return math.sqrt(max(float(d @ cov @ d), 0.0))


def risk_factors_from_model(
    exposure: Mat, base_loadings: Mat, factor_cov: Mat, base_specific: Mat
) -> tuple[Mat, Mat]:
    """(M1, M2) with M1ᵀM1 + M2ᵀM2 = E (B F Bᵀ + diag D) Eᵀ.

    M1 = Qᵀ Bᵀ Eᵀ  (k × n, dense but only k ≈ 17 rows), F = Q Qᵀ
    M2 = diag(√D) Eᵀ (n_base × n, sparse: identity rows for stocks + fund look-through columns)
    """
    vals, vecs = np.linalg.eigh(0.5 * (factor_cov + factor_cov.T))
    q = vecs * np.sqrt(np.clip(vals, 0.0, None))
    m1 = q.T @ base_loadings.T @ exposure.T
    m2 = np.sqrt(np.clip(base_specific, 0.0, None))[:, None] * exposure.T
    return np.asarray(m1, dtype=np.float64), np.asarray(m2, dtype=np.float64)


def _cov_factor(cov: Mat) -> Mat:
    """G with GᵀG = Σ (eigen-decomposition; robust for singular look-through covariances)."""
    vals, vecs = np.linalg.eigh(0.5 * (cov + cov.T))
    keep = vals > 1e-12 * max(float(vals.max()), 1e-18)
    return np.asarray(np.sqrt(vals[keep])[:, None] * vecs[:, keep].T, dtype=np.float64)


class TransitionOptimizer:
    """Builds the convex problem once (budget is a cvxpy Parameter) and solves it repeatedly."""

    def __init__(self, problem: OptimizationProblem, settings: OptimizerSettings) -> None:
        self.p = problem
        self.s = settings
        n, nl = len(problem.tickers), len(problem.lots)
        self.n, self.nl = n, nl
        self.V = problem.total_value
        self.h = problem.held_shares
        price_l = np.array([problem.prices[lot.sec] for lot in problem.lots])
        q = np.array([lot.quantity for lot in problem.lots])
        self.lot_value = price_l * q  # value of each lot
        self.gain = q * (price_l - np.array([lot.basis_per_share for lot in problem.lots]))
        self.is_st = np.array([problem.term(lot) == "ST" for lot in problem.lots], dtype=bool)
        secs = np.array([lot.sec for lot in problem.lots], dtype=int)
        # lot → security aggregation, sparse (n × L)
        self.agg = sp.csr_matrix((np.ones(nl), (secs, np.arange(nl))), shape=(n, nl))
        # weight removed from security i when lot l is fully sold: agg · diag(lot_value) / V
        self.sell_w = (
            sp.csr_matrix((self.lot_value / self.V, (secs, np.arange(nl))), shape=(n, nl))
            if self.V > 0
            else self.agg
        )
        self.factors: list[Any] = (
            [problem.cov_factors[0]] + [sp.csr_matrix(f) for f in problem.cov_factors[1:]]
            if problem.cov_factors
            else [_cov_factor(problem.cov)]
        )
        self.notes: list[str] = []
        self.wash_blocked: list[str] = []
        self.base_ub = self._lot_upper_bounds()

    # ------------------------------------------------------------------ pre-processing
    def _lot_upper_bounds(self) -> Vec:
        p = self.p
        recent: set[int] = {
            lot.sec for lot in p.lots if (p.as_of - lot.acquired).days <= WASH_SALE_DAYS
        }
        ub = np.ones(self.nl)
        blocked_secs: set[str] = set()
        for j, lot in enumerate(p.lots):
            if lot.locked:
                ub[j] = 0.0
                continue
            is_loss = self.gain[j] < 0
            # Wash-sale guard: a loss sale is disallowed when the same security is bought in this
            # rebalance (it is a target product) or was purchased in the prior 30 days.
            if p.taxable and is_loss and (p.buyable[lot.sec] or lot.sec in recent):
                ub[j] = 0.0
                self.wash_blocked.append(lot.lot_id)
                blocked_secs.add(p.tickers[lot.sec])
        if blocked_secs:
            self.notes.append(
                "Wash-sale guard: loss lots of "
                + ", ".join(sorted(blocked_secs))
                + " are held back (bought now or within the prior 30 days)."
            )
        return ub

    # ------------------------------------------------------------------ model
    def _build(
        self,
        mode: BudgetMode,
        ub: Vec,
        buy_mask: BoolVec,
        use_sector: bool,
        cash_buffer: float,
        forced_full: BoolVec | None = None,
    ) -> tuple[cp.Problem, cp.Variable, cp.Variable, cp.Parameter]:
        p, V = self.p, self.V
        u = cp.Variable(self.nl, nonneg=True)
        v = cp.Variable(self.n, nonneg=True)
        budget = cp.Parameter(nonneg=True)
        held_w = self.h * p.prices / V
        x = held_w - self.sell_w @ u + v
        d = x - p.target
        sells = self.lot_value @ u / V
        buys = cp.sum(v)
        cost = (
            COST_WEIGHT
            * (self.s.transaction_cost_bps / 1e4 + self.s.turnover_penalty)
            * (sells + buys)
        )
        risk = cp.sum([cp.sum_squares(f @ d) for f in self.factors])
        objective = cp.Minimize(risk + cost)
        cons: list[Any] = [u <= ub, v[~buy_mask] == 0] if (~buy_mask).any() else [u <= ub]
        cons.append(p.cash / V + sells >= buys + cash_buffer)
        if forced_full is not None and forced_full.any():
            cons.append(u[forced_full] == ub[forced_full])
        if p.taxable and mode is BudgetMode.NET_GAIN:
            cons.append(self.gain @ u <= budget)
        elif p.taxable and mode is BudgetMode.TAX:
            g_st = np.where(self.is_st, self.gain, 0.0)
            g_lt = np.where(self.is_st, 0.0, self.gain)
            st_net, lt_net = g_st @ u, g_lt @ u
            cons.append(p.st_rate * st_net + p.lt_rate * lt_net <= budget)
            cons.append(p.lt_rate * (st_net + lt_net) <= budget)
        if self.s.max_weight is not None or self.s.max_stock_weight is not None:
            locked_w = np.zeros(self.n)
            for j, lot in enumerate(p.lots):
                if ub[j] == 0:
                    locked_w[lot.sec] += self.lot_value[j] / V
            cap = np.full(self.n, np.inf)
            if self.s.max_weight is not None:
                cap = np.minimum(cap, self.s.max_weight)
            if self.s.max_stock_weight is not None:
                stock = p.single_stock if p.single_stock is not None else np.ones(self.n, bool)
                cap = np.where(stock, np.minimum(cap, self.s.max_stock_weight), cap)
            cap = np.maximum(cap, locked_w + 1e-9)  # locked lots can't be sold down
            idx = np.flatnonzero(np.isfinite(cap))
            if idx.size:
                cons.append(x[idx] <= cap[idx])
        if use_sector and self.s.sector_band is not None and p.sector_loadings.size:
            target_sec = p.sector_loadings.T @ p.target
            band = self.s.sector_band
            cons += [
                p.sector_loadings.T @ x <= target_sec + band,
                p.sector_loadings.T @ x >= target_sec - band,
            ]
        return cp.Problem(objective, cons), u, v, budget

    @staticmethod
    def _solve(prob: cp.Problem) -> str:
        for solver in ("CLARABEL", "OSQP", "SCS"):
            try:
                prob.solve(solver=solver)
            except (cp.error.SolverError, ValueError):
                continue
            if prob.status in ("optimal", "optimal_inaccurate", "infeasible", "unbounded"):
                return solver
        return "none"

    # ------------------------------------------------------------------ public API
    def solve(self, mode: BudgetMode, budget: float | None, *, finalize: bool = True) -> Solution:
        """Solve for one budget. ``finalize`` applies min-trade, rounding and lot relief."""
        t0 = time.perf_counter()
        p = self.p
        te_before = _te(self.h * p.prices / self.V - p.target, p.cov) if self.V > 0 else 0.0
        if self.V <= 0:
            return self._empty(mode, budget, t0)
        if not p.taxable and mode is not BudgetMode.NONE:
            self.notes.append("Tax-deferred account: the gain/tax budget does not apply.")
            mode = BudgetMode.NONE
        b_val = float(budget) if (budget is not None and mode is not BudgetMode.NONE) else 0.0

        relax: list[str] = []
        ub, buy_mask = self.base_ub.copy(), p.buyable.copy()
        use_sector, cash_buffer = True, self.s.min_cash_buffer
        forced: BoolVec | None = None

        def run(budget_value: float) -> tuple[str, str, Vec, Vec]:
            prob, u, v, bp = self._build(mode, ub, buy_mask, use_sector, cash_buffer, forced)
            bp.value = max(budget_value, 0.0)
            solver = self._solve(prob)
            if prob.status not in ("optimal", "optimal_inaccurate"):
                return prob.status, solver, np.zeros(self.nl), np.zeros(self.n)
            uu = np.clip(np.asarray(u.value, dtype=float), 0.0, ub)
            vv = np.clip(np.asarray(v.value, dtype=float), 0.0, None)
            return prob.status, solver, uu, vv

        status, solver, u_val, v_val = run(b_val)
        # relaxation ladder for infeasibility (min-trade is only introduced on the re-solve)
        if status not in ("optimal", "optimal_inaccurate") and use_sector and self.s.sector_band:
            use_sector = False
            relax.append("sector bounds")
            status, solver, u_val, v_val = run(b_val)
        if status not in ("optimal", "optimal_inaccurate") and cash_buffer > 0:
            cash_buffer = 0.0
            relax.append("cash buffer")
            status, solver, u_val, v_val = run(b_val)
        if status not in ("optimal", "optimal_inaccurate"):
            return self._empty(mode, budget, t0, status=status, solver=solver, relaxations=relax)

        if finalize:
            # max names: fully exit the smallest non-target holdings, then re-solve
            if self.s.max_names is not None:
                forced = self._max_names_forcing(u_val, v_val, ub)
                if forced is not None and forced.any():
                    st2, sv2, u2, v2 = run(b_val)
                    if st2 in ("optimal", "optimal_inaccurate"):
                        status, solver, u_val, v_val = st2, sv2, u2, v2
                    else:
                        self.notes.append("Max-names target not reachable within the budget.")
                        forced = None
            # minimum trade size: zero out small trades and re-solve once (relax if infeasible)
            if self.s.min_trade_value > 0:
                small_sell, small_buy = self._small_trades(u_val, v_val)
                if small_sell.any() or small_buy.any():
                    ub_prev, mask_prev = ub.copy(), buy_mask.copy()
                    ub = np.where(small_sell, 0.0, ub)
                    buy_mask = buy_mask & ~small_buy
                    st2, sv2, u2, v2 = run(b_val)
                    if st2 in ("optimal", "optimal_inaccurate"):
                        status, solver, u_val, v_val = st2, sv2, u2, v2
                    else:
                        ub, buy_mask = ub_prev, mask_prev
                        relax.append("min-trade size")
        sol = self._assemble(
            mode, budget, status, solver, u_val, v_val, ub, te_before, relax, finalize, t0
        )
        return sol

    def frontier(self, mode: BudgetMode, n_points: int) -> tuple[list[FrontierPoint], float]:
        """Sweep the budget from 0 to the unconstrained (full-transition) level."""
        full = self.solve(BudgetMode.NONE, None, finalize=False)
        top = max(full.est_tax if mode is BudgetMode.TAX else full.realized.net, 0.0)
        if not self.p.taxable or top <= 0:
            pt = FrontierPoint(
                0.0, full.est_tax, full.realized.net, full.te_after, full.turnover, full.status
            )
            return [pt], top
        pts = []
        for b in np.linspace(0.0, top, n_points):
            sol = self.solve(mode, float(b), finalize=False)
            pts.append(
                FrontierPoint(
                    budget=round(float(b), 2),
                    est_tax=sol.est_tax,
                    net_gain=round(sol.realized.net, 2),
                    te=sol.te_after,
                    turnover=sol.turnover,
                    status=sol.status,
                )
            )
        return pts, top

    # ------------------------------------------------------------------ helpers
    def _exact_tax(self, u_val: Vec) -> float:
        r = RealizedGains()
        for j in np.flatnonzero(u_val > 1e-9):
            r = add_realized(r, float(self.gain[j] * u_val[j]), "ST" if self.is_st[j] else "LT")
        return tax_on_realized(r, self.p.st_rate, self.p.lt_rate) if self.p.taxable else 0.0

    def _small_trades(self, u_val: Vec, v_val: Vec) -> tuple[BoolVec, BoolVec]:
        sell_by_sec = np.asarray(self.agg @ (u_val * self.lot_value)).ravel()
        small_sec = (sell_by_sec > 1e-6) & (sell_by_sec < self.s.min_trade_value)
        small_sell = np.array([small_sec[lot.sec] for lot in self.p.lots], dtype=bool)
        buy_val = v_val * self.V
        small_buy = (buy_val > 1e-6) & (buy_val < self.s.min_trade_value)
        return small_sell, small_buy

    def _max_names_forcing(self, u_val: Vec, v_val: Vec, ub: Vec) -> BoolVec | None:
        assert self.s.max_names is not None
        post = self.h * self.p.prices / self.V - np.asarray(self.sell_w @ u_val).ravel()
        post = post + v_val
        held = [i for i in np.flatnonzero(post > 1e-6)]
        excess = len(held) - self.s.max_names
        if excess <= 0:
            return None
        sellable_secs = {self.p.lots[j].sec for j in range(self.nl) if ub[j] > 0}
        candidates = sorted(
            (i for i in held if self.p.target[i] == 0 and i in sellable_secs),
            key=lambda i: post[i],
        )[:excess]
        if len(candidates) < excess:
            self.notes.append("Max-names: not enough unlocked non-target positions to exit.")
        forced = np.array(
            [lot.sec in set(candidates) and ub[j] > 0 for j, lot in enumerate(self.p.lots)],
            dtype=bool,
        )
        return forced

    def _assemble(
        self,
        mode: BudgetMode,
        budget: float | None,
        status: str,
        solver: str,
        u_val: Vec,
        v_val: Vec,
        ub: Vec,
        te_before: float,
        relax: list[str],
        finalize: bool,
        t0: float,
    ) -> Solution:
        p, V = self.p, self.V
        # ---- sells per lot (optionally re-attributed by a lot-relief method), rounding
        shares_sold = u_val * np.array([lot.quantity for lot in p.lots])
        if finalize and self.s.round_shares:
            shares_sold = np.floor(shares_sold * 1000 + 1e-6) / 1000
        # drop dust (< $1) left by the interior-point solver
        lot_px = np.array([p.prices[lot.sec] for lot in p.lots])
        shares_sold[shares_sold * lot_px < DUST_VALUE] = 0.0
        relief_check: dict[str, float] = {"optimizer_tax": self._tax_of(shares_sold)}
        if finalize and self.s.lot_relief is not LotRelief.OPTIMIZER:
            shares_sold = self._reattribute(shares_sold, ReliefMethod(self.s.lot_relief.value))
            relief_check[f"{self.s.lot_relief.value}_tax"] = self._tax_of(shares_sold)
        sells: list[LotSell] = []
        realized = RealizedGains()
        for j in np.flatnonzero(shares_sold > 0):
            lot = p.lots[j]
            px = float(p.prices[lot.sec])
            sh = float(shares_sold[j])
            cost = sh * lot.basis_per_share
            gain = sh * px - cost
            term = p.term(lot)
            realized = add_realized(realized, gain, term)
            sells.append(
                LotSell(
                    lot.lot_id, p.tickers[lot.sec], sh, px, sh * px, cost, gain, term, lot.acquired
                )
            )
        proceeds = sum(s.proceeds for s in sells)
        # ---- buys, rounded down to whole shares so cash always suffices
        buy_value = v_val * V
        buy_sh = buy_value / p.prices
        if finalize and self.s.round_shares:
            buy_sh = np.floor(buy_sh + 1e-9)
        buy_sh[buy_sh * p.prices < DUST_VALUE] = 0.0
        buys = [
            Buy(p.tickers[i], float(buy_sh[i]), float(p.prices[i]), float(buy_sh[i] * p.prices[i]))
            for i in np.flatnonzero(buy_sh > 0)
        ]
        bought = sum(b.value for b in buys)
        sold_by_sec = np.zeros(self.n)
        for j in np.flatnonzero(shares_sold > 0):
            sold_by_sec[p.lots[j].sec] += shares_sold[j]
        post_sh = self.h - sold_by_sec + buy_sh
        post_w = post_sh * p.prices / V
        post_cash = p.cash + proceeds - bought
        d = post_w - p.target
        te_after = _te(d, p.cov)
        est_tax = tax_on_realized(realized, p.st_rate, p.lt_rate) if p.taxable else 0.0
        g_st = float(sum(s.realized_gain for s in sells if s.term == "ST"))
        g_lt = float(sum(s.realized_gain for s in sells if s.term == "LT"))
        linear_tax = p.st_rate * g_st + p.lt_rate * g_lt if p.taxable else 0.0

        binding = self._binding(mode, budget, realized, linear_tax, post_cash, ub, u_val)
        contribs = self._contributions(d, te_after, shares_sold, ub, mode, binding)
        return Solution(
            status=status,
            solver=solver,
            solve_ms=round((time.perf_counter() - t0) * 1000, 1),
            mode=mode,
            budget=budget,
            sells=sells,
            buys=buys,
            post_weights=post_w,
            post_cash=post_cash,
            te_before=te_before,
            te_after=te_after,
            realized=realized,
            est_tax=round(est_tax, 2),
            linear_tax=round(linear_tax, 2),
            turnover=(proceeds + bought) / 2 / V,
            total_value=V,
            binding=binding,
            relaxations=relax,
            notes=list(dict.fromkeys(self.notes)),
            contributions=contribs,
            wash_blocked_lots=list(self.wash_blocked),
            lot_relief_check={k: round(v, 2) for k, v in relief_check.items()},
        )

    def _tax_of(self, shares_sold: Vec) -> float:
        r = RealizedGains()
        for j in np.flatnonzero(shares_sold > 0):
            lot = self.p.lots[j]
            g = float(shares_sold[j] * (self.p.prices[lot.sec] - lot.basis_per_share))
            r = add_realized(r, g, self.p.term(lot))
        return tax_on_realized(r, self.p.st_rate, self.p.lt_rate) if self.p.taxable else 0.0

    def _reattribute(self, shares_sold: Vec, method: ReliefMethod) -> Vec:
        """Re-assign each security's total sold shares to lots by a standard relief method."""
        out = np.zeros_like(shares_sold)
        index = {lot.lot_id: j for j, lot in enumerate(self.p.lots)}
        for sec in {self.p.lots[j].sec for j in np.flatnonzero(shares_sold > 0)}:
            js = [j for j, lot in enumerate(self.p.lots) if lot.sec == sec]
            total = float(sum(shares_sold[j] for j in js))
            dl = [
                Lot(
                    lot.lot_id,
                    "",
                    self.p.tickers[sec],
                    lot.quantity,
                    lot.quantity * lot.basis_per_share,
                    lot.acquired,
                    lot.locked or self.base_ub[j] == 0,
                )
                for j in js
                for lot in [self.p.lots[j]]
            ]
            for sale in relieve(
                dl,
                total,
                float(self.p.prices[sec]),
                self.p.as_of,
                method,
                self.p.st_rate,
                self.p.lt_rate,
            ):
                out[index[sale.lot_id]] = sale.shares
        return out

    def _binding(
        self,
        mode: BudgetMode,
        budget: float | None,
        realized: RealizedGains,
        linear_tax: float,
        post_cash: float,
        ub: Vec,
        u_val: Vec,
    ) -> list[str]:
        out = []
        if budget is not None and self.p.taxable and mode is not BudgetMode.NONE:
            used = (
                realized.net
                if mode is BudgetMode.NET_GAIN
                else max(linear_tax, self.p.lt_rate * realized.net)
            )
            if used >= budget - max(0.01 * budget, 50.0):
                out.append(f"{mode.value} budget")
        if post_cash <= self.V * self.s.min_cash_buffer * 1.05 + 1.0:
            out.append("cash buffer")
        if any(lot.locked for lot in self.p.lots):
            out.append("locked lots")
        if self.wash_blocked:
            out.append("wash-sale guard")
        return out

    def _contributions(
        self,
        d: Vec,
        te: float,
        shares_sold: Vec,
        ub: Vec,
        mode: BudgetMode,
        binding: list[str],
    ) -> list[TEContribution]:
        if te < 1e-6:
            return []
        p = self.p
        marg = p.cov @ d
        contrib = d * marg / te
        locked_secs = {p.lots[j].sec for j in range(self.nl) if p.lots[j].locked}
        blocked_secs = {
            p.lots[j].sec for j in range(self.nl) if ub[j] == 0 and not p.lots[j].locked
        }
        budget_binding = any("budget" in b for b in binding)
        out = []
        for i in np.argsort(-np.abs(contrib))[:8]:
            if abs(contrib[i]) < 1e-5:
                continue
            if i in locked_secs and d[i] > 0:
                reason = "locked"
            elif i in blocked_secs and d[i] > 0:
                reason = "wash_sale"
            elif d[i] > 0 and p.target[i] == 0 and budget_binding:
                reason = "budget"
            elif d[i] < 0 and p.target[i] > 0:
                reason = "underweight"
            else:
                reason = "other"
            out.append(TEContribution(p.tickers[i], float(d[i]), float(contrib[i]), reason))
        return out

    def _empty(
        self,
        mode: BudgetMode,
        budget: float | None,
        t0: float,
        status: str = "empty",
        solver: str = "none",
        relaxations: list[str] | None = None,
    ) -> Solution:
        n = self.n
        return Solution(
            status=status,
            solver=solver,
            solve_ms=round((time.perf_counter() - t0) * 1000, 1),
            mode=mode,
            budget=budget,
            sells=[],
            buys=[],
            post_weights=np.zeros(n),
            post_cash=self.p.cash,
            te_before=0.0,
            te_after=0.0,
            realized=RealizedGains(),
            est_tax=0.0,
            linear_tax=0.0,
            turnover=0.0,
            total_value=self.V,
            binding=[],
            relaxations=relaxations or [],
            notes=list(self.notes),
            contributions=[],
            wash_blocked_lots=list(self.wash_blocked),
            lot_relief_check={},
        )


def apply_solution(problem: OptimizationProblem, sol: Solution) -> OptimizationProblem:
    """Holdings after executing ``sol`` (buys become new lots acquired on the as-of date)."""
    sold = {s.lot_id: s.shares for s in sol.sells}
    lots: list[OptLot] = []
    for lot in problem.lots:
        q = lot.quantity - sold.get(lot.lot_id, 0.0)
        if q > 1e-9:
            lots.append(replace(lot, quantity=q))
    index = {t: i for i, t in enumerate(problem.tickers)}
    for b in sol.buys:
        lots.append(
            OptLot(
                f"new:{b.ticker}:{problem.as_of}",
                index[b.ticker],
                b.shares,
                b.price,
                problem.as_of,
                False,
            )
        )
    return replace(problem, lots=tuple(lots), cash=sol.post_cash)


def glide_path(
    problem: OptimizationProblem,
    settings: OptimizerSettings,
    mode: BudgetMode,
    annual_budgets: Sequence[float],
) -> tuple[list[GlideYear], list[Solution]]:
    """Spread the transition over several tax years (prices held constant between years)."""
    years: list[GlideYear] = []
    sols: list[Solution] = []
    prob = problem
    for k, b in enumerate(annual_budgets):
        sol = TransitionOptimizer(prob, settings).solve(mode, b)
        sols.append(sol)
        years.append(
            GlideYear(
                year=k + 1,
                budget=b,
                est_tax=sol.est_tax,
                net_gain=round(sol.realized.net, 2),
                te_after=sol.te_after,
                n_trades=len(sol.sells) + len(sol.buys),
            )
        )
        prob = replace(apply_solution(prob, sol), as_of=prob.as_of + timedelta(days=366))
    return years, sols
