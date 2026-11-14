"""Analytics panel on the client book and client pages (saved point-in-time reports).

The panel is collapsed by default. Numbers are fetched the first time it is opened (and again
only when the scope changes or Recalculate is pressed), so closing / reopening is instant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dash import Input, Output, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

from components.common import error_state
from components.risk_panel import asof_text, risk_body, toggle_label
from services.api_client import ApiError, AuthError, api


def _badge(r: dict[str, Any]) -> html.Span | None:
    if r.get("data_source") != "mock":
        return None
    return html.Span("Simulated analytics", className="ts-sim-badge",
                     title="Mock numbers from the synthetic market")


def _is_open(n: int | None) -> bool:
    return bool((n or 0) % 2)


def _render(fetch: Any, client: bool, key: str) -> tuple[Any, ...]:
    """(body, as-of, badge, auth-expired, loaded-key)."""
    try:
        r = fetch()
    except AuthError:
        return no_update, no_update, no_update, datetime.now().timestamp(), no_update
    except ApiError as exc:
        return error_state(exc.message), None, None, no_update, None
    return risk_body(r, client=client), asof_text(r), _badge(r), no_update, key


# ------------------------------------------------------------------ show / hide
for _p in ("book", "cd"):

    @callback(
        Output(f"{_p}-risk-panel", "style"),
        Output(f"{_p}-risk-toggle", "children"),
        Output(f"{_p}-risk-toggle", "aria-expanded"),
        Output(f"{_p}-risk-refresh", "style"),
        Input(f"{_p}-risk-toggle", "n_clicks"),
    )
    def _toggle(n):  # type: ignore[no-untyped-def]
        o = _is_open(n)
        return ({"display": "block" if o else "none"}, toggle_label(o), "true" if o else "false",
                {"display": "inline-flex" if o else "none"})


# ------------------------------------------------------------------ data
@callback(
    Output("book-risk-body", "children"),
    Output("book-risk-asof", "children"),
    Output("book-risk-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Output("book-risk-loaded", "data"),
    Input("book-risk-toggle", "n_clicks"),
    Input("book-risk-refresh", "n_clicks"),
    State("book-risk-loaded", "data"),
    State("session", "data"),
    running=[(Output("book-risk-refresh", "disabled"), True, False)],
    prevent_initial_call=True,
)
def book_risk(toggle, _refresh, loaded, session):
    token = (session or {}).get("token")
    refresh = ctx.triggered_id == "book-risk-refresh"
    if not token or not _is_open(toggle) or (loaded == "book" and not refresh):
        raise PreventUpdate
    return _render(lambda: api(token).book_risk(refresh=refresh), client=False, key="book")


@callback(
    Output("cd-risk-body", "children"),
    Output("cd-risk-asof", "children"),
    Output("cd-risk-badge", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Output("cd-risk-loaded", "data"),
    Output("cd-risk-sub", "children"),
    Input("cd-risk-toggle", "n_clicks"),
    Input("cd-risk-refresh", "n_clicks"),
    Input("cd-account", "value"),
    State("cd-risk-loaded", "data"),
    State("cd-client-id", "data"),
    State("session", "data"),
    running=[(Output("cd-risk-refresh", "disabled"), True, False)],
    prevent_initial_call=True,
)
def client_risk(toggle, _refresh, account, loaded, client_id, session):
    """Same analytics as the book, for the whole household or the selected account."""
    token = (session or {}).get("token")
    acct = None if account in (None, "all") else account
    key = acct or "all"
    refresh = ctx.triggered_id == "cd-risk-refresh"
    if not token or not client_id or not _is_open(toggle) or (loaded == key and not refresh):
        raise PreventUpdate  # closed: the scope change is picked up when it is opened
    out = _render(lambda: api(token).client_risk(client_id, acct, refresh=refresh),
                  client=True, key=key)
    sub = "Household view, all accounts combined" if acct is None else "Selected account only"
    return (*out, sub)
