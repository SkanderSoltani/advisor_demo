"""Step 4 — Compare models: cards + metrics table (React's Metric/Current/Model layout) + charts."""

from __future__ import annotations

from typing import Any

import dash_ag_grid as dag
import plotly.graph_objects as go
from dash import html

from components.canvas.common import arrow, header
from components.canvas.model_list import CONSTRUCTIONS, OBJECTIVES
from components.common import graph, sim_badge
from services import format as fmt
from theme import tokens as t

METRICS: list[tuple[str, str, Any, str | None]] = [
    # (label, key, formatter, tooltip)
    ("Annualized return", "stats.annualized_return", fmt.pct, "Backtested annual return (synthetic history)"),
    ("Volatility", "stats.volatility", fmt.pct, "Annualized standard deviation of returns"),
    ("Sharpe ratio", "stats.sharpe", lambda v: fmt.number(v, 2), "Excess return per unit of volatility"),
    ("Max drawdown", "stats.max_drawdown", lambda v: f"-{fmt.pct(v)}", "Largest peak-to-trough loss"),
    ("Dividend yield", "stats.dividend_yield", fmt.pct, None),
    ("Holdings", "stats.n_holdings", fmt.number, "Products held (look-through stocks in tooltip)"),
    ("Expected TE vs benchmark", "expected_te", fmt.pct, "Ex-ante tracking error to the model's benchmark"),
    ("Fee", "fee_bps", lambda v: fmt.pct(v / 10000), "Weighted product expense ratio + advisory fee"),
    ("TE from current portfolio", "te_from_current", fmt.pct,
     "Ex-ante tracking error from today's holdings to this model"),
    ("Est. tax to fully transition", "full_transition.est_tax", fmt.money_full,
     "Estimated tax to move fully into the model today"),
]
HIGHLIGHT = {"TE from current portfolio", "Est. tax to fully transition"}


def _get(d: dict[str, Any], path: str) -> Any:
    for k in path.split("."):
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    cmp = turn["ui_payload"]["data"]
    comps = cmp["comparisons"]
    cur = cmp["current"]
    cards = []
    for c in comps:
        m = c["model"]
        cards.append(html.Div(
            [
                html.Div([html.P(m["id"], className="ts-model-id"),
                          html.Span(CONSTRUCTIONS.get(m["construction"], m["construction"]),
                                    className="ts-badge")], className="ts-row ts-between ts-gap-2"),
                html.P(m["name"], className="ts-model-name"),
                html.P(OBJECTIVES.get(m["objective"], m["objective"]), className="ts-sub-sm ts-mt-2"),
                html.P(f"{fmt.pct(m['fee_bps'] / 10000)} fee", className="ts-model-fee ts-mt-4"),
                html.Button(arrow("Select this model "), id={"type": "ws-select-model", "id": m["id"]},
                            n_clicks=0, type="button", className="ts-btn-cta ts-mt-5 ts-w-full"),
            ],
            className="ts-model-card",
        ))
    rows = []
    for label, key, f, tip in METRICS:
        row = {"metric": label, "tip": tip, "hl": label in HIGHLIGHT,
               "current": {"Dividend yield": fmt.pct(cur["dividend_yield"]),
                           "Holdings": fmt.number(cur["n_positions"])}.get(label, "—")}
        for c in comps:
            src = c if key in ("te_from_current",) or key.startswith("full_transition") else c["model"]
            v = _get(src, key)
            row[c["model"]["id"]] = "—" if v is None else f(v)
        rows.append(row)
    cols = [{"field": "metric", "headerName": "Metric", "flex": 1.6, "cellClass": "ts-fw-500 ts-c-navy",
             "tooltipField": "tip"},
            {"field": "current", "headerName": "Current", "flex": 1, "cellClass": "ts-num"}]
    cols += [{"field": c["model"]["id"], "headerName": c["model"]["id"], "flex": 1, "cellClass": "ts-num"}
             for c in comps]

    # sector mix (stacked bars) + factor exposures (grouped bars) — values straight from the API
    sectors = sorted({s for c in comps for s in c["model"]["stats"]["sector_mix"]})
    fig_sec = go.Figure()
    for i, s in enumerate(sectors):
        fig_sec.add_bar(y=[c["model"]["id"] for c in comps], x=[c["model"]["stats"]["sector_mix"].get(s, 0)
                                                                for c in comps],
                        name=s, orientation="h", marker_color=t.COLORWAY[i % len(t.COLORWAY)],
                        marker_opacity=1 - 0.12 * (i // len(t.COLORWAY)),
                        hovertemplate=f"{s}: %{{x:.1%}}<extra></extra>")
    fig_sec.update_layout(barmode="stack", showlegend=False, bargap=0.45,
                          margin={"l": 104, "r": 8, "t": 8, "b": 28},
                          xaxis={"tickformat": ".0%", "showgrid": False}, hovermode="closest")
    factors = ["value", "quality", "momentum", "size"]
    fig_fac = go.Figure()
    for i, c in enumerate(comps):
        fe = c["model"]["stats"]["factor_exposures"]
        fig_fac.add_bar(x=[f.capitalize() for f in factors], y=[fe.get(f, 0) for f in factors],
                        name=c["model"]["id"], marker_color=t.COLORWAY[i % len(t.COLORWAY)],
                        hovertemplate=c["model"]["id"] + " %{x}: %{y:.2f}<extra></extra>")
    fig_fac.update_layout(barmode="group", margin={"l": 36, "r": 8, "t": 24, "b": 24}, hovermode="closest")

    return [
        header(turn["state"], "Compare models", "See the trade-offs before optimizing the transition."),
        html.Div(cards, className=f"ts-model-grid ts-model-grid--{min(len(cards), 3)}"),
        html.Div(
            [
                html.Div([html.H2("Key metrics", className="ts-h2"), sim_badge(cmp.get("data_source"))],
                         className="ts-row ts-gap-2 ts-section-head"),
                dag.AgGrid(rowData=rows, columnDefs=cols,
                           defaultColDef={"sortable": False, "suppressMovable": True},
                           dashGridOptions={"rowHeight": 52, "headerHeight": 48, "domLayout": "autoHeight",
                                            "suppressCellFocus": True, "tooltipShowDelay": 200,
                                            "rowClassRules": {"ts-row-highlight": "params.data.hl"}},
                           className="ts-grid", style={"width": "100%"}),
            ],
            className="ts-card ts-overflow-hidden ts-mt-6",
        ),
        html.Div(
            [
                html.Div([html.H2("Sector mix", className="ts-h2"),
                          graph(fig_sec, 220, cls="ts-mt-3")], className="ts-card ts-p-5"),
                html.Div([html.H2("Factor exposure", className="ts-h2"),
                          graph(fig_fac, 220, cls="ts-mt-3")], className="ts-card ts-p-5"),
            ],
            className="ts-two-col ts-mt-6",
        ),
        html.P(cmp.get("disclaimer", ""), className="ts-disclaimer"),
    ]
