"""Step 3 — choose a target from the catalog (React step 3 cards). Also the confirm step."""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from components.canvas.common import act, arrow, header, reply_actions
from components.model_mgmt import (
    CATEGORY_ICON,
    _holdings,
    _line_summary,
    fold_label,
    provider_heading,
    split_by_provider,
)
from components.shell import icon
from services import format as fmt

OBJECTIVES = {"income": "Income", "total_return": "Total return", "tax_efficient": "Tax efficient"}
CONSTRUCTIONS = {"market_cap": "Market cap", "market_cap_fundamental": "Market cap + fundamental",
                 "market_cap_fundamental_active": "Market cap + fundamental + active"}


def card(m: dict[str, Any], selected: bool = False, clickable: bool = True) -> Any:
    body = [
        html.P(m["model_id"], className="ts-model-id"),
        html.P(m["name"], className="ts-model-name"),
        html.P(OBJECTIVES.get(m["objective"], m["objective"]), className="ts-sub-sm ts-mt-2"),
        html.P(CONSTRUCTIONS.get(m["construction"], m["construction"]), className="ts-sub ts-mt-5"),
        html.Div([html.Span(f"{fmt.pct(m['fee_bps'] / 10000)} fee", className="ts-model-fee"),
                  html.Span(f"Yield {fmt.pct(m['target_yield'])}", className="ts-sub")],
                 className="ts-row ts-between ts-mt-4"),
    ]
    cls = "ts-model-card" + (" is-selected" if selected else "")
    if not clickable:
        return html.Div(body, className=cls)
    return html.Button(body, id={"type": "ws-act", "id": f"choose:{m['model_id']}"}, n_clicks=0,
                       type="button", className=cls,
                       title=f"Expected TE vs benchmark {fmt.pct(m['expected_te_vs_benchmark'])}")


# ------------------------------------------------------------------ grouped picker
def _pick_row(m: dict[str, Any]) -> html.Tr:
    return html.Tr([
        html.Td([html.Div(m["name"], className="ts-fw-500 ts-c-navy"),
                 html.Div(m["id"], className="ts-mm-id")]),
        html.Td(html.Span(m["risk_profile"] or "—", className="ts-mm-risk")),
        html.Td(_holdings(m["holdings"][:4] + ([{"ticker": f"+{len(m['holdings']) - 4}",
                                                  "weight": None, "name": "more holdings"}]
                                                if len(m["holdings"]) > 4 else []))),
        html.Td(fmt.pct(m["target_yield"]) if m["target_yield"] is not None else "—",
                className="ts-num"),
        html.Td(f"{m['fee_bps']:.1f} bps" if m["fee_bps"] is not None else "—", className="ts-num"),
        html.Td(fmt.pct(m["expected_te"]) if m["expected_te"] is not None else "—",
                className="ts-num"),
        html.Td(act(f"choose:{m['id']}", "Select", extra_cls="ts-btn-sm"), className="ts-num"),
    ])


_PICK_HEAD = ["Model", "Mix", "Top holdings", "Yield", "Fee", "TE", ""]


def _pick_line(ln: dict[str, Any], is_open: bool) -> html.Div:
    n = len(ln["models"])
    table = html.Div(html.Table(
        [html.Thead(html.Tr([html.Th(h, className="ts-num" if h in ("Yield", "Fee", "TE")
                                     else None) for h in _PICK_HEAD])),
         html.Tbody([_pick_row(m) for m in ln["models"]])],
        className="ts-mm-table ts-pick-table"), className="ts-mm-table-wrap")
    return html.Div([
        html.Div([
            html.Div([html.Div([html.H3(ln["name"], className="ts-mm-line-name"),
                                html.Span(f"{n} model{'s' if n != 1 else ''}",
                                          className="ts-mm-count")], className="ts-row ts-gap-2"),
                      html.P(ln["description"], className="ts-sub ts-mt-1") if ln["description"]
                      else None,
                      html.Div(_line_summary(ln["models"]), className="ts-fold-summary ts-mt-2")]),
            html.Div(html.Button(fold_label(is_open), id={"type": "ws-line-btn", "id": ln["id"]},
                                 n_clicks=1 if is_open else 0, type="button",
                                 className="ts-btn ts-btn-secondary ts-btn-sm ts-fold-btn"),
                     className="ts-row"),
        ], className="ts-mm-line-head"),
        html.Div(table, id={"type": "ws-line-body", "id": ln["id"]},
                 style={"display": "block" if is_open else "none"}),
    ], className="ts-card ts-mm-line")


def grouped_picker(cat: dict[str, Any], query: str = "") -> list[Any]:
    """Schwab Models → category → line (closed, with a summary) → models with a Select button.
    With a search, only matching models show and their lines open."""
    q = query.strip().lower()

    def hit(m: dict[str, Any]) -> bool:
        return not q or q in f"{m['id']} {m['name']} {m['risk_profile']}".lower()

    out: list[Any] = []
    for k, (title, sub, cats) in enumerate(split_by_provider(cat)):
        sections: list[Any] = []
        for c in cats:
            lines = [{**ln, "models": [m for m in ln["models"] if hit(m)]} for ln in c["lines"]]
            lines = [ln for ln in lines if ln["models"]]
            if not lines:
                continue
            n = sum(len(ln["models"]) for ln in lines)
            sections.append(html.Section([
                html.Div([html.Span(icon(CATEGORY_ICON.get(c["id"], "layers"), 18),
                                    className="ts-mm-cat-icon"),
                          html.H2(c["label"], className="ts-mm-cat-title"),
                          html.Span(f"{len(lines)} line{'s' if len(lines) != 1 else ''} · "
                                    f"{n} model{'s' if n != 1 else ''}", className="ts-sub")],
                         className="ts-row ts-gap-3 ts-mb-4"),
                html.Div([_pick_line(ln, bool(q)) for ln in lines], className="ts-stack-4"),
            ], className="ts-mb-6"))
        if sections:
            n_all = sum(1 for c in cats for ln in c["lines"] for mm in ln["models"] if hit(mm))
            out += [provider_heading(title, "Open a line to see its models." if not k else sub,
                                     n_all, "ts-mt-4" if out else ""), *sections]
    if not out:
        return [html.P("No models match your search.", className="ts-sub")]
    return out


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    models = turn["ui_payload"]["data"].get("models", [])
    if turn["state"] == "TARGET_CONFIRM":
        m = models[0] if models else None
        return [
            header(turn["state"], "Confirm target", "Use this model as the account's target?"),
            html.Div(card(m, selected=True, clickable=False), className="ts-model-grid") if m else None,
            html.Div([act("yes", arrow("Select this model "), primary=True),
                      act("no", "Choose another")], className="ts-canvas-actions"),
        ]
    search = dcc.Input(id={"type": "ws-model-search", "id": "c"}, type="search",
                       placeholder="Search models", debounce=False, className="ts-search")
    return [
        header(turn["state"], "Choose your target",
               "Select a model aligned to this client's objective."),
        html.Label([icon("search", 16, "ts-search-icon"), search],
                   className="ts-search-wrap ts-search-wide ts-mb-4"),
        html.Div(grouped_picker(extra["catalog"]), id={"type": "ws-model-groups", "id": "c"})
        if extra.get("catalog") else
        html.Div([card(m) for m in models], id={"type": "ws-model-grid", "id": "c"},
                 className="ts-model-grid"),
        reply_actions(turn, skip={f"choose:{m['model_id']}" for m in models}),
    ]
