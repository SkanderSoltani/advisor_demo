"""Transition sessions: target, locks, optimization, frontier and exports."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import replace
from typing import Any

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy.orm.attributes import flag_modified

from app.analytics.types import AccountContext, LotInput
from app.db import models as m
from app.model_builder.analytics import BuilderData
from app.model_builder.diagnosis import FIXES
from app.model_builder.transition_view import TransitionAnalytics, transition_analytics
from app.optimizer.problem import (
    BudgetMode,
    LotRelief,
    OptimizationProblem,
    OptimizerSettings,
    OptLot,
    Solution,
    TransitionOptimizer,
    glide_path,
    risk_factors_from_model,
)
from app.schemas import transitions as st
from app.schemas.common import DISCLAIMER
from app.services.portfolio import PortfolioService

# every session starts at INGEST_CHOICE; accounts with holdings get a "use current holdings" option
INITIAL_STATE = "INGEST_CHOICE"


def _err(code: int, msg: str) -> HTTPException:
    return HTTPException(code, msg)


class TransitionService:
    def __init__(self, ps: PortfolioService) -> None:
        self.ps = ps
        self.db = ps.db
        self.p = ps.p

    # ------------------------------------------------------------------ sessions
    def get(self, transition_id: str) -> m.Transition:
        t = self.db.get(m.Transition, transition_id)
        if t is None or self.ps.client(t.client_id) is None:
            raise _err(status.HTTP_404_NOT_FOUND, f"Transition {transition_id} not found")
        return t

    def account(self, t: m.Transition) -> m.Account:
        a = self.ps.account(t.account_id)
        if a is None:
            raise _err(status.HTTP_404_NOT_FOUND, f"Account {t.account_id} not found")
        return a

    def create(self, client_id: str, account_id: str, fixes: list[str] | None = None
               ) -> m.Transition:
        c = self.ps.client(client_id)
        if c is None:
            raise _err(status.HTTP_404_NOT_FOUND, f"Client {client_id} not found")
        a = next((x for x in c.accounts if x.id == account_id), None)
        if a is None:
            raise _err(status.HTTP_404_NOT_FOUND, f"Account {account_id} not found for {client_id}")
        t = m.Transition(
            id=f"trn_{uuid.uuid4().hex[:8]}",
            client_id=c.id,
            account_id=a.id,
            state=INITIAL_STATE,
            data={"target_model_id": a.target_model_id, "locks": [], "path": [INITIAL_STATE],
                  "fixes": [f for f in (fixes or []) if f in FIXES]},
        )
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def _save(self, t: m.Transition, drop: tuple[str, ...] = (), **updates: Any) -> None:
        data = {k: v for k, v in (t.data or {}).items() if k not in drop}
        data.update(updates)
        t.data = data
        flag_modified(t, "data")
        self.db.commit()
        self.db.refresh(t)

    def out(self, t: m.Transition) -> st.TransitionOut:
        a = self.account(t)
        data = t.data or {}
        return st.TransitionOut(
            transition_id=t.id,
            client_id=t.client_id,
            account_id=t.account_id,
            state=t.state,
            target_model_id=data.get("target_model_id"),
            locked_lot_ids=list(data.get("locks", [])),
            account_locked_lot_ids=sorted(lot.id for lot in a.lots if lot.locked),
            has_optimization="optimization" in data,
            has_frontier="frontier" in data,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )

    def set_locks(self, t: m.Transition, lot_ids: list[str]) -> st.TransitionOut:
        a = self.account(t)
        known = {lot.id for lot in a.lots}
        unknown = sorted(set(lot_ids) - known)
        if unknown:
            raise _err(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Lots not in account {a.id}: {', '.join(unknown[:10])}",
            )
        # downstream results are invalidated when inputs change
        self._save(t, locks=sorted(set(lot_ids)), drop=("optimization", "frontier"))
        return self.out(t)

    # ------------------------------------------------------------------ problem
    def _target(self, t: m.Transition, override: str | None) -> str:
        a = self.account(t)
        target = override or (t.data or {}).get("target_model_id") or a.target_model_id
        if target is None:
            raise _err(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "No target model: choose one (target_model_id) before optimizing",
            )
        if self.db.get(m.ModelPortfolio, target) is None:
            raise _err(status.HTTP_404_NOT_FOUND, f"Model {target} not found")
        return target

    def problem(
        self, t: m.Transition, target_id: str
    ) -> tuple[OptimizationProblem, AccountContext]:
        a = self.account(t)
        if not a.lots and a.cash <= 0:
            raise _err(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Account has no holdings yet: ingest holdings before optimizing",
            )
        view = self.ps.view(a)
        ctx = replace(
            view.ctx,
            target_model_id=target_id,
            target_weights=self.ps.model_weights(target_id),
        )
        tw = ctx.target_weights
        tickers = sorted({lot.ticker for lot in a.lots} | set(tw))
        idx = {tk: i for i, tk in enumerate(tickers)}
        rm = self.p.get_risk_model(tickers)
        prices = self.p.get_prices(tickers)
        locks = set((t.data or {}).get("locks", []))
        sec_cols = [k for k, f in enumerate(rm.factor_names) if f.startswith("sector:")]
        problem = OptimizationProblem(
            tickers=tuple(tickers),
            prices=np.array([prices[tk] for tk in tickers]),
            cov=rm.covariance,
            target=np.array([tw.get(tk, 0.0) for tk in tickers]),
            buyable=np.array([tw.get(tk, 0.0) > 0 for tk in tickers], dtype=bool),
            lots=tuple(
                OptLot(
                    lot_id=lot.id,
                    sec=idx[lot.ticker],
                    quantity=lot.quantity,
                    basis_per_share=lot.cost_basis_total / lot.quantity,
                    acquired=lot.acquired_date,
                    locked=lot.locked or lot.id in locks,
                )
                for lot in a.lots
                if lot.quantity > 0
            ),
            cash=a.cash,
            as_of=self.ps.as_of,
            single_stock=np.array(
                [tk in BuilderData.get(self.p).stocks for tk in tickers], dtype=bool
            ),
            st_rate=ctx.st_rate,
            lt_rate=ctx.lt_rate,
            taxable=ctx.taxable,
            sector_names=tuple(rm.factor_names[k].removeprefix("sector:") for k in sec_cols),
            sector_loadings=rm.loadings[:, sec_cols],
            cov_factors=(
                risk_factors_from_model(
                    rm.exposure, rm.base_loadings, rm.factor_covariance, rm.base_specific_variance
                )
                if rm.exposure is not None
                and rm.base_loadings is not None
                and rm.base_specific_variance is not None
                else ()
            ),
        )
        return problem, ctx

    @staticmethod
    def settings(c: st.Constraints) -> OptimizerSettings:
        return OptimizerSettings(
            min_cash_buffer=c.min_cash_buffer,
            transaction_cost_bps=c.transaction_cost_bps,
            turnover_penalty=c.turnover_penalty,
            min_trade_value=c.min_trade_value,
            max_names=c.max_names,
            max_weight=c.max_weight,
            max_stock_weight=c.max_stock_weight,
            sector_band=c.sector_band,
            round_shares=c.round_shares,
            lot_relief=LotRelief(c.lot_relief),
        )

    # ------------------------------------------------------------------ snapshots
    def _snapshot(self, ctx: AccountContext, te: float) -> st.PortfolioSnapshot:
        x = self.p.get_exposures(ctx)
        return st.PortfolioSnapshot(
            te=round(te, 5),
            n_holdings=x.n_positions,
            dividend_yield=x.dividend_yield,
            beta=x.beta,
            sector_active={s.sector: round(s.active_weight, 5) for s in x.sectors},
            factor_active={f.factor: round(f.active, 4) for f in x.factors},
        )

    @staticmethod
    def _post_ctx(ctx: AccountContext, prob: OptimizationProblem, sol: Solution) -> AccountContext:
        V = sol.total_value
        lots = tuple(
            LotInput(f"post:{tk}", tk, w * V / prob.prices[i], w * V, ctx.as_of, False)
            for i, (tk, w) in enumerate(zip(prob.tickers, sol.post_weights, strict=True))
            if w > 1e-9
        )
        return replace(
            ctx, lots=lots, cash=sol.post_cash, events=(), account_id=f"{ctx.account_id}:post"
        )

    @staticmethod
    def weights(
        prob: OptimizationProblem, sol: Solution, target: dict[str, float]
    ) -> st.PortfolioWeights:
        """Current, post-trade and target weights of total value; cash under ``CASH``."""
        held = np.zeros(len(prob.tickers))
        for lot in prob.lots:
            held[lot.sec] += lot.quantity * prob.prices[lot.sec]

        def norm(vals: dict[str, float]) -> dict[str, float]:
            tot = sum(v for v in vals.values() if v > 0)
            return {k: round(v / tot, 6) for k, v in vals.items() if v > 0 and v / tot > 1e-6}

        cur = {tk: float(v) for tk, v in zip(prob.tickers, held, strict=True)}
        cur["CASH"] = cur.get("CASH", 0.0) + float(prob.cash)
        V = sol.total_value or 1.0
        post = {tk: float(w) * V for tk, w in zip(prob.tickers, sol.post_weights, strict=True)}
        post["CASH"] = post.get("CASH", 0.0) + float(sol.post_cash)
        return st.PortfolioWeights(current=norm(cur), transition=norm(post), target=norm(target))

    @staticmethod
    def explain(sol: Solution, mode: str, budget: float | None) -> list[str]:
        te = sol.te_after
        if sol.status not in ("optimal", "optimal_inaccurate"):
            return [f"The optimizer did not find a solution (status: {sol.status})."]
        out: list[str] = []
        if te < 0.0025:
            out.append(f"The portfolio closely matches the target (residual TE {te:.2%}).")
            return out
        by_reason: dict[str, list[tuple[str, float]]] = {}
        for c in sol.contributions:
            by_reason.setdefault(c.reason, []).append((c.ticker, c.contribution))
        for reason, label in (
            ("locked", "Locked lots in"),
            ("wash_sale", "Wash-sale-held lots in"),
        ):
            items = by_reason.get(reason, [])
            if items:
                names = ", ".join(tk for tk, _ in items[:3])
                share = sum(v for _, v in items)
                out.append(f"{label} {names} contribute {share:.2%} of the {te:.2%} residual TE.")
        if by_reason.get("budget"):
            names = ", ".join(tk for tk, _ in by_reason["budget"][:4])
            share = sum(v for _, v in by_reason["budget"])
            what = "tax" if mode == "tax" else "net-gain"
            amount = f" of ${budget:,.0f}" if budget is not None else ""
            out.append(
                f"The {what} budget{amount} is fully used: legacy positions with embedded gains "
                f"({names}) stay overweight and contribute {share:.2%} of residual TE."
            )
        if not out:
            out.append(
                f"Residual TE of {te:.2%} comes from small differences between held positions "
                "and the target after costs and the cash buffer."
            )
        return out

    # ------------------------------------------------------------------ optimize
    def optimize(self, t: m.Transition, req: st.OptimizeRequest) -> st.OptimizationResult:
        target = self._target(t, req.target_model_id)
        prob, ctx = self.problem(t, target)
        settings = self.settings(req.constraints)
        mode = BudgetMode(req.budget_mode)
        budget = None if mode is BudgetMode.NONE else req.budget_value
        if mode is not BudgetMode.NONE and budget is None:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "budget_value is required")
        glide = None
        if req.glide_path_budgets:
            if mode is BudgetMode.NONE:
                raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "glide path needs a budget mode")
            years, sols = glide_path(prob, settings, mode, req.glide_path_budgets)
            sol = sols[0]
            budget = req.glide_path_budgets[0]
            glide = [
                st.GlideYearOut(
                    year=y.year,
                    budget=y.budget,
                    est_tax=y.est_tax,
                    net_gain=y.net_gain,
                    te_after=round(y.te_after, 5),
                    n_trades=y.n_trades,
                )
                for y in years
            ]
        else:
            sol = TransitionOptimizer(prob, settings).solve(mode, budget)

        r = sol.realized
        used = None
        if budget and ctx.taxable and mode is not BudgetMode.NONE:
            spent = r.net if mode is BudgetMode.NET_GAIN else sol.est_tax
            used = round(100 * max(spent, 0.0) / budget, 2)
        proceeds = sum(s.proceeds for s in sol.sells)
        purchases = sum(b.value for b in sol.buys)
        lot_refs = {lot.id: lot.lot_ref for lot in self.account(t).lots}
        result = st.OptimizationResult(
            data_source=self.p.data_source,
            transition_id=t.id,
            account_id=t.account_id,
            target_model_id=target,
            as_of=self.ps.as_of,
            taxable=ctx.taxable,
            budget_mode=req.budget_mode,
            budget_value=budget,
            constraints=req.constraints,
            trades=st.Trades(
                sells=[
                    st.LotSellOut(
                        lot_id=s.lot_id,
                        lot_ref=lot_refs.get(s.lot_id),
                        ticker=s.ticker,
                        shares=round(s.shares, 3),
                        price=round(s.price, 4),
                        proceeds=round(s.proceeds, 2),
                        cost_basis=round(s.cost_basis, 2),
                        realized_gain=round(s.realized_gain, 2),
                        term=s.term,
                        acquired_date=s.acquired,
                    )
                    for s in sorted(sol.sells, key=lambda s: (s.ticker, s.acquired))
                ],
                buys=[
                    st.BuyOut(
                        ticker=b.ticker,
                        shares=b.shares,
                        price=round(b.price, 4),
                        value=round(b.value, 2),
                    )
                    for b in sol.buys
                ],
            ),
            summary=st.TradeSummary(
                n_lot_sells=len(sol.sells),
                n_buys=len(sol.buys),
                proceeds=round(proceeds, 2),
                purchases=round(purchases, 2),
                turnover=round(sol.turnover, 4),
                cash_before=round(prob.cash, 2),
                cash_after=round(sol.post_cash, 2),
                total_value=round(sol.total_value, 2),
            ),
            realized=st.RealizedSummary(
                st_gain=round(r.st_gain, 2),
                st_loss=round(r.st_loss, 2),
                lt_gain=round(r.lt_gain, 2),
                lt_loss=round(r.lt_loss, 2),
                net_gain=round(r.net, 2),
                est_tax=sol.est_tax,
                budget_used_pct=used,
            ),
            pre=self._snapshot(ctx, sol.te_before),
            post=self._snapshot(self._post_ctx(ctx, prob, sol), sol.te_after),
            glide_path=glide,
            diagnostics=st.Diagnostics(
                solver=sol.solver,
                status=sol.status,
                solve_ms=sol.solve_ms,
                binding_constraints=sol.binding,
                relaxations=sol.relaxations,
                notes=sol.notes,
                explanation=self.explain(sol, req.budget_mode, budget),
                te_contributions=[
                    st.TEContributionOut(
                        ticker=c.ticker,
                        active_weight=round(c.active_weight, 5),
                        te_contribution=round(c.contribution, 5),
                        reason=c.reason,
                    )
                    for c in sol.contributions
                ],
                wash_blocked_lot_ids=sol.wash_blocked_lots,
                lot_relief_check=sol.lot_relief_check,
            ),
            portfolios=self.weights(prob, sol, ctx.target_weights),
        )
        self._save(t, target_model_id=target, optimization=result.model_dump(mode="json"))
        return result

    def frontier(self, t: m.Transition, req: st.FrontierRequest) -> st.FrontierResult:
        target = self._target(t, req.target_model_id)
        prob, _ = self.problem(t, target)
        opt = TransitionOptimizer(prob, self.settings(req.constraints))
        mode = BudgetMode(req.budget_mode)
        pts, top = opt.frontier(mode, req.n_points)
        te_before = opt.solve(BudgetMode.NONE, None, finalize=False).te_before
        chosen = None
        last = (t.data or {}).get("optimization")
        if (
            last
            and last.get("budget_mode") == req.budget_mode
            and last.get("budget_value") is not None
        ):
            b = float(last["budget_value"])
            chosen = int(np.argmin([abs(p.budget - b) for p in pts]))
        result = st.FrontierResult(
            data_source=self.p.data_source,
            transition_id=t.id,
            target_model_id=target,
            budget_mode=req.budget_mode,
            max_budget=round(top, 2),
            te_before=round(te_before, 5),
            points=[
                st.FrontierPointOut(
                    budget=p.budget,
                    est_tax=p.est_tax,
                    net_gain=p.net_gain,
                    te=round(p.te, 5),
                    turnover=round(p.turnover, 4),
                )
                for p in pts
            ],
            chosen_index=chosen,
        )
        self._save(t, target_model_id=target, frontier=result.model_dump(mode="json"))
        return result

    # ------------------------------------------------------------------ analytics
    def analytics(self, t: m.Transition) -> TransitionAnalytics:
        """Model Builder analytics for current / post-trade / target, measured against the
        target. Results saved before weights were stored are re-solved (not re-saved)."""
        r = self.last_result(t)
        w = r.portfolios
        if w is None:
            prob, ctx = self.problem(t, r.target_model_id)
            mode = BudgetMode(r.budget_mode)
            sol = TransitionOptimizer(prob, self.settings(r.constraints)).solve(
                mode, None if mode is BudgetMode.NONE else r.budget_value
            )
            w = self.weights(prob, sol, ctx.target_weights)
        mp = self.db.get(m.ModelPortfolio, r.target_model_id)
        try:
            return transition_analytics(
                r.target_model_id,
                mp.name if mp else r.target_model_id,
                w.model_dump(),
                {"current": r.pre.te, "transition": r.post.te, "target": 0.0},
                BuilderData.get(self.p),
            )
        except ValueError as exc:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    # ------------------------------------------------------------------ exports
    def last_result(self, t: m.Transition) -> st.OptimizationResult:
        raw = (t.data or {}).get("optimization")
        if not raw:
            raise _err(status.HTTP_404_NOT_FOUND, "No optimization yet for this transition")
        return st.OptimizationResult.model_validate(raw)

    def trades_csv(self, t: m.Transition) -> str:
        r = self.last_result(t)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"# Transition Studio — {DISCLAIMER} SYNTHETIC DATA."])
        w.writerow(
            [
                f"# transition={r.transition_id} account={r.account_id} "
                f"target={r.target_model_id} as_of={r.as_of}"
            ]
        )
        w.writerow(
            [
                "side",
                "ticker",
                "lot_id",
                "shares",
                "price",
                "value",
                "cost_basis",
                "realized_gain",
                "term",
                "acquired_date",
            ]
        )
        for s in r.trades.sells:
            w.writerow(
                [
                    "SELL",
                    s.ticker,
                    s.lot_ref or s.lot_id,
                    s.shares,
                    s.price,
                    s.proceeds,
                    s.cost_basis,
                    s.realized_gain,
                    s.term,
                    s.acquired_date.isoformat(),
                ]
            )
        for b in r.trades.buys:
            w.writerow(["BUY", b.ticker, "", b.shares, b.price, b.value, "", "", "", ""])
        return buf.getvalue()

    def summary_pdf(self, t: m.Transition) -> bytes:
        from app.services.summary_pdf import render_summary_pdf

        a = self.account(t)
        return render_summary_pdf(self.last_result(t), a.client.name, a.nickname or a.id)
