"""Service layer: DB rows → provider inputs → API payloads.

Holds the business rules for statuses and roll-ups. It never inspects which analytics provider is
active; it only forwards ``provider.data_source``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.analytics import aggregate as agg
from app.analytics.provider import AnalyticsProvider
from app.analytics.types import (
    AccountContext,
    DatedValue,
    EventInput,
    Granularity,
    LotInput,
    TaxPeriod,
    period_key,
    period_range,
)
from app.db import models as m
from app.domain.entities import AccountType, holding_period
from app.schemas import accounts as sa
from app.schemas import analytics as an
from app.schemas import clients as sc
from app.schemas.common import ClientStatus, DatedValueOut
from app.services.book_cache import account_cached, book_cached

REBALANCE_TYPES = {"rebalance", "transition", "model_change"}
EVENT_TYPES = ["transition", "rebalance", "tax_loss_harvest", "cash_flow", "model_change"]
NEEDS_REVIEW_TE_MULTIPLE = 1.5
NEEDS_REVIEW_STALE_DAYS = 120


@dataclass(slots=True)
class AccountView:
    """Per-account numbers computed once per request and reused by every roll-up."""

    acct: m.Account
    ctx: AccountContext
    prices: dict[str, float]
    market_value: float
    ex_ante_te: float | None
    taxes_saved_ytd: float
    taxes_saved_since_inception: float
    last_rebalance: date | None
    has_history: bool

    @property
    def outside_tolerance(self) -> bool:
        return self.ex_ante_te is not None and self.ex_ante_te > self.acct.drift_tolerance_te


class PortfolioService:
    def __init__(self, db: Session, provider: AnalyticsProvider, advisor_id: str) -> None:
        self.db = db
        self.p = provider
        self.advisor_id = advisor_id
        self.as_of = provider.as_of
        self._views: dict[str, AccountView] = {}
        self._model_weights: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ loading
    def clients(self, light: bool = False) -> list[m.Client]:
        """The advisor's clients with accounts. ``light`` skips loading every lot and event
        (book-level views read them from the per-account cache instead)."""
        opts = (
            [selectinload(m.Client.accounts)]
            if light
            else [
                selectinload(m.Client.accounts).selectinload(m.Account.lots),
                selectinload(m.Client.accounts).selectinload(m.Account.events),
            ]
        )
        stmt = (
            select(m.Client)
            .where(m.Client.advisor_id == self.advisor_id)
            .options(*opts)
            .order_by(m.Client.name)
        )
        return list(self.db.scalars(stmt))

    def client(self, client_id: str) -> m.Client | None:
        c = self.db.get(m.Client, client_id)
        return c if c is not None and c.advisor_id == self.advisor_id else None

    def account(self, account_id: str) -> m.Account | None:
        a = self.db.get(m.Account, account_id)
        return a if a is not None and a.client.advisor_id == self.advisor_id else None

    def model_weights(self, model_id: str | None) -> dict[str, float]:
        if model_id is None:
            return {}
        if model_id not in self._model_weights:
            rows = self.db.scalars(
                select(m.ModelHolding).where(m.ModelHolding.model_id == model_id)
            )
            self._model_weights[model_id] = {h.ticker: h.weight for h in rows}
        return self._model_weights[model_id]

    # ------------------------------------------------------------------ per account
    def _memo(self, a: m.Account, name: str, args: tuple[Any, ...], fn: Any) -> Any:
        return account_cached(self.db.get_bind(), a.id, name, args, fn)

    def context(self, a: m.Account) -> AccountContext:
        return self._memo(a, "ctx", (), lambda: self._build_context(a))  # type: ignore[no-any-return]

    def te_history(self, v: AccountView, window: int) -> Any:
        return self._memo(
            v.acct, "te", (window,), lambda: self.p.get_tracking_error_history(v.ctx, window)
        )

    def aum_history(self, v: AccountView) -> Any:
        return self._memo(v.acct, "aum", (), lambda: self.p.get_aum_history(v.ctx))

    def tax_history(self, v: AccountView, granularity: Granularity) -> Any:
        return self._memo(
            v.acct, "tax", (granularity,), lambda: self.p.get_tax_history(v.ctx, granularity)
        )

    def _build_context(self, a: m.Account) -> AccountContext:
        c = a.client
        return AccountContext(
            account_id=a.id,
            onboarding_date=a.onboarding_date,
            as_of=self.as_of,
            cash=a.cash,
            taxable=AccountType(a.account_type).is_taxable,
            st_rate=c.federal_st_rate + c.state_rate,
            lt_rate=c.federal_lt_rate + c.state_rate,
            drift_tolerance_te=a.drift_tolerance_te,
            lots=tuple(
                LotInput(
                    lot.id,
                    lot.ticker,
                    lot.quantity,
                    lot.cost_basis_total,
                    lot.acquired_date,
                    lot.locked,
                )
                for lot in a.lots
            ),
            events=tuple(
                EventInput(
                    e.id,
                    e.event_date,
                    e.event_type,
                    e.te_before,
                    e.te_after,
                    e.realized_st_gain,
                    e.realized_lt_gain,
                    e.losses_harvested,
                    e.est_taxes_saved,
                    e.turnover,
                    e.cash_flow_amount,
                    e.realized_st_loss,
                    e.realized_lt_loss,
                )
                for e in sorted(a.events, key=lambda e: e.event_date)
            ),
            target_model_id=a.target_model_id,
            target_weights=self.model_weights(a.target_model_id),
        )

    def view(self, a: m.Account) -> AccountView:
        if a.id in self._views:
            return self._views[a.id]
        ctx = self.context(a)

        def numbers() -> dict[str, Any]:
            tickers = sorted({lot.ticker for lot in ctx.lots})
            prices = self.p.get_prices(tickers) if tickers else {}
            mv = ctx.cash + sum(lot.quantity * prices[lot.ticker] for lot in ctx.lots)
            rebal = [e.event_date for e in ctx.events if e.event_type in REBALANCE_TYPES]
            year = self.as_of.year
            return {
                "prices": prices,
                "market_value": round(mv, 2),
                "ex_ante_te": self.p.get_ex_ante_te(ctx),
                "taxes_saved_ytd": round(
                    sum(e.est_taxes_saved for e in ctx.events if e.event_date.year == year), 2
                ),
                "taxes_saved_since_inception": round(sum(e.est_taxes_saved for e in ctx.events), 2),
                "last_rebalance": max(rebal) if rebal else None,
                "has_history": bool(ctx.events),
            }

        v = AccountView(acct=a, ctx=ctx, **self._memo(a, "view", (), numbers))
        self._views[a.id] = v
        return v

    def account_summary(self, a: m.Account) -> sc.AccountSummary:
        v = self.view(a)
        return sc.AccountSummary(
            id=a.id,
            client_id=a.client_id,
            account_type=a.account_type,
            taxable=v.ctx.taxable,
            custodian=a.custodian,
            nickname=a.nickname,
            target_model_id=a.target_model_id,
            onboarding_date=a.onboarding_date,
            market_value=v.market_value,
            cash=round(a.cash, 2),
            n_positions=len({lot.ticker for lot in a.lots}),
            n_lots=len(a.lots),
            ex_ante_te=v.ex_ante_te,
            drift_tolerance_te=a.drift_tolerance_te,
            outside_tolerance=v.outside_tolerance,
            taxes_saved_ytd=v.taxes_saved_ytd,
            taxes_saved_since_inception=v.taxes_saved_since_inception,
            last_rebalance_date=v.last_rebalance,
            has_history=v.has_history,
        )

    # ------------------------------------------------------------------ status rules
    def account_status(self, v: AccountView) -> ClientStatus:
        a = v.acct
        if a.target_model_id is None or not v.has_history:
            return ClientStatus.onboarding
        stale = v.last_rebalance is None or (self.as_of - v.last_rebalance) > timedelta(
            days=NEEDS_REVIEW_STALE_DAYS
        )
        if stale or (
            v.ex_ante_te is not None
            and v.ex_ante_te > NEEDS_REVIEW_TE_MULTIPLE * a.drift_tolerance_te
        ):
            return ClientStatus.needs_review
        if v.outside_tolerance:
            return ClientStatus.drifting
        return ClientStatus.on_target

    def client_status(self, c: m.Client) -> ClientStatus:
        """Worst account status wins: onboarding > needs_review > drifting > on_target."""
        if not c.accounts:
            return ClientStatus.onboarding
        order = [
            ClientStatus.onboarding,
            ClientStatus.needs_review,
            ClientStatus.drifting,
            ClientStatus.on_target,
        ]
        statuses = {self.account_status(self.view(a)) for a in c.accounts}
        return next(s for s in order if s in statuses)

    # ------------------------------------------------------------------ client level
    def _te_weighted(self, views: list[AccountView]) -> float | None:
        pts = [(v.ex_ante_te, v.market_value) for v in views if v.ex_ante_te is not None]
        res = agg.value_weighted([p[0] for p in pts], [p[1] for p in pts])
        return None if res is None else round(res, 5)

    @book_cached
    def client_rows(self) -> list[tuple[sc.ClientSummaryRow, str]]:
        """Every client's summary row with its e-mail (for search), in name order."""
        return [(self.client_row(c), (c.email or "").lower()) for c in self.clients(light=True)]

    def client_row(self, c: m.Client) -> sc.ClientSummaryRow:
        views = [self.view(a) for a in c.accounts]
        last = [v.last_rebalance for v in views if v.last_rebalance]
        return sc.ClientSummaryRow(
            id=c.id,
            name=c.name,
            client_type=c.client_type,
            n_accounts=len(views),
            market_value=round(sum(v.market_value for v in views), 2),
            target_models=sorted({a.target_model_id for a in c.accounts if a.target_model_id}),
            ex_ante_te=self._te_weighted(views),
            taxes_saved_ytd=round(sum(v.taxes_saved_ytd for v in views), 2),
            last_rebalance_date=max(last) if last else None,
            status=self.client_status(c),
        )

    def tax_profile_out(self, c: m.Client) -> sc.TaxProfileOut:
        return sc.TaxProfileOut(
            federal_st_rate=c.federal_st_rate,
            federal_lt_rate=c.federal_lt_rate,
            state=c.state,
            state_rate=c.state_rate,
            st_rate=round(c.federal_st_rate + c.state_rate, 5),
            lt_rate=round(c.federal_lt_rate + c.state_rate, 5),
        )

    def client_out(self, c: m.Client) -> sc.ClientOut:
        return sc.ClientOut(
            id=c.id,
            name=c.name,
            email=c.email,
            phone=c.phone,
            client_type=c.client_type,
            notes=c.notes,
            tax_profile=self.tax_profile_out(c),
            status=self.client_status(c),
        )

    def client_detail(self, c: m.Client) -> sc.ClientDetail:
        views = [self.view(a) for a in c.accounts]
        last = [v.last_rebalance for v in views if v.last_rebalance]
        unreal = sum(
            lot.quantity * v.prices[lot.ticker] - lot.cost_basis_total
            for v in views
            for lot in v.acct.lots
        )
        return sc.ClientDetail(
            data_source=self.p.data_source,
            id=c.id,
            name=c.name,
            email=c.email,
            phone=c.phone,
            client_type=c.client_type,
            notes=c.notes,
            status=self.client_status(c),
            tax_profile=self.tax_profile_out(c),
            accounts=[self.account_summary(a) for a in c.accounts],
            metrics=sc.ClientMetrics(
                market_value=round(sum(v.market_value for v in views), 2),
                cash=round(sum(v.acct.cash for v in views), 2),
                n_accounts=len(views),
                n_positions=len({lot.ticker for v in views for lot in v.acct.lots}),
                ex_ante_te=self._te_weighted(views),
                taxes_saved_ytd=round(sum(v.taxes_saved_ytd for v in views), 2),
                taxes_saved_since_inception=round(
                    sum(v.taxes_saved_since_inception for v in views), 2
                ),
                unrealized_gain=round(unreal, 2),
                last_rebalance_date=max(last) if last else None,
                first_onboarding_date=min((a.onboarding_date for a in c.accounts), default=None),
            ),
        )

    def _scope(self, c: m.Client, account_id: str | None) -> list[m.Account]:
        if account_id is None:
            return list(c.accounts)
        return [a for a in c.accounts if a.id == account_id]

    def tracking_error(
        self, accounts: list[m.Account], window: int, account_id: str | None
    ) -> an.TrackingError:
        views = [self.view(a) for a in accounts]
        te = {v.acct.id: self.te_history(v, window) for v in views}
        if len(views) == 1:
            series = [an.TEPoint(date=p.d, te=p.value) for p in te[views[0].acct.id].series]
        else:
            aum = {v.acct.id: self.aum_history(v) for v in views}
            pts = agg.weighted_te_series({k: h.series for k, h in te.items()}, aum)
            series = [an.TEPoint(date=p.d, te=p.avg_te) for p in pts]
        markers = sorted(
            (
                an.EventMarker(event_id=e.id, account_id=a.id, date=e.event_date, type=e.event_type)
                for a in accounts
                for e in a.events
            ),
            key=lambda x: x.date,
        )
        return an.TrackingError(
            data_source=self.p.data_source,
            window=window,
            account_id=account_id,
            series=series,
            ex_ante_te=self._te_weighted(views),
            events=markers,
        )

    def _tax_histories(
        self, accounts: list[m.Account], granularity: Granularity
    ) -> list[TaxPeriod]:
        hists = [self.tax_history(self.view(a), granularity) for a in accounts]
        return agg.sum_tax_periods(hists)

    def tax_savings(
        self, accounts: list[m.Account], granularity: Granularity, account_id: str | None
    ) -> an.TaxSavings:
        periods = self._tax_histories(accounts, granularity)
        out, cum = [], 0.0
        for p in periods:
            cum += p.est_taxes_saved
            out.append(
                an.TaxSavingsPeriod(
                    period=p.period,
                    taxes_saved=p.est_taxes_saved,
                    losses_harvested=p.losses_harvested,
                    cum_taxes_saved=round(cum, 2),
                    realized_st_gain=p.realized_st_gain,
                    realized_lt_gain=p.realized_lt_gain,
                    realized_st_loss=p.realized_st_loss,
                    realized_lt_loss=p.realized_lt_loss,
                )
            )
        views = [self.view(a) for a in accounts]
        return an.TaxSavings(
            data_source=self.p.data_source,
            granularity=granularity,
            account_id=account_id,
            periods=out,
            taxes_saved_ytd=round(sum(v.taxes_saved_ytd for v in views), 2),
            taxes_saved_since_inception=round(sum(v.taxes_saved_since_inception for v in views), 2),
        )

    def client_summary(
        self, accounts: list[m.Account], account_id: str | None
    ) -> an.ClientAnalyticsSummary:
        aum_by = {a.id: self.aum_history(self.view(a)) for a in accounts}
        all_dates = sorted({p.d for s in aum_by.values() for p in s})
        totals = agg.sum_aum(aum_by, all_dates)
        monthly = agg.month_ends([DatedValue(d, v) for d, v in zip(all_dates, totals, strict=True)])

        years: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for a in accounts:
            for e in a.events:
                y = years[e.event_date.year]
                y["st"] += e.realized_st_gain
                y["lt"] += e.realized_lt_gain
                y["losses"] += e.losses_harvested
                y["saved"] += e.est_taxes_saved
                y["turnover"] += e.turnover
                if e.event_type == "rebalance":
                    y["n_rebal"] += 1
        first = min((a.onboarding_date for a in accounts), default=None)
        by_year = []
        if first is not None:
            for yr in range(first.year, self.as_of.year + 1):
                y = years.get(yr, {})
                by_year.append(
                    an.YearSummary(
                        year=yr,
                        realized_st_gain=round(y.get("st", 0.0), 2),
                        realized_lt_gain=round(y.get("lt", 0.0), 2),
                        losses_harvested=round(y.get("losses", 0.0), 2),
                        taxes_saved=round(y.get("saved", 0.0), 2),
                        n_rebalances=int(y.get("n_rebal", 0)),
                        turnover=round(y.get("turnover", 0.0) / max(len(accounts), 1), 4),
                    )
                )
        has_events = any(a.events for a in accounts)
        span_years = ((self.as_of - first).days / 365.25) if first else 0.0
        avg_turn = None
        if has_events and span_years > 0:
            total_turn = sum(e.turnover for a in accounts for e in a.events) / max(len(accounts), 1)
            avg_turn = round(total_turn / max(span_years, 1.0), 4)
        return an.ClientAnalyticsSummary(
            data_source=self.p.data_source,
            account_id=account_id,
            aum_history=[DatedValueOut(date=p.d, value=p.value) for p in monthly],
            by_year=by_year,
            avg_annual_turnover=avg_turn,
        )

    # ------------------------------------------------------------------ account level
    def account_detail(self, a: m.Account) -> sa.AccountDetail:
        v = self.view(a)
        secs = {
            s.ticker: s
            for s in self.db.scalars(
                select(m.Security).where(m.Security.ticker.in_({lot.ticker for lot in a.lots}))
            )
        }
        tw = v.ctx.target_weights
        total = v.market_value or 1.0
        lots_out: list[sa.LotOut] = []
        split = {"st_gains": 0.0, "st_losses": 0.0, "lt_gains": 0.0, "lt_losses": 0.0}
        by_ticker: dict[str, list[m.Lot]] = defaultdict(list)
        for lot in a.lots:
            px = v.prices[lot.ticker]
            mv = lot.quantity * px
            gain = mv - lot.cost_basis_total
            hp = holding_period(lot.acquired_date, self.as_of).value
            split[f"{hp.lower()}_{'gains' if gain >= 0 else 'losses'}"] += gain
            by_ticker[lot.ticker].append(lot)
            lots_out.append(
                sa.LotOut(
                    lot_id=lot.id,
                    lot_ref=lot.lot_ref,
                    account_id=a.id,
                    ticker=lot.ticker,
                    quantity=lot.quantity,
                    cost_basis_total=round(lot.cost_basis_total, 2),
                    acquired_date=lot.acquired_date,
                    holding_period=hp,
                    current_price=round(px, 4),
                    market_value=round(mv, 2),
                    unrealized_gain=round(gain, 2),
                    locked=lot.locked,
                    source=lot.source,
                    basis_unknown=lot.basis_unknown,
                )
            )
        holdings = []
        for t, lots in by_ticker.items():
            q = sum(lot.quantity for lot in lots)
            px = v.prices[t]
            cost = sum(lot.cost_basis_total for lot in lots)
            holdings.append(
                sa.HoldingOut(
                    ticker=t,
                    name=secs[t].name,
                    sector=secs[t].sector,
                    quantity=round(q, 3),
                    price=round(px, 4),
                    market_value=round(q * px, 2),
                    weight=round(q * px / total, 6),
                    target_weight=round(tw.get(t, 0.0), 6),
                    cost_basis_total=round(cost, 2),
                    unrealized_gain=round(q * px - cost, 2),
                    n_lots=len(lots),
                    locked=any(lot.locked for lot in lots),
                )
            )
        holdings.sort(key=lambda h: -h.market_value)
        lots_out.sort(key=lambda x: (x.ticker, x.acquired_date))
        return sa.AccountDetail(
            data_source=self.p.data_source,
            account=self.account_summary(a),
            client_name=a.client.name,
            unrealized=sa.UnrealizedSplit(
                **{k: round(x, 2) for k, x in split.items()}, net=round(sum(split.values()), 2)
            ),
            holdings=holdings,
            lots=lots_out,
        )

    def account_tax_history(self, a: m.Account, granularity: Granularity) -> an.TaxHistory:
        v = self.view(a)
        periods = self.tax_history(v, granularity)

        def conv(p: TaxPeriod) -> an.TaxHistoryPeriod:
            return an.TaxHistoryPeriod(
                period=p.period,
                realized_st_gain=p.realized_st_gain,
                realized_lt_gain=p.realized_lt_gain,
                losses_harvested=p.losses_harvested,
                est_tax_paid=p.est_tax_paid,
                taxes_saved=p.est_taxes_saved,
            )

        tot = agg.sum_tax_periods([[TaxPeriod("total", *_tp_values(p)) for p in periods]])
        totals = conv(tot[0]) if tot else conv(TaxPeriod("total", 0, 0, 0, 0, 0))
        return an.TaxHistory(
            data_source=self.p.data_source,
            account_id=a.id,
            granularity=granularity,
            taxable=v.ctx.taxable,
            periods=[conv(p) for p in periods],
            totals=totals,
        )

    def account_exposures(self, a: m.Account) -> an.ExposuresOut:
        v = self.view(a)
        x = self.p.get_exposures(v.ctx)
        return an.ExposuresOut(
            data_source=self.p.data_source,
            account_id=a.id,
            target_model_id=a.target_model_id,
            sectors=[
                an.SectorWeight(
                    sector=s.sector,
                    portfolio_weight=s.portfolio_weight,
                    target_weight=s.target_weight,
                    active_weight=round(s.active_weight, 6),
                )
                for s in x.sectors
            ],
            top_active_weights=[
                an.ActiveWeight(
                    ticker=s.ticker,
                    name=s.name,
                    sector=s.sector,
                    portfolio_weight=s.portfolio_weight,
                    target_weight=s.target_weight,
                    active_weight=round(s.active_weight, 6),
                )
                for s in x.top_active
            ],
            factor_exposures=[
                an.FactorWeight(
                    factor=f.factor,
                    portfolio=f.portfolio,
                    target=f.target,
                    active=round(f.active, 4),
                )
                for f in x.factors
            ],
            top10_weight=x.top10_weight,
            hhi=x.hhi,
            n_positions=x.n_positions,
            dividend_yield=x.dividend_yield,
            target_dividend_yield=x.target_dividend_yield,
            beta=x.beta,
            target_beta=x.target_beta,
        )

    # ------------------------------------------------------------------ book level
    @book_cached
    def book_summary(self) -> an.BookSummary:
        clients = self.clients(light=True)
        views = [self.view(a) for c in clients for a in c.accounts]
        statuses: dict[str, int] = {s.value: 0 for s in ClientStatus}
        for c in clients:
            statuses[self.client_status(c).value] += 1
        return an.BookSummary(
            data_source=self.p.data_source,
            as_of=self.as_of,
            n_clients=len(clients),
            n_accounts=len(views),
            total_aum=round(sum(v.market_value for v in views), 2),
            taxes_saved_ytd=round(sum(v.taxes_saved_ytd for v in views), 2),
            taxes_saved_since_inception=round(sum(v.taxes_saved_since_inception for v in views), 2),
            avg_ex_ante_te=self._te_weighted(views),
            n_accounts_outside_tolerance=sum(v.outside_tolerance for v in views),
            clients_by_status=statuses,
        )

    def _all_accounts(self) -> list[m.Account]:
        return [a for c in self.clients(light=True) for a in c.accounts]

    @book_cached
    def book_tracking_error(self, window: int) -> an.BookTrackingError:
        views = [self.view(a) for a in self._all_accounts()]
        te = {v.acct.id: self.te_history(v, window).series for v in views}
        aum = {v.acct.id: self.aum_history(v) for v in views}
        pts = agg.weighted_te_series(te, aum)
        return an.BookTrackingError(
            data_source=self.p.data_source,
            window=window,
            series=[
                an.BookTEPoint(
                    date=p.d, avg_te=p.avg_te, p10=p.p10, p90=p.p90, n_accounts=p.n_accounts
                )
                for p in pts
            ],
        )

    @book_cached
    def book_tax_impact(self, granularity: Granularity) -> an.TaxImpact:
        accounts = self._all_accounts()
        periods = self._tax_histories(accounts, granularity)
        if accounts:
            first = min(a.onboarding_date for a in accounts)
            keys = period_range(first, self.as_of, granularity)
            have = {p.period: p for p in periods}
            periods = [have.get(k, TaxPeriod(k, 0, 0, 0, 0, 0)) for k in keys]
        out = []
        c = [0.0] * 6
        for p in periods:
            c[0] += p.est_taxes_saved
            c[1] += p.losses_harvested
            c[2] += p.realized_st_gain
            c[3] += p.realized_lt_gain
            c[4] += p.realized_st_loss
            c[5] += p.realized_lt_loss
            out.append(
                an.TaxImpactPeriod(
                    period=p.period,
                    taxes_saved=p.est_taxes_saved,
                    losses_harvested=p.losses_harvested,
                    realized_st_gain=p.realized_st_gain,
                    realized_lt_gain=p.realized_lt_gain,
                    realized_st_loss=p.realized_st_loss,
                    realized_lt_loss=p.realized_lt_loss,
                    cum_taxes_saved=round(c[0], 2),
                    cum_losses_harvested=round(c[1], 2),
                    cum_realized_st_gain=round(c[2], 2),
                    cum_realized_lt_gain=round(c[3], 2),
                    cum_realized_st_loss=round(c[4], 2),
                    cum_realized_lt_loss=round(c[5], 2),
                )
            )
        return an.TaxImpact(data_source=self.p.data_source, granularity=granularity, periods=out)

    @book_cached
    def book_activity(self, granularity: Granularity) -> an.Activity:
        accounts = self._all_accounts()
        if not accounts:
            return an.Activity(data_source=self.p.data_source, granularity=granularity, periods=[])
        first = min(a.onboarding_date for a in accounts)
        keys = period_range(first, self.as_of, granularity)
        counts: dict[str, dict[str, int]] = {k: dict.fromkeys(EVENT_TYPES, 0) for k in keys}
        for a in accounts:
            for e in self.view(a).ctx.events:
                k = period_key(e.event_date, granularity)
                if k in counts:
                    counts[k][e.event_type] += 1
        aum_by = {a.id: self.aum_history(self.view(a)) for a in accounts}
        ends = [min(_period_end(k), self.as_of) for k in keys]
        aum = agg.sum_aum(aum_by, ends)
        return an.Activity(
            data_source=self.p.data_source,
            granularity=granularity,
            periods=[
                an.ActivityPeriod(period=k, counts=counts[k], total=sum(counts[k].values()), aum=v)
                for k, v in zip(keys, aum, strict=True)
            ],
        )


def _tp_values(p: TaxPeriod) -> tuple[float, float, float, float, float]:
    return (
        p.realized_st_gain,
        p.realized_lt_gain,
        p.losses_harvested,
        p.est_tax_paid,
        p.est_taxes_saved,
    )


def _period_end(key: str) -> date:
    if len(key) == 4:
        return date(int(key), 12, 31)
    y, mth = int(key[:4]), int(key[5:])
    nxt = date(y + (mth == 12), 1 if mth == 12 else mth + 1, 1)
    return nxt - timedelta(days=1)
