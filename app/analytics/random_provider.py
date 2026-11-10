"""RandomAnalyticsProvider — simulated analytics (``data_source = "mock_random"``).

Every number is deterministic: randomness is drawn from ``np.random.default_rng([seed,
crc32(key)])`` where ``key`` is the account / model id, so values never change across refreshes.

How each metric is simulated
----------------------------
* Risk model: factor model fitted to the synthetic return history (loadings from the generator,
  factor covariance and specific variance estimated over the last 2 years). Always PSD.
* Ex-ante TE today: computed exactly, sqrt(dᵀΣd) of current holdings vs target weights using the
  risk model above (cash counts as zero weight). This is the same number the optimizer will use.
* Tracking-error history: a simulated daily TE path anchored on the account's management events
  (TE drops to ``te_after`` at each event and drifts toward the next event's ``te_before``), ending
  at today's risk-model ex-ante TE, plus seeded noise; rolling ex-post TE is the RMS of the noisy
  path over the window.
* Tax history: aggregated from the account's (synthetic) management events, with losses netted
  against ST gains first, then LT, within each period.
* AUM history: today's shares × synthetic price history + cash, backing out later cash flows.
* Exposures: computed from synthetic holdings and synthetic reference data (sector, scores).
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np
import numpy.typing as npt
import pandas as pd

from app.analytics.provider import AnalyticsProvider
from app.analytics.types import (
    AccountContext,
    DatedValue,
    Exposures,
    FactorExposure,
    Granularity,
    ModelStats,
    RegimePerformance,
    RiskModel,
    SectorExposure,
    SecurityExposure,
    TaxPeriod,
    TrackingErrorHistory,
    period_key,
    period_range,
)
from app.db.catalog import FundProxies
from app.db.synthetic_market import SyntheticMarket
from app.domain.tax import pooled_tax as net_tax

TE_FLOOR, TE_CAP = 0.003, 0.06
RISK_LOOKBACK_DAYS = 504
FACTORS = ("value", "quality", "momentum", "size")
RISK_FREE_RATE = 0.03


class RandomAnalyticsProvider(AnalyticsProvider):
    """Seeded simulated analytics over the synthetic market."""

    data_source = "mock_random"

    def __init__(
        self, market: SyntheticMarket, seed: int, funds: FundProxies | None = None
    ) -> None:
        self.market = market
        self.seed = seed
        self.funds = funds
        self.as_of = market.as_of
        self._universe = market.universe
        self._prices = (
            pd.concat([market.prices, funds.nav], axis=1) if funds is not None else market.prices
        )
        self._last = self._prices.iloc[-1]
        self._risk: RiskModel | None = None
        self._te_cache: dict[tuple[object, ...], pd.Series] = {}
        self._model_ret_cache: dict[tuple[object, ...], pd.Series] = {}
        log_cap = np.log(self._universe["market_cap"].to_numpy(dtype=float))
        self._size = pd.Series(
            (log_cap - log_cap.mean()) / log_cap.std(), index=self._universe.index
        )

    # ------------------------------------------------------------------ helpers
    def _rng(self, key: str) -> np.random.Generator:
        return np.random.default_rng([self.seed, zlib.crc32(key.encode())])

    def look_through(self, weights: Mapping[str, float]) -> dict[str, float]:
        """Product (fund) weights replaced by constituent stock weights; stocks pass through."""
        if self.funds is None:
            return dict(weights)
        return self.funds.look_through(dict(weights))

    def _exposure_matrix(self, tickers: Sequence[str]) -> npt.NDArray[np.float64]:
        """Rows map each ticker (stock or fund) onto the stock universe."""
        stocks = list(self._universe.index)
        pos = {t: i for i, t in enumerate(stocks)}
        e = np.zeros((len(tickers), len(stocks)))
        for r, t in enumerate(tickers):
            if t in pos:
                e[r, pos[t]] = 1.0
            elif self.funds is not None and t in self.funds.weights.index:
                e[r] = self.funds.weights.loc[t, stocks].to_numpy(dtype=float)
            else:
                raise KeyError(f"unknown security {t}")
        return e

    # ------------------------------------------------------------------ market data / risk
    def get_prices(self, tickers: Sequence[str]) -> dict[str, float]:
        return {t: float(self._last[t]) for t in tickers}

    def _full_risk_model(self) -> RiskModel:
        if self._risk is None:
            rets = self.market.returns.iloc[-RISK_LOOKBACK_DAYS:]
            f = self.market.factor_returns.loc[rets.index]
            b = self.market.loadings.loc[rets.columns]
            fac_cov = np.cov(f.to_numpy(), rowvar=False) * 252
            resid = rets.to_numpy() - f.to_numpy() @ b.to_numpy().T
            spec = resid.var(axis=0, ddof=1) * 252
            bl = b.to_numpy(dtype=float)
            cov = bl @ fac_cov @ bl.T + np.diag(spec)
            self._risk = RiskModel(
                tickers=tuple(rets.columns),
                covariance=0.5 * (cov + cov.T),
                factor_names=tuple(f.columns),
                loadings=bl,
                factor_covariance=fac_cov,
                specific_variance=spec,
            )
        return self._risk

    def get_risk_model(self, tickers: Sequence[str]) -> RiskModel:
        """Covariance for any mix of stocks and funds: E·Σ·Eᵀ with E the look-through matrix."""
        full = self._full_risk_model()
        e = self._exposure_matrix(tickers)
        cov = e @ full.covariance @ e.T
        return RiskModel(
            tickers=tuple(tickers),
            covariance=0.5 * (cov + cov.T),
            factor_names=full.factor_names,
            loadings=e @ full.loadings,
            factor_covariance=full.factor_covariance,
            specific_variance=(e**2) @ full.specific_variance,
            exposure=e,
            base_loadings=full.loadings,
            base_specific_variance=full.specific_variance,
        )

    def _weights(self, ctx: AccountContext) -> tuple[dict[str, float], float]:
        """Portfolio weights of total value (incl. cash) and the total value."""
        shares = ctx.shares()
        mv = {t: q * float(self._last[t]) for t, q in shares.items()}
        total = sum(mv.values()) + ctx.cash
        if total <= 0:
            return {}, 0.0
        return {t: v / total for t, v in mv.items()}, total

    def _holdings_te(self, ctx: AccountContext) -> float | None:
        w, _ = self._weights(ctx)
        if not w or not ctx.target_weights:
            return None
        return self.te_between(w, ctx.target_weights)

    def te_between(self, a: Mapping[str, float], b: Mapping[str, float]) -> float:
        """Ex-ante TE between two weight vectors (stocks and/or funds), via look-through."""
        la, lb = self.look_through(a), self.look_through(b)
        names = sorted(set(la) | set(lb))
        full = self._full_risk_model()
        pos = {t: i for i, t in enumerate(full.tickers)}
        idx = np.array([pos[t] for t in names], dtype=int)
        cov = full.covariance[np.ix_(idx, idx)]
        d = np.array([la.get(t, 0.0) - lb.get(t, 0.0) for t in names])
        return float(np.sqrt(max(float(d @ cov @ d), 0.0)))

    # ------------------------------------------------------------------ tracking error
    def _te_path(self, ctx: AccountContext) -> pd.Series:
        """Daily simulated ex-ante TE from onboarding to as-of, anchored on events."""
        key = (
            ctx.account_id,
            ctx.as_of,
            len(ctx.events),
            ctx.events[-1].event_id if ctx.events else "",
        )
        if key in self._te_cache:
            return self._te_cache[key]
        if not ctx.events or ctx.target_model_id is None:
            path = pd.Series(dtype=float)
            self._te_cache[key] = path
            return path

        rng = self._rng(f"te:{ctx.account_id}")
        days = pd.bdate_range(ctx.events[0].event_date, ctx.as_of)
        # the simulated history ends exactly at today's risk-model ex-ante TE
        holdings_te = self._holdings_te(ctx)
        te_now = holdings_te if holdings_te is not None else ctx.events[-1].te_after
        anchors: list[tuple[pd.Timestamp, float, float]] = [
            (pd.Timestamp(e.event_date), e.te_before, e.te_after) for e in ctx.events
        ]
        values = np.empty(len(days))
        starts = [a[0] for a in anchors]
        seg = (
            np.searchsorted(np.array(starts, dtype="datetime64[ns]"), days.values, side="right") - 1
        )
        for i, (day, k) in enumerate(zip(days, seg, strict=True)):
            t0, _, start_val = anchors[k]
            if k + 1 < len(anchors):
                t1, end_val, _ = anchors[k + 1]
            else:
                t1, end_val = pd.Timestamp(ctx.as_of), te_now
            span = max((t1 - t0).days, 1)
            frac = min((day - t0).days / span, 1.0)
            values[i] = start_val + (end_val - start_val) * frac
        # smooth multiplicative noise (AR(1)) so the line looks like a real risk-model series
        noise = np.zeros(len(days))
        for i in range(1, len(days)):
            noise[i] = 0.97 * noise[i - 1] + rng.normal(0, 0.02)
        path = pd.Series(np.clip(values * np.exp(noise), TE_FLOOR, TE_CAP), index=days)
        path.iloc[-1] = float(te_now)
        self._te_cache[key] = path
        return path

    def get_tracking_error_history(self, ctx: AccountContext, window: int) -> TrackingErrorHistory:
        path = self._te_path(ctx)
        ex_ante = self.get_ex_ante_te(ctx)
        if path.empty:
            return TrackingErrorHistory(window=window, series=(), ex_ante_te=ex_ante)
        rng = self._rng(f"expost:{ctx.account_id}:{window}")
        realised = path.to_numpy() * np.exp(rng.normal(0, 0.18, len(path)))
        min_periods = max(21, window // 4)
        rolled = (
            pd.Series(realised**2, index=path.index)
            .rolling(window, min_periods=min_periods)
            .mean()
            .pow(0.5)
            .dropna()
        )
        series = tuple(
            DatedValue(ts.date(), round(float(v), 5))
            for ts, v in zip(pd.DatetimeIndex(rolled.index), rolled.to_numpy(), strict=True)
        )
        return TrackingErrorHistory(window=window, series=series, ex_ante_te=ex_ante)

    def get_ex_ante_te(self, ctx: AccountContext) -> float | None:
        """Risk-model TE of current holdings vs target weights (never simulated)."""
        if ctx.target_model_id is None:
            return None
        te = self._holdings_te(ctx)
        return None if te is None else round(te, 5)

    # ------------------------------------------------------------------ tax
    def get_tax_history(self, ctx: AccountContext, granularity: Granularity) -> list[TaxPeriod]:
        keys = period_range(ctx.onboarding_date, ctx.as_of, granularity)
        acc = {k: [0.0] * 6 for k in keys}  # st, lt, losses, saved, st_loss, lt_loss
        for e in ctx.events:
            k = period_key(e.event_date, granularity)
            if k in acc:
                a = acc[k]
                a[0] += e.realized_st_gain
                a[1] += e.realized_lt_gain
                a[2] += e.losses_harvested
                a[3] += e.est_taxes_saved
                a[4] += e.realized_st_loss
                a[5] += e.realized_lt_loss
        out = []
        for k in keys:
            st, lt, losses, saved, st_loss, lt_loss = acc[k]
            paid = net_tax(st, lt, losses, ctx.st_rate, ctx.lt_rate) if ctx.taxable else 0.0
            out.append(
                TaxPeriod(
                    period=k,
                    realized_st_gain=round(st, 2),
                    realized_lt_gain=round(lt, 2),
                    losses_harvested=round(losses, 2),
                    est_tax_paid=round(paid, 2),
                    est_taxes_saved=round(saved, 2),
                    realized_st_loss=round(st_loss, 2),
                    realized_lt_loss=round(lt_loss, 2),
                )
            )
        return out

    # ------------------------------------------------------------------ AUM
    def get_aum_history(self, ctx: AccountContext) -> list[DatedValue]:
        shares = ctx.shares()
        start = pd.Timestamp(ctx.onboarding_date)
        px = self._prices.loc[self._prices.index >= start]
        if px.empty:
            px = self._prices.iloc[[-1]]
        if shares:
            tick = list(shares)
            q = np.array([shares[t] for t in tick])
            values = px[tick].to_numpy() @ q + ctx.cash
        else:
            values = np.full(len(px), ctx.cash)
        flows = [
            (pd.Timestamp(e.event_date), e.cash_flow_amount)
            for e in ctx.events
            if e.cash_flow_amount
        ]
        idx = px.index
        later = np.zeros(len(idx))
        for when, amt in flows:
            later[idx < when] += amt  # money that had not arrived yet (or not yet left)
        aum = np.clip(values - later, 0.0, None)
        return [DatedValue(ts.date(), round(float(v), 2)) for ts, v in zip(idx, aum, strict=True)]

    # ------------------------------------------------------------------ exposures
    def get_exposures(self, ctx: AccountContext) -> Exposures:
        u = self._universe
        direct, total = self._weights(ctx)
        # sector / security / factor views are on look-through stock weights (funds expanded)
        w = self.look_through(direct)
        tw = self.look_through(ctx.target_weights)
        has_target = bool(tw)
        cash_w = ctx.cash / total if total > 0 else 0.0

        sec_p: dict[str, float] = {}
        sec_t: dict[str, float] = {}
        for t, x in w.items():
            sec_p[str(u.at[t, "sector"])] = sec_p.get(str(u.at[t, "sector"]), 0.0) + x
        for t, x in tw.items():
            sec_t[str(u.at[t, "sector"])] = sec_t.get(str(u.at[t, "sector"]), 0.0) + x
        sectors = [
            SectorExposure(s, round(sec_p.get(s, 0.0), 6), round(sec_t.get(s, 0.0), 6))
            for s in sorted(set(sec_p) | set(sec_t))
        ]
        if total > 0:
            sectors.append(SectorExposure("Cash", round(cash_w, 6), 0.0))

        names = set(w) | set(tw)
        secs = sorted(
            (
                SecurityExposure(
                    t,
                    str(u.at[t, "name"]),
                    str(u.at[t, "sector"]),
                    round(w.get(t, 0.0), 6),
                    round(tw.get(t, 0.0), 6),
                )
                for t in names
            ),
            key=lambda s: -abs(s.active_weight),
        )[:10]

        invested = sum(direct.values())

        def score(weights: dict[str, float], col: str, normalise: bool) -> float:
            if not weights:
                return 0.0
            denom = sum(weights.values()) if normalise else 1.0
            src = self._size if col == "size" else u[col]
            return float(sum(x * float(src[t]) for t, x in weights.items()) / (denom or 1.0))

        factors = tuple(
            FactorExposure(f, round(score(w, f, True), 4), round(score(tw, f, True), 4))
            for f in FACTORS
        )
        wv = np.array(sorted(direct.values(), reverse=True))
        return Exposures(
            sectors=tuple(sectors),
            top_active=tuple(secs),
            factors=factors,
            top10_weight=round(float(wv[:10].sum()), 6) if len(wv) else 0.0,
            hhi=round(float((wv / invested) @ (wv / invested)), 6) if invested > 0 else 0.0,
            n_positions=len(direct),
            dividend_yield=round(score(w, "dividend_yield", False), 6),
            target_dividend_yield=round(score(tw, "dividend_yield", False), 6)
            if has_target
            else None,
            beta=round(score(w, "beta", False), 4),
            target_beta=round(score(tw, "beta", False), 4) if has_target else None,
        )

    # ------------------------------------------------------------------ models
    def _model_returns(self, model_id: str, weights: Mapping[str, float]) -> pd.Series:
        """Daily returns of the model held at constant weights (daily rebalanced)."""
        key = (model_id, tuple(sorted(weights.items())))
        if key not in self._model_ret_cache:
            weights = self.look_through(weights)
            tick = [t for t, w in weights.items() if w > 0]
            w = np.array([weights[t] for t in tick])
            rets = self.market.returns[tick].to_numpy() @ (w / w.sum())
            self._model_ret_cache[key] = pd.Series(rets, index=self.market.returns.index)
        return self._model_ret_cache[key]

    def get_model_stats(self, model_id: str, weights: Mapping[str, float]) -> ModelStats:
        r = self._model_returns(model_id, weights)
        u = self._universe
        growth = np.cumprod(1.0 + r.to_numpy())
        years = len(r) / 252
        ann = float(growth[-1] ** (1 / years) - 1)
        vol = float(r.std() * np.sqrt(252))
        mdd = float(np.max(1.0 - growth / np.maximum.accumulate(growth)))
        n_direct = sum(1 for w in weights.values() if w > 0)
        held = {t: w for t, w in self.look_through(weights).items() if w > 0}
        sectors: dict[str, float] = {}
        for t, w in held.items():
            sec = str(u.at[t, "sector"])
            sectors[sec] = sectors.get(sec, 0.0) + w

        def avg(col: str) -> float:
            src = self._size if col == "size" else u[col]
            return float(sum(w * float(src[t]) for t, w in held.items()))

        return ModelStats(
            model_id=model_id,
            annualized_return=round(ann, 5),
            volatility=round(vol, 5),
            sharpe=round((ann - RISK_FREE_RATE) / vol, 3) if vol > 0 else 0.0,
            max_drawdown=round(mdd, 5),
            dividend_yield=round(avg("dividend_yield"), 5),
            beta=round(avg("beta"), 4),
            n_holdings=n_direct,
            n_underlying=len(held),
            sector_mix={k: round(v, 6) for k, v in sorted(sectors.items())},
            factor_exposures={f: round(avg(f), 4) for f in FACTORS},
            history_start=pd.Timestamp(r.index[0]).date(),
            history_end=pd.Timestamp(r.index[-1]).date(),
        )

    def get_regime_performance(
        self, model_id: str, weights: Mapping[str, float], labels: Mapping[date, str]
    ) -> list[RegimePerformance]:
        r = self._model_returns(model_id, weights)
        lab = pd.Series({pd.Timestamp(d): v for d, v in labels.items()}).sort_index()
        # each trading day takes the most recent label on or before it (labels may be monthly)
        aligned = lab.reindex(r.index, method="ffill")
        out = []
        for regime in sorted({str(v) for v in lab.to_numpy()}):
            x = r[aligned == regime]
            if len(x) == 0:
                out.append(RegimePerformance(regime, 0, 0.0, 0.0))
                continue
            out.append(
                RegimePerformance(
                    regime=regime,
                    n_days=len(x),
                    annualized_return=round(float(x.mean() * 252), 5),
                    volatility=round(float(x.std(ddof=1) * np.sqrt(252)) if len(x) > 1 else 0.0, 5),
                )
            )
        return out
