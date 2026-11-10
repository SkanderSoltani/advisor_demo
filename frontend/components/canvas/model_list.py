"""Step 3 — choose a target from the catalog (React step 3 cards). Also the confirm step."""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from components.canvas.common import act, arrow, header, reply_actions
from components.shell import icon
from services import format as fmt

OBJECTIVES = {"income": "Income", "total_return": "Total return"}
CONSTRUCTIONS = {"market_cap": "Market cap", "market_cap_fundamental": "Market cap + fundamental",
                 "market_cap_fundamental_active": "Market cap + fundamental + active"}


def card(m: dict[str, Any], selected: bool = False, clickable: bool = True) -> Any:
    body = [
        html.P(m["model_id"], className="ts-model-id"),
        html.P(m["name"], className="ts-model-name"),
        html.P(OBJECTIVES.get(m["objective"], m["objective"]), className="ts-sub-sm ts-mt-2"),
        html.P(CONSTRUCTIONS.get(m["construction"], m["construction"]), className="ts-sub ts-mt-5"),
        html.Div([html.Span(f"{fmt.pct(m['fee_bps'] / 10000)} fee", className="ts-model-fee"),
                  html.Span(f"Yield {fmt.pct(m['target_yield'])}", className="ts-sub")],
                 className="ts-row ts-between ts-mt-4"),
    ]
    cls = "ts-model-card" + (" is-selected" if selected else "")
    if not clickable:
        return html.Div(body, className=cls)
    return html.Button(body, id={"type": "ws-act", "id": f"choose:{m['model_id']}"}, n_clicks=0,
                       type="button", className=cls,
                       title=f"Expected TE vs benchmark {fmt.pct(m['expected_te_vs_benchmark'])}")


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    models = turn["ui_payload"]["data"].get("models", [])
    if turn["state"] == "TARGET_CONFIRM":
        m = models[0] if models else None
        return [
            header(turn["state"], "Confirm target", "Use this model as the account's target?"),
            html.Div(card(m, selected=True, clickable=False), className="ts-model-grid") if m else None,
            html.Div([act("yes", arrow("Select this model "), primary=True),
                      act("no", "Choose another")], className="ts-canvas-actions"),
        ]
    search = dcc.Input(id={"type": "ws-model-search", "id": "c"}, type="search",
                       placeholder="Search models", debounce=False, className="ts-search")
    return [
        header(turn["state"], "Choose your target",
               "Select a model aligned to this client's objective."),
        html.Label([icon("search", 16, "ts-search-icon"), search],
                   className="ts-search-wrap ts-search-wide ts-mb-4"),
        html.Div([card(m) for m in models], id={"type": "ws-model-grid", "id": "c"},
                 className="ts-model-grid"),
        reply_actions(turn, skip={f"choose:{m['model_id']}" for m in models}),
    ]
