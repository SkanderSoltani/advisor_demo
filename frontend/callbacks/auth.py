"""Auth: route guard, sign-in, password visibility."""

from __future__ import annotations

from dash import (
    ALL,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    html,
    no_update,
)
from dash.exceptions import PreventUpdate

from components.shell import icon
from services.api_client import ApiClient, ApiError

PUBLIC = {"/login"}


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Input("url", "pathname"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def guard(pathname: str | None, session: dict | None):
    """No token → /login; already signed in on /login → client book."""
    has_token = bool(session and session.get("token"))
    if pathname in PUBLIC:
        return "/" if has_token else no_update
    return no_update if has_token else "/login"


def _error(msg: str) -> html.Div:
    return html.Div([icon("circle-alert", 16, "ts-shrink-0 ts-mt-05"), html.Span(msg)],
                    className="ts-alert-error")


@callback(
    Output("session", "data"),
    Output("redirect", "href", allow_duplicate=True),
    Output("login-error", "children"),
    Output("login-error", "className"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Input("login-submit", "n_clicks"),
    Input("login-password", "n_submit"),
    State("login-email", "value"),
    State("login-password", "value"),
    State("login-remember", "value"),
    running=[
        (Output("login-submit", "disabled"), True, False),
        (Output("login-submit", "children"),
         [html.Span(className="ts-spinner"), "Signing in…"],
         ["Sign in ", icon("arrow-right", 17)]),
    ],
    prevent_initial_call=True,
)
def sign_in(clicks, submit, email, password, remember):
    if not (clicks or submit):  # Dash Pages fires callbacks when the page renders; ignore that
        raise PreventUpdate
    email = (email or "").strip()
    if not email or not password:
        return (no_update, no_update, _error("Enter your email and password to continue."),
                "", no_update)
    try:
        res = ApiClient().login(email, password)
    except ApiError:
        note = [{"action": "show", "id": "login-failed", "title": "Sign-in failed",
                 "message": "Check your email and password.", "color": "red"}]
        return (no_update, no_update,
                _error("We couldn’t sign you in. Check your credentials and try again."), "", note)
    user = res.user.model_dump(mode="json")
    session = {"token": res.access_token, "user": user,
               "session_only": "remember" not in (remember or [])}
    return session, "/", None, "ts-hidden", no_update


clientside_callback(
    ClientsideFunction(namespace="ts", function_name="togglePassword"),
    Output("login-password", "type"),
    Output("login-eye", "aria-label"),
    Output("login-eye", "className"),
    Input("login-eye", "n_clicks"),
    State("login-password", "type"),
    State("login-eye", "className"),
    prevent_initial_call=True,
)


@callback(
    Output("session", "data", allow_duplicate=True),
    Output("redirect", "href", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Input("auth-expired", "data"),
    prevent_initial_call=True,
)
def session_expired(ts):
    """Any API 401 → clear the session and go to /login."""
    if not ts:
        raise PreventUpdate
    return None, "/login", [{"action": "show", "id": "session-expired", "title": "Signed out",
                             "message": "Your session expired. Please sign in again.",
                             "color": "yellow"}]


# Global "refresh" → every page's local load store (pages only listen to their own components).
clientside_callback(
    "function (r, ids) { return ids.map(function () { return r; }); }",
    Output({"type": "page-load", "page": ALL}, "data"),
    Input("refresh", "data"),
    State({"type": "page-load", "page": ALL}, "id"),
    prevent_initial_call=True,
)
