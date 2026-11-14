"""Client detail callbacks — every value comes from the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

from components import charts
from components.common import empty_state, error_state, graph, kpi_card, sim_badge
from components.event_timeline import drawer_body, event_row
from components.holdings_table import holdings_rows
from components.shell import icon, topbar_client
from services import format as fmt
from services.api_client import ApiError, AuthError, api

PAGE = {"type": "page-load", "page": "client"}
CLIENT_TYPES = {"individual": "Individual", "couple": "Joint", "family": "Family", "trust": "Trust"}
ACCOUNT_TYPES = {"individual_taxable": "Individual taxable", "joint_taxable": "Joint", "trust": "Trust",
                 "ira": "IRA", "roth_ira": "Roth IRA"}
EVENT_FILTER_LABELS = {"transition": "Transitions", "rebalance": "Rebalances",
                       "tax_loss_harvest": "Tax-loss harvests", "cash_flow": "Cash flows",
                       "model_change": "Model changes"}


def _tok(session: dict | None) -> str | None:
    return (session or {}).get("token")


def _expired() -> float:
    return datetime.now().timestamp()


def account_label(a: dict[str, Any]) -> str:
    return a.get("nickname") or ACCOUNT_TYPES.get(a["account_type"], a["account_type"])


def _acct(account: str | None) -> str | None:
    return None if account in (None, "all") else account


# ------------------------------------------------------------------ header + selector
@callback(
    Output("cd-topbar", "children"),
    Output("cd-name", "children"),
    Output("cd-subtitle", "children"),
    Output("cd-chips", "children"),
    Output("cd-account", "options"),
    Output("cd-detail", "data"),
    Output("cd-start-menu", "children"),
    Output("cd-error", "children"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input(PAGE, "data"),
    Input({"type": "retry", "id": ALL}, "n_clicks"),
    State("cd-client-id", "data"),
    State("cd-start-hint", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def load_client(_load, _retry, client_id, start_hint, session):
    if not _tok(session) or not client_id:
        raise PreventUpdate
    try:
        d = api(_tok(session)).client(client_id)
    except AuthError:
        return (no_update,) * 9 + (_expired(),)
    except ApiError as exc:
        msg = "This client doesn't exist or isn't in your book." if exc.status == 404 else exc.message
        return (no_update,) * 7 + (error_state(msg, {"type": "retry", "id": "client"}), no_update,
                                   no_update)
    data = d.model_dump(mode="json")
    tp = data["tax_profile"]
    onboarded = data["metrics"]["first_onboarding_date"] or "—"
    chips = [html.Span(f"Federal ST {fmt.rate(tp['federal_st_rate'])}", className="ts-tax-chip"),
             html.Span(f"Federal LT {fmt.rate(tp['federal_lt_rate'])}", className="ts-tax-chip"),
             html.Span(f"{tp['state']} state", className="ts-tax-chip"),
             html.Span(f"State {fmt.rate(tp['state_rate'])}", className="ts-tax-chip")]
    options = [{"label": html.Span(["All accounts", html.Span(fmt.money_full(data["metrics"]["market_value"]),
                                                               className="ts-acct-value")]),
                "value": "all"}]
    for a in data["accounts"]:
        options.append({
            "label": html.Span([account_label(a), html.Span(fmt.money_full(a["market_value"]),
                                                            className="ts-acct-value")],
                               title=f"{ACCOUNT_TYPES.get(a['account_type'], a['account_type'])} · "
                                     f"{a['custodian']} · target {a['target_model_id'] or 'not set'}"),
            "value": a["id"]})
    if data["accounts"]:
        menu = [dmc.MenuLabel("Choose an account")] + [
            dmc.MenuItem(
                html.Div([html.P(account_label(a), className="ts-menu-title"),
                          html.P(f"{ACCOUNT_TYPES.get(a['account_type'], a['account_type'])} · "
                                 f"{fmt.money(a['market_value'])}", className="ts-menu-meta")]),
                id={"type": "start-acct", "id": a["id"]}, n_clicks=0)
            for a in data["accounts"]]
    else:
        menu = [dmc.MenuItem("Add an account first", disabled=True)]
    note = no_update
    if start_hint and len(data["accounts"]) > 1:
        note = [{"action": "show", "id": "choose-account", "title": "Start a transition",
                 "message": "Choose which account to transition from “Start transition”.",
                 "color": "blue"}]
    return (topbar_client(data["name"]), data["name"],
            f"{CLIENT_TYPES.get(data['client_type'], data['client_type'])} · Onboarded {onboarded}",
            chips, options, data, menu, None, note, no_update)


@callback(
    Output("cd-kpis", "children"),
    Output("cd-years", "rowData"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("cd-account", "value"),
    Input("cd-detail", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def kpis(account, detail, session):
    if not detail:
        raise PreventUpdate
    acct = _acct(account)
    src = next((a for a in detail["accounts"] if a["id"] == acct), None) if acct else detail["metrics"]
    if src is None:
        raise PreventUpdate
    try:
        summ = api(_tok(session)).client_summary(detail["id"], acct)
    except AuthError:
        return no_update, no_update, _expired()
    except ApiError:
        summ = None
    years = [y.model_dump(mode="json") for y in summ.by_year] if summ else []
    # AUM at each year end = the last month-end point the API returned for that year
    year_end = {p.date.year: p.value for p in summ.aum_history} if summ else {}
    for y in years:
        y["aum"] = year_end.get(y["year"])
    reb = years[-1]["n_rebalances"] if years else None
    last = src.get("last_rebalance_date")
    cards = [
        kpi_card("Market value", fmt.money_full(src["market_value"]), size="lg"),
        kpi_card("Current TE", fmt.pct(src.get("ex_ante_te")), size="lg",
                 tooltip="Ex-ante tracking error vs target today (value-weighted for all accounts)"),
        kpi_card("Taxes saved YTD", fmt.money_full(src["taxes_saved_ytd"]), size="lg"),
        kpi_card("Since inception", fmt.money_full(src["taxes_saved_since_inception"]), size="lg"),
        kpi_card("Rebalances, YTD", fmt.number(reb) if reb is not None else "—", size="lg",
                 tooltip="Rebalances this calendar year"),
        kpi_card("Last rebalance", last or "—", size="lg"),
    ]
    return cards, list(reversed(years)), no_update


@callback(
    Output("cd-te-chart", "children"),
    Output("cd-te-sub", "children"),
    Output("cd-te-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("cd-account", "value"),
    Input("cd-te-window", "value"),
    Input("cd-detail", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def te_chart(account, window, detail, session):
    if not detail:
        raise PreventUpdate
    w = int(window or 63)
    try:
        res = api(_tok(session)).client_tracking_error(detail["id"], w, _acct(account))
    except AuthError:
        return no_update, no_update, no_update, _expired()
    except ApiError as exc:
        return error_state(exc.message), no_update, None, no_update
    sub = f"Rolling {w}-day history with target band"
    series = [p.model_dump(mode="json") for p in res.series]
    if not series:
        return (empty_state("No tracking-error history yet",
                            "History starts after the first transition.", icon_name="activity"),
                sub, sim_badge(res.data_source), no_update)
    accts = [a for a in detail["accounts"] if not _acct(account) or a["id"] == account]
    tols = {a["drift_tolerance_te"] for a in accts}
    tol = tols.pop() if len(tols) == 1 else None
    events = [e.model_dump(mode="json") for e in res.events]
    return (graph(charts.client_te_figure(series, events, tol, w), 250), sub,
            sim_badge(res.data_source), no_update)


@callback(
    Output("cd-tax-chart", "children"),
    Output("cd-tax-sub", "children"),
    Output("cd-tax-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Output("cd-tax-title", "children"),
    Input("cd-account", "value"),
    Input("cd-tax-gran", "value"),
    Input("cd-tax-view", "value"),
    Input("cd-detail", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def tax_chart(account, gran, view, detail, session):
    if not detail:
        raise PreventUpdate
    g = gran or "month"
    view = view if view in charts.TAX_SERIES else "saved"
    title = {"saved": "Taxes saved", "gl": "Gains & losses", "term": "Short- vs long-term"}[view]
    try:
        res = api(_tok(session)).client_tax_savings(detail["id"], g, _acct(account))
    except AuthError:
        return no_update, no_update, no_update, _expired(), title
    except ApiError as exc:
        return error_state(exc.message), no_update, None, no_update, title
    periods = [p.model_dump(mode="json") for p in res.periods]
    cadence = "Monthly" if g == "month" else "Annual"
    if view == "saved":
        sub = f"{cadence} realized impact · " \
              f"{fmt.money_full(res.taxes_saved_since_inception)} since inception"
        empty = not any(p["taxes_saved"] for p in periods)
        msg = ("No tax savings yet", "Savings appear after harvesting or tax-aware rebalancing.")
    else:
        net = sum(sign * charts.tax_series_value(p, keys) for p in periods
                  for _, _, sign, keys in charts.TAX_SERIES[view])
        sub = f"{cadence} realized gains and losses · net {fmt.money_full(net)}"
        empty = not any(charts.tax_series_value(p, keys) for p in periods
                        for _, _, _, keys in charts.TAX_SERIES[view])
        msg = ("No realized gains or losses yet", "They appear after trades that sell lots.")
    if empty:
        return (empty_state(*msg, icon_name="piggy-bank"), sub, sim_badge(res.data_source),
                no_update, title)
    fig = graph(charts.client_tax_figure(periods, view), 250)
    if view != "saved":
        items = [html.Span([html.I(style={"background": c}), lbl])
                 for lbl, c in charts.tax_legend_items(view)]
        items.append(html.Span([html.I(className="ts-legend-line"), "Cumulative net (right axis)"]))
        fig = html.Div([fig, html.Div(items, className="ts-legend")])
    return fig, sub, sim_badge(res.data_source), no_update, title


# ------------------------------------------------------------------ management history
@callback(
    Output("cd-event-type", "data"),
    Input({"type": "evt-filter", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def pick_event_type(clicks):
    if not ctx.triggered_id or not any(clicks):
        raise PreventUpdate
    return ctx.triggered_id["value"]


@callback(
    Output("cd-events-limit", "data"),
    Input("cd-more", "n_clicks"),
    State("cd-events-limit", "data"),
    prevent_initial_call=True,
)
def more_events(n, limit):
    if not n:
        raise PreventUpdate
    return (limit or 12) + 12


def _history_summary(items: list[dict[str, Any]], etype: str | None) -> list[html.Span]:
    """One line for the closed Management history section."""
    if not items:
        return [html.Span("No events yet" if not etype else "No events of this type")]
    n = len(items)
    last = max(items, key=lambda e: e["date"])
    noun = EVENT_FILTER_LABELS[etype].lower() if etype else "events"
    return [html.Span([html.Strong(fmt.number(n)), f" {noun}"]),
            html.Span(["Latest: ", html.Strong(charts.EVENT_LABELS.get(last["type"], last["type"])),
                       f" on {last['date']}"]),
            html.Span([html.Strong(fmt.money_full(sum(e.get("est_taxes_saved") or 0
                                                      for e in items))), " taxes saved"])]


@callback(
    Output("cd-events", "children"),
    Output("cd-filter-chip", "children"),
    Output("cd-history-summary", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("cd-account", "value"),
    Input("cd-event-type", "data"),
    Input("cd-events-limit", "data"),
    Input("cd-detail", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def events(account, etype, limit, detail, session):
    if not detail:
        raise PreventUpdate
    t = None if etype in (None, "all") else etype
    try:
        res = api(_tok(session)).client_events(detail["id"], type_=t, account_id=_acct(account))
    except AuthError:
        return no_update, no_update, no_update, _expired()
    except ApiError as exc:
        return error_state(exc.message), None, None, no_update
    chip = None
    if t:
        chip = html.Div([html.Span(f"Showing: {EVENT_FILTER_LABELS[t]}", className="ts-filter-chip"),
                         html.Button("Clear", id={"type": "evt-filter", "value": "all"}, n_clicks=0,
                                     type="button", className="ts-link-btn ts-text-xs")],
                        className="ts-row ts-gap-2 ts-px-5 ts-pt-3")
    items = [e.model_dump(mode="json") for e in res.items]
    summary = _history_summary(items, t)
    if not items:
        if t:
            return (html.P("No events of this type.", className="ts-sub ts-p-5"), chip, summary,
                    no_update)
        has_accounts = bool(detail["accounts"])
        return (empty_state(
            "No management history yet",
            "Events appear here after the first transition, rebalance or harvest.",
            [html.Button([icon("plus", 15), "Add account"], id={"type": "empty-action", "id": "add"},
                         n_clicks=0, type="button", className="ts-btn-outline"),
             html.Button(["Start first transition", icon("arrow-right", 15)],
                         id={"type": "empty-action", "id": "start"}, n_clicks=0, type="button",
                         className="ts-btn-cta", disabled=not has_accounts)],
            icon_name="calendar-clock"), chip, summary, no_update)
    rows = [event_row(e) for e in items[: limit or 12]]
    if len(items) > (limit or 12):
        rows.append(html.Button(f"Show more ({len(items) - (limit or 12)} remaining)", id="cd-more",
                                n_clicks=0, type="button", className="ts-show-more"))
    return html.Div(rows, className="ts-evt-list"), chip, summary, no_update


@callback(
    Output("cd-drawer", "opened"),
    Output("cd-drawer-title", "children"),
    Output("cd-drawer-body", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input({"type": "event-row", "id": ALL}, "n_clicks"),
    State("session", "data"),
    prevent_initial_call=True,
)
def open_event(clicks, session):
    if not ctx.triggered_id or not any(c for c in clicks if c):
        raise PreventUpdate
    try:
        e = api(_tok(session)).event(ctx.triggered_id["id"])
    except AuthError:
        return no_update, no_update, no_update, _expired()
    except ApiError as exc:
        return True, "Event", error_state(exc.message), no_update
    data = e.model_dump(mode="json")
    title = html.Div([html.P(charts.EVENT_LABELS.get(data["type"], data["type"]), className="ts-h2"),
                      html.P(data["date"], className="ts-sub")])
    return True, title, drawer_body(data), no_update


# ------------------------------------------------------------------ accounts grid
@callback(
    Output("cd-accounts-grid", "rowData"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("cd-detail", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def accounts_grid(detail, session):
    if not detail:
        raise PreventUpdate
    rows = []
    try:
        a = api(_tok(session))
        for acct in detail["accounts"]:
            unreal = a.account(acct["id"]).unrealized.net if acct["n_lots"] else None
            rows.append({**acct, "label": account_label(acct),
                         "type_label": ACCOUNT_TYPES.get(acct["account_type"], acct["account_type"]),
                         "unrealized_gain": unreal})
    except AuthError:
        return no_update, _expired()
    except ApiError:
        rows = [{**x, "label": account_label(x), "type_label": x["account_type"],
                 "unrealized_gain": None} for x in detail["accounts"]]
    return rows, no_update


# ------------------------------------------------------------------ actions
def _start(session: dict | None, client_id: str, account_id: str,
           fixes: list[str] | None = None) -> tuple[Any, Any]:
    try:
        t = api(_tok(session)).create_transition(client_id, account_id, fixes)
    except ApiError as exc:
        return no_update, [{"action": "show", "id": "start-failed", "title": "Couldn't start",
                            "message": exc.message, "color": "red"}]
    return f"/transition/{t.transition_id}", no_update


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Input({"type": "start-acct", "id": ALL}, "n_clicks"),
    Input("cd-accounts-grid", "cellRendererData"),
    Input({"type": "empty-action", "id": ALL}, "n_clicks"),
    State("cd-detail", "data"),
    State("cd-account", "value"),
    State("session", "data"),
    prevent_initial_call=True,
)
def start_transition(menu_clicks, grid, empty_start, detail, selected, session):
    if not detail:
        raise PreventUpdate
    trig = ctx.triggered_id
    if isinstance(trig, dict) and trig.get("type") == "start-acct":
        if not any(c for c in menu_clicks if c):
            raise PreventUpdate
        return _start(session, detail["id"], trig["id"])
    if trig == "cd-accounts-grid" and grid and isinstance(grid.get("value"), dict):
        return _start(session, detail["id"], grid["value"]["id"])
    if (isinstance(trig, dict) and trig.get("type") == "empty-action" and trig.get("id") == "start"
            and any(c for c in empty_start if c)):
        acct = _acct(selected) or (detail["accounts"][0]["id"] if detail["accounts"] else None)
        if acct:
            return _start(session, detail["id"], acct)
    raise PreventUpdate


@callback(
    Output("add-account-modal", "opened", allow_duplicate=True),
    Output("aa-client", "data", allow_duplicate=True),
    Input("cd-add-account", "n_clicks"),
    Input({"type": "empty-action", "id": ALL}, "n_clicks"),
    State("cd-client-id", "data"),
    prevent_initial_call=True,
)
def open_add_account(a, b, client_id):
    trig = ctx.triggered_id
    is_empty_add = isinstance(trig, dict) and trig.get("id") == "add" and any(c for c in b if c)
    if not (a and trig == "cd-add-account") and not is_empty_add:
        raise PreventUpdate
    return True, client_id


@callback(
    Output("edit-modal", "opened"),
    Output("ed-name", "value"),
    Output("ed-email", "value"),
    Output("ed-phone", "value"),
    Output("ed-type", "value"),
    Output("ed-notes", "value"),
    Output("ed-fst", "value"),
    Output("ed-flt", "value"),
    Output("ed-state", "value"),
    Output("ed-sr", "value"),
    Output("ed-error", "children"),
    Input("cd-edit", "n_clicks"),
    State("cd-detail", "data"),
    prevent_initial_call=True,
)
def open_edit(n, d):
    if not n or not d:
        raise PreventUpdate
    tp = d["tax_profile"]
    return (True, d["name"], d["email"], d["phone"], d["client_type"], d["notes"],
            round(tp["federal_st_rate"] * 100, 2), round(tp["federal_lt_rate"] * 100, 2), tp["state"],
            round(tp["state_rate"] * 100, 2), None)


@callback(
    Output("edit-modal", "opened", allow_duplicate=True),
    Input("ed-close", "n_clicks"),
    Input("ed-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def close_edit(a, b):
    if not (a or b):
        raise PreventUpdate
    return False


@callback(
    Output("edit-modal", "opened", allow_duplicate=True),
    Output("ed-error", "children", allow_duplicate=True),
    Output("refresh", "data", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Input("ed-save", "n_clicks"),
    State("cd-client-id", "data"),
    State("ed-name", "value"), State("ed-email", "value"), State("ed-phone", "value"),
    State("ed-type", "value"), State("ed-notes", "value"), State("ed-fst", "value"),
    State("ed-flt", "value"), State("ed-state", "value"), State("ed-sr", "value"),
    State("refresh", "data"), State("session", "data"),
    running=[(Output("ed-save", "disabled"), True, False)],
    prevent_initial_call=True,
)
def save_edit(n, cid, name, email, phone, ctype, notes, fst, flt, state, sr, refresh, session):
    if not n:
        raise PreventUpdate
    body = {"name": (name or "").strip(), "email": (email or "").strip(),
            "phone": (phone or "").strip() or None, "client_type": ctype,
            "notes": (notes or "").strip() or None,
            "tax_profile": {"federal_st_rate": round((fst or 0) / 100, 5),
                            "federal_lt_rate": round((flt or 0) / 100, 5),
                            "state": (state or "").strip().upper(),
                            "state_rate": round((sr or 0) / 100, 5)}}
    try:
        api(_tok(session)).update_client(cid, body)
    except ApiError as exc:
        return no_update, html.Div([icon("circle-alert", 16), html.Span(exc.message)],
                                   className="ts-alert-error ts-mt-4"), no_update, no_update
    return False, None, (refresh or 0) + 1, [{"action": "show", "id": "client-saved",
                                              "title": "Client updated", "message": "Changes saved.",
                                              "color": "green"}]


# ------------------------------------------------------------------ holdings
@callback(
    Output("cd-hold-state", "data"),
    Output("cd-holdings", "rowData"),
    Output("cd-hold-totals", "children"),
    Output("cd-hold-sub", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("cd-account", "value"),
    Input("cd-detail", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def load_holdings(account, detail, session):
    if not detail:
        raise PreventUpdate
    accts = [a for a in detail["accounts"] if not _acct(account) or a["id"] == account]
    lots: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    total = cash = 0.0
    try:
        a_api = api(_tok(session))
        for a in accts:
            d = a_api.account(a["id"])
            label = account_label(a)
            names.update({h.ticker: h.name for h in d.holdings})
            lots += [{**x.model_dump(mode="json"), "account_label": label} for x in d.lots]
            total += d.account.market_value
            cash += d.account.cash
    except AuthError:
        return no_update, no_update, no_update, no_update, _expired()
    except ApiError as exc:
        return None, [], error_state(exc.message), no_update, no_update
    state = {"lots": lots, "names": names, "total": total, "expanded": [],
             "show_account": len(accts) > 1}
    n_pos = len({x["ticker"] for x in lots})
    totals = [
        html.Span([html.Strong(fmt.number(n_pos)), f" position{'s' if n_pos != 1 else ''}"]),
        html.Span([html.Strong(fmt.money_full(total - cash)), " invested"]),
        html.Span([html.Strong(fmt.money_full(cash)), " cash"]),
    ]
    scope = "all accounts" if len(accts) > 1 else account_label(accts[0]) if accts else ""
    sub = f"Current positions in {scope}. Click a ticker to see its tax lots."
    return state, holdings_rows(state), totals, sub, no_update


@callback(
    Output("cd-hold-state", "data", allow_duplicate=True),
    Output("cd-holdings", "rowData", allow_duplicate=True),
    Input("cd-holdings", "cellClicked"),
    State("cd-hold-state", "data"),
    prevent_initial_call=True,
)
def toggle_holding(clicked, state):
    rid = str((clicked or {}).get("rowId") or "")
    if not state or (clicked or {}).get("colId") != "label" or not rid.startswith("t:"):
        raise PreventUpdate
    tk = rid[2:]
    open_ = list(state.get("expanded", []))
    state = {**state, "expanded": [x for x in open_ if x != tk] if tk in open_ else [*open_, tk]}
    return state, holdings_rows(state)
