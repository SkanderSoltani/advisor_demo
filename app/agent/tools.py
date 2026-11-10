"""Tools available to the conversation (and to the LLM for question answering).

Every number the assistant shows comes from one of these calls. The engine calls the
state-changing tools itself (run_optimization, run_frontier, lock_lots); the LLM may call only
the read-only tools in :data:`READ_ONLY_TOOL_SPECS` to answer free-text questions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db import models as m
from app.schemas import transitions as st
from app.services.models import ModelService
from app.services.transitions import TransitionService


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


class AgentTools:
    def __init__(self, ts: TransitionService, t: m.Transition) -> None:
        self.ts = ts
        self.t = t
        self.ms = ModelService(ts.ps)

    @property
    def account(self) -> m.Account:
        return self.ts.account(self.t)

    # ------------------------------------------------------------------ read-only
    def get_account_summary(self) -> dict[str, Any]:
        a = self.account
        v = self.ts.ps.view(a)
        unreal = sum(lot.quantity * v.prices[lot.ticker] - lot.cost_basis_total for lot in a.lots)
        locked = set((self.t.data or {}).get("locks", []))
        locked_value = sum(
            lot.quantity * v.prices[lot.ticker] for lot in a.lots if lot.locked or lot.id in locked
        )
        return {
            "account_id": a.id,
            "account_type": a.account_type,
            "taxable": v.ctx.taxable,
            "market_value": _r(v.market_value),
            "cash": _r(a.cash),
            "n_positions": len({lot.ticker for lot in a.lots}),
            "n_lots": len(a.lots),
            "unrealized_gain": _r(unreal),
            "locked_value": _r(locked_value),
            "st_rate": _r(v.ctx.st_rate, 4),
            "lt_rate": _r(v.ctx.lt_rate, 4),
            "current_target_model_id": a.target_model_id,
        }

    def list_models(self, objective: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "model_id": mp.id,
                "name": mp.name,
                "objective": mp.objective,
                "construction": mp.construction,
                "target_yield": _r(mp.target_yield, 4),
                "expected_te_vs_benchmark": _r(mp.expected_te, 4),
                "fee_bps": mp.fee_bps,
            }
            for mp in self.ms.all_models()
            if objective is None or mp.objective == objective
        ]

    def compare_models(self, model_ids: list[str]) -> dict[str, Any]:
        ids = [i for i in dict.fromkeys(model_ids) if self.ms.get(i) is not None]
        if not ids:
            return {"error": "no known model ids"}
        payload = self.ms.compare(ids, self.account)
        return payload.model_dump(mode="json")

    def te_to_model(self, model_id: str) -> dict[str, Any]:
        cmp = self.compare_models([model_id])
        if "error" in cmp:
            return cmp
        c = cmp["comparisons"][0]
        return {"model_id": model_id, "te_from_current": c["te_from_current"]}

    def estimate_transition_tax(self, model_id: str) -> dict[str, Any]:
        cmp = self.compare_models([model_id])
        if "error" in cmp:
            return cmp
        ft = cmp["comparisons"][0]["full_transition"]
        return {"model_id": model_id, "full_transition": ft, "taxable": cmp["taxable"]}

    def explain_result(self) -> dict[str, Any]:
        opt = (self.t.data or {}).get("optimization")
        if not opt:
            return {"error": "no optimization has been run yet"}
        return {
            "te_before": opt["pre"]["te"],
            "te_after": opt["post"]["te"],
            "est_tax": opt["realized"]["est_tax"],
            "net_gain": opt["realized"]["net_gain"],
            "explanation": opt["diagnostics"]["explanation"],
            "binding_constraints": opt["diagnostics"]["binding_constraints"],
        }

    # ------------------------------------------------------------------ state-changing
    def run_optimization(
        self,
        budget_mode: str,
        budget_value: float | None,
        target_model_id: str,
        constraints: dict[str, Any] | None = None,
    ) -> st.OptimizationResult:
        req = st.OptimizeRequest(
            budget_mode=budget_mode,
            budget_value=budget_value,
            target_model_id=target_model_id,
            constraints=st.Constraints(**(constraints or {})),
        )
        return self.ts.optimize(self.t, req)

    def run_frontier(
        self, target_model_id: str, budget_mode: str, n_points: int = 12
    ) -> st.FrontierResult:
        mode = budget_mode if budget_mode in ("tax", "net_gain") else "tax"
        return self.ts.frontier(
            self.t,
            st.FrontierRequest(
                n_points=n_points,
                budget_mode=mode,
                target_model_id=target_model_id,
            ),
        )

    def lock_lots(self, tickers: list[str]) -> list[str]:
        """Lock every lot of the given tickers for this transition; returns the locked lot ids."""
        want = {t.upper() for t in tickers}
        ids = [lot.id for lot in self.account.lots if lot.ticker in want]
        existing = list((self.t.data or {}).get("locks", []))
        self.ts._save(self.t, locks=sorted(set(existing) | set(ids)))
        return ids

    # ------------------------------------------------------------------ LLM tool interface
    def read_only_dispatch(self) -> dict[str, Callable[..., Any]]:
        return {
            "get_account_summary": lambda **_: self.get_account_summary(),
            "list_models": lambda objective="any", **_: self.list_models(
                None if objective == "any" else objective
            ),
            "compare_models": lambda model_ids, **_: self.compare_models(list(model_ids)),
            "te_to_model": lambda model_id, **_: self.te_to_model(model_id),
            "estimate_transition_tax": lambda model_id, **_: self.estimate_transition_tax(model_id),
            "explain_result": lambda **_: self.explain_result(),
        }


def _tool(
    name: str, description: str, props: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        },
    }


READ_ONLY_TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "get_account_summary",
        "Market value, cash, positions, unrealized gain, locked value and tax rates of the "
        "account in this transition.",
        {},
        [],
    ),
    _tool(
        "list_models",
        "The target-model catalog, optionally filtered by objective.",
        {"objective": {"type": "string", "enum": ["income", "total_return", "any"]}},
        ["objective"],
    ),
    _tool(
        "compare_models",
        "Side-by-side stats for models, the tracking error from the current holdings to each, "
        "and the estimated tax of a full transition.",
        {"model_ids": {"type": "array", "items": {"type": "string"}}},
        ["model_ids"],
    ),
    _tool(
        "te_to_model",
        "Ex-ante tracking error from the current holdings to one model.",
        {"model_id": {"type": "string"}},
        ["model_id"],
    ),
    _tool(
        "estimate_transition_tax",
        "Estimated realized gains and tax to move fully into one model today.",
        {"model_id": {"type": "string"}},
        ["model_id"],
    ),
    _tool(
        "explain_result",
        "Why the last optimization's tracking error is not zero, with its key numbers.",
        {},
        [],
    ),
]
