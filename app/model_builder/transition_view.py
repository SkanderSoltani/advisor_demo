"""Three-portfolio analytics for a transition: the account today, the account after the proposed
trades, and the target model — each a full Model Builder report measured against the target."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

from pydantic import BaseModel

from app.model_builder.analytics import Benchmark, BuilderData, BuilderReport, analyze

KEYS = (("current", "Current"), ("transition", "Transition"), ("target", "Target"))


class TransitionAnalytics(BaseModel):
    target_model_id: str
    target_name: str
    te_ex_ante: dict[str, float]  # optimizer's ex-ante TE vs target: current / transition / target
    reports: dict[str, BuilderReport]  # current / transition / target

    model_config = {"populate_by_name": True}


_cache: OrderedDict[str, TransitionAnalytics] = OrderedDict()
_lock = threading.Lock()


def target_benchmark(model_id: str, name: str, weights: dict[str, float],
                     data: BuilderData) -> Benchmark:
    eq = sum(w for t, w in weights.items() if data.known(t)
             and data.asset_class(t) in ("US Equity", "Non-US Stocks"))
    return Benchmark(name=f"Target model · {name}", short="Target", equity_pct=round(eq * 100),
                     holdings=weights,
                     note=f"The transition's target model {model_id} — every portfolio is "
                          "measured against it.")


def transition_analytics(model_id: str, name: str, weights: dict[str, dict[str, float]],
                         te: dict[str, float], data: BuilderData) -> TransitionAnalytics:
    """Reports for the three portfolios (cached by their weights)."""
    key = hashlib.sha1(json.dumps([model_id, weights], sort_keys=True).encode()).hexdigest()
    with _lock:
        if key in _cache:
            return _cache[key]
    bench = target_benchmark(model_id, name, weights["target"], data)
    reports = {k: analyze(weights[k], label, data, benchmark=bench) for k, label in KEYS}
    out = TransitionAnalytics(target_model_id=model_id, target_name=name, te_ex_ante=te,
                              reports=reports)
    with _lock:
        _cache[key] = out
        while len(_cache) > 32:
            _cache.popitem(last=False)
    return out
