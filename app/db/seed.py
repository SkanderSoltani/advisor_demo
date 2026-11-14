"""Deterministic demo seed: advisor + user, universe, 6 models, ~9 households, accounts,
tax lots and 1–3 years of management history per account. All data is synthetic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import models as m
from app.db.book_generator import generate_clients
from app.db.catalog import EQUITY_CLASSES, build_fund_proxies, load_catalog
from app.db.catalog_sync import sync_catalog
from app.db.lot_refs import make_lot_ref
from app.db.seed_specs import AccountSpec, ClientSpec
from app.db.synthetic_market import SyntheticMarket
from app.domain.entities import AccountType, EventTrigger, EventType, TaxProfile

DEMO_EMAIL = "demo@advisor.test"
DEMO_PASSWORD = "demo1234"
ADVISOR_ID = "adv_001"


# --------------------------------------------------------------------------- demo book spec
AT = AccountType
DEMO_BOOK: list[ClientSpec] = [
    ClientSpec(
        "Okafor Family",
        "family",
        "okafor.family@example.com",
        "555-0101",
        TaxProfile(0.37, 0.238, "CA", 0.133),
        "Three-generation household; prefers low turnover.",
        [
            AccountSpec(AT.JOINT_TAXABLE, "Schwab", "Joint brokerage", "TR", 4_200_000, 3.0),
            AccountSpec(AT.TRUST, "Schwab", "Family trust", "TR", 6_800_000, 2.8),
            AccountSpec(AT.IRA, "Schwab", "Rollover IRA", "INC", 1_100_000, 2.5),
        ],
    ),
    ClientSpec(
        "Maren Lindqvist",
        "individual",
        "m.lindqvist@example.com",
        "555-0102",
        TaxProfile(0.35, 0.238, "NY", 0.109),
        "Tech executive; holds restricted employer stock (locked).",
        [
            AccountSpec(
                AT.INDIVIDUAL_TAXABLE,
                "Fidelity",
                "Individual",
                "TR",
                3_100_000,
                2.2,
                locked_legacy=True,
            ),
            AccountSpec(AT.ROTH_IRA, "Fidelity", "Roth IRA", "TR", 420_000, 2.2),
        ],
    ),
    ClientSpec(
        "Castellanos Household",
        "couple",
        "castellanos@example.com",
        "555-0103",
        TaxProfile(0.32, 0.15, "TX", 0.0),
        "Retired; income focus.",
        [
            AccountSpec(
                AT.JOINT_TAXABLE,
                "Pershing",
                "Joint income",
                "INC",
                2_400_000,
                1.8,
                previous_model_id="TR",  # moved to income at retirement
            ),
            AccountSpec(AT.IRA, "Pershing", "IRA", "INC", 950_000, 1.8),
        ],
    ),
    ClientSpec(
        "Whitford Revocable Trust",
        "trust",
        "trustee.whitford@example.com",
        "555-0104",
        TaxProfile(0.37, 0.238, "MA", 0.05),
        "Single trust account; trustee reviews quarterly.",
        [AccountSpec(AT.TRUST, "Pershing", "Revocable trust", "TR", 9_500_000, 3.0)],
    ),
    ClientSpec(
        "Julian & Ana Pemberton",
        "couple",
        "pembertons@example.com",
        "555-0105",
        TaxProfile(0.32, 0.15, "IL", 0.0495),
        "Dual income; saving for college.",
        [
            AccountSpec(
                AT.JOINT_TAXABLE, "Schwab", "Joint", "TR", 1_350_000, 1.5, locked_legacy=True
            ),
            AccountSpec(AT.INDIVIDUAL_TAXABLE, "Schwab", "Ana — individual", "INC", 600_000, 1.2),
        ],
    ),
    ClientSpec(
        "Kenji Nakashima",
        "individual",
        "k.nakashima@example.com",
        "555-0106",
        TaxProfile(0.37, 0.238, "WA", 0.0),
        "Founder post-liquidity event; comfortable with active risk.",
        [
            AccountSpec(
                AT.INDIVIDUAL_TAXABLE,
                "Fidelity",
                "Individual",
                "TR",
                7_200_000,
                2.0,
            ),
            AccountSpec(AT.IRA, "Fidelity", "IRA", "TR", 800_000, 2.0),
        ],
    ),
    ClientSpec(
        "Abernathy Family",
        "family",
        "abernathy@example.com",
        "555-0107",
        TaxProfile(0.37, 0.238, "NJ", 0.1075),
        "Multi-account household; wants consolidated reporting.",
        [
            AccountSpec(AT.JOINT_TAXABLE, "Schwab", "Joint income", "INC", 2_900_000, 2.6),
            AccountSpec(AT.TRUST, "Schwab", "Children's trust", "TR", 1_700_000, 2.6),
            AccountSpec(AT.ROTH_IRA, "Schwab", "Roth IRA", "INC", 380_000, 1.0),
        ],
    ),
    ClientSpec(
        "Lucia Ferreira",
        "individual",
        "l.ferreira@example.com",
        "555-0108",
        TaxProfile(0.24, 0.15, "FL", 0.0),
        "Early-career physician.",
        [AccountSpec(AT.INDIVIDUAL_TAXABLE, "Fidelity", "Individual", "TR", 520_000, 1.1)],
    ),
    ClientSpec(
        "Theo & Priya Brennan",
        "couple",
        "brennans@example.com",
        "555-0109",
        TaxProfile(0.35, 0.238, "CO", 0.044),
        "NEW — onboarding. Legacy portfolio from prior advisor; target not yet chosen.",
        [
            AccountSpec(
                AT.JOINT_TAXABLE,
                "Schwab",
                "Joint (legacy)",
                None,
                2_750_000,
                0.0,
                locked_legacy=True,
            ),
        ],
    ),
]


# --------------------------------------------------------------------------- helpers
class PriceBook:
    """Price lookups on the synthetic history, with back-extrapolation before the first date."""

    def __init__(self, prices: pd.DataFrame) -> None:
        self.prices = prices
        self.index = pd.DatetimeIndex(prices.index)
        self.first = self.index[0].date()

    def at(self, ticker: str, d: date, rng: np.random.Generator | None = None) -> float:
        if d < self.first:
            years = (self.first - d).days / 365.25
            noise = rng.normal(0, 0.25 * math.sqrt(years)) if rng is not None else 0.0
            return float(self.prices[ticker].iloc[0] * math.exp(-0.09 * years + noise))
        pos = int(self.index.searchsorted(pd.Timestamp(d), side="right")) - 1
        return float(self.prices[ticker].iloc[max(pos, 0)])

    def market_drawdown(self, d: date, weights: pd.Series, lookback: int = 63) -> float:
        """Drawdown of a cap-weighted index from its trailing high (positive number)."""
        pos = int(self.index.searchsorted(pd.Timestamp(d), side="right")) - 1
        window = self.prices.iloc[max(pos - lookback, 0) : pos + 1]
        idx = (window / window.iloc[0]) @ weights
        return float(1.0 - idx.iloc[-1] / idx.max())


def _random_date(rng: np.random.Generator, start: date, end: date) -> date:
    span = max((end - start).days, 1)
    return start + timedelta(days=int(rng.integers(0, span)))


def _bday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class IdGen:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    def next(self, prefix: str, width: int) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:0{width}d}"

    def lot_ref(self, account_id: str) -> str:
        """Next Lot ID for the account (L017-0001, L017-0002, …)."""
        key = f"lot_ref:{account_id}"
        self.counters[key] = self.counters.get(key, 0) + 1
        return make_lot_ref(account_id, self.counters[key])


# --------------------------------------------------------------------------- builders
def _make_lots(
    rng: np.random.Generator,
    ids: IdGen,
    pb: PriceBook,
    account_id: str,
    ticker: str,
    shares: float,
    start: date,
    end: date,
    locked: bool,
) -> list[m.Lot]:
    n_lots = int(rng.integers(1, 5))
    splits = rng.dirichlet(np.ones(n_lots)) * shares
    lots = []
    for q in splits:
        q = max(round(float(q), 3), 0.001)
        acquired = _bday_on_or_before(_random_date(rng, start, end))
        px = pb.at(ticker, acquired, rng) * (1.0 + rng.normal(0, 0.01))
        lots.append(
            m.Lot(
                id=ids.next("lot", 6),
                account_id=account_id,
                lot_ref=ids.lot_ref(account_id),
                ticker=ticker,
                quantity=q,
                cost_basis_total=round(q * px, 2),
                acquired_date=acquired,
                locked=locked,
                source="seed",
            )
        )
    return lots


def _build_holdings(
    rng: np.random.Generator,
    ids: IdGen,
    pb: PriceBook,
    market: SyntheticMarket,
    models: dict[str, np.ndarray],
    acct: m.Account,
    spec: AccountSpec,
    as_of: date,
) -> None:
    u = market.universe
    tickers = np.array(u.index)
    last = market.last_prices()
    cash_pct = (
        float(rng.uniform(0.005, 0.04)) if spec.target_model_id else float(rng.uniform(0.01, 0.06))
    )
    acct.cash = round(spec.market_value * cash_pct, 2)

    weights: dict[str, float] = {}
    legacy: list[str] = []
    if spec.target_model_id:
        mw = models[spec.target_model_id]  # look-through stock weights of the target model
        held = np.flatnonzero(mw > 0)
        n_model = int(rng.integers(20, min(57, len(held)) + 1))
        p = mw[held] ** 0.7
        pick = rng.choice(held, size=n_model, replace=False, p=p / p.sum())
        for i in pick:
            weights[tickers[i]] = float(mw[i] * math.exp(rng.normal(0, 0.25)))
        n_legacy = int(rng.integers(0, 4)) + (1 if spec.locked_legacy else 0)
        outside = [
            t for t in tickers[np.argsort(-u["market_cap"].to_numpy())][:220] if t not in weights
        ]
        legacy = list(rng.choice(outside, size=n_legacy, replace=False)) if n_legacy else []
    else:
        # legacy portfolio from a prior advisor: concentrated, cap-biased, no model
        caps = u["market_cap"].to_numpy()
        p = caps**0.5 / (caps**0.5).sum()
        names = rng.choice(tickers, size=int(rng.integers(30, 46)), replace=False, p=p)
        for t in names:
            weights[str(t)] = float(rng.lognormal(0, 0.8))
        legacy = list(rng.choice([t for t in tickers if t not in weights], size=3, replace=False))

    legacy_w = {str(t): float(rng.uniform(0.03, 0.09)) for t in legacy}
    if spec.locked_legacy and legacy:
        legacy_w[str(legacy[0])] = float(rng.uniform(0.08, 0.14))  # concentrated employer stock
    total_core = sum(weights.values())
    core_share = 1.0 - cash_pct - sum(legacy_w.values())
    invest = spec.market_value

    onboard = acct.onboarding_date
    for t, w in weights.items():
        shares = invest * core_share * w / total_core / float(last[t])
        if spec.target_model_id:
            start, end = onboard, as_of - timedelta(days=5)
        else:
            start, end = as_of - timedelta(days=365 * 9), as_of - timedelta(days=20)
        acct.lots.extend(_make_lots(rng, ids, pb, acct.id, t, shares, start, end, locked=False))
    for j, (t, w) in enumerate(legacy_w.items()):
        shares = invest * w / float(last[t])
        lock = spec.locked_legacy and j == 0
        start = as_of - timedelta(days=365 * 10)
        end = (
            (onboard - timedelta(days=30)) if spec.target_model_id else as_of - timedelta(days=400)
        )
        acct.lots.extend(_make_lots(rng, ids, pb, acct.id, t, shares, start, end, locked=lock))


def _event_trades(
    rng: np.random.Generator,
    pb: PriceBook,
    tickers: list[str],
    d: date,
    sell_total: float,
    buy_total: float,
    n_sells: int,
    n_buys: int,
    loss_prob: float,
    lt_prob: float,
    gain_range: tuple[float, float],
    taxable: bool,
) -> list[m.EventTrade]:
    trades: list[m.EventTrade] = []
    if n_sells and sell_total > 0:
        sells = rng.choice(tickers, size=min(n_sells, len(tickers)), replace=False)
        vals = rng.dirichlet(np.ones(len(sells))) * sell_total
        for t, v in zip(sells, vals, strict=True):
            px = pb.at(str(t), d)
            if rng.random() < loss_prob:
                gain = -v * rng.uniform(0.04, 0.15)
            else:
                gain = v * rng.uniform(*gain_range)
            term = "LT" if rng.random() < lt_prob else "ST"
            trades.append(
                m.EventTrade(
                    ticker=str(t),
                    side="sell",
                    shares=round(v / px, 3),
                    price=round(px, 4),
                    value=round(v, 2),
                    realized_gain=round(gain, 2) if taxable else 0.0,
                    term=term if taxable else None,
                )
            )
    if n_buys and buy_total > 0:
        sold = {tr.ticker for tr in trades}
        pool = [t for t in tickers if t not in sold] or tickers
        buys = rng.choice(pool, size=min(n_buys, len(pool)), replace=False)
        vals = rng.dirichlet(np.ones(len(buys))) * buy_total
        for t, v in zip(buys, vals, strict=True):
            px = pb.at(str(t), d)
            trades.append(
                m.EventTrade(
                    ticker=str(t),
                    side="buy",
                    shares=round(v / px, 3),
                    price=round(px, 4),
                    value=round(v, 2),
                    realized_gain=0.0,
                    term=None,
                )
            )
    return trades


def _build_history(
    rng: np.random.Generator,
    ids: IdGen,
    pb: PriceBook,
    market: SyntheticMarket,
    models: dict[str, np.ndarray],
    acct: m.Account,
    spec: AccountSpec,
    tax: TaxProfile,
    as_of: date,
) -> None:
    """Generate the account's management-event history from onboarding to as-of."""
    if not spec.target_model_id or spec.years_managed <= 0:
        return
    taxable = spec.account_type.is_taxable
    blended = 0.5 * (tax.st_rate + tax.lt_rate)
    tickers_all = list(market.universe.index)
    caps = market.universe["market_cap"]
    bench_w = caps / caps.sum()
    mv0 = spec.market_value / math.exp(0.07 * spec.years_managed)  # rough growth back-out

    def model_tickers(model_id: str) -> list[str]:
        w = models[model_id]
        return [tickers_all[i] for i in np.flatnonzero(w > 0)]

    onboard = acct.onboarding_date
    change_date = None
    if spec.previous_model_id:
        change_date = _bday_on_or_before(
            onboard + timedelta(days=int(365 * spec.years_managed * 0.55))
        )

    # candidate event schedule ------------------------------------------------
    schedule: list[tuple[date, EventType, EventTrigger]] = [
        (onboard, EventType.TRANSITION, EventTrigger.CLIENT_REQUEST)
    ]
    d = onboard + timedelta(days=91)
    while d < as_of:
        schedule.append((_bday_on_or_before(d), EventType.REBALANCE, EventTrigger.SCHEDULED))
        d += timedelta(days=91)
    month = onboard + timedelta(days=30)
    while month < as_of:
        dd = _bday_on_or_before(month + timedelta(days=int(rng.integers(0, 20))))
        if dd < as_of:
            if taxable:
                dd_draw = pb.market_drawdown(dd, bench_w)
                if rng.random() < (0.6 if dd_draw > 0.05 else 0.08):
                    schedule.append(
                        (dd, EventType.TAX_LOSS_HARVEST, EventTrigger.HARVEST_OPPORTUNITY)
                    )
            if rng.random() < 0.07:
                schedule.append((dd, EventType.REBALANCE, EventTrigger.DRIFT))
            if rng.random() < 0.12:
                schedule.append((dd, EventType.CASH_FLOW, EventTrigger.CLIENT_REQUEST))
        month += timedelta(days=30)
    if change_date:
        schedule.append((change_date, EventType.MODEL_CHANGE, EventTrigger.CLIENT_REQUEST))
    schedule.sort(key=lambda x: (x[0], x[1] != EventType.TRANSITION))

    # walk the schedule -------------------------------------------------------
    te_after = 0.0
    last_date = onboard
    for ev_date, etype, trig in schedule:
        frac = (ev_date - onboard).days / max((as_of - onboard).days, 1)
        mv = mv0 + (spec.market_value - mv0) * frac
        model_id = (
            spec.previous_model_id
            if (spec.previous_model_id and change_date and ev_date < change_date)
            else spec.target_model_id
        )
        if etype == EventType.MODEL_CHANGE:
            model_id = spec.target_model_id
        universe_t = model_tickers(model_id)
        drift = te_after + rng.uniform(0.001, 0.006) * (ev_date - last_date).days / 90
        cash_flow_amount = 0.0

        if etype == EventType.TRANSITION:
            te_before, te_new = rng.uniform(0.03, 0.08), rng.uniform(0.003, 0.010)
            turnover = rng.uniform(0.4, 0.85)
            n_s, n_b = int(rng.integers(15, 35)), int(rng.integers(20, 45))
            kw = dict(loss_prob=0.25, lt_prob=0.8, gain_range=(0.05, 0.45))
            sell_total = buy_total = turnover * mv
            pool = tickers_all
            deferral = rng.uniform(0.3, 0.8)
            note = f"Initial transition into {model_id}; gains budgeted, low-basis lots deferred."
        elif etype == EventType.MODEL_CHANGE:
            te_before, te_new = rng.uniform(0.02, 0.05), rng.uniform(0.004, 0.012)
            turnover = rng.uniform(0.25, 0.5)
            n_s, n_b = int(rng.integers(12, 30)), int(rng.integers(12, 30))
            kw = dict(loss_prob=0.3, lt_prob=0.7, gain_range=(0.03, 0.35))
            sell_total = buy_total = turnover * mv
            pool = universe_t
            deferral = rng.uniform(0.2, 0.6)
            note = f"Model changed from {spec.previous_model_id} to {model_id} at client request."
        elif etype == EventType.TAX_LOSS_HARVEST:
            te_before = max(drift, 0.002)
            te_new = te_before + rng.uniform(0.0, 0.002)
            turnover = rng.uniform(0.01, 0.06)
            n_s = int(rng.integers(2, 10))
            n_b = n_s
            kw = dict(loss_prob=1.0, lt_prob=0.35, gain_range=(0.0, 0.0))
            sell_total = buy_total = turnover * mv
            pool = universe_t
            deferral = 0.0
            note = (
                "Harvested losses; proceeds reinvested in correlated replacements (wash-sale safe)."
            )
        elif etype == EventType.CASH_FLOW:
            deposit = rng.random() < 0.65
            amt = mv * rng.uniform(0.01, 0.10)
            cash_flow_amount = amt if deposit else -amt
            te_before = max(drift, 0.002)
            te_new = max(te_before - rng.uniform(0.0, 0.004), 0.002)
            turnover = amt / mv
            n_s, n_b = (0, int(rng.integers(5, 25))) if deposit else (int(rng.integers(3, 15)), 0)
            kw = dict(loss_prob=0.4, lt_prob=0.6, gain_range=(0.02, 0.25))
            sell_total, buy_total = (0.0, amt) if deposit else (amt, 0.0)
            pool = universe_t
            deferral = 0.0
            note = (
                f"Client deposit of ${amt:,.0f} invested toward target."
                if deposit
                else f"Client withdrawal of ${amt:,.0f}; sold highest-basis lots first."
            )
        else:  # rebalance
            if trig == EventTrigger.DRIFT:
                te_before = max(drift, acct.drift_tolerance_te + rng.uniform(0.001, 0.008))
            else:
                te_before = max(drift, 0.003)
            te_new = rng.uniform(0.003, 0.008)
            turnover = rng.uniform(0.02, 0.10)
            n_s, n_b = int(rng.integers(3, 15)), int(rng.integers(3, 15))
            kw = dict(loss_prob=0.2, lt_prob=0.65, gain_range=(0.02, 0.30))
            sell_total = buy_total = turnover * mv
            pool = universe_t
            deferral = rng.uniform(0.1, 0.5)
            note = (
                "Drift exceeded tolerance; rebalanced within gain budget."
                if trig == EventTrigger.DRIFT
                else "Scheduled quarterly rebalance."
            )

        trades = _event_trades(
            rng,
            pb,
            pool,
            ev_date,
            sell_total,
            buy_total,
            n_s,
            n_b,
            taxable=taxable,
            **kw,  # type: ignore[arg-type]
        )
        st_gain = sum(t.realized_gain for t in trades if t.term == "ST" and t.realized_gain > 0)
        lt_gain = sum(t.realized_gain for t in trades if t.term == "LT" and t.realized_gain > 0)
        losses = -sum(t.realized_gain for t in trades if t.realized_gain < 0)
        st_loss = -sum(t.realized_gain for t in trades if t.term == "ST" and t.realized_gain < 0)
        lt_loss = losses - st_loss
        gains_deferred = (st_gain + lt_gain) * deferral
        taxes_saved = (losses * blended + gains_deferred * tax.lt_rate) if taxable else 0.0

        acct.events.append(
            m.ManagementEvent(
                id=ids.next("evt", 5),
                account_id=acct.id,
                event_date=ev_date,
                event_type=etype.value,
                trigger=trig.value,
                n_trades=len(trades),
                turnover=round(float(turnover), 4),
                realized_st_gain=round(st_gain, 2),
                realized_lt_gain=round(lt_gain, 2),
                losses_harvested=round(losses, 2),
                realized_st_loss=round(st_loss, 2),
                realized_lt_loss=round(lt_loss, 2),
                est_taxes_saved=round(taxes_saved, 2),
                te_before=round(float(te_before), 5),
                te_after=round(float(te_new), 5),
                cash_flow_amount=round(cash_flow_amount, 2),
                note=note,
                trades=trades,
            )
        )
        te_after = float(te_new)
        last_date = ev_date


# --------------------------------------------------------------------------- entry point
@dataclass(slots=True)
class SeedSummary:
    users: int
    clients: int
    accounts: int
    lots: int
    events: int
    trades: int
    models: int
    securities: int


def seed_demo(
    session: Session,
    engine: Engine,
    market: SyntheticMarket,
    seed: int,
    models_file: Path | None = None,
    extra_clients: int = 0,
    total_aum: float | None = None,
    book_data: dict[str, Any] | None = None,
) -> SeedSummary:
    """Drop and recreate all tables, then load the demo book.

    The book (clients, accounts, lots, history) comes from ``book_data`` (the contents of the
    book file) when given; otherwise it is generated: the hand-written households plus
    ``extra_clients`` generated ones sized so the whole book is about ``total_aum``.

    Target models come from the JSON catalog; demo accounts target the first catalog model whose
    objective matches their spec ("TR" → total_return, "INC" → income).
    """
    from app.core.config import get_settings

    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)

    as_of = market.as_of
    pb = PriceBook(market.prices)
    ids = IdGen()

    # securities (stocks)
    u = market.universe
    session.add_all(
        m.Security(
            ticker=str(t),
            name=r["name"],
            sector=r["sector"],
            market_cap=float(r["market_cap"]),
            dividend_yield=float(r["dividend_yield"]),
            value_score=float(r["value"]),
            quality_score=float(r["quality"]),
            profitability_score=float(r["profitability"]),
            momentum_score=float(r["momentum"]),
            beta=float(r["beta"]),
            last_price=float(r["price"]),
            security_type="equity",
        )
        for t, r in u.iterrows()
    )
    session.flush()

    # target models from the JSON catalog (products become fund securities)
    catalog = load_catalog(models_file or get_settings().MODELS_FILE)
    funds = build_fund_proxies(market, catalog)
    model_ids = sync_catalog(session, catalog, market, funds)
    tickers = list(u.index)
    models = {
        ms.id: np.array(
            [
                funds.look_through({h.ticker: h.weight for h in ms.holdings}).get(t, 0.0)
                for t in tickers
            ]
        )
        for ms in catalog.models
    }
    # demo accounts hold all-stock portfolios: each objective's most equity-heavy model in its
    # first line (e.g. Core 96/04, Income 60/40) keeps their tracking error realistic
    by_code: dict[str, str] = {}
    first_line: dict[str, str | None] = {}
    eq_share: dict[str, float] = {}
    for ms in catalog.models:
        code = {"total_return": "TR", "income": "INC"}.get(ms.objective)
        if code is None:
            continue
        line = first_line.setdefault(code, ms.line_id)
        if ms.line_id != line:
            continue
        eq = sum(h.weight for h in ms.holdings
                 if catalog.asset_class(h.ticker) in EQUITY_CLASSES)
        if code not in by_code or eq > eq_share[code] + 1e-9:
            by_code[code], eq_share[code] = ms.id, eq
    by_code.setdefault("TR", catalog.models[0].id)
    by_code.setdefault("INC", catalog.models[0].id)

    def resolve(spec: AccountSpec) -> AccountSpec:
        target = by_code[spec.target_model_id] if spec.target_model_id else None
        prev = by_code[spec.previous_model_id] if spec.previous_model_id else None
        return replace(
            spec, target_model_id=target, previous_model_id=prev if prev != target else None
        )

    # advisor & user
    session.add(
        m.Advisor(id=ADVISOR_ID, name="Demo Advisor", firm="Harborview Wealth Partners (demo)")
    )
    session.add(
        m.User(
            id="usr_001",
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            name="Demo Advisor",
            role="advisor",
            advisor_id=ADVISOR_ID,
        )
    )

    if book_data is not None:
        from app.db.book_store import load_book

        session.flush()
        load_book(session, book_data)
        session.commit()
        return _summary(session, len(model_ids), len(u) + len(catalog.products))

    book = list(DEMO_BOOK)
    if extra_clients:
        hand = sum(a.market_value for c in DEMO_BOOK for a in c.accounts)
        rest = (total_aum or hand * 2) - hand
        book += generate_clients(
            seed, extra_clients, max(rest, 0.0), phone_start=110, taken={c.name for c in book}
        )

    # clients, accounts, lots, history
    for ci, cs in enumerate(book):
        client = m.Client(
            id=ids.next("cli", 3),
            advisor_id=ADVISOR_ID,
            name=cs.name,
            email=cs.email,
            phone=cs.phone,
            client_type=cs.client_type,
            notes=cs.notes,
            federal_st_rate=cs.tax.federal_st_rate,
            federal_lt_rate=cs.tax.federal_lt_rate,
            state=cs.tax.state,
            state_rate=cs.tax.state_rate,
        )
        session.add(client)
        for ai, raw_spec in enumerate(cs.accounts):
            spec = resolve(raw_spec)
            rng = np.random.default_rng([seed, ci, ai])
            onboard = (
                _bday_on_or_before(as_of - timedelta(days=int(365 * spec.years_managed)))
                if spec.years_managed > 0
                else _bday_on_or_before(as_of - timedelta(days=4))
            )
            acct = m.Account(
                id=ids.next("acc", 3),
                client_id=client.id,
                account_type=spec.account_type.value,
                custodian=spec.custodian,
                nickname=spec.nickname,
                target_model_id=spec.target_model_id,
                onboarding_date=onboard,
                drift_tolerance_te=0.015,
            )
            client.accounts.append(acct)
            _build_holdings(rng, ids, pb, market, models, acct, spec, as_of)
            _build_history(rng, ids, pb, market, models, acct, spec, cs.tax, as_of)

    session.commit()
    return _summary(session, len(model_ids), len(u) + len(catalog.products))


def _summary(session: Session, n_models: int, n_securities: int) -> SeedSummary:
    return SeedSummary(
        users=session.query(m.User).count(),
        clients=session.query(m.Client).count(),
        accounts=session.query(m.Account).count(),
        lots=session.query(m.Lot).count(),
        events=session.query(m.ManagementEvent).count(),
        trades=session.query(m.EventTrade).count(),
        models=n_models,
        securities=n_securities,
    )
