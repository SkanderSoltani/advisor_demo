"""Model Builder callbacks: the draft (holdings, name, scale settings) lives in ``mb-draft``; the
canvas and the AI guide both edit it. Analytics, scaling and saving are API calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dash import ALL, Input, Output, State, callback, clientside_callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from components.chat_panel import bubble
from components.common import error_state, sim_badge
from components.model_builder import (
    analytics_view,
    bench_banner,
    builder_header,
    chips,
    holdings_editor,
    line_preview,
)
from components.shell import icon
from components.transition_analytics import HIDDEN
from services.api_client import ApiError, AuthError, api

PAGE = {"type": "page-load", "page": "model-builder"}
DEFAULT_DRAFT = {"name": "My model", "objective": "total_return", "holdings": {}, "step": "build",
                 "scale_n": 10, "scale_lo": 10, "scale_hi": 100, "line_name": "",
                 "saved_line_id": None, "saved_model_ids": []}


def _tok(session: dict | None) -> str | None:
    return (session or {}).get("token")


def _expired() -> float:
    return datetime.now().timestamp()


def _clicked() -> bool:
    return bool(ctx.triggered and ctx.triggered[0].get("value"))


def _total(h: dict[str, float]) -> tuple[str, str]:
    tot = sum(h.values()) * 100
    ok = abs(tot - 100) < 0.05
    return f"Total {tot:.2f}%", "ts-mm-w-total " + ("is-ok" if ok else "is-off")


def _thread(items: list[dict[str, str]]) -> list[Any]:
    return [bubble(x["role"], x["text"]) for x in items]


def _note(text: str, ok: bool = True) -> html.Div:
    return html.Div([icon("circle-check" if ok else "circle-alert", 16,
                          "ts-c-positive" if ok else "ts-c-negative"), dcc.Markdown(text)],
                    className="ts-bld-note")


# ================================================================== load
@callback(
    Output("mb-names", "data"),
    Output("mb-search", "data"),
    Output("mb-start", "data"),
    Output("mb-draft", "data"),
    Output("mb-thread-data", "data"),
    Output("mb-thread", "children"),
    Output("mb-chips", "children"),
    Output("mb-holdings", "children"),
    Output("auth-expired", "data", allow_duplicate=True),
    Input(PAGE, "data"),
    State("session", "data"),
    prevent_initial_call="initial_duplicate",
)
def load(_p, session):
    token = _tok(session)
    if not token:
        raise PreventUpdate
    try:
        a = api(token)
        uni = a.mb_universe(limit=400)
        cat = a.model_catalog()
        turn = a.mb_assist(DEFAULT_DRAFT)
    except AuthError:
        return (no_update,) * 8 + (_expired(),)
    except ApiError as exc:
        return ({}, [], [], DEFAULT_DRAFT, [], [error_state(exc.message)], None, no_update,
                no_update)
    names = {x["ticker"]: x for x in uni}
    funds = [{"value": x["ticker"], "label": f"{x['ticker']} — {x['name']}"}
             for x in uni if x["kind"] == "fund"]
    stocks = [{"value": x["ticker"], "label": f"{x['ticker']} — {x['name']} ({x['sector']})"}
              for x in uni if x["kind"] == "stock"]
    search = [{"group": "Funds & ETFs", "items": funds}, {"group": "Stocks", "items": stocks}]
    start = [{"group": f"{ln['name']} ({c['label']})",
              "items": [{"value": m["id"], "label": m["name"]} for m in ln["models"]]}
             for c in cat["categories"] for ln in c["lines"] if ln["models"]]
    thread = [{"role": "ai", "text": turn["message"]}]
    return (names, search, start, turn["draft"], thread, _thread(thread),
            chips(turn["quick_replies"]), holdings_editor({}, names), no_update)


# ================================================================== canvas edits
@callback(
    Output("mb-draft", "data", allow_duplicate=True),
    Output("mb-holdings", "children", allow_duplicate=True),
    Output("mb-total", "children"),
    Output("mb-total", "className"),
    Output("mb-import-note", "children"),
    Output("mb-search", "value"),
    Output("mb-start", "value"),
    Output("mb-refresh", "data", allow_duplicate=True),
    Output("mb-name", "value", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mb-add", "n_clicks"),
    Input({"type": "mb-rm", "t": ALL}, "n_clicks"),
    Input({"type": "mb-w", "t": ALL}, "value"),
    Input("mb-normalize", "n_clicks"),
    Input("mb-clear", "n_clicks"),
    Input("mb-start", "value"),
    Input("mb-upload", "contents"),
    Input("mb-name", "value"),
    Input("mb-n", "value"),
    Input("mb-lo", "value"),
    Input("mb-hi", "value"),
    Input("mb-line-name", "value"),
    Input("mb-objective", "value"),
    State({"type": "mb-w", "t": ALL}, "id"),
    State("mb-draft", "data"),
    State("mb-search", "value"),
    State("mb-add-w", "value"),
    State("mb-upload", "filename"),
    State("mb-names", "data"),
    State("mb-refresh", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def canvas_edit(_add, _rm, w_values, _norm, _clear, start, upload, name, n, lo, hi, line_name,
                objective, w_ids, draft, search, add_w, filename, names, refresh, session):
    d = dict(draft or DEFAULT_DRAFT)
    h = dict(d.get("holdings") or {})
    trig = ctx.triggered_id
    rerender, note, refresh_out = False, no_update, no_update
    clear_search, clear_start = no_update, no_update
    if trig == "mb-add":
        if not _add or not search:
            raise PreventUpdate
        h[search] = round(h.get(search, 0.0) + float(add_w or 0) / 100, 6)
        rerender, clear_search = True, None
    elif isinstance(trig, dict) and trig.get("type") == "mb-rm":
        if not _clicked():
            raise PreventUpdate
        h.pop(trig["t"], None)
        rerender = True
    elif isinstance(trig, dict) and trig.get("type") == "mb-w":
        new = {i["t"]: round(float(v or 0) / 100, 6) for i, v in zip(w_ids, w_values, strict=True)}
        if new == {k: round(v, 6) for k, v in h.items()}:
            raise PreventUpdate
        h = new
    elif trig == "mb-normalize":
        tot = sum(h.values())
        if not _norm or tot <= 0:
            raise PreventUpdate
        h = {k: round(v / tot, 6) for k, v in h.items()}
        rerender = True
    elif trig == "mb-clear":
        if not _clear:
            raise PreventUpdate
        h, rerender = {}, True
        d.update(step="build", saved_line_id=None, saved_model_ids=[])
    elif trig == "mb-start":
        if not start:
            raise PreventUpdate
        try:
            cat = api(_tok(session)).model_catalog()
        except AuthError:
            return (no_update,) * 9 + (_expired(),)
        m = next((m for c in cat["categories"] for ln in c["lines"] for m in ln["models"]
                  if m["id"] == start), None)
        if m is None:
            raise PreventUpdate
        h = {x["ticker"]: x["weight"] for x in m["holdings"]}
        d["name"] = f"My {m['name']}"
        d["step"] = "analyze"
        rerender, clear_start, refresh_out = True, None, (refresh or 0) + 1
        note = _note(f"Copied **{m['name']}** ({len(h)} holdings). Edit it freely.")
    elif trig == "mb-upload":
        if not upload:
            raise PreventUpdate
        try:
            res = api(_tok(session)).mb_import(filename or "model.xlsx", upload)
        except AuthError:
            return (no_update,) * 9 + (_expired(),)
        except ApiError as exc:
            return (no_update, no_update, no_update, no_update, _note(exc.message, ok=False),
                    no_update, no_update, no_update, no_update, no_update)
        h = res["holdings"]
        d["name"] = (filename or "Imported model").rsplit(".", 1)[0].replace("_", " ")[:60]
        d["step"] = "analyze"
        rerender, refresh_out = True, (refresh or 0) + 1
        note = _note(f"**{filename}**: {res['note']}", ok=not res["unmatched"])
    elif trig == "mb-name":
        d["name"] = (name or "").strip() or "My model"
    elif trig in ("mb-n", "mb-lo", "mb-hi"):
        d.update(scale_n=int(n or 10), scale_lo=int(lo or 0), scale_hi=int(hi or 100))
    elif trig == "mb-line-name":
        d["line_name"] = (line_name or "").strip()
    elif trig == "mb-objective":
        d["objective"] = objective or "total_return"
    else:
        raise PreventUpdate
    d["holdings"] = h
    total, total_cls = _total(h)
    name_out = d["name"] if trig in ("mb-start", "mb-upload") else no_update
    return (d, holdings_editor(h, names or {}) if rerender else no_update, total, total_cls, note,
            clear_search, clear_start, refresh_out, name_out, no_update)


# ================================================================== analytics
@callback(
    Output("mb-report", "data"),
    Output("mb-bench", "children"),
    Output("mb-sim", "children"),
    Output("mb-draft", "data", allow_duplicate=True),
    Output("mb-analytics", "children", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mb-run", "n_clicks"),
    Input("mb-refresh", "data"),
    State("mb-draft", "data"),
    State("session", "data"),
    running=[(Output("mb-run", "disabled"), True, False)],
    prevent_initial_call=True,
)
def run_analytics(_run, _refresh, draft, session):
    d = dict(draft or DEFAULT_DRAFT)
    if not d.get("holdings"):
        return (None, None, None, no_update,
                html.P("Add holdings first.", className="ts-mm-empty"), no_update)
    try:
        r = api(_tok(session)).mb_analyze(d["holdings"], d.get("name") or "My model")
    except AuthError:
        return (no_update,) * 5 + (_expired(),)
    except ApiError as exc:
        return None, None, None, no_update, error_state(exc.message), no_update
    if d.get("step") == "build":
        d["step"] = "analyze"
    return r, bench_banner(r), sim_badge("mock_random"), d, no_update, no_update


@callback(
    Output("mb-analytics", "children"),
    Input("mb-report", "data"),
    State("mb-tab", "value"),
)
def render_analytics(r, tab):
    """All five tabs are rendered once per report; switching tabs only toggles visibility in the
    browser (no server round-trip, so the page height never collapses mid-switch)."""
    if not r:
        raise PreventUpdate
    tab = tab or "overview"
    return [html.Div(analytics_view(r, k), id={"type": "mb-pane", "id": k},
                     style={} if k == tab else HIDDEN)
            for k in ("overview", "equity", "fi", "risk", "perf")]


clientside_callback(
    "function(tab, ids) { return window.dash_clientside.ts.switchTab('#mb-analytics', tab, ids); }",
    Output({"type": "mb-pane", "id": ALL}, "style"),
    Input("mb-tab", "value"),
    State({"type": "mb-pane", "id": ALL}, "id"),
    prevent_initial_call=True,
)


# ================================================================== guide
@callback(
    Output("mb-thread-data", "data", allow_duplicate=True),
    Output("mb-thread", "children", allow_duplicate=True),
    Output("mb-chips", "children", allow_duplicate=True),
    Output("mb-draft", "data", allow_duplicate=True),
    Output("mb-holdings", "children", allow_duplicate=True),
    Output("mb-input", "value"),
    Output("mb-refresh", "data", allow_duplicate=True),
    Output("mb-scale-go", "data", allow_duplicate=True),
    Output("mb-name", "value"),
    Output("mb-n", "value"),
    Output("mb-lo", "value"),
    Output("mb-hi", "value"),
    Output("mb-line-name", "value"),
    Output("mb-objective", "value"),
    Output("mb-save-note", "children", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mb-send", "n_clicks"),
    Input("mb-input", "n_submit"),
    Input({"type": "mb-qr", "id": ALL}, "n_clicks"),
    State("mb-input", "value"),
    State("mb-draft", "data"),
    State("mb-thread-data", "data"),
    State("mb-names", "data"),
    State("mb-refresh", "data"),
    State("mb-scale-go", "data"),
    State("session", "data"),
    running=[(Output("mb-typing", "className"), "ts-typing", "ts-typing ts-hidden")],
    prevent_initial_call=True,
)
def guide(_send, _submit, _qr, text, draft, thread, names, refresh, scale_go, session):
    trig = ctx.triggered_id
    reply = message = None
    if isinstance(trig, dict) and trig.get("type") == "mb-qr":
        if not _clicked():
            raise PreventUpdate
        reply = trig["id"]
    else:
        message = (text or "").strip()
        if not message:
            raise PreventUpdate
    try:
        turn = api(_tok(session)).mb_assist(draft or DEFAULT_DRAFT, message=message, reply=reply)
    except AuthError:
        return (no_update,) * 15 + (_expired(),)
    except ApiError as exc:
        turn = {"draft": draft, "message": f"Sorry — {exc.message}", "quick_replies": [],
                "refresh_analytics": False}
    d_old, d = draft or DEFAULT_DRAFT, turn["draft"]
    items = list(thread or [])
    if message is not None:
        items.append({"role": "user", "text": message})
    else:
        items.append({"role": "user", "text": _reply_label(reply)})
    items.append({"role": "ai", "text": turn["message"]})
    structure = d["holdings"] != d_old.get("holdings")
    new_scale = d["step"] == "scale" and (
        d_old.get("step") != "scale" or any(d[k] != d_old.get(k)
                                            for k in ("scale_n", "scale_lo", "scale_hi")))
    saved = d.get("saved_line_id") and d.get("saved_line_id") != d_old.get("saved_line_id")
    return (items, _thread(items), chips(turn["quick_replies"]), d,
            holdings_editor(d["holdings"], names or {}) if structure else no_update, "",
            (refresh or 0) + 1 if turn.get("refresh_analytics") else no_update,
            (scale_go or 0) + 1 if new_scale else no_update,
            d["name"], d["scale_n"], d["scale_lo"], d["scale_hi"], d["line_name"] or None,
            d["objective"],
            _saved_note(d) if saved else no_update, no_update)


REPLY_LABELS = {"import": "Import a file", "help": "What can you do?", "analyze": "Run analytics",
                "less_risk": "Less risk", "more_risk": "More risk", "go_scale": "Scale into a line",
                "go_save": "Save this line", "restart": "Build another model",
                "explain:benchmark": "Which benchmark?"}


def _reply_label(rid: str | None) -> str:
    if not rid:
        return ""
    if rid in REPLY_LABELS:
        return REPLY_LABELS[rid]
    if rid.startswith("start:"):
        return f"Start from {rid.split(':', 1)[1]}"
    if rid.startswith("scale:"):
        n, lo, hi = rid.split(":")[1:]
        return f"{n} models from {lo}/{100 - int(lo)} to {hi}/{100 - int(hi)}"
    if rid.startswith("objective:"):
        return {"total_return": "Total Return", "income": "Income",
                "tax_efficient": "Tax Efficient"}.get(rid.split(":", 1)[1], rid)
    return rid


def _saved_note(d: dict[str, Any]) -> html.Div:
    ids = d.get("saved_model_ids") or []
    return _note(f"Saved **{d.get('line_name') or d.get('name')}** under Custom Models with "
                 f"{len(ids)} models ({ids[0] if ids else ''} … {ids[-1] if ids else ''}). "
                 "Open [Model management](/models) to see it.")


# ================================================================== scale + save
@callback(
    Output("mb-line", "children"),
    Output("mb-draft", "data", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mb-preview", "n_clicks"),
    Input("mb-scale-go", "data"),
    State("mb-draft", "data"),
    State("session", "data"),
    running=[(Output("mb-preview", "disabled"), True, False)],
    prevent_initial_call=True,
)
def preview_line(_n, _go, draft, session):
    d = dict(draft or DEFAULT_DRAFT)
    if not d.get("holdings"):
        return html.P("Build the model first.", className="ts-mm-empty"), no_update, no_update
    try:
        models = api(_tok(session)).mb_scale(d["holdings"], d["scale_n"], d["scale_lo"],
                                             d["scale_hi"])
    except AuthError:
        return no_update, no_update, _expired()
    except ApiError as exc:
        return error_state(exc.message), no_update, no_update
    if d.get("step") in ("build", "analyze"):
        d["step"] = "scale"
    return line_preview(models), d, no_update


@callback(
    Output("mb-save-note", "children"),
    Output("mb-draft", "data", allow_duplicate=True),
    Output("mb-thread-data", "data", allow_duplicate=True),
    Output("mb-thread", "children", allow_duplicate=True),
    Output("auth-expired", "data", allow_duplicate=True),
    Input("mb-save", "n_clicks"),
    State("mb-draft", "data"),
    State("mb-thread-data", "data"),
    State("session", "data"),
    running=[(Output("mb-save", "disabled"), True, False)],
    prevent_initial_call=True,
)
def save_line(n, draft, thread, session):
    if not n:
        raise PreventUpdate
    d = dict(draft or DEFAULT_DRAFT)
    if not d.get("holdings"):
        return _note("Build the model first.", ok=False), no_update, no_update, no_update, no_update
    if not (d.get("line_name") or "").strip():
        return (_note("Give the line a name first.", ok=False), no_update, no_update, no_update,
                no_update)
    try:
        res = api(_tok(session)).mb_save(d)
    except AuthError:
        return no_update, no_update, no_update, no_update, _expired()
    except ApiError as exc:
        return _note(exc.message, ok=False), no_update, no_update, no_update, no_update
    d.update(saved_line_id=res["line_id"], saved_model_ids=res["model_ids"], step="done")
    msg = (f"Saved **{d['line_name']}** with {len(res['model_ids'])} models under Custom Models. "
           "They're in [Model management](/models) and can be used as transition targets.")
    items = [*list(thread or []), {"role": "ai", "text": msg}]
    return _saved_note(d), d, items, _thread(items), no_update


# ================================================================== header, samples, scroll
@callback(Output("mb-header", "children"), Input("mb-draft", "data"))
def header(draft):
    return builder_header((draft or {}).get("step", "build"))


@callback(
    Output("mb-download", "data"),
    Input("mb-sample-xlsx", "n_clicks"),
    Input("mb-sample-pdf", "n_clicks"),
    State("session", "data"),
    prevent_initial_call=True,
)
def sample(_x, _p, session):
    if not _clicked():
        raise PreventUpdate
    fmt_ = "pdf" if ctx.triggered_id == "mb-sample-pdf" else "xlsx"
    data = api(_tok(session)).mb_sample(fmt_)
    return dcc.send_bytes(data, f"sample_model_growth_income_70_30.{fmt_}")


clientside_callback(
    """function(_children) {
        const el = document.getElementById('mb-scroll');
        if (el) { setTimeout(() => { el.scrollTop = el.scrollHeight; }, 50); }
        return null;
    }""",
    Output("mb-scroll-sink", "data"),
    Input("mb-thread", "children"),
)

