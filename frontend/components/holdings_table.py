"""Client page — Holdings: one row per ticker; click a ticker to see its lots (with Lot IDs).

Rows are built from the accounts' lots as returned by GET /accounts/{id} (nothing is computed
beyond summing lots by ticker), for one account or all of the client's accounts.
"""

from __future__ import annotations

from typing import Any

import dash_ag_grid as dag
from dash import dcc, html

from components.fold import fold_body, fold_button, fold_extra

COLUMNS = [
    {"field": "label", "headerName": "Ticker / Lot ID", "width": 130, "pinned": "left",
     "cellClass": {"function": "params.data.kind === 'ticker' ? 'ts-lot-label ts-lot-ticker'"
                               " : 'ts-lot-label ts-lot-sub'"},
     "tooltipValueGetter": {"function": "params.data.kind === 'ticker' ? "
                                        "'Click to show or hide lots' : null"}},
    {"field": "name", "headerName": "Name / account", "flex": 1.6, "minWidth": 170,
     "cellClass": {"function": "params.data.kind === 'ticker' ? '' : 'ts-c-ink600'"},
     "tooltipField": "name"},
    {"field": "lots_text", "headerName": "Lots", "width": 84, "cellClass": "ts-c-ink600"},
    {"field": "shares", "headerName": "Shares", "flex": 1, "minWidth": 96, "cellClass": "ts-num",
     "valueFormatter": {"function": "num(params.value, 3)"}},
    {"field": "price", "headerName": "Price", "flex": 1, "minWidth": 84, "cellClass": "ts-num",
     "valueFormatter": {"function": "params.value == null ? '' : '$' + params.value.toFixed(2)"}},
    {"field": "market_value", "headerName": "Market value", "flex": 1, "minWidth": 112,
     "cellClass": "ts-num ts-fw-500", "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "weight", "headerName": "Weight", "width": 84, "cellClass": "ts-num",
     "valueFormatter": {"function": "pct(params.value, 2)"}},
    {"field": "cost_basis", "headerName": "Cost basis", "flex": 1, "minWidth": 104,
     "cellClass": "ts-num", "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "unrealized_gain", "headerName": "Unrealized", "flex": 1, "minWidth": 110,
     "cellRenderer": "Signed"},
    {"field": "term", "headerName": "Term", "width": 76, "cellRenderer": "TermBadge"},
    {"field": "acquired_date", "headerName": "Acquired", "width": 108,
     "valueFormatter": {"function": "params.value || ''"}},
]


def holdings_rows(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Grid rows: tickers by market value (largest first), each followed by its lots if open."""
    if not state:
        return []
    lots, names, total = state["lots"], state["names"], state["total"] or 0.0
    expanded, show_account = set(state.get("expanded", [])), state.get("show_account", False)
    by: dict[str, list[dict[str, Any]]] = {}
    for x in lots:
        by.setdefault(x["ticker"], []).append(x)
    groups = sorted(by.items(), key=lambda kv: -sum(x["market_value"] for x in kv[1]))
    rows: list[dict[str, Any]] = []
    for tk, group in groups:
        group = sorted(group, key=lambda x: x["acquired_date"])
        mv = sum(x["market_value"] for x in group)
        cost = sum(x["cost_basis_total"] for x in group)
        terms = {x["holding_period"] for x in group}
        n_locked = sum(1 for x in group if x["locked"])
        is_open = tk in expanded
        rows.append({
            "row_id": f"t:{tk}", "kind": "ticker", "ticker": tk,
            "label": f"{'▾' if is_open else '▸'} {tk}",
            "name": names.get(tk, ""),
            "lots_text": f"{len(group)}" + (" 🔒" if n_locked else ""),
            "shares": sum(x["quantity"] for x in group),
            "price": group[0]["current_price"],
            "market_value": round(mv, 2),
            "weight": mv / total if total else None,
            "cost_basis": round(cost, 2),
            "unrealized_gain": round(mv - cost, 2),
            "term": terms.pop() if len(terms) == 1 else "Mixed",
            "acquired_date": None,
        })
        if is_open:
            for i, x in enumerate(group, 1):
                rows.append({
                    "row_id": f"l:{x['lot_id']}", "kind": "lot", "ticker": tk,
                    "label": x.get("lot_ref") or f"Lot {i}",
                    "name": x.get("account_label", "") if show_account else "",
                    "lots_text": "🔒" if x["locked"] else "",
                    "shares": x["quantity"],
                    "price": x["current_price"],
                    "market_value": x["market_value"],
                    "weight": x["market_value"] / total if total else None,
                    "cost_basis": x["cost_basis_total"],
                    "unrealized_gain": x["unrealized_gain"],
                    "term": x["holding_period"],
                    "acquired_date": x["acquired_date"],
                })
    return rows


def holdings_section() -> html.Section:
    return html.Section(
        [
            html.Div(
                [html.Div([html.H2("Holdings", className="ts-h2"),
                           html.P("Current positions. Click a ticker to see its tax lots.",
                                  id="cd-hold-sub", className="ts-sub ts-mt-1"),
                           html.Div(id="cd-hold-totals", className="ts-hold-totals ts-mt-2")]),
                 fold_button("cd-holdings", "holdings"), fold_extra("cd-holdings")],
                className="ts-section-head ts-row ts-between ts-items-start ts-gap-3",
            ),
            dcc.Store(id="cd-hold-state", data=None),
            fold_body("cd-holdings", dag.AgGrid(
                id="cd-holdings", rowData=[], columnDefs=COLUMNS,
                defaultColDef={"sortable": False, "suppressMovable": True},
                dashGridOptions={"rowHeight": 44, "headerHeight": 40, "domLayout": "autoHeight",
                                 "suppressCellFocus": True, "tooltipShowDelay": 400,
                                 "pagination": True, "paginationPageSize": 25,
                                 "paginationPageSizeSelector": False,
                                 "getRowId": {"function": "params.data.row_id"},
                                 "rowClassRules": {"ts-lot-child": "params.data.kind === 'lot'"},
                                 "localeText": {"noRowsToShow": "No holdings in this account."}},
                className="ts-grid ts-grid-compact", style={"width": "100%"},
            )),
        ],
        className="ts-card ts-overflow-hidden ts-mt-6",
    )
