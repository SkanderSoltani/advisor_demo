"""Step 2 — Review lots: editable parse preview (rows with issues highlighted and editable)."""

from __future__ import annotations

from typing import Any

import dash_ag_grid as dag
from dash import dcc, html

from components.canvas.common import arrow, header, reply_actions, stat
from services import format as fmt

COLUMNS = [
    {"field": "include", "headerName": "", "width": 56, "editable": True, "cellDataType": "boolean",
     "headerTooltip": "Include this row"},
    {"field": "lot_ref", "headerName": "Lot ID", "width": 112, "cellClass": "ts-c-ink600",
     "editable": {"function": "params.data.issues.length > 0"},
     "valueFormatter": {"function": "params.value || 'New'"},
     "headerTooltip": "Lot ID from the statement; lots without one get a new ID when confirmed"},
    {"field": "ticker", "headerName": "Ticker", "width": 96, "cellClass": "ts-fw-600 ts-c-navy",
     "editable": {"function": "params.data.issues.length > 0"}},
    {"field": "quantity", "headerName": "Shares", "flex": 1, "minWidth": 80, "cellClass": "ts-num",
     "editable": {"function": "params.data.issues.length > 0"},
     "valueFormatter": {"function": "num(params.value, 3)"}, "cellDataType": "number"},
    {"field": "acquired_date", "headerName": "Acquired", "flex": 1, "minWidth": 96,
     "editable": {"function": "params.data.issues.length > 0"},
     "valueFormatter": {"function": "dash(params.value)"}, "cellDataType": "text"},
    {"field": "holding_period", "headerName": "Term", "width": 76, "cellRenderer": "TermBadge"},
    {"field": "cost_basis_total", "headerName": "Cost basis", "flex": 1, "minWidth": 96,
     "cellClass": "ts-num", "editable": {"function": "params.data.issues.length > 0"},
     "valueFormatter": {"function": "moneyFull(params.value)"}, "cellDataType": "number"},
    {"field": "unrealized_gain", "headerName": "Unrealized", "flex": 1, "minWidth": 96,
     "cellRenderer": "Signed"},
    {"field": "issue_text", "headerName": "Issues", "flex": 1.6, "minWidth": 150,
     "cellClass": "ts-issue-cell", "tooltipField": "issue_text"},
]


WARN_ROW = "!params.data.has_error && params.data.issues.length > 0"


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    pv = turn["ui_payload"]["data"]
    sm = pv["summary"]
    rows = []
    for r in pv["rows"]:
        msgs = [i["message"] for i in r["issues"]]
        rows.append({**r, "issue_text": " · ".join(msgs),
                     "has_error": any(i["severity"] == "error" for i in r["issues"])})
    via = {"table": "statement tables", "plaid": "Plaid", "llm": "extraction pass"}[pv["method"]]
    confirm = html.Button(arrow("Confirm holdings "), id={"type": "ws-confirm", "id": "c"}, n_clicks=0,
                          type="button", className="ts-btn-cta")
    assume = None
    if pv["requires_basis_decision"]:
        assume = dcc.Checklist(
            id={"type": "ws-assume", "id": "c"},
            options=[{"label": " Accept an average-cost assumption for lots without basis or dates",
                      "value": "yes"}],
            value=[], className="ts-check-line ts-mb-4")
    return [
        header(turn["state"], "Review lots", "Confirm positions before selecting a target model.",
               confirm),
        html.Div([stat("Lots imported", fmt.number(sm["n_rows"])),
                  stat("Portfolio value", fmt.money(sm["total_market_value"])),
                  stat("Issues remaining", fmt.number(sm["n_error_rows"]),
                       "warning" if sm["n_error_rows"] else "navy")],
                 className="ts-stat-grid ts-mb-4"),
        html.P(f"Read via {via} · confidence {pv['confidence']:.0%}"
               + (f" · cash detected {fmt.money_full(pv['cash_detected'])}"
                  if pv.get("cash_detected") else ""),
               className="ts-sub ts-mb-3"),
        assume,
        html.Div(id={"type": "ws-confirm-error", "id": "c"}),
        html.Div(
            dag.AgGrid(
                id={"type": "ws-preview-grid", "id": "c"},
                rowData=rows, columnDefs=COLUMNS,
                defaultColDef={"sortable": True, "suppressMovable": True, "resizable": True},
                dashGridOptions={"rowHeight": 54, "headerHeight": 40, "domLayout": "autoHeight",
                                 "singleClickEdit": True, "stopEditingWhenCellsLoseFocus": True,
                                 "tooltipShowDelay": 200,
                                 "getRowId": {"function": "String(params.data.row_id)"},
                                 "rowClassRules": {"ts-row-error": "params.data.has_error",
                                                   "ts-row-warn": WARN_ROW}},
                className="ts-grid", style={"width": "100%"},
            ),
            className="ts-card ts-overflow-hidden",
        ),
        reply_actions(turn, skip={"confirm"}),
    ]
