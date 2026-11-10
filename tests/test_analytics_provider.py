"""RandomAnalyticsProvider: interface conformance, shapes, ranges, determinism; Aladdin stub."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.analytics.aggregate import sum_tax_periods, value_weighted, weighted_te_series
from app.analytics.aladdin_provider import AladdinAnalyticsProvider
from app.analytics.provider import AnalyticsProvider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.analytics.types import (
    AccountContext,
    DatedValue,
    Granularity,
    TaxPeriod,
    period_range,
)
from app.db import models as m
from app.db.catalog import FundProxies
from app.db.synthetic_market import SyntheticMarket
from app.domain.tax import pooled_tax as net_tax
from app.services.portfolio import PortfolioService
from tests.conftest import TEST_SEED


@pytest.fixture()
def contexts(db: Session, provider: RandomAnalyticsProvider) -> dict[str, AccountContext]:
    svc = PortfolioService(db, provider, "adv_001")
    return {a.id: svc.context(a) for a in db.query(m.Account).all()}


def _managed(contexts: dict[str, AccountContext]) -> list[AccountContext]:
    return [c for c in contexts.values() if c.events]


def test_is_an_analytics_provider(provider: RandomAnalyticsProvider) -> None:
    assert isinstance(provider, AnalyticsProvider)
    assert provider.data_source == "mock_random"


def test_risk_model_psd_and_subsetting(provider: RandomAnalyticsProvider) -> None:
    tickers = list(provider.market.universe.index[:50])
    rm = provider.get_risk_model(tickers)
    cov = rm.covariance
    assert cov.shape == (50, 50)
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() > 0
    vols = np.sqrt(np.diag(cov))
    assert 0.10 < float(np.median(vols)) < 0.45
    # subset is consistent with the full model
    full = provider.get_risk_model(list(provider.market.universe.index))
    assert np.allclose(full.covariance[:50, :50], cov)


def test_te_history_ranges_and_anchoring(
    provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]
) -> None:
    for ctx in _managed(contexts):
        for window in (63, 252):
            h = provider.get_tracking_error_history(ctx, window)
            assert h.series, ctx.account_id
            vals = np.array([p.value for p in h.series])
            assert vals.min() >= 0.002 and vals.max() <= 0.06
            assert h.series[0].d >= ctx.onboarding_date
            assert h.series[-1].d <= ctx.as_of
        assert h.ex_ante_te is not None and 0.001 <= h.ex_ante_te <= 0.15


def test_ex_ante_te_is_risk_model_te(
    provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]
) -> None:
    """Option (b): today's TE is sqrt(dᵀΣd) of holdings vs target, and the history ends on it."""
    for ctx in _managed(contexts):
        w, _ = provider._weights(ctx)
        names = sorted(set(w) | set(ctx.target_weights))
        cov = provider.get_risk_model(names).covariance
        d = np.array([w.get(t, 0.0) - ctx.target_weights.get(t, 0.0) for t in names])
        expected = float(np.sqrt(d @ cov @ d))
        assert provider.get_ex_ante_te(ctx) == pytest.approx(expected, abs=1e-5)
        assert float(provider._te_path(ctx).iloc[-1]) == pytest.approx(expected, rel=1e-9)


def test_te_deterministic(
    market: SyntheticMarket, funds: FundProxies, contexts: dict[str, AccountContext]
) -> None:
    ctx = _managed(contexts)[0]

    def make(seed: int) -> RandomAnalyticsProvider:
        return RandomAnalyticsProvider(market, seed=seed, funds=funds)

    a = make(TEST_SEED).get_tracking_error_history(ctx, 63)
    b = make(TEST_SEED).get_tracking_error_history(ctx, 63)
    c = make(TEST_SEED + 1).get_tracking_error_history(ctx, 63)
    assert a == b
    assert a.series != c.series


def test_ex_ante_te_is_account_specific(
    provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]
) -> None:
    tes = [provider.get_ex_ante_te(c) for c in _managed(contexts)]
    assert all(t is not None and t > 0.003 for t in tes)
    assert len(set(tes)) == len(tes)


def test_no_target_or_no_history(
    provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]
) -> None:
    new = next(c for c in contexts.values() if c.target_model_id is None)
    h = provider.get_tracking_error_history(new, 63)
    assert h.series == () and h.ex_ante_te is None
    # with a target but no history, ex-ante TE comes from the risk model on holdings
    model_w = next(c for c in contexts.values() if c.target_weights).target_weights
    fresh = AccountContext(
        **{
            **{f: getattr(new, f) for f in new.__dataclass_fields__},
            "target_model_id": "SCHWAB-TR",
            "target_weights": model_w,
        }
    )
    te = provider.get_ex_ante_te(fresh)
    assert te is not None and 0.005 < te < 0.15


def test_tax_history_matches_events(
    provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]
) -> None:
    for ctx in _managed(contexts):
        for g in Granularity:
            hist = provider.get_tax_history(ctx, g)
            assert [p.period for p in hist] == period_range(ctx.onboarding_date, ctx.as_of, g)
            assert sum(p.est_taxes_saved for p in hist) == pytest.approx(
                sum(e.est_taxes_saved for e in ctx.events), abs=0.05
            )
            assert sum(p.losses_harvested for p in hist) == pytest.approx(
                sum(e.losses_harvested for e in ctx.events), abs=0.05
            )
            assert all(p.est_tax_paid >= 0 for p in hist)
            if not ctx.taxable:
                assert all(p.est_tax_paid == 0 for p in hist)


def test_net_tax() -> None:
    # losses offset ST first, then LT
    assert net_tax(100, 100, 150, 0.5, 0.2) == pytest.approx(50 * 0.2)
    assert net_tax(100, 100, 50, 0.5, 0.2) == pytest.approx(50 * 0.5 + 100 * 0.2)
    assert net_tax(0, 0, 10, 0.5, 0.2) == 0


def test_aum_history(
    provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]
) -> None:
    for ctx in contexts.values():
        aum = provider.get_aum_history(ctx)
        assert aum and all(p.value >= 0 for p in aum)
        assert aum[0].d >= ctx.onboarding_date or len(aum) == 1
        mv = ctx.cash + sum(
            q * p
            for q, p in zip(
                ctx.shares().values(), provider.get_prices(list(ctx.shares())).values(), strict=True
            )
        )
        assert aum[-1].value == pytest.approx(mv, rel=1e-6)


def test_exposures(provider: RandomAnalyticsProvider, contexts: dict[str, AccountContext]) -> None:
    for ctx in contexts.values():
        x = provider.get_exposures(ctx)
        assert sum(s.portfolio_weight for s in x.sectors) == pytest.approx(1.0, abs=1e-4)
        if ctx.target_weights:
            assert sum(s.target_weight for s in x.sectors) == pytest.approx(1.0, abs=1e-4)
            assert x.target_dividend_yield is not None and 0.005 < x.target_dividend_yield < 0.05
        assert 0 < x.top10_weight <= 1 and 0 < x.hhi <= 1
        assert 0.0 <= x.dividend_yield < 0.08 and 0.3 < x.beta < 2.0
        assert len(x.top_active) == 10
        assert {f.factor for f in x.factors} == {"value", "quality", "momentum", "size"}


def test_aladdin_stub_raises() -> None:
    p = AladdinAnalyticsProvider(as_of=date(2026, 10, 30))
    assert isinstance(p, AnalyticsProvider) and p.data_source == "aladdin"
    with pytest.raises(NotImplementedError):
        p.get_prices(["X"])
    with pytest.raises(NotImplementedError):
        p.get_risk_model(["X"])


def test_factory_selects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.analytics import factory
    from app.core.config import get_settings

    monkeypatch.setenv("ANALYTICS_PROVIDER", "aladdin")
    get_settings.cache_clear()
    factory.get_provider.cache_clear()
    try:
        assert isinstance(factory.get_provider(), AladdinAnalyticsProvider)
    finally:
        monkeypatch.delenv("ANALYTICS_PROVIDER")
        get_settings.cache_clear()
        factory.get_provider.cache_clear()


# ---------------------------------------------------------------- aggregation helpers
def test_value_weighted() -> None:
    assert value_weighted([], []) is None
    assert value_weighted([0.01, 0.03], [1, 3]) == pytest.approx(0.025)


def test_weighted_te_series_band() -> None:
    d = date(2026, 1, 2)
    te = {"a": [DatedValue(d, 0.01)], "b": [DatedValue(d, 0.03)], "c": [DatedValue(d, 0.02)]}
    aum = {"a": [DatedValue(d, 100.0)], "b": [DatedValue(d, 300.0)], "c": [DatedValue(d, 0.0)]}
    (pt,) = weighted_te_series(te, aum)
    assert pt.avg_te == pytest.approx(0.025)
    assert pt.p10 <= pt.avg_te <= pt.p90 and pt.n_accounts == 3


def test_sum_tax_periods() -> None:
    a = [TaxPeriod("2026-01", 1, 2, 3, 4, 5)]
    b = [TaxPeriod("2026-01", 1, 1, 1, 1, 1), TaxPeriod("2026-02", 1, 0, 0, 0, 0)]
    out = sum_tax_periods([a, b])
    assert [p.period for p in out] == ["2026-01", "2026-02"]
    assert out[0].est_taxes_saved == 6 and out[0].realized_st_gain == 2
