"""Client page AI review: findings for the household or the selected account, and starting a
transition that carries the picked fixes (GET /clients|accounts/{id}/diagnosis)."""

from __future__ import annotations

from dash import Input, Output, State, callback, no_update
from dash.exceptions import PreventUpdate

from callbacks.client_detail import _expired, _start, _tok
from components.common import error_state
from components.diagnosis import client_review
from services.api_client import ApiError, AuthError, api


@callback(
    Output("cd-ai-body", "children"),
    Output("cd-ai-sub", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("cd-account", "value"),
    Input("cd-client-id", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def ai_review(account, client_id, session):
    if not client_id or not _tok(session):
        raise PreventUpdate
    acct = None if account in (None, "all") else account
    try:
        c = api(_tok(session))
        d = c.account_diagnosis(acct) if acct else c.client_diagnosis(client_id)
    except AuthError:
        return no_update, no_update, _expired()
    except ApiError as exc:
        if exc.status == 422:  # no holdings yet
            return [], "Nothing to review yet: the account has no holdings.", no_update
        return error_state(exc.message), None, no_update
    sub = ("What the guide notices in the selected account." if acct else
           "What the guide notices across the household (all accounts combined).")
    return client_review(d, can_start=acct is not None), sub, no_update


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Input("cd-ai-start", "n_clicks"),
    State("cd-ai-fixes", "value"),
    State("cd-account", "value"),
    State("cd-client-id", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def start_with_fixes(n, fixes, account, client_id, session):
    if not n or account in (None, "all"):
        raise PreventUpdate
    return _start(session, client_id, account, fixes or [])
