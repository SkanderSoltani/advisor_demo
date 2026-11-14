"""Builds portfolios from the database and serves saved reports (generating them only once)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import models as m
from app.risk_analytics.provider import RiskAnalyticsProvider
from app.risk_analytics.snapshot import SnapshotStore, signature
from app.risk_analytics.types import AccountRisk, Portfolio, Position, RiskReport


def account_label(a: m.Account) -> str:
    return a.nickname or a.account_type.replace("_", " ").title()


class RiskAnalyticsService:
    def __init__(self, db: Session, provider: RiskAnalyticsProvider, store: SnapshotStore) -> None:
        self.db = db
        self.p = provider
        self.store = store

    # ------------------------------------------------------------------ portfolios
    def portfolio(self, id_: str, name: str, accounts: Iterable[m.Account]) -> Portfolio:
        shares: dict[str, float] = defaultdict(float)
        cash = 0.0
        for a in accounts:
            cash += a.cash or 0.0
            for lot in a.lots:
                shares[lot.ticker] += lot.quantity
        px = self.p.prices(list(shares))
        positions = [Position(ticker=t, market_value=q * px[t])
                     for t, q in shares.items() if t in px and q]
        return Portfolio(id=id_, name=name, positions=positions, cash=cash)

    # ------------------------------------------------------------------ reports
    def client_report(self, c: m.Client, refresh: bool = False) -> RiskReport:
        sig = signature([a.id for a in c.accounts])
        if not refresh:
            cached = self.store.get_client(c.id, sig, self.p.data_source, self.p.as_of)
            if cached is not None:
                return cached
        rep = self.p.analyze(self.portfolio(c.id, c.name, c.accounts), scope="client")
        accts = []
        for a in c.accounts:
            r = self.p.analyze(self.portfolio(a.id, account_label(a), [a]), scope="account")
            v95 = next(t for t in r.tail if t.days == 1 and t.confidence == 0.95)
            accts.append(AccountRisk(account_id=a.id, label=account_label(a),
                                     market_value=r.market_value, volatility=r.volatility,
                                     beta=r.beta, var_95_1d=v95.var, var_95_1d_usd=v95.var_usd))
        rep.accounts = sorted(accts, key=lambda x: -x.market_value)
        self.store.put_client(c.id, sig, rep)
        return rep

    def account_report(self, a: m.Account, refresh: bool = False) -> RiskReport:
        """One account on its own (the client page's account selector)."""
        sig = signature([a.id, a.client_id])
        if not refresh:
            cached = self.store.get_account(a.id, sig, self.p.data_source, self.p.as_of)
            if cached is not None:
                return cached
        rep = self.p.analyze(self.portfolio(a.id, account_label(a), [a]), scope="account")
        self.store.put_account(a.id, sig, rep)
        return rep

    def book_report(self, advisor_id: str, advisor_name: str, refresh: bool = False) -> RiskReport:
        ids = list(self.db.scalars(select(m.Client.id).where(m.Client.advisor_id == advisor_id)))
        sig = signature(ids)
        if not refresh:
            cached = self.store.get_book(advisor_id, sig, self.p.data_source, self.p.as_of)
            if cached is not None:
                return cached
        clients = list(self.db.scalars(
            select(m.Client).where(m.Client.advisor_id == advisor_id)
            .options(selectinload(m.Client.accounts).selectinload(m.Account.lots))
        ))
        accounts = [a for c in clients for a in c.accounts]
        rep = self.p.analyze(self.portfolio(advisor_id, advisor_name, accounts), scope="book")
        self.store.put_book(advisor_id, sig, rep)
        self.store.prune(set(self.db.scalars(select(m.Client.id))),
                         set(self.db.scalars(select(m.Account.id))))
        return rep
