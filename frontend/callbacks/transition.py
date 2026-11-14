"""Transition workspace callbacks — every step is a backend ChatTurn.

Flow: page load → GET transition/client/account/history + POST chat {} (current turn) → render.
Any user action (chip, canvas button, free text, upload, Plaid, stepper) → one backend call →
new ChatTurn → re-render header, thread, chips and canvas from it.
"""

from __future__ import annotations

import base64
import contextlib
from datetime import datetime
from typing import Any

from dash import ALL, MATCH, Input, Output, State, callback, clientside_callback, ctx, dcc, no_update
from dash.exceptions import PreventUpdate

from callbacks.client_detail import account_label
from components import transition_analytics
from components.canvas import render_canvas
from components.canvas.transition_setup import lock_rows
from components.chat_panel import bubble, chips, humanize_reply
from components.common import error_state
from components.stepper import STEP_BACK_TARGETS, STEPS, step_of, workspace_header
from services import format as fmt
from services.api_client import ApiClient, ApiError, AuthError, api

PAGE = {"type": "page-load", "page": "transition"}


def _tok(session: dict | None) -> str | None:
    return (session or {}).get("token")


def _note(title: str, message: str, color: str = "red") -> list[dict]:
    return [{"action": "show", "id": f"ws-{datetime.now().timestamp()}", "title": title,
             "message": message, "color": color}]


def _dump(x: Any) -> Any:
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


def _extra(client: ApiClient, tid: str, turn: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Data a canvas needs beyond the ChatTurn (fetched from the API, never computed here)."""
    extra: dict[str, Any] = {"client_href": f"/clients/{meta['client_id']}"}
    if turn["state"] == "TARGET_PICK_LIST":
        with contextlib.suppress(ApiError):  # fall back to the flat card list
            extra["catalog"] = client.model_catalog()  # grouped like Model management
    if turn["state"] == "TRANSITION_SETUP":
        acct = client.account(meta["account_id"])
        extra["lots"] = [{**lot.model_dump(mode="json"), "account_locked": lot.locked} for lot in acct.lots]
        if acct.lots:
            extra["frontier"] = _dump(client.frontier(tid, {"budget_mode": "tax", "n_points": 12}))
    return extra


def _thread_from_history(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for h in items:
        text = humanize_reply(h["text"]) if h["role"] == "user" else h["text"]
        # re-rendering the current step (reload) logs the same assistant message again
        if out and h["role"] == "assistant" and out[-1] == {"role": "assistant", "text": text}:
            continue
        out.append({"role": h["role"], "text": text})
    return out


# ------------------------------------------------------------------ load
@callback(
    Output("ws-meta", "data"),
    Output("ws-turn", "data"),
    Output("ws-thread-data", "data"),
    Output("ws-extra", "data"),
    Output("ws-error", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input(PAGE, "data"),
    Input({"type": "retry", "id": ALL}, "n_clicks"),
    State("ws-tid", "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def load(_, __, tid, session):
    if not tid:
        raise PreventUpdate
    try:
        client = api(_tok(session))
        tr = client.transition(tid)
        cl = client.client(tr.client_id)
        acct = next((a for a in cl.accounts if a.id == tr.account_id), None)
        hist = client.history(tid)
        turn = _dump(client.chat(tid))
        meta = {"client_id": tr.client_id, "account_id": tr.account_id, "client_name": cl.name,
                "account_label": account_label(_dump(acct)) if acct else "Account"}
        thread = _thread_from_history([*[_dump(h) for h in hist.items],
                                       {"role": "assistant", "text": turn["assistant_message"]}])
        return meta, turn, thread, _extra(client, tid, turn, meta), None, no_update
    except AuthError:
        return no_update, no_update, no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        msg = "This transition wasn't found." if exc.status == 404 else exc.message
        return (no_update, no_update, no_update, no_update,
                error_state(msg, {"type": "retry", "id": "ws"}), no_update)


# ------------------------------------------------------------------ render
@callback(
    Output("ws-header", "children"),
    Output("ws-canvas", "children"),
    Output("ws-chips", "children"),
    Input("ws-turn", "data"),
    Input("ws-extra", "data"),
    State("ws-meta", "data"),
)
def render(turn, extra, meta):
    if not turn or not meta:
        raise PreventUpdate
    state = turn["state"]
    back = f"/clients/{meta['client_id']}"
    header = workspace_header(meta["client_name"], meta["account_label"], step_of(state), back,
                              done=state == "DONE")
    return header, render_canvas(turn, extra), chips(turn.get("quick_replies", []))


# ------------------------------------------------------------------ three-portfolio analytics
@callback(
    Output({"type": "ws-pa", "id": ALL}, "children"),
    Input({"type": "ws-pa-key", "id": ALL}, "data"),
    State("ws-tid", "data"),
    State("session", "data"),
)
def portfolio_analytics(keys, tid, session):
    if not keys or not tid:
        raise PreventUpdate
    try:
        a = api(_tok(session)).transition_analytics(tid)
    except ApiError as exc:
        return [error_state(exc.message)] * len(keys)
    return [transition_analytics.view(a)] * len(keys)


clientside_callback(
    """function(tabs, ids) {
        return window.dash_clientside.ts.switchTab('.ts-pa-body', tabs[0] || 'overview', ids);
    }""",
    Output({"type": "ws-pa-pane", "id": ALL}, "style"),
    Input({"type": "ws-pa-tab", "id": ALL}, "value"),
    State({"type": "ws-pa-pane", "id": ALL}, "id"),
    prevent_initial_call=True,
)


@callback(Output("ws-thread", "children"), Input("ws-thread-data", "data"))
def thread(items):
    return [bubble(i["role"], i["text"]) for i in items or []]


clientside_callback(
    """function (items) {
        setTimeout(function () {
            var el = document.getElementById('ws-scroll');
            if (el) el.scrollTo({top: el.scrollHeight, behavior: 'smooth'});
        }, 60);
        return window.dash_clientside.no_update;
    }""",
    Output("ws-scroll-sink", "data"),
    Input("ws-thread-data", "data"),
    Input("ws-chips", "children"),
)


# ------------------------------------------------------------------ converse
def _fired() -> tuple[Any, Any]:
    """The trigger that actually carries a user action (new ALL components fire with 0/None)."""
    for t in ctx.triggered:
        if t["value"]:
            return _parse(t["prop_id"]), t["value"]
    raise PreventUpdate


def _parse(prop_id: str) -> Any:
    import json

    raw = prop_id.rsplit(".", 1)[0]
    return json.loads(raw) if raw.startswith("{") else raw


def _label(turn: dict[str, Any] | None, reply_id: str) -> str:
    for r in (turn or {}).get("quick_replies", []):
        if r["id"] == reply_id:
            return r["label"]
    return humanize_reply(f"[{reply_id}]")


def _first(values: list[Any]) -> Any:
    return values[0] if values else None


@callback(
    Output("ws-turn", "data", allow_duplicate=True),
    Output("ws-thread-data", "data", allow_duplicate=True),
    Output("ws-extra", "data", allow_duplicate=True),
    Output("ws-input", "value"),
    Output("ws-plaid-link", "data"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input({"type": "ws-qr", "id": ALL}, "n_clicks"),
    Input({"type": "ws-act", "id": ALL}, "n_clicks"),
    Input("ws-send", "n_clicks"),
    Input("ws-input", "n_submit"),
    Input({"type": "ws-step", "step": ALL}, "n_clicks"),
    Input({"type": "ws-run", "id": ALL}, "n_clicks"),
    Input({"type": "ws-approve", "id": ALL}, "n_clicks"),
    Input({"type": "ws-select-model", "id": ALL}, "n_clicks"),
    Input({"type": "ws-frontier", "id": ALL}, "clickData"),
    Input({"type": "ws-confirm", "id": ALL}, "n_clicks"),
    Input("ws-attach", "contents"),
    Input({"type": "ws-upload", "id": ALL}, "contents"),
    Input({"type": "ws-plaid", "id": ALL}, "n_clicks"),
    Input("ws-plaid-public", "data"),
    State("ws-input", "value"),
    State("ws-attach", "filename"),
    State({"type": "ws-upload", "id": ALL}, "filename"),
    State({"type": "ws-budget", "id": ALL}, "value"),
    State({"type": "ws-preview-grid", "id": ALL}, "rowData"),
    State({"type": "ws-assume", "id": ALL}, "value"),
    State("ws-tid", "data"),
    State("ws-turn", "data"),
    State("ws-meta", "data"),
    State("ws-thread-data", "data"),
    State("session", "data"),
    running=[(Output("ws-typing", "className"), "ts-typing", "ts-typing ts-hidden"),
             (Output("ws-chips", "className"), "ts-dim", ""),
             (Output("ws-canvas", "className"), "ts-busy", "")],
    prevent_initial_call=True,
)
def converse(_qr, _act, _send, _submit, _step, _run, _approve, _sel, _fr, _confirm, attach, uploads,
             _plaid, plaid_public, text, attach_name, upload_names, budgets, preview_rows, assume,
             tid, turn, meta, thread_items, session):
    trig, value = _fired()
    kind = trig.get("type") if isinstance(trig, dict) else trig
    client = api(_tok(session))
    user_text: str | None = None
    clear_input = no_update
    try:
        if kind in ("ws-qr", "ws-act"):
            rid = trig["id"]
            user_text = _label(turn, rid)
            new = client.chat(tid, quick_reply=rid)
        elif kind in ("ws-send", "ws-input"):
            if not (text or "").strip():
                raise PreventUpdate
            user_text, clear_input = text.strip(), ""
            new = client.chat(tid, message=user_text)
        elif kind == "ws-step":
            new = None
            for target in STEP_BACK_TARGETS[trig["step"]]:
                try:
                    new = client.back(tid, target)
                    break
                except AuthError:
                    raise
                except ApiError as exc:
                    if exc.status >= 500:
                        raise
            if new is None:
                raise PreventUpdate
            user_text = f"Back to {STEPS[trig['step'] - 1].lower()}"
        elif kind == "ws-run":
            v = int(_first(budgets) or 0)
            rid = f"budget:tax:{v}"
            user_text = f"Run with up to {fmt.money_full(v)} tax"
            new = client.chat(tid, quick_reply=rid)
        elif kind == "ws-approve":
            user_text = "Trade" if (turn or {}).get("state") == "TRANSITION_APPROVE" \
                else "Approve transition"
            new = client.chat(tid, action="approve")
        elif kind == "ws-select-model":
            user_text = f"Select {trig['id']}"
            new = client.chat(tid, quick_reply=f"choose:{trig['id']}")
        elif kind == "ws-frontier":
            pt = (value or {}).get("points", [{}])[0]
            if pt.get("curveNumber") != 1 or not pt.get("customdata"):
                raise PreventUpdate
            budget = round(pt["customdata"][0])
            user_text = f"Run with up to {fmt.money_full(budget)} tax"
            new = client.chat(tid, quick_reply=f"budget:tax:{budget}")
        elif kind == "ws-confirm":
            rows = _confirm_rows(_first(preview_rows) or [])
            client.confirm_ingest(tid, {"rows": rows, "assume_average_cost": "yes" in (_first(assume) or [])})
            user_text = "Confirm holdings"
            new = client.chat(tid)
        elif kind in ("ws-attach", "ws-upload"):
            contents = attach if kind == "ws-attach" else value
            name = attach_name if kind == "ws-attach" else _first(upload_names)
            _, b64 = contents.split(",", 1)
            client.upload_pdf(tid, name or "statement.pdf", base64.b64decode(b64))
            user_text = f"Uploaded {name or 'statement.pdf'}"
            new = client.chat(tid)
        elif kind == "ws-plaid":
            link = client.plaid_link_token()
            if link.mode != "mock" or not link.mock_public_token:
                # live Plaid: assets/plaid.js opens Link and writes ws-plaid-public on success
                return (no_update,) * 4 + (link.link_token, no_update, no_update)
            client.plaid_exchange(tid, link.mock_public_token)
            user_text = "Connected brokerage via Plaid"
            new = client.chat(tid)
        elif kind == "ws-plaid-public":
            client.plaid_exchange(tid, plaid_public)
            user_text = "Connected brokerage via Plaid"
            new = client.chat(tid)
        else:
            raise PreventUpdate
    except AuthError:
        return (no_update,) * 6 + (datetime.now().timestamp(),)
    except ApiError as exc:
        title = "Couldn't reach the server" if exc.status == 0 else "That didn't work"
        return (no_update,) * 3 + (clear_input, no_update, _note(title, exc.message), no_update)

    nt = _dump(new)
    items = list(thread_items or [])
    if user_text:
        items.append({"role": "user", "text": user_text})
    items.append({"role": "assistant", "text": nt["assistant_message"]})
    try:
        extra = _extra(client, tid, nt, meta)
    except AuthError:
        return (no_update,) * 6 + (datetime.now().timestamp(),)
    except ApiError:
        extra = {"client_href": f"/clients/{meta['client_id']}"}
    return nt, items, extra, clear_input, no_update, no_update, no_update


def _confirm_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if not r.get("include"):
            continue
        out.append({"row_id": r.get("row_id"), "lot_ref": (r.get("lot_ref") or "").strip() or None,
                    "ticker": (r.get("ticker") or "").strip().upper(),
                    "quantity": r.get("quantity"), "acquired_date": r.get("acquired_date") or None,
                    "cost_basis_total": r.get("cost_basis_total"), "include": True})
    return out


# ------------------------------------------------------------------ canvas helpers
@callback(
    Output({"type": "ws-budget-label", "id": ALL}, "children"),
    Input({"type": "ws-budget", "id": ALL}, "value"),
)
def budget_label(values):
    return [fmt.money_full(v or 0) for v in values]


@callback(
    Output({"type": "ws-model-grid", "id": ALL}, "children"),
    Input({"type": "ws-model-search", "id": ALL}, "value"),
    State("ws-turn", "data"),
    State({"type": "ws-model-grid", "id": ALL}, "id"),
    prevent_initial_call=True,
)
def search_models(values, turn, grids):
    from components.canvas.model_list import card

    if not turn or not values or not grids:  # the grouped picker has its own search
        raise PreventUpdate
    q = (values[0] or "").strip().lower()
    models = (turn.get("ui_payload") or {}).get("data", {}).get("models", [])
    hits = [m for m in models if not q or q in f"{m['model_id']} {m['name']} {m['construction']}".lower()]
    return [[card(m) for m in hits] or [fmt_empty()]]


@callback(
    Output({"type": "ws-model-groups", "id": ALL}, "children"),
    Input({"type": "ws-model-search", "id": ALL}, "value"),
    State("ws-extra", "data"),
    State({"type": "ws-model-groups", "id": ALL}, "id"),
    prevent_initial_call=True,
)
def search_grouped(values, extra, groups):
    from components.canvas.model_list import grouped_picker

    if not values or not groups or not (extra or {}).get("catalog"):
        raise PreventUpdate
    return [grouped_picker(extra["catalog"], values[0] or "")]


@callback(
    Output({"type": "ws-line-body", "id": MATCH}, "style"),
    Output({"type": "ws-line-btn", "id": MATCH}, "children"),
    Input({"type": "ws-line-btn", "id": MATCH}, "n_clicks"),
)
def toggle_pick_line(n):
    from components.model_mgmt import fold_label

    o = bool((n or 0) % 2)
    return {"display": "block" if o else "none"}, fold_label(o)


def fmt_empty():
    from dash import html

    return html.P("No models match your search.", className="ts-sub")


@callback(
    Output({"type": "ws-lock-grid", "id": ALL}, "rowData"),
    Output({"type": "ws-lock-state", "id": ALL}, "data"),
    Output({"type": "ws-lock-count", "id": ALL}, "children"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input({"type": "ws-lock-grid", "id": ALL}, "cellClicked"),
    Input({"type": "ws-lock-grid", "id": ALL}, "cellValueChanged"),
    State({"type": "ws-lock-state", "id": ALL}, "data"),
    State("ws-tid", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def lock_table(clicked, changed, states, tid, session):
    """Lock table grouped by ticker: clicking a ticker shows/hides its lots; the checkbox on a
    ticker locks or unlocks all of its lots, on a lot just that lot. Lots locked on the account
    itself always stay locked."""
    if not states or not states[0]:
        raise PreventUpdate
    lots, expanded = states[0]["lots"], list(states[0]["expanded"])
    prop = (ctx.triggered[0]["prop_id"] if ctx.triggered else "").rsplit(".", 1)[-1]
    if prop == "cellClicked":
        c = (clicked or [None])[0] or {}
        rid = str(c.get("rowId") or "")
        if c.get("colId") != "label" or not rid.startswith("t:"):
            raise PreventUpdate
        tk = rid[2:]
        expanded = [x for x in expanded if x != tk] if tk in expanded else [*expanded, tk]
        state = {"lots": lots, "expanded": expanded}
        return [lock_rows(lots, expanded)], [state], [no_update], no_update, no_update
    ev = (changed or [None])[0]
    if isinstance(ev, list):
        ev = ev[-1] if ev else None
    if not ev or ev.get("colId") != "locked":
        raise PreventUpdate
    row, value = ev["data"], bool(ev["data"].get("locked"))
    hit = (lambda x: x["ticker"] == row["ticker"]) if row.get("kind") == "ticker" \
        else (lambda x: x["lot_id"] == row.get("lot_id"))
    lots = [{**x, "locked": value or bool(x.get("account_locked"))} if hit(x) else x for x in lots]
    state = {"lots": lots, "expanded": expanded}
    ids = [x["lot_id"] for x in lots if x["locked"] and not x.get("account_locked")]
    try:
        api(_tok(session)).set_locks(tid, ids)
    except AuthError:
        return no_update, no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        # revert the table to the last saved state
        return ([lock_rows(states[0]["lots"], expanded)], [states[0]], [no_update],
                _note("Couldn't save locks", exc.message), no_update)
    n = sum(1 for x in lots if x["locked"])
    return [lock_rows(lots, expanded)], [state], [f"{n} locked"], no_update, no_update


@callback(
    Output("ws-download", "data"),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input({"type": "ws-dl", "id": ALL}, "n_clicks"),
    State("ws-tid", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def download(clicks, tid, session):
    if not any(c for c in clicks or []):
        raise PreventUpdate
    which = ctx.triggered_id["id"]
    try:
        client = api(_tok(session))
        if which == "csv":
            return dcc.send_bytes(client.trades_csv(tid), f"trades-{tid}.csv"), no_update, no_update
        return dcc.send_bytes(client.summary_pdf(tid), f"transition-{tid}.pdf"), no_update, no_update
    except AuthError:
        return no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return no_update, _note("Download failed", exc.message), no_update


# live Plaid Link (sandbox): assets/plaid.js loads cdn.plaid.com and sets ws-plaid-public
clientside_callback(
    """function (token) {
        if (!token || !window.tsPlaid) return window.dash_clientside.no_update;
        window.tsPlaid.open(token);
        return window.dash_clientside.no_update;
    }""",
    Output("ws-plaid-sink", "data"),
    Input("ws-plaid-link", "data"),
)
