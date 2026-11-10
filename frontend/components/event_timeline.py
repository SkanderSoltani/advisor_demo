"""Management history list (React "Management history" rows) + event drawer content."""

from __future__ import annotations

from datetime import date
from typing import Any

import dash_ag_grid as dag
from dash import html

from components.charts import EVENT_LABELS
from components.shell import icon
from services import format as fmt

EVENT_ICONS = {
    "transition": "arrow-left-right",
    "rebalance": "scale",
    "tax_loss_harvest": "scissors",
    "cash_flow": "banknote",
    "model_change": "replace",
}
TRIGGERS = {
    "scheduled": "Scheduled",
    "drift": "Drift",
    "harvest_opportunity": "Harvest opportunity",
    "client_request": "Client request",
}


def days_ago(iso: str, as_of: date | None = None) -> str:
    d = date.fromisoformat(iso[:10])
    n = ((as_of or date.today()) - d).days
    if n <= 0:
        return "Today"
    if n == 1:
        return "1 day ago"
    if n < 60:
        return f"{n} days ago"
    return f"{d:%b} {d.day}, {d:%Y}"


def event_row(e: dict[str, Any]) -> html.Button:
    label = EVENT_LABELS.get(e["type"], e["type"])
    meta = [days_ago(e["date"]), e.get("account_nickname") or e["account_id"],
            f"{e['n_trades']} trades", TRIGGERS.get(e["trigger"], e["trigger"]),
            f"TE {fmt.pct(e['te_before'])} → {fmt.pct(e['te_after'])}"]
    saved = e["est_taxes_saved"]
    return html.Button(
        [
            html.Div(
                [
                    html.Div(icon(EVENT_ICONS.get(e["type"], "calendar-days"), 16),
                             className=f"ts-evt-icon ts-evt-icon--{e['type']}"),
                    html.Div([html.P(label, className="ts-evt-title"),
                              html.P(" · ".join(meta), className="ts-evt-meta")]),
                ],
                className="ts-row ts-gap-3",
            ),
            html.Div(
                [html.P(fmt.signed_money(saved) if saved else "—",
                        className="ts-evt-amount" + (" ts-c-positive" if saved else "")),
                 html.P("Tax savings", className="ts-evt-meta")],
                className="ts-text-right",
            ),
        ],
        id={"type": "event-row", "id": e["id"]},
        n_clicks=0,
        type="button",
        className="ts-evt-row",
        title=e.get("note") or label,
    )


def drawer_body(e: dict[str, Any]) -> list[Any]:
    rows = [
        ("Date", e["date"]), ("Account", e.get("account_nickname") or e["account_id"]),
        ("Trigger", TRIGGERS.get(e["trigger"], e["trigger"])), ("Trades", str(e["n_trades"])),
        ("Turnover", fmt.pct(e["turnover"], 1)),
        ("Realized ST gain", fmt.money_full(e["realized_st_gain"])),
        ("Realized LT gain", fmt.money_full(e["realized_lt_gain"])),
        ("Losses harvested", fmt.money_full(e["losses_harvested"])),
        ("Taxes saved", fmt.money_full(e["est_taxes_saved"])),
        ("Tracking error", f"{fmt.pct(e['te_before'])} → {fmt.pct(e['te_after'])}"),
    ]
    if e.get("cash_flow_amount"):
        rows.insert(4, ("Cash flow", fmt.signed_money(e["cash_flow_amount"])))
    trades = e.get("trades") or []
    return [
        html.P(e.get("note") or "", className="ts-drawer-note"),
        html.Dl([x for k, v in rows for x in (html.Dt(k), html.Dd(v))], className="ts-dl"),
        html.H3(f"Trades ({len(trades)})", className="ts-h3 ts-mt-5 ts-mb-3"),
        dag.AgGrid(
            rowData=trades,
            columnDefs=[
                {"field": "side", "headerName": "Side", "width": 80,
                 "cellClass": {"function": "params.value === 'sell' ? 'ts-c-negative' : 'ts-c-positive'"},
                 "valueFormatter": {"function": "params.value.toUpperCase()"}},
                {"field": "ticker", "headerName": "Ticker", "width": 92, "cellClass": "ts-fw-500"},
                {"field": "shares", "headerName": "Shares", "flex": 1, "cellClass": "ts-num",
                 "valueFormatter": {"function": "num(params.value, 3)"}},
                {"field": "value", "headerName": "Value", "flex": 1, "cellClass": "ts-num",
                 "valueFormatter": {"function": "moneyFull(params.value)"}},
                {"field": "realized_gain", "headerName": "Gain", "flex": 1, "cellRenderer": "Signed"},
                {"field": "term", "headerName": "Term", "width": 76,
                 "valueFormatter": {"function": "dash(params.value)"}},
            ],
            defaultColDef={"sortable": True, "suppressMovable": True},
            dashGridOptions={"rowHeight": 40, "headerHeight": 36, "domLayout": "autoHeight",
                             "suppressCellFocus": True},
            className="ts-grid ts-grid--compact",
            style={"width": "100%"},
        ),
    ]
