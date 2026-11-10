"""Model catalog and model-comparison service."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from sqlalchemy import select

from app.analytics.types import AccountContext, LotInput
from app.db import models as m
from app.domain.entities import Lot
from app.optimizer.transition_cost import estimate_full_transition
from app.schemas import models as sm
from app.services.portfolio import PortfolioService


class ModelService:
    def __init__(self, portfolio: PortfolioService) -> None:
        self.ps = portfolio
        self.db = portfolio.db
        self.p = portfolio.p

    # ------------------------------------------------------------------ catalog
    def all_models(self) -> list[m.ModelPortfolio]:
        return list(self.db.scalars(select(m.ModelPortfolio).order_by(m.ModelPortfolio.id)))

    def get(self, model_id: str) -> m.ModelPortfolio | None:
        return self.db.get(m.ModelPortfolio, model_id)

    def summary(self, mp: m.ModelPortfolio) -> sm.ModelSummary:
        weights = self.ps.model_weights(mp.id)
        st = self.p.get_model_stats(mp.id, weights)
        return sm.ModelSummary(
            id=mp.id,
            name=mp.name,
            provider=mp.provider,
            objective=mp.objective,
            construction=mp.construction,
            benchmark=mp.benchmark,
            description=mp.description,
            rationale=mp.rationale,
            target_yield=mp.target_yield,
            expected_te=mp.expected_te,
            fee_bps=mp.fee_bps,
            regime_overlay=mp.regime_overlay,
            stats=sm.ModelStatsOut(
                annualized_return=st.annualized_return,
                volatility=st.volatility,
                sharpe=st.sharpe,
                max_drawdown=st.max_drawdown,
                dividend_yield=st.dividend_yield,
                beta=st.beta,
                n_holdings=st.n_holdings,
                n_underlying=st.n_underlying,
                sector_mix=st.sector_mix,
                factor_exposures=st.factor_exposures,
                history_start=st.history_start,
                history_end=st.history_end,
            ),
        )

    def list_models(self, objective: str | None, construction: str | None) -> sm.ModelList:
        items = [
            self.summary(mp)
            for mp in self.all_models()
            if (objective is None or mp.objective == objective)
            and (construction is None or mp.construction == construction)
        ]
        return sm.ModelList(data_source=self.p.data_source, total=len(items), items=items)

    def regime_labels(self) -> dict[date, str]:
        rows = self.db.scalars(
            select(m.RegimeLabel).where(m.RegimeLabel.advisor_id == self.ps.advisor_id)
        )
        return {r.label_date: r.regime for r in rows}

    def detail(self, mp: m.ModelPortfolio) -> sm.ModelDetail:
        secs = {
            s.ticker: s
            for s in self.db.scalars(
                select(m.Security).where(m.Security.ticker.in_([h.ticker for h in mp.holdings]))
            )
        }
        labels = self.regime_labels()
        regime = None
        if labels:
            regime = [
                sm.RegimePerformanceOut(
                    regime=r.regime,
                    n_days=r.n_days,
                    annualized_return=r.annualized_return,
                    volatility=r.volatility,
                )
                for r in self.p.get_regime_performance(mp.id, self.ps.model_weights(mp.id), labels)
            ]
        return sm.ModelDetail(
            **self.summary(mp).model_dump(),
            data_source=self.p.data_source,
            holdings=[
                sm.ModelHoldingOut(
                    ticker=h.ticker,
                    name=secs[h.ticker].name,
                    security_type=secs[h.ticker].security_type,
                    asset_class=secs[h.ticker].asset_class,
                    expense_ratio_bps=secs[h.ticker].expense_ratio_bps,
                    weight=h.weight,
                )
                for h in sorted(mp.holdings, key=lambda h: -h.weight)
            ],
            regime_performance=regime,
        )

    # ------------------------------------------------------------------ comparison
    def compare(self, model_ids: list[str], account: m.Account) -> sm.ComparisonPayload:
        view = self.ps.view(account)
        ctx = view.ctx
        x = self.p.get_exposures(ctx)
        prices_held = view.prices
        unreal = sum(
            lot.quantity * prices_held[lot.ticker] - lot.cost_basis_total for lot in account.lots
        )
        locked = sum(lot.quantity * prices_held[lot.ticker] for lot in account.lots if lot.locked)
        current = sm.CurrentPortfolio(
            account_id=account.id,
            market_value=view.market_value,
            cash=round(account.cash, 2),
            n_positions=x.n_positions,
            target_model_id=account.target_model_id,
            dividend_yield=x.dividend_yield,
            beta=x.beta,
            sector_mix={s.sector: s.portfolio_weight for s in x.sectors},
            factor_exposures={f.factor: f.portfolio for f in x.factors},
            unrealized_gain=round(unreal, 2),
            locked_value=round(locked, 2),
        )
        domain_lots = [
            Lot(
                lot_id=lot.id,
                account_id=account.id,
                ticker=lot.ticker,
                quantity=lot.quantity,
                cost_basis_total=lot.cost_basis_total,
                acquired_date=lot.acquired_date,
                locked=lot.locked,
            )
            for lot in account.lots
        ]
        comparisons = []
        for mid in model_ids:
            mp = self.get(mid)
            assert mp is not None  # validated by the router
            weights = self.ps.model_weights(mid)
            target_ctx = replace(ctx, target_model_id=mid, target_weights=weights)
            te_now = self.p.get_ex_ante_te(target_ctx) if account.lots else None
            prices = {**prices_held, **self.p.get_prices(list(weights))}
            est = estimate_full_transition(
                domain_lots,
                prices,
                account.cash,
                weights,
                self.ps.as_of,
                ctx.st_rate,
                ctx.lt_rate,
                ctx.taxable,
            )
            post_ctx = self._post_context(
                target_ctx, est.post_weights, est.post_cash, est.total_value, prices
            )
            post_te = self.p.get_ex_ante_te(post_ctx) if est.post_weights else None
            r = est.realized
            comparisons.append(
                sm.ModelComparison(
                    model=self.summary(mp),
                    te_from_current=te_now,
                    yield_change=round(mp.target_yield - x.dividend_yield, 5),
                    full_transition=sm.FullTransitionOut(
                        est_tax=est.est_tax,
                        realized_st_gain=round(r.st_gain, 2),
                        realized_st_loss=round(r.st_loss, 2),
                        realized_lt_gain=round(r.lt_gain, 2),
                        realized_lt_loss=round(r.lt_loss, 2),
                        net_realized_gain=round(r.net, 2),
                        n_lot_sales=len(est.sales),
                        n_buys=len(est.buys),
                        turnover=round(est.turnover, 4),
                        locked_value_retained=round(est.locked_value_retained, 2),
                        post_te=round(post_te or 0.0, 5),
                    ),
                )
            )
        return sm.ComparisonPayload(
            data_source=self.p.data_source,
            as_of=self.ps.as_of,
            taxable=ctx.taxable,
            current=current,
            comparisons=comparisons,
        )

    @staticmethod
    def _post_context(
        ctx: AccountContext,
        post_weights: dict[str, float],
        post_cash: float,
        total: float,
        prices: dict[str, float],
    ) -> AccountContext:
        """A synthetic context holding the post-trade portfolio (one lot per security)."""
        lots = tuple(
            LotInput(f"post:{t}", t, w * total / prices[t], w * total, ctx.as_of, False)
            for t, w in post_weights.items()
        )
        return replace(
            ctx, lots=lots, cash=post_cash, events=(), account_id=f"{ctx.account_id}:post"
        )
