"""Onboard-client and add-account modal flows (shared by the client book and client detail pages)."""

from __future__ import annotations

import re
from datetime import datetime

from dash import (
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
from services.api_client import ApiError, AuthError, api

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HIDDEN = "ts-hidden"


def _tok(session: dict | None) -> str | None:
    return (session or {}).get("token")


def _note(id_: str, title: str, message: str, color: str = "green") -> list[dict]:
    return [{"action": "show", "id": id_, "title": title, "message": message, "color": color}]


def _err(msg: str) -> html.Div:
    return html.Div([icon("circle-alert", 16, "ts-shrink-0 ts-mt-05"), html.Span(msg)],
                    className="ts-alert-error ts-mt-4")


# ================================================================== onboard client
@callback(
    Output("onboard-modal", "opened"),
    Output("ob-step", "data"),
    Output("ob-created", "data"),
    Input("open-onboard", "n_clicks"),
    prevent_initial_call=True,
)
def open_onboard(n):
    if not n:
        raise PreventUpdate
    return True, 1, None


@callback(
    Output("onboard-modal", "opened", allow_duplicate=True),
    Input("ob-close", "n_clicks"),
    Input("ob-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def close_onboard(a, b):
    if not (a or b):
        raise PreventUpdate
    return False


@callback(
    Output("ob-step1", "className"),
    Output("ob-step2", "className"),
    Output("ob-done", "className"),
    Output("ob-eyebrow", "children"),
    Output("ob-title", "children"),
    Output("ob-sub", "children"),
    Output("ob-cancel", "className"),
    Output("ob-back", "className"),
    Output("ob-next", "className"),
    Output("ob-save", "className"),
    Output("ob-goto", "className"),
    Output("ob-add-account", "className"),
    Input("ob-step", "data"),
)
def render_step(step):
    show = lambda on, base: base if on else f"{base} {HIDDEN}"  # noqa: E731
    s = step or 1
    titles = {
        1: ("Step 1 of 2", "Onboard a new client",
            "Add the household details to create their advisor profile."),
        2: ("Step 2 of 2", "Tax profile",
            "Rates drive every tax estimate for this household. You can edit them later."),
        3: ("Client created", "Onboard a new client", ""),
    }[s]
    return (show(s == 1, "ts-stack-4"), show(s == 2, "ts-stack-4"), show(s == 3, ""),
            *titles,
            show(s in (1,), "ts-btn-plain"), show(s == 2, "ts-btn-plain"),
            show(s == 1, "ts-btn-modal-primary"), show(s == 2, "ts-btn-modal-primary"),
            show(s == 3, "ts-btn-plain"), show(s == 3, "ts-btn-modal-primary"))


@callback(
    Output("ob-step", "data", allow_duplicate=True),
    Output("ob-name-err", "children"),
    Output("ob-email-err", "children"),
    Output("ob-state-err", "children"),
    Output("ob-state2", "value"),
    Input("ob-next", "n_clicks"),
    State("ob-name", "value"),
    State("ob-email", "value"),
    State("ob-state", "value"),
    prevent_initial_call=True,
)
def onboard_next(n, name, email, state):
    if not n:
        raise PreventUpdate
    errs = ["", "", ""]
    if not (name or "").strip():
        errs[0] = "Enter the client or household name."
    if not EMAIL_RE.match((email or "").strip()):
        errs[1] = "Enter a valid email address."
    if state and not re.fullmatch(r"[A-Za-z]{2}", state.strip()):
        errs[2] = "Use the two-letter state code."
    if any(errs):
        return no_update, *errs, no_update
    return 2, "", "", "", (state or "").strip().upper() or no_update


@callback(
    Output("ob-step", "data", allow_duplicate=True),
    Input("ob-back", "n_clicks"),
    prevent_initial_call=True,
)
def onboard_back(n):
    if not n:
        raise PreventUpdate
    return 1


@callback(
    Output("ob-step", "data", allow_duplicate=True),
    Output("ob-created", "data", allow_duplicate=True),
    Output("ob-done-text", "children"),
    Output("ob-error", "children"),
    Output("ob-state2-err", "children"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("refresh", "data", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("ob-save", "n_clicks"),
    State("ob-name", "value"),
    State("ob-email", "value"),
    State("ob-phone", "value"),
    State("ob-type", "value"),
    State("ob-notes", "value"),
    State("ob-fst", "value"),
    State("ob-flt", "value"),
    State("ob-state2", "value"),
    State("ob-sr", "value"),
    State("refresh", "data"),
    State("session", "data"),
    running=[(Output("ob-save", "disabled"), True, False)],
    prevent_initial_call=True,
)
def onboard_save(n, name, email, phone, ctype, notes, fst, flt, state, sr, refresh, session):
    if not n:
        raise PreventUpdate
    if not re.fullmatch(r"[A-Za-z]{2}", (state or "").strip()):
        return (no_update,) * 4 + ("Use the two-letter state code.",) + (no_update,) * 3
    body = {
        "name": name.strip(), "email": email.strip(), "phone": (phone or "").strip() or None,
        "client_type": ctype, "notes": (notes or "").strip() or None,
        "tax_profile": {"federal_st_rate": round((fst or 0) / 100, 5),
                        "federal_lt_rate": round((flt or 0) / 100, 5),
                        "state": state.strip().upper(), "state_rate": round((sr or 0) / 100, 5)},
    }
    try:
        c = api(_tok(session)).create_client(body)
    except AuthError:
        return (no_update,) * 7 + (datetime.now().timestamp(),)
    except ApiError as exc:
        return (no_update, no_update, no_update, _err(exc.message), "", no_update, no_update, no_update)
    return (3, {"id": c.id, "name": c.name},
            [html.Strong(c.name), " is onboarded. Their profile and tax settings are saved."],
            None, "", _note("client-created", "Client onboarded", f"{c.name} was added to your book."),
            (refresh or 0) + 1, no_update)


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Output("onboard-modal", "opened", allow_duplicate=True),
    Input("ob-goto", "n_clicks"),
    State("ob-created", "data"),
    prevent_initial_call=True,
)
def onboard_goto(n, created):
    if not n or not created:
        raise PreventUpdate
    return f"/clients/{created['id']}", False


@callback(
    Output("onboard-modal", "opened", allow_duplicate=True),
    Output("add-account-modal", "opened", allow_duplicate=True),
    Output("aa-client", "data", allow_duplicate=True),
    Input("ob-add-account", "n_clicks"),
    State("ob-created", "data"),
    prevent_initial_call=True,
)
def onboard_to_account(n, created):
    if not n or not created:
        raise PreventUpdate
    return False, True, created["id"]


# ================================================================== add account
@callback(
    Output("aa-model", "options"),
    Output("aa-eyebrow", "children"),
    Output("aa-form", "className"),
    Output("aa-done", "className"),
    Output("aa-save", "className"),
    Output("aa-cancel", "className"),
    Output("aa-later", "className"),
    Output("aa-start", "className"),
    Output("aa-error", "children", allow_duplicate=True),
    Output("aa-created", "data", allow_duplicate=True),
    Input("add-account-modal", "opened"),
    State("aa-client", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def open_add_account(opened, client_id, session):
    if not opened:
        raise PreventUpdate
    try:
        a = api(_tok(session))
        models = a.models().items
        client = a.client(client_id) if client_id else None
    except ApiError:
        models, client = [], None
    opts = [{"value": m.id, "label": f"{m.id} · {m.name}"} for m in models]
    return (opts, f"New account · {client.name}" if client else "New account", "ts-stack-4",
            HIDDEN, "ts-btn-modal-primary", "ts-btn-plain", f"ts-btn-plain {HIDDEN}",
            f"ts-btn-modal-primary {HIDDEN}", None, None)


@callback(
    Output("add-account-modal", "opened", allow_duplicate=True),
    Input("aa-close", "n_clicks"),
    Input("aa-cancel", "n_clicks"),
    Input("aa-later", "n_clicks"),
    prevent_initial_call=True,
)
def close_add_account(a, b, c):
    if not (a or b or c):
        raise PreventUpdate
    return False


@callback(
    Output("aa-created", "data"),
    Output("aa-form", "className", allow_duplicate=True),
    Output("aa-done", "className", allow_duplicate=True),
    Output("aa-done-text", "children"),
    Output("aa-save", "className", allow_duplicate=True),
    Output("aa-cancel", "className", allow_duplicate=True),
    Output("aa-later", "className", allow_duplicate=True),
    Output("aa-start", "className", allow_duplicate=True),
    Output("aa-error", "children"),
    Output("aa-custodian-err", "children"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("refresh", "data", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("aa-save", "n_clicks"),
    State("aa-client", "data"),
    State("aa-type", "value"),
    State("aa-custodian", "value"),
    State("aa-nickname", "value"),
    State("aa-model", "value"),
    State("refresh", "data"),
    State("session", "data"),
    running=[(Output("aa-save", "disabled"), True, False)],
    prevent_initial_call=True,
)
def add_account_save(n, client_id, atype, custodian, nickname, model_id, refresh, session):
    if not n or not client_id:
        raise PreventUpdate
    if not (custodian or "").strip():
        return (no_update,) * 9 + ("Enter the custodian.",) + (no_update,) * 3
    body = {"account_type": atype, "custodian": custodian.strip(),
            "nickname": (nickname or "").strip() or None, "target_model_id": model_id or None}
    try:
        acct = api(_tok(session)).create_account(client_id, body)
    except AuthError:
        return (no_update,) * 12 + (datetime.now().timestamp(),)
    except ApiError as exc:
        return (no_update,) * 8 + (_err(exc.message), "", no_update, no_update, no_update)
    label = acct.nickname or acct.account_type.replace("_", " ").capitalize()
    return ({"client_id": client_id, "account_id": acct.id}, f"ts-stack-4 {HIDDEN}", "",
            [html.Strong(label), f" ({acct.custodian}) was added. It starts empty."],
            f"ts-btn-modal-primary {HIDDEN}", f"ts-btn-plain {HIDDEN}", "ts-btn-plain",
            "ts-btn-modal-primary", None, "",
            _note("account-created", "Account added", f"{label} is ready for a transition."),
            (refresh or 0) + 1, no_update)


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Output("add-account-modal", "opened", allow_duplicate=True),
    Output("aa-error", "children", allow_duplicate=True),
    Input("aa-start", "n_clicks"),
    State("aa-created", "data"),
    State("session", "data"),
    running=[(Output("aa-start", "disabled"), True, False)],
    prevent_initial_call=True,
)
def add_account_start(n, created, session):
    if not n or not created:
        raise PreventUpdate
    try:
        t = api(_tok(session)).create_transition(created["client_id"], created["account_id"])
    except ApiError as exc:
        return no_update, no_update, _err(exc.message)
    return f"/transition/{t.transition_id}", False, None


for _modal, _first in (("onboard-modal", "ob-name"), ("add-account-modal", "aa-nickname")):
    clientside_callback(
        ClientsideFunction(namespace="ts", function_name="focusOnOpen"),
        Output(_modal, "id"),
        Input(_modal, "opened"),
        State(_first, "id"),
        prevent_initial_call=True,
    )
