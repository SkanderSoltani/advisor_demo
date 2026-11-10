"""Results (step 5 after optimize) and Review & export (step 6 / done) — React step 6 layout:
four stat cards, Approve / Download CSV / Download PDF, disclaimer; plus trades, frontier, glide path."""

from __future__ import annotations

from typing import Any

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html

from components.canvas.common import DISCLAIMER, act, header
from components.canvas.frontier import frontier_figure
from components.common import graph, sim_badge
from components.shell import icon
from services import format as fmt

SELL_COLUMNS = [
    {"field": "ticker", "headerName": "Ticker", "width": 100, "cellClass": "ts-fw-600 ts-c-navy"},
    {"field": "lot_ref", "headerName": "Lot ID", "width": 112, "cellClass": "ts-c-ink600",
     "valueFormatter": {"function": "params.value || params.data.lot_id"}},
    {"field": "shares", "headerName": "Shares", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "num(params.value, 3)"}},
    {"field": "proceeds", "headerName": "Proceeds", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "cost_basis", "headerName": "Cost basis", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "realized_gain", "headerName": "Realized", "flex": 1, "cellRenderer": "Signed"},
    {"field": "term", "headerName": "Term", "width": 76, "cellRenderer": "TermBadge"},
    {"field": "acquired_date", "headerName": "Acquired", "flex": 1},
]
BUY_COLUMNS = [
    {"field": "ticker", "headerName": "Ticker", "width": 100, "cellClass": "ts-fw-600 ts-c-navy"},
    {"field": "shares", "headerName": "Shares", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "num(params.value, 3)"}},
    {"field": "price", "headerName": "Price", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "value", "headerName": "Value", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
]
GLIDE_COLUMNS = [
    {"field": "year", "headerName": "Year", "width": 90},
    {"field": "budget", "headerName": "Budget", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "est_tax", "headerName": "Est. tax", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "te_after", "headerName": "TE after", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "pct(params.value, 2)"}},
    {"field": "n_trades", "headerName": "Trades", "width": 100, "cellClass": "ts-num"},
]


def _grid(rows: list[dict[str, Any]], cols: list[dict[str, Any]], empty: str) -> dag.AgGrid:
    return dag.AgGrid(rowData=rows, columnDefs=cols,
                      defaultColDef={"sortable": True, "suppressMovable": True},
                      dashGridOptions={"rowHeight": 44, "headerHeight": 40, "domLayout": "autoHeight",
                                       "suppressCellFocus": True, "pagination": len(rows) > 10,
                                       "paginationPageSize": 10, "paginationPageSizeSelector": False,
                                       "localeText": {"noRowsToShow": empty}},
                      className="ts-grid", style={"width": "100%"})


def _card(label: str, value: Any, tip: str | None = None, tone: str = "navy") -> html.Div:
    return html.Div([html.P(label, className="ts-kpi-label", title=tip),
                     html.P(value, className=f"ts-review-value ts-tone-{tone}")], className="ts-review-card")


def _gains_losses_card(r: dict[str, Any]) -> html.Div:
    """Realized ST/LT gains and losses from the solution's lot sales, with the estimated tax cost
    (dollars, after ST/LT netting) as its own line."""
    def row(label: str, value: str, tone: str) -> html.Div:
        return html.Div([html.Span(label), html.Span(value, className=f"ts-tone-{tone}")],
                        className="ts-gl-row")
    return html.Div(
        [html.P("Realized gains & losses", className="ts-kpi-label",
                title="From the lot sales in this solution"),
         html.Div([row("ST gains", fmt.money_full(r["st_gain"]), "navy"),
                   row("ST losses", fmt.money_full(-abs(r["st_loss"])), "navy"),
                   row("LT gains", fmt.money_full(r["lt_gain"]), "navy"),
                   row("LT losses", fmt.money_full(-abs(r["lt_loss"])), "navy")],
                  className="ts-gl-rows"),
         html.Div([html.Span("Est. tax cost", title="After ST/LT netting at the household's rates"),
                   html.Span(fmt.money_full(r["est_tax"]))], className="ts-gl-row ts-gl-tax")],
        className="ts-review-card",
    )


def _downloads() -> list[html.Button]:
    return [
        html.Button("Download CSV", id={"type": "ws-dl", "id": "csv"}, n_clicks=0,
                    type="button", className="ts-btn-outline"),
        html.Button("Download PDF", id={"type": "ws-dl", "id": "pdf"}, n_clicks=0,
                    type="button", className="ts-btn-outline"),
    ]


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    state = turn["state"]
    d = turn["ui_payload"]["data"]
    if state == "DONE":
        return [
            header(state, "Transition recorded", "The account now targets the new model."),
            html.Div([icon("circle-check", 22, "ts-c-positive"),
                      html.Div([html.P("Traded and recorded — holdings updated",
                                       className="ts-fw-600 ts-c-navy"),
                                html.P(f"Event {d.get('event_id', '')} was added to the client's timeline.",
                                       className="ts-sub-sm")])],
                     className="ts-banner ts-banner--ok"),
            html.Div([*_downloads(),
                      dcc.Link("Back to client", href=extra.get("client_href", "/"),
                               className="ts-btn-outline"),
                      act("restart", "Start another transition")],
                     className="ts-canvas-actions ts-mt-6"),
            html.P(DISCLAIMER, className="ts-disclaimer"),
        ]

    o = d["optimization"]
    s, r, pre, post = o["summary"], o["realized"], o["pre"], o["post"]
    n_trades = s["n_lot_sells"] + s["n_buys"]
    cards = html.Div(
        [
            _card("Target model", o["target_model_id"]),
            _card("Resulting TE", fmt.pct(post["te"]), f"Ex-ante tracking error; today {fmt.pct(pre['te'])}"),
            _gains_losses_card(r),
            _card("Trades", fmt.number(n_trades),
                  f"{s['n_lot_sells']} lot sales · {s['n_buys']} buys"),
        ],
        className="ts-review-grid",
    )
    # the last confirmation executes the trades and updates the account's holdings
    approve_label = "Trade" if state == "TRANSITION_APPROVE" else "Approve transition"
    buttons = html.Div(
        [html.Button(approve_label, id={"type": "ws-approve", "id": "c"}, n_clicks=0, type="button",
                     className="ts-btn-cta"),
         *(_downloads() if state == "TRANSITION_APPROVE" else []),
         act("adjust", "Change settings"),
         html.Div(sim_badge(o.get("data_source")), className="ts-ml-auto")],
        className="ts-canvas-actions ts-canvas-actions--center ts-mt-6",
    )
    detail = html.Div(
        [
            html.Div([_mini("TE before", fmt.pct(pre["te"])), _mini("TE after", fmt.pct(post["te"])),
                      _mini("Net realized gain", fmt.signed_money(r["net_gain"])),
                      _mini("Turnover", fmt.pct(s["turnover"], 1)),
                      _mini("Budget used", "—" if r.get("budget_used_pct") is None
                            else fmt.pct(r["budget_used_pct"] / 100, 1)),  # API sends 0–100
                      _mini("Cash after", fmt.money(s["cash_after"]))],
                     className="ts-mini-grid"),
            html.P(_settings_text(o.get("constraints") or {}), className="ts-settings-line"),
            html.Ul([html.Li(x) for x in o["diagnostics"]["explanation"]], className="ts-explain")
            if o["diagnostics"]["explanation"] else None,
        ],
        className="ts-card ts-p-5 ts-mt-6",
    )
    fr = d.get("frontier") or extra.get("frontier")
    frontier = html.Div(
        [html.Div([html.H2("Efficient frontier", className="ts-h2"), sim_badge(fr.get("data_source"))],
                  className="ts-row ts-gap-2"),
         graph(frontier_figure(fr, selected_budget=o.get("budget_value")), 240,
               id_={"type": "ws-frontier", "id": "c"}, cls="ts-mt-4"),
         html.P("Click a point to re-run at that budget.", className="ts-sub ts-mt-2")],
        className="ts-card ts-p-5 ts-mt-6",
    ) if fr and fr.get("points") and state == "TRANSITION_RESULTS" else None
    glide = html.Div(
        [html.H2("Glide path", className="ts-h2 ts-section-head"),
         _grid(o["glide_path"], GLIDE_COLUMNS, "No glide path")],
        className="ts-card ts-overflow-hidden ts-mt-6",
    ) if o.get("glide_path") else None
    trades = html.Div(
        dmc.Tabs(
            [
                dmc.TabsList([dmc.TabsTab(f"Sells ({len(o['trades']['sells'])})", value="sells"),
                              dmc.TabsTab(f"Buys ({len(o['trades']['buys'])})", value="buys")]),
                dmc.TabsPanel(_grid(o["trades"]["sells"], SELL_COLUMNS, "No sales"), value="sells"),
                dmc.TabsPanel(_grid(o["trades"]["buys"], BUY_COLUMNS, "No purchases"), value="buys"),
            ],
            value="sells", className="ts-tabs",
        ),
        className="ts-card ts-overflow-hidden ts-mt-6",
    )
    if state == "TRANSITION_APPROVE":
        title, lede = "Review & export", "Your recommended transition is ready for review."
    else:
        title, lede = "Optimization results", "Review the trade-off, then approve or adjust."
    return [
        header(state, title, lede),
        cards, buttons, detail, frontier, glide, trades,
        html.P(o.get("disclaimer") or DISCLAIMER, className="ts-disclaimer"),
    ]


def _mini(label: str, value: str) -> html.Div:
    return html.Div([html.P(label, className="ts-kpi-label"), html.P(value, className="ts-mini-value")])


LOT_RELIEF = {"optimizer": "optimizer-chosen lots", "tax_optimal": "tax-optimal lots", "hifo": "HIFO lots"}


def _settings_text(c: dict[str, Any]) -> str:
    """The constraints the backend actually applied (OptimizationResult.constraints)."""
    parts = [f"Cash buffer {fmt.pct(c.get('min_cash_buffer', 0), 1)}"]
    if c.get("min_trade_value"):
        parts.append(f"min trade {fmt.money_full(c['min_trade_value'])}")
    parts.append(f"trading cost {fmt.number(c.get('transaction_cost_bps', 0), 0)} bps")
    parts.append(LOT_RELIEF.get(c.get("lot_relief", "optimizer"), c.get("lot_relief", "")))
    if c.get("round_shares", True):
        parts.append("whole shares")
    if c.get("max_weight"):
        parts.append(f"max weight {fmt.pct(c['max_weight'], 0)}")
    if c.get("sector_band"):
        parts.append(f"sector band ±{fmt.pct(c['sector_band'], 0)}")
    return "Settings: " + " · ".join(parts)
