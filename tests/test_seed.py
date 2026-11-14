from __future__ import annotations

from collections import Counter
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.db import models as m
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, SeedSummary
from app.domain.entities import AccountType, EventType, holding_period
from tests.conftest import TEST_AS_OF


def test_counts(seeded: SeedSummary) -> None:
    assert seeded.users == 1
    assert 8 <= seeded.clients <= 10
    from app.core.config import get_settings
    from app.db.catalog import load_catalog

    assert seeded.models == len(load_catalog(get_settings().MODELS_FILE).models)
    n_products = len(load_catalog(get_settings().MODELS_FILE).products)
    assert seeded.securities == 300 + n_products  # stocks + catalog products


def test_demo_user_login(db: Session) -> None:
    user = db.query(m.User).filter_by(email=DEMO_EMAIL).one()
    assert verify_password(DEMO_PASSWORD, user.password_hash)
    assert not verify_password("wrong", user.password_hash)


def test_hierarchy_and_positions(db: Session) -> None:
    clients = db.query(m.Client).all()
    for c in clients:
        assert 1 <= len(c.accounts) <= 3
        assert 0 <= c.state_rate < 0.15 and c.federal_lt_rate < c.federal_st_rate
        for a in c.accounts:
            tickers = {lot.ticker for lot in a.lots}
            assert 20 <= len(tickers) <= 60, (a.id, len(tickers))
            assert len(a.lots) > len(tickers)  # multiple lots per position somewhere
            assert a.cash > 0
            assert all(lot.quantity > 0 and lot.cost_basis_total > 0 for lot in a.lots)
            assert all(lot.acquired_date <= TEST_AS_OF for lot in a.lots)
            refs = [lot.lot_ref for lot in a.lots]
            assert all(refs) and len(set(refs)) == len(refs)  # Lot IDs unique in the account


def test_lots_have_mixed_terms_and_gains(db: Session) -> None:
    lots = db.query(m.Lot).all()
    prices = {s.ticker: s.last_price for s in db.query(m.Security)}
    terms = Counter(holding_period(lot.acquired_date, TEST_AS_OF).value for lot in lots)
    assert terms["ST"] > 50 and terms["LT"] > 50
    gains = [lot.quantity * prices[lot.ticker] - lot.cost_basis_total for lot in lots]
    n_loss = sum(g < 0 for g in gains)
    assert 0.2 < n_loss / len(gains) < 0.7
    assert sum(gains) > 0  # embedded gains overall


def test_locked_lots_exist(db: Session) -> None:
    assert db.query(m.Lot).filter_by(locked=True).count() > 0


def test_onboarding_client_has_no_history(db: Session) -> None:
    new = [a for a in db.query(m.Account) if a.target_model_id is None]
    assert len(new) == 1
    acct = new[0]
    assert acct.events == []
    assert (TEST_AS_OF - acct.onboarding_date).days < 14
    assert len(acct.lots) > 0  # legacy holdings waiting to be transitioned


def test_event_history(db: Session) -> None:
    events = db.query(m.ManagementEvent).all()
    types = Counter(e.event_type for e in events)
    for t in EventType:
        assert types[t.value] > 0, t
    for acct in db.query(m.Account).filter(m.Account.target_model_id.is_not(None)):
        evs = acct.events
        assert evs[0].event_type == "transition"
        assert evs[0].event_date == acct.onboarding_date
        span = (TEST_AS_OF - acct.onboarding_date).days
        assert 300 <= span <= 3 * 366
        assert all(acct.onboarding_date <= e.event_date <= TEST_AS_OF for e in evs)
        if not AccountType(acct.account_type).is_taxable:
            assert all(e.event_type != "tax_loss_harvest" for e in evs)
            assert all(e.est_taxes_saved == 0 for e in evs)


def test_event_totals_match_trades(db: Session) -> None:
    for e in db.query(m.ManagementEvent).limit(80):
        assert e.n_trades == len(e.trades)
        st = sum(t.realized_gain for t in e.trades if t.term == "ST" and t.realized_gain > 0)
        lt = sum(t.realized_gain for t in e.trades if t.term == "LT" and t.realized_gain > 0)
        losses = -sum(t.realized_gain for t in e.trades if t.realized_gain < 0)
        assert e.realized_st_gain == pytest.approx(st, abs=0.05)
        assert e.realized_lt_gain == pytest.approx(lt, abs=0.05)
        assert e.losses_harvested == pytest.approx(losses, abs=0.05)
        assert 0 <= e.te_after < 0.1 and 0 <= e.te_before < 0.1
        if e.event_type == "tax_loss_harvest":
            sold = {t.ticker for t in e.trades if t.side == "sell"}
            bought = {t.ticker for t in e.trades if t.side == "buy"}
            assert not sold & bought  # no same-name repurchase (wash-sale safe)


def test_seed_is_deterministic(db: Session) -> None:
    # spot-check stable identifiers / values produced from the fixed seed
    first = db.get(m.Account, "acc_001")
    assert first is not None and first.onboarding_date < date(2024, 1, 1)
