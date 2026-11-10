"""Step 5 — Optimize transition: tax budget card + efficient frontier (React .8fr/1.2fr layout),
then lot locks. The frontier comes from POST /frontier (``extra``). Advanced constraints and the
glide path aren't exposed yet; the guided run uses the backend defaults (docs/backend_issues.md B5)."""

from __future__ import annotations

from typing import Any

import dash_ag_grid as dag
from dash import dcc, html

from components.canvas.common import arrow, header
from components.canvas.frontier import frontier_figure
from components.common import graph, sim_badge
from components.shell import icon
from services import format as fmt

LOCK_COLUMNS = [
    {"field": "locked", "headerName": "Lock", "width": 68, "cellDataType": "boolean",
     "editable": {"function": "!params.data.fixed"},
     "headerTooltip": "Locked lots are never sold. Lock a ticker to lock all of its lots."},
    {"field": "label", "headerName": "Ticker / Lot ID", "width": 112,
     "cellClass": {"function": "params.data.kind === 'ticker' ? 'ts-lot-label ts-lot-ticker'"
                               " : 'ts-lot-label ts-lot-sub'"},
     "tooltipValueGetter": {"function": "params.data.kind === 'ticker' ? "
                                        "'Click to show or hide lots' : null"}},
    {"field": "lots_text", "headerName": "Lots", "width": 100, "cellClass": "ts-c-ink600"},
    {"field": "quantity", "headerName": "Shares", "flex": 1, "minWidth": 80, "cellClass": "ts-num",
     "valueFormatter": {"function": "num(params.value, 3)"}},
    {"field": "acquired_date", "headerName": "Acquired", "flex": 1, "minWidth": 96},
    {"field": "holding_period", "headerName": "Term", "width": 66, "cellRenderer": "TermBadge"},
    {"field": "cost_basis_total", "headerName": "Cost basis", "flex": 1, "minWidth": 88,
     "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "market_value", "headerName": "Market value", "flex": 1, "minWidth": 96,
     "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "unrealized_gain", "headerName": "Unrealized", "flex": 1, "minWidth": 104,
     "cellRenderer": "Signed"},
]


def lock_rows(lots: list[dict[str, Any]], expanded: list[str]) -> list[dict[str, Any]]:
    """Grid rows for the lock table: one row per ticker (totals, lock-all checkbox), followed by
    its lots when the ticker is expanded. A ticker shows as locked only when all its lots are."""
    by: dict[str, list[dict[str, Any]]] = {}
    for lot in lots:
        by.setdefault(lot["ticker"], []).append(lot)
    rows: list[dict[str, Any]] = []
    for tk in sorted(by):
        group = sorted(by[tk], key=lambda x: x["acquired_date"])
        n, n_locked, is_open = len(group), sum(1 for x in group if x["locked"]), tk in expanded
        terms = {x["holding_period"] for x in group}

        rows.append({
            "row_id": f"t:{tk}", "kind": "ticker", "ticker": tk,
            "label": f"{'▾' if is_open else '▸'} {tk}",
            "lots_text": f"{n_locked} of {n} locked" if 0 < n_locked < n
                         else f"{n} lot{'s' if n != 1 else ''}",
            "locked": n_locked == n, "fixed": all(x.get("account_locked") for x in group),
            "quantity": sum(x["quantity"] for x in group), "acquired_date": None,
            "holding_period": terms.pop() if len(terms) == 1 else "Mixed",
            "cost_basis_total": sum(x["cost_basis_total"] for x in group),
            "market_value": sum(x["market_value"] for x in group),
            "unrealized_gain": sum(x["unrealized_gain"] for x in group),
        })
        if is_open:
            rows += [{**x, "row_id": x["lot_id"], "kind": "lot",
                      "label": x.get("lot_ref") or f"Lot {i}",
                      "lots_text": "", "fixed": bool(x.get("account_locked"))}
                     for i, x in enumerate(group, 1)]
    return rows


def budget_default(full_tax: float, setup: dict[str, Any]) -> int:
    if setup.get("budget_mode") == "tax" and setup.get("budget_value") is not None:
        return int(setup["budget_value"])
    return int(round(full_tax * 0.25 / 1000) * 1000)


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    d = turn["ui_payload"]["data"]
    full = d["full_transition"]
    full_tax = max(float(full["est_tax"]), 0.0)
    slider_max = max(int(-(-full_tax // 1000) * 1000), 1000)
    value = min(budget_default(full_tax, d.get("setup") or {}), slider_max)
    acct = d["account"]
    locked = set(d.get("locked_lot_ids") or [])
    lots = [{**lot, "locked": lot["locked"] or lot["lot_id"] in locked} for lot in extra.get("lots", [])]
    fr = extra.get("frontier")

    budget_card = html.Div(
        [
            html.Div([html.H2("Max tax cost", className="ts-h2"), icon("sliders-horizontal", 17, "ts-c-ink")],
                     className="ts-row ts-between"),
            html.P(fmt.money_full(value), id={"type": "ws-budget-label", "id": "c"},
                   className="ts-budget-value"),
            dcc.Slider(id={"type": "ws-budget", "id": "c"}, min=0, max=slider_max,
                       step=max(slider_max // 100, 100), value=value, marks=None,
                       tooltip=None, updatemode="drag", className="ts-range"),
            html.Div([html.Span("$0"), html.Span(f"Full transition {fmt.money(full_tax)}")],
                     className="ts-range-ends"),
            html.Div("A higher budget lowers expected tracking error and enables more tax-aware trades."
                     if acct.get("taxable", True) else
                     "This account is tax-deferred, so trades carry no tax cost — the optimizer "
                     "moves fully to the model.", className="ts-hint ts-mt-8"),
            html.Button(arrow("Run optimization "), id={"type": "ws-run", "id": "c"}, n_clicks=0,
                        type="button", className="ts-btn-cta ts-btn-block ts-mt-6"),
            html.Button("No limit (full transition)", id={"type": "ws-act", "id": "budget:none"},
                        n_clicks=0, type="button", className="ts-btn-plain ts-btn-block ts-mt-2"),
        ],
        className="ts-card ts-p-5",
    )
    frontier_card = html.Div(
        [
            html.Div([html.H2("Efficient frontier", className="ts-h2"),
                      sim_badge(fr.get("data_source")) if fr else None],
                     className="ts-row ts-gap-2"),
            (graph(frontier_figure(fr, selected_budget=value), 256, id_={"type": "ws-frontier", "id": "c"},
                   cls="ts-mt-6")
             if fr and fr.get("points") else
             html.Div("The frontier appears once tax lots are loaded.", className="ts-empty ts-mt-6")),
            html.Div([html.Span("Lower tax cost"), html.Span("Higher tax cost")], className="ts-range-ends"),
            html.P("Click a point to optimize at that budget.", className="ts-sub ts-mt-2"),
        ],
        className="ts-card ts-p-5",
    )
    summary = html.Div(
        [
            html.Div([html.P("Account value", className="ts-kpi-label"),
                      html.P(fmt.money(acct["market_value"]), className="ts-stat-value")],
                     className="ts-stat"),
            html.Div([html.P("Unrealized gain", className="ts-kpi-label"),
                      html.P(fmt.signed_money(acct.get("unrealized_gain", 0)), className="ts-stat-value")],
                     className="ts-stat"),
            html.Div([html.P("Tax to fully transition", className="ts-kpi-label"),
                      html.P(fmt.money_full(full_tax), className="ts-stat-value")], className="ts-stat"),
            html.Div([html.P("TE after full transition", className="ts-kpi-label",
                             title="Non-zero when locked lots stay above target"),
                      html.P(fmt.pct(full["post_te"]), className="ts-stat-value")], className="ts-stat"),
        ],
        className="ts-stat-grid ts-stat-grid--4 ts-mt-6",
    )
    lock_card = html.Div(
        [
            html.Div([html.H2("Lock lots", className="ts-h2"),
                      html.Span(f"{len([x for x in lots if x['locked']])} locked",
                                id={"type": "ws-lock-count", "id": "c"}, className="ts-badge")],
                     className="ts-row ts-gap-2 ts-section-head"),
            html.P("Click a ticker to see its lots. Lock a ticker to keep all of its lots, or "
                   "lock individual lots.", className="ts-sub ts-lock-hint"),
            dag.AgGrid(
                id={"type": "ws-lock-grid", "id": "c"}, rowData=lock_rows(lots, []),
                columnDefs=LOCK_COLUMNS,
                defaultColDef={"sortable": False, "suppressMovable": True},
                dashGridOptions={"rowHeight": 48, "headerHeight": 40, "domLayout": "autoHeight",
                                 "singleClickEdit": True, "tooltipShowDelay": 400,
                                 "pagination": len({x["ticker"] for x in lots}) > 12,
                                 "paginationPageSize": 12, "paginationPageSizeSelector": False,
                                 "getRowId": {"function": "params.data.row_id"},
                                 "rowClassRules": {"ts-lot-child": "params.data.kind === 'lot'"},
                                 "localeText": {"noRowsToShow": "No lots in this account"}},
                className="ts-grid ts-grid-compact", style={"width": "100%"},
            ),
            dcc.Store(id={"type": "ws-lock-state", "id": "c"},
                      data={"lots": lots, "expanded": []}),
        ],
        className="ts-card ts-overflow-hidden ts-mt-6",
    ) if lots else None

    return [
        header(turn["state"], "Optimize transition",
               "Tune the tax budget and choose the solution that fits best."),
        html.Div([budget_card, frontier_card], className="ts-opt-grid"),
        summary,
        lock_card,
        dcc.Store(id={"type": "ws-full-tax", "id": "c"}, data=full_tax),
    ]
