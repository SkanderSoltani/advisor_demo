"""Write the JSON target-model catalog into the database (products → securities, models)."""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models as m
from app.db.catalog import EQUITY_CLASSES, CatalogFile, FundProxies, universe_arrays
from app.db.synthetic_market import SyntheticMarket
from app.domain import model_construction as mc

log = get_logger("catalog")


def sync_catalog(
    session: Session, catalog: CatalogFile, market: SyntheticMarket, funds: FundProxies
) -> list[str]:
    """Upsert products and models from ``catalog``. Returns the model ids now in the catalog.

    Models that left the JSON are deleted unless an account still targets them (then kept, with
    a warning, so the account keeps working until it is moved).

    Multi-asset models (equity plus bonds / cash) are measured against a blended benchmark:
    the equity share in the category's equity index and the rest in the aggregate bond product
    (SCHZ) when the catalog has it.
    """
    u = market.universe
    ua = universe_arrays(market)
    tickers = list(u.index)
    cov = mc.shrunk_sample_covariance(market.returns.iloc[-504:].to_numpy())
    benches = mc.build_benchmarks(ua)

    def lt_vec(weights: dict[str, float]) -> list[float]:
        lt = funds.look_through(weights)
        return [lt.get(t, 0.0) for t in tickers]

    # ---------------------------------------------------------------- products as securities
    dy = u["dividend_yield"].to_numpy(dtype=float)
    yields: dict[str, float] = {}
    for p in catalog.products:
        w = funds.weights.loc[p.ticker].to_numpy(dtype=float)
        exposure = float(w.sum())
        yields[p.ticker] = (
            float(p.yield_) if p.yield_ is not None
            else float(w @ dy) / exposure if exposure > 0 else 0.0
        )
        sec = session.get(m.Security, p.ticker) or m.Security(ticker=p.ticker)
        sec.name = p.name
        sec.sector = "Fund"
        sec.security_type = "fund"
        sec.issuer = p.issuer
        sec.asset_class = p.asset_class
        sec.expense_ratio_bps = p.expense_ratio_bps
        sec.market_cap = 0.0
        sec.dividend_yield = yields[p.ticker]
        sec.value_score = float(w @ u["value"].to_numpy(dtype=float))
        sec.quality_score = float(w @ u["quality"].to_numpy(dtype=float))
        sec.profitability_score = float(w @ u["profitability"].to_numpy(dtype=float))
        sec.momentum_score = float(w @ u["momentum"].to_numpy(dtype=float))
        sec.beta = float(w @ u["beta"].to_numpy(dtype=float))
        sec.last_price = float(funds.nav[p.ticker].iloc[-1])
        session.add(sec)
        if funds.rules[p.ticker] != p.proxy:
            log.warning("unknown proxy rule; using fallback", ticker=p.ticker, rule=p.proxy)
    session.flush()

    # ---------------------------------------------------------------- models
    ids = []
    for spec in catalog.models:
        weights = {h.ticker: h.weight for h in spec.holdings}
        lt = np.array(lt_vec(weights))
        code = spec.benchmark.split()[0] if spec.benchmark else ""
        bench = benches.get(code, benches[mc.TR_BENCHMARK])
        eq = sum(h.weight for h in spec.holdings
                 if catalog.asset_class(h.ticker) in EQUITY_CLASSES)
        if eq < 0.999:
            bonds = np.array(lt_vec({"SCHZ": 1.0})) if "SCHZ" in funds.rows else 0.0
            bench = eq * bench + (1.0 - eq) * bonds
        er = sum(h.weight * catalog.expense_ratio_bps(h.ticker) for h in spec.holdings)
        mp = session.get(m.ModelPortfolio, spec.id) or m.ModelPortfolio(id=spec.id)
        mp.name = spec.name
        mp.provider = spec.provider
        mp.objective = spec.objective
        mp.construction = spec.construction
        mp.benchmark = spec.benchmark
        mp.description = spec.description
        mp.rationale = spec.rationale
        stock_y = u["dividend_yield"]
        mp.target_yield = round(sum(
            h.weight * (yields[h.ticker] if h.ticker in yields
                        else float(stock_y.get(h.ticker, 0.0)))
            for h in spec.holdings), 5)
        mp.expected_te = round(mc.tracking_error(lt, bench, cov), 5)
        mp.advisory_fee_bps = spec.advisory_fee_bps
        mp.fee_bps = round(er + spec.advisory_fee_bps, 2)
        mp.regime_overlay = spec.regime_overlay
        session.add(mp)
        session.flush()
        mp.holdings.clear()
        session.flush()
        mp.holdings.extend(m.ModelHolding(ticker=h.ticker, weight=h.weight) for h in spec.holdings)
        ids.append(spec.id)

    keep = set(ids)
    for old in session.scalars(select(m.ModelPortfolio).where(m.ModelPortfolio.id.not_in(keep))):
        used = session.scalar(select(m.Account.id).where(m.Account.target_model_id == old.id))
        if used:
            log.warning("model removed from catalog but still targeted", model_id=old.id)
        else:
            session.delete(old)
    session.commit()
    return ids
