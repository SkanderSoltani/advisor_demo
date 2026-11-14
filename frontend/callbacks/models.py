"""Model management callbacks: load the catalog; add / edit / delete lines and models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dash import ALL, MATCH, Input, Output, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

from components.common import error_state
from components.model_mgmt import catalog_view, fold_label, line_options, weight_rows
from components.shell import icon
from services.api_client import ApiError, AuthError, api

PAGE = {"type": "page-load", "page": "models"}


def _tok(session: dict | None) -> str | None:
    return (session or {}).get("token")


def _note(title: str, message: str, color: str = "green") -> list[dict]:
    return [{"action": "show", "id": f"mm-{datetime.now().timestamp()}", "title": title,
             "message": message, "color": color}]


def _err(msg: str) -> html.Div:
    return html.Div([icon("circle-alert", 16, "ts-shrink-0 ts-mt-05"), html.Span(msg)],
                    className="ts-alert-error ts-mt-4")


def _clicked() -> bool:
    """A real click (pattern-matching buttons also fire with 0/None when re-rendered)."""
    return bool(ctx.triggered and ctx.triggered[0].get("value"))


def _lines(cat: dict) -> list[dict]:
    return [ln for c in cat["categories"] for ln in c["lines"]]


def _models(cat: dict) -> list[dict]:
    return [mdl for c in cat["categories"]
            for mdl in [*(x for ln in c["lines"] for x in ln["models"]), *c["unassigned"]]]


# ================================================================== load
@callback(
    Output("mm-catalog", "data"),
    Output("mm-content", "children"),
    Output("mm-error", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input(PAGE, "data"),
    Input("mm-version", "data"),
    Input({"type": "mm-retry", "id": ALL}, "n_clicks"),
    State("session", "data"),
    State("mm-open", "data"),
    prevent_initial_call="initial_duplicate",
)
def load_catalog(_load, _version, _retry, session, open_lines):
    token = _tok(session)
    if not token:
        raise PreventUpdate
    try:
        cat = api(token).model_catalog()
    except AuthError:
        return no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return (no_update, None, error_state(exc.message, {"type": "mm-retry", "id": "models"}),
                no_update)
    return cat, catalog_view(cat, open_lines), None, no_update


# ================================================================== show / hide a line's models
@callback(
    Output({"type": "mm-fold-body", "id": MATCH}, "style"),
    Output({"type": "mm-fold-btn", "id": MATCH}, "children"),
    Output({"type": "mm-fold-btn", "id": MATCH}, "aria-expanded"),
    Input({"type": "mm-fold-btn", "id": MATCH}, "n_clicks"),
)
def fold_line(n):
    o = bool((n or 0) % 2)
    return {"display": "block" if o else "none"}, fold_label(o), "true" if o else "false"


@callback(
    Output("mm-open", "data"),
    Input({"type": "mm-fold-btn", "id": ALL}, "n_clicks"),
    State({"type": "mm-fold-btn", "id": ALL}, "id"),
    prevent_initial_call=True,
)
def remember_open(clicks, ids):
    """Open lines stay open when the catalog re-renders after an edit."""
    return [i["id"] for n, i in zip(clicks, ids, strict=True) if (n or 0) % 2]


# ================================================================== lines
@callback(
    Output("mm-line-modal", "opened"),
    Output("mm-line-target", "data"),
    Output("mm-line-title", "children"),
    Output("mm-line-name", "value"),
    Output("mm-line-cat", "value"),
    Output("mm-line-desc", "value"),
    Output("mm-line-error", "children"),
    Input("mm-add-line", "n_clicks"),
    Input({"type": "mm-edit-line", "id": ALL}, "n_clicks"),
    Input("mm-line-close", "n_clicks"),
    Input("mm-line-cancel", "n_clicks"),
    State("mm-catalog", "data"),
    prevent_initial_call=True,
)
def open_line(_add, _edit, _close, _cancel, cat):
    if not _clicked():
        raise PreventUpdate
    trig = ctx.triggered_id
    if trig in ("mm-line-close", "mm-line-cancel"):
        return False, no_update, no_update, no_update, no_update, no_update, None
    if trig == "mm-add-line":
        return True, None, "Add line", "", "total_return", "", None
    ln = next((x for x in _lines(cat or {"categories": []}) if x["id"] == trig["id"]), None)
    if ln is None:
        raise PreventUpdate
    return True, ln["id"], "Edit line", ln["name"], ln["objective"], ln["description"], None


@callback(
    Output("mm-line-modal", "opened", allow_duplicate=True),
    Output("mm-line-error", "children", allow_duplicate=True),
    Output("mm-version", "data", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mm-line-save", "n_clicks"),
    State("mm-line-target", "data"),
    State("mm-line-name", "value"),
    State("mm-line-cat", "value"),
    State("mm-line-desc", "value"),
    State("mm-version", "data"),
    State("session", "data"),
    running=[(Output("mm-line-save", "disabled"), True, False)],
    prevent_initial_call=True,
)
def save_line(n, target, name, objective, desc, version, session):
    if not n:
        raise PreventUpdate
    name = (name or "").strip()
    if not name:
        return no_update, _err("Give the line a name."), no_update, no_update, no_update
    body = {"name": name, "objective": objective, "description": (desc or "").strip()}
    try:
        a = api(_tok(session))
        if target:
            a.update_line(target, body)
        else:
            a.create_line(body)
    except AuthError:
        return no_update, no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return no_update, _err(exc.message), no_update, no_update, no_update
    msg = f"“{name}” was {'updated' if target else 'added'}."
    return False, None, (version or 0) + 1, _note("Line saved", msg), no_update


# ================================================================== models
@callback(
    Output("mm-model-modal", "opened"),
    Output("mm-model-target", "data"),
    Output("mm-model-title", "children"),
    Output("mm-model-name", "value"),
    Output("mm-model-line", "data"),
    Output("mm-model-line", "value"),
    Output("mm-model-risk", "data"),
    Output("mm-model-risk", "value"),
    Output("mm-model-desc", "value"),
    Output("mm-model-fee", "value"),
    Output("mm-w-rows", "children"),
    Output("mm-model-error", "children"),
    Input("mm-add-model", "n_clicks"),
    Input({"type": "mm-line-add-model", "id": ALL}, "n_clicks"),
    Input({"type": "mm-edit-model", "id": ALL}, "n_clicks"),
    Input("mm-model-close", "n_clicks"),
    Input("mm-model-cancel", "n_clicks"),
    State("mm-catalog", "data"),
    prevent_initial_call=True,
)
def open_model(_add, _line_add, _edit, _close, _cancel, cat):
    if not _clicked():
        raise PreventUpdate
    trig = ctx.triggered_id
    if trig in ("mm-model-close", "mm-model-cancel"):
        return (False,) + (no_update,) * 10 + (None,)
    if not cat:
        raise PreventUpdate
    lines, risks = line_options(cat), cat["risk_profiles"]
    if trig == "mm-add-model" or trig["type"] == "mm-line-add-model":
        all_lines = _lines(cat)
        line_id = trig["id"] if trig != "mm-add-model" else (all_lines[0]["id"] if all_lines else None)
        return (True, None, "Add model", "", lines, line_id, risks, None, "", 0,
                weight_rows(cat, {}), None)
    mdl = next((x for x in _models(cat) if x["id"] == trig["id"]), None)
    if mdl is None:
        raise PreventUpdate
    risk_data = risks if mdl["risk_profile"] in risks or not mdl["risk_profile"] \
        else [*risks, mdl["risk_profile"]]
    weights = {h["ticker"]: h["weight"] for h in mdl["holdings"]}
    return (True, mdl["id"], f"Edit {mdl['name']}", mdl["name"], lines, mdl["line_id"],
            risk_data, mdl["risk_profile"] or None, mdl["description"], mdl["advisory_fee_bps"],
            weight_rows(cat, weights), None)


@callback(
    Output("mm-w-total", "children"),
    Output("mm-w-total", "className"),
    Input({"type": "mm-w", "t": ALL}, "value"),
)
def weight_total(values):
    total = sum(float(v) for v in values if v not in (None, ""))
    ok = abs(total - 100) < 0.05
    return f"Total {total:.2f}%", "ts-mm-w-total " + ("is-ok" if ok else "is-off")


@callback(
    Output("mm-model-modal", "opened", allow_duplicate=True),
    Output("mm-model-error", "children", allow_duplicate=True),
    Output("mm-version", "data", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mm-model-save", "n_clicks"),
    State("mm-model-target", "data"),
    State("mm-model-name", "value"),
    State("mm-model-line", "value"),
    State("mm-model-risk", "value"),
    State("mm-model-desc", "value"),
    State("mm-model-fee", "value"),
    State({"type": "mm-w", "t": ALL}, "value"),
    State({"type": "mm-w", "t": ALL}, "id"),
    State("mm-version", "data"),
    State("session", "data"),
    running=[(Output("mm-model-save", "disabled"), True, False)],
    prevent_initial_call=True,
)
def save_model(n, target, name, line_id, risk, desc, fee, values, ids, version, session):
    if not n:
        raise PreventUpdate
    name = (name or "").strip()
    problem = ("Give the model a name." if not name else
               "Choose a line." if not line_id else
               "Choose a risk profile." if not risk else None)
    holdings = [{"ticker": i["t"], "weight": round(float(v) / 100, 6)}
                for v, i in zip(values, ids, strict=True) if v not in (None, "") and float(v) > 0]
    total = sum(h["weight"] for h in holdings)
    if problem is None and not holdings:
        problem = "Give at least one product a weight."
    if problem is None and abs(total - 1) > 0.0005:
        problem = f"Weights add up to {total * 100:.2f}%. They must add up to 100%."
    if problem:
        return no_update, _err(problem), no_update, no_update, no_update
    body = {"name": name, "line_id": line_id, "risk_profile": risk,
            "description": (desc or "").strip(), "advisory_fee_bps": float(fee or 0),
            "holdings": holdings}
    try:
        a = api(_tok(session))
        if target:
            a.update_catalog_model(target, body)
        else:
            a.create_catalog_model(body)
    except AuthError:
        return no_update, no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return no_update, _err(exc.message), no_update, no_update, no_update
    msg = f"“{name}” was {'updated' if target else 'added'}."
    return False, None, (version or 0) + 1, _note("Model saved", msg), no_update


# ================================================================== delete
@callback(
    Output("mm-del-modal", "opened"),
    Output("mm-del-target", "data"),
    Output("mm-del-title", "children"),
    Output("mm-del-body", "children"),
    Output("mm-del-error", "children"),
    Input({"type": "mm-del-line", "id": ALL}, "n_clicks"),
    Input({"type": "mm-del-model", "id": ALL}, "n_clicks"),
    Input("mm-del-cancel", "n_clicks"),
    State("mm-catalog", "data"),
    prevent_initial_call=True,
)
def open_delete(_l, _m, _cancel, cat):
    if not _clicked():
        raise PreventUpdate
    trig = ctx.triggered_id
    if trig == "mm-del-cancel":
        return False, None, no_update, no_update, None
    if not cat:
        raise PreventUpdate
    if trig["type"] == "mm-del-line":
        ln = next((x for x in _lines(cat) if x["id"] == trig["id"]), None)
        if ln is None:
            raise PreventUpdate
        n = len(ln["models"])
        body = ([f"This deletes the line “{ln['name']}” and its {n} model{'s' if n != 1 else ''}: ",
                 html.Strong(", ".join(x["name"] for x in ln["models"])), "."] if n else
                [f"The line “{ln['name']}” has no models."])
        return (True, {"kind": "line", "id": ln["id"], "name": ln["name"]}, "Delete line?",
                [*body, " This can't be undone."], None)
    mdl = next((x for x in _models(cat) if x["id"] == trig["id"]), None)
    if mdl is None:
        raise PreventUpdate
    warn = (f" {mdl['n_accounts']} account(s) target this model, so it can't be deleted until "
            "they move to another model." if mdl["n_accounts"] else "")
    return (True, {"kind": "model", "id": mdl["id"], "name": mdl["name"]}, "Delete model?",
            [f"This removes “{mdl['name']}” from the catalog. This can't be undone.", warn], None)


@callback(
    Output("mm-del-modal", "opened", allow_duplicate=True),
    Output("mm-del-error", "children", allow_duplicate=True),
    Output("mm-version", "data", allow_duplicate=True),
    Output("notify", "sendNotifications", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mm-del-confirm", "n_clicks"),
    State("mm-del-target", "data"),
    State("mm-version", "data"),
    State("session", "data"),
    running=[(Output("mm-del-confirm", "disabled"), True, False)],
    prevent_initial_call=True,
)
def confirm_delete(n, target: dict[str, Any] | None, version, session):
    if not n or not target:
        raise PreventUpdate
    try:
        a = api(_tok(session))
        if target["kind"] == "line":
            a.delete_line(target["id"])
        else:
            a.delete_catalog_model(target["id"])
    except AuthError:
        return no_update, no_update, no_update, no_update, datetime.now().timestamp()
    except ApiError as exc:
        return no_update, _err(exc.message), no_update, no_update, no_update
    what = "Line" if target["kind"] == "line" else "Model"
    return (False, None, (version or 0) + 1,
            _note(f"{what} deleted", f"“{target['name']}” was deleted."), no_update)
