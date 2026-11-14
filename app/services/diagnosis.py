"""Builds the inputs of the account diagnosis (holdings at today's prices, tax lots, rates,
benchmark) from the database and runs the checks. Results are cached until holdings change."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

from fastapi import HTTPException

from app.db import models as m
from app.model_builder.analytics import BuilderData
from app.model_builder.diagnosis import Diagnosis, LotIn, diagnose
from app.model_builder.transition_view import target_benchmark
from app.services.portfolio import PortfolioService

_cache: OrderedDict[str, Diagnosis] = OrderedDict()
_lock = threading.Lock()


class DiagnosisService:
    def __init__(self, ps: PortfolioService) -> None:
        self.ps = ps

    def _inputs(self, accounts: list[m.Account]) -> tuple[dict[str, float], list[LotIn], float,
                                                          float]:
        tickers = sorted({lot.ticker for a in accounts for lot in a.lots if lot.quantity > 0})
        px = self.ps.p.get_prices(tickers) if tickers else {}
        weights: dict[str, float] = {}
        lots: list[LotIn] = []
        st = lt = 0.0
        for a in accounts:
            ctx = self.ps.context(a)
            st, lt = ctx.st_rate, ctx.lt_rate
            for lot in a.lots:
                if lot.quantity <= 0:
                    continue
                mv = lot.quantity * float(px[lot.ticker])
                weights[lot.ticker] = weights.get(lot.ticker, 0.0) + mv
                lots.append(LotIn(lot.ticker, lot.quantity, lot.cost_basis_total, mv,
                                  lot.acquired_date, ctx.taxable, lot.basis_unknown))
            if a.cash > 0:
                weights["CASH"] = weights.get("CASH", 0.0) + a.cash
        return weights, lots, st, lt

    def run(self, accounts: list[m.Account], scope: str,
            target_model_id: str | None = None) -> Diagnosis:
        weights, lots, st, lt = self._inputs(accounts)
        if not weights:
            raise HTTPException(422, "No holdings to diagnose yet")
        key = hashlib.sha1(json.dumps(
            [scope, target_model_id, sorted((t, round(w, 2)) for t, w in weights.items()),
             len(lots), str(self.ps.as_of)]).encode()).hexdigest()
        with _lock:
            if key in _cache:
                return _cache[key]
        data = BuilderData.get(self.ps.p)
        bench = None
        if target_model_id:
            mp = self.ps.db.get(m.ModelPortfolio, target_model_id)
            tw = self.ps.model_weights(target_model_id)
            if tw:
                bench = target_benchmark(target_model_id, mp.name if mp else target_model_id,
                                         tw, data)
        total = sum(weights.values())
        d = diagnose({t: w / total for t, w in weights.items()}, lots, data, scope=scope,
                     as_of=self.ps.as_of, st_rate=st, lt_rate=lt,
                     taxable=any(x.taxable for x in lots), target=bench)
        with _lock:
            _cache[key] = d
            while len(_cache) > 64:
                _cache.popitem(last=False)
        return d

    def account(self, a: m.Account, target_model_id: str | None = None,
                use_target: bool = True) -> Diagnosis:
        """Against ``target_model_id`` (or the account's own target), else the auto blend."""
        tgt = target_model_id or (a.target_model_id if use_target else None)
        return self.run([a], a.id, tgt)

    def client(self, c: m.Client) -> Diagnosis:
        return self.run(list(c.accounts), "household")
