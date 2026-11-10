"""Client book callbacks. Every number shown comes from an API call."""

from __future__ import annotations

from datetime import datetime

from dash import ALL, Input, Output, State, callback, html, no_update
from dash.exceptions import PreventUpdate

from components import charts
from components.common import error_state, graph, kpi_card, sim_badge
from components.shell import topbar_book
from services import format as fmt
from services.api_client import ApiError, AuthError, api


def _greeting(name: str) -> str:
    h = datetime.now().hour
    part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    first = (name or "").split()[0] if name else ""
    return f"Good {part}, {first}".rstrip(", ")


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "—"


BOOK_LOAD = {"type": "page-load", "page": "book"}


def _token(session: dict | None) -> str | None:
    return (session or {}).get("token")


@callback(
    Output("book-topbar", "children"),
    Output("book-greeting", "children"),
    Output("book-kpis", "children"),
    Output("book-clients", "data"),
    Output("book-error", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input(BOOK_LOAD, "data"),
    Input({"type": "retry", "id": ALL}, "n_clicks"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def load_book(_reload, _retry, session):
    token = _token(session)
    if not token:
        raise PreventUpdate
    user = (session or {}).get("user") or {}
    try:
        a = api(token)
        b = a.book_summary()
        rows = a.clients().items
    except AuthError:
        return (no_update,) * 5 + (datetime.now().timestamp(),)
    except ApiError as exc:
        return (no_update, no_update, no_update, no_update,
                error_state(exc.message, {"type": "retry", "id": "book"}), no_update)
    kpis = [
        kpi_card("Clients", fmt.number(b.n_clients)),
        kpi_card("Accounts", fmt.number(b.n_accounts)),
        kpi_card("Total AUM", fmt.money(b.total_aum), tooltip="Market value of all accounts"),
        kpi_card("Taxes saved YTD", fmt.money(b.taxes_saved_ytd), "positive",
                 tooltip="Estimated taxes saved this calendar year"),
        kpi_card("Since inception", fmt.money(b.taxes_saved_since_inception), "positive",
                 tooltip="Estimated taxes saved since each account was onboarded"),
        kpi_card("Average TE", fmt.pct(b.avg_ex_ante_te),
                 tooltip="AUM-weighted ex-ante tracking error vs each account's target"),
        kpi_card("Outside tolerance", fmt.number(b.n_accounts_outside_tolerance),
                 id_="kpi-outside", clickable=True,
                 tooltip="Accounts whose tracking error exceeds their drift tolerance — click to filter"),
    ]
    data = [r.model_dump(mode="json") for r in rows]
    return (topbar_book(fmt.long_date(), initials(user.get("name", ""))),
            _greeting(user.get("name", "")), kpis, data, None, no_update)


@callback(
    Output("book-te-chart", "children"),
    Output("book-te-value", "children"),
    Output("book-te-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("book-te-window", "value"),
    Input("book-period", "value"),
    Input(BOOK_LOAD, "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def te_chart(window, period, _r, session):
    token = _token(session)
    if not token:
        raise PreventUpdate
    try:
        res = api(token).book_tracking_error(int(window or 63))
    except AuthError:
        return no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return error_state(exc.message), "", None, no_update
    series = [p.model_dump(mode="json") for p in res.series]
    if not series:
        return html.P("No tracking-error history yet.", className="ts-sub"), "—", None, no_update
    last = series[-1]
    value = html.Div([
        html.P(fmt.pct(last["avg_te"]), className="ts-big-value"),
        html.P(f"As of {fmt.short_month(last['date'])} · {last['n_accounts']} accounts",
               className="ts-big-sub"),
    ])
    keep = charts.in_period([p["date"] for p in series], period)
    shown = [p for p, k in zip(series, keep, strict=True) if k]
    body = html.Div([
        graph(charts.book_te_figure(series, period), 48),
        html.Div([html.Span(fmt.short_month(shown[0]["date"])),
                  html.Span(fmt.short_month(shown[-1]["date"]))], className="ts-axis-labels"),
    ])
    return body, value, sim_badge(res.data_source), no_update


@callback(
    Output("book-tax-chart", "children"),
    Output("book-tax-value", "children"),
    Output("book-tax-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("book-tax-gran", "value"),
    Input("book-tax-view", "value"),
    Input("book-period", "value"),
    Input(BOOK_LOAD, "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def tax_chart(gran, view, period, _r, session):
    token = _token(session)
    if not token:
        raise PreventUpdate
    try:
        a = api(token)
        res = a.book_tax_impact(gran or "month")
        ytd = a.book_summary().taxes_saved_ytd
    except AuthError:
        return no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return error_state(exc.message), "", None, no_update
    periods = [p.model_dump(mode="json") for p in res.periods]
    if not periods:
        return html.P("No tax history yet.", className="ts-sub"), "—", None, no_update
    view = view if view in charts.TAX_SERIES else "saved"
    if view == "saved":
        value = html.Div([
            html.P(fmt.money_full(periods[-1]["cum_taxes_saved"]), className="ts-big-value"),
            html.P(f"+{fmt.money_full(ytd)} YTD", className="ts-big-sub ts-c-positive"),
        ])
    else:
        last = periods[-1]
        totals = [(label, sign * charts.tax_series_value(last, keys, cum=True))
                  for label, _, sign, keys in charts.TAX_SERIES[view]]
        value = html.Div([
            html.P(fmt.money_full(sum(v for _, v in totals)), className="ts-big-value"),
            html.P("Net realized · " + " · ".join(f"{lbl} {fmt.money(abs(v))}" for lbl, v in totals),
                   className="ts-big-sub"),
        ])
    keep = charts.in_period([p["period"] for p in periods], period)
    shown = [p for p, k in zip(periods, keep, strict=True) if k]
    def label(k: str) -> str:
        return fmt.short_month(f"{k}-01") if len(k) == 7 else k
    body = html.Div([
        graph(charts.book_tax_figure(periods, gran or "month", period, view), 48),
        html.Div([html.Span(label(shown[0]["period"])), html.Span(label(shown[-1]["period"]))],
                 className="ts-axis-labels"),
        *([html.Div([html.Span([html.I(style={"background": color}), lbl])
                     for lbl, color in charts.tax_legend_items(view)], className="ts-legend")]
          if view in charts.TAX_SERIES else []),
    ])
    return body, value, sim_badge(res.data_source), no_update


@callback(
    Output("book-act-chart", "children"),
    Output("book-act-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("book-period", "value"),
    Input(BOOK_LOAD, "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def activity_chart(period, _r, session):
    token = _token(session)
    if not token:
        raise PreventUpdate
    try:
        res = api(token).book_activity("month")
    except AuthError:
        return no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return error_state(exc.message), None, no_update
    periods = [p.model_dump(mode="json") for p in res.periods]
    if not periods:
        return html.P("No management activity yet.", className="ts-sub"), None, no_update
    return graph(charts.activity_figure(periods, period), 112), sim_badge(res.data_source), no_update


@callback(
    Output("book-grid", "rowData"),
    Output("book-sort", "children"),
    Output("book-grid-wrap", "className"),
    Input("book-clients", "data"),
    Input("book-search", "value"),
    Input("book-status", "value"),
    Input("book-sort", "n_clicks"),
)
def filter_grid(rows, search, status, sort_clicks):
    if rows is None:
        raise PreventUpdate
    asc = (sort_clicks or 0) % 2 == 0
    q = (search or "").strip().lower()
    out = [r for r in rows if q in r["name"].lower()]
    if status == "outside":
        out = [r for r in out if r["status"] in ("drifting", "needs_review")]
    elif status and status != "all":
        out = [r for r in out if r["status"] == status]
    out.sort(key=lambda r: r["name"].lower(), reverse=not asc)
    empty = not rows
    return out, f"Name {'A–Z' if asc else 'Z–A'}", "ts-grid-empty" if empty else ""


@callback(
    Output("book-status", "value"),
    Input("kpi-outside", "n_clicks"),
    prevent_initial_call=True,
)
def outside_filter(n):
    if not n:
        raise PreventUpdate
    return "outside"


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Output("add-account-modal", "opened", allow_duplicate=True),
    Output("aa-client", "data", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Input("book-grid", "cellRendererData"),
    State("book-clients", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def row_action(data, rows, session):
    if not data or not isinstance(data.get("value"), dict):
        raise PreventUpdate
    action, cid = data["value"].get("action"), data["value"].get("id")
    if action == "view":
        return f"/clients/{cid}", no_update, no_update, no_update
    if action == "add_account":
        return no_update, True, cid, no_update
    if action == "start":
        try:
            accts = api(_token(session)).client_accounts(cid).items
            if len(accts) == 1:
                t = api(_token(session)).create_transition(cid, accts[0].id)
                return f"/transition/{t.transition_id}", no_update, no_update, no_update
        except ApiError as exc:
            return no_update, no_update, no_update, [{"action": "show", "id": "start-failed",
                                                      "title": "Couldn't start the transition",
                                                      "message": exc.message, "color": "red"}]
        # several (or no) accounts: choose on the client page
        return f"/clients/{cid}?start=1", no_update, no_update, no_update
    raise PreventUpdate


# ------------------------------------------------------------------ delete client
@callback(
    Output("delete-client-modal", "opened"),
    Output("dc-client", "data"),
    Output("dc-title", "children"),
    Output("dc-body", "children"),
    Input("book-grid", "cellRendererData"),
    State("book-clients", "data"),
    prevent_initial_call=True,
)
def ask_delete(data, rows):
    if not data or not isinstance(data.get("value"), dict) or data["value"].get("action") != "delete":
        raise PreventUpdate
    cid = data["value"].get("id")
    row = next((r for r in rows or [] if r["id"] == cid), None)
    if row is None:
        raise PreventUpdate
    n = row.get("n_accounts") or 0
    body = [
        "This permanently removes ", html.Strong(row["name"]),
        f" ({fmt.money(row.get('market_value'))}), their {n} account{'s' if n != 1 else ''}, "
        "all tax lots and management history from your book. This can't be undone.",
    ]
    return True, {"id": cid, "name": row["name"]}, f"Delete {row['name']}?", body


@callback(
    Output("delete-client-modal", "opened", allow_duplicate=True),
    Input("dc-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_delete(n):
    if not n:
        raise PreventUpdate
    return False


@callback(
    Output("delete-client-modal", "opened", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("refresh", "data", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("dc-confirm", "n_clicks"),
    State("dc-client", "data"),
    State("refresh", "data"),
    State("session", "data"),
    running=[(Output("dc-confirm", "disabled"), True, False)],
    prevent_initial_call=True,
)
def confirm_delete(n, client, refresh, session):
    if not n or not client:
        raise PreventUpdate
    try:
        api(_token(session)).delete_client(client["id"])
    except AuthError:
        return False, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return no_update, [{"action": "show", "id": "delete-failed", "title": "Couldn't delete client",
                            "message": exc.message, "color": "red"}], no_update, no_update
    note = [{"action": "show", "id": "client-deleted", "title": "Client deleted",
             "message": f"{client['name']} was removed from your book.", "color": "green"}]
    return False, note, (refresh or 0) + 1, no_update
