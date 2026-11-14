"""Model management page pieces: category → line cards → model rows, and the edit dialogs."""

from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
from dash import dcc, html

from components.onboard_client_modal import field, text_input
from components.shell import icon
from services import format as fmt

CATEGORY_OPTIONS = [{"label": "Total Return", "value": "total_return"},
                    {"label": "Income", "value": "income"},
                    {"label": "Tax Efficient", "value": "tax_efficient"}]
CATEGORY_ICON = {"total_return": "trending-up", "income": "hand-coins", "tax_efficient": "receipt-text"}

_MODAL = dict(withCloseButton=False, centered=True, radius=12, padding=24, opened=False,
              overlayProps={"color": "#003D5C", "backgroundOpacity": 0.35},
              classNames={"content": "ts-modal"})


def _modal_head(eyebrow: str, title_id: str, close_id: str) -> html.Div:
    return html.Div(
        [html.Div([html.P(eyebrow, className="ts-eyebrow"),
                   html.H2(id=title_id, className="ts-modal-title")]),
         html.Button("×", id=close_id, n_clicks=0, type="button", className="ts-modal-x",
                     **{"aria-label": "Close dialog"})],
        className="ts-row ts-between ts-items-start ts-mb-6",
    )


# ------------------------------------------------------------------ page content
def _icon_btn(name: str, label: str, id_: dict[str, str], danger: bool = False) -> html.Button:
    return html.Button(icon(name, 15), id=id_, n_clicks=0, type="button", title=label,
                       className="ts-icon-btn" + (" is-danger" if danger else ""),
                       **{"aria-label": label})


def _holdings(h: list[dict[str, Any]]) -> html.Div:
    return html.Div([html.Span([html.B(x["ticker"]),
                               "" if x["weight"] is None
                               else f" {x['weight'] * 100:.1f}%".replace(".0%", "%")],
                               className="ts-chip ts-mm-chip", title=x["name"]) for x in h],
                    className="ts-mm-chips")


def _model_row(mdl: dict[str, Any]) -> html.Tr:
    n = mdl["n_accounts"]
    return html.Tr(
        [
            html.Td([html.Div(mdl["name"], className="ts-fw-500 ts-c-navy"),
                     html.Div(mdl["id"], className="ts-mm-id")]),
            html.Td(html.Span(mdl["risk_profile"] or "—", className="ts-mm-risk")),
            html.Td(_holdings(mdl["holdings"])),
            html.Td(fmt.pct(mdl["target_yield"]) if mdl["target_yield"] is not None else "—",
                    className="ts-num"),
            html.Td(f"{mdl['fee_bps']:.1f} bps" if mdl["fee_bps"] is not None else "—",
                    className="ts-num"),
            html.Td(fmt.pct(mdl["expected_te"]) if mdl["expected_te"] is not None else "—",
                    className="ts-num"),
            html.Td(str(n) if n else "—", className="ts-num",
                    title=f"{n} account(s) target this model" if n else "No accounts yet"),
            html.Td(html.Div([_icon_btn("pencil", "Edit model", {"type": "mm-edit-model", "id": mdl["id"]}),
                              _icon_btn("trash-2", "Delete model",
                                        {"type": "mm-del-model", "id": mdl["id"]}, danger=True)],
                             className="ts-row ts-gap-1 ts-justify-end")),
        ]
    )


_HEAD = ["Model", "Risk profile", "Holdings", "Yield", "Fee", "Expected TE", "Accounts", ""]


def _models_table(models: list[dict[str, Any]], empty: str) -> html.Div:
    if not models:
        return html.P(empty, className="ts-mm-empty")
    return html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th(h, className="ts-num" if h in
                                         ("Yield", "Fee", "Expected TE", "Accounts") else None)
                                 for h in _HEAD])),
             html.Tbody([_model_row(x) for x in models])],
            className="ts-mm-table",
        ),
        className="ts-mm-table-wrap",
    )


def _range(vals: list[float], fmt_one: Any) -> str:
    lo, hi = min(vals), max(vals)
    return fmt_one(lo) if abs(hi - lo) < 1e-9 else f"{fmt_one(lo)}–{fmt_one(hi)}"


def _line_summary(models: list[dict[str, Any]]) -> list[Any]:
    """One line shown while the line's models are hidden."""
    if not models:
        return [html.Span("No models yet")]
    out: list[Any] = []
    risks = [m["risk_profile"] for m in models if m["risk_profile"]]
    if risks:
        out.append(html.Span([html.Strong(risks[0] if len(risks) == 1
                                          else f"{risks[0]} to {risks[-1]}"), " allocations"]))
    fees = [m["fee_bps"] for m in models if m["fee_bps"] is not None]
    if fees:
        out.append(html.Span([html.Strong(_range(fees, lambda v: f"{v:.1f}")), " bps fee"]))
    ylds = [m["target_yield"] for m in models if m["target_yield"] is not None]
    if ylds:
        out.append(html.Span([html.Strong(_range(ylds, lambda v: fmt.pct(v))), " yield"]))
    n_acc = sum(m["n_accounts"] for m in models)
    used = sum(1 for m in models if m["n_accounts"])
    out.append(html.Span([html.Strong(str(n_acc)), f" account{'s' if n_acc != 1 else ''} targeting "
                          f"{used} model{'s' if used != 1 else ''}"] if n_acc
                         else [html.Strong("No"), " accounts yet"]))
    return out


def fold_label(is_open: bool) -> list[Any]:
    return ([icon("chevron-up", 16), " Hide models"] if is_open
            else [icon("chevron-down", 16), " Show models"])


def _line_card(ln: dict[str, Any], is_open: bool = False) -> html.Div:
    n = len(ln["models"])
    show = {"display": "block" if is_open else "none"}
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [html.Div([html.H3(ln["name"], className="ts-mm-line-name"),
                                   html.Span(f"{n} model{'s' if n != 1 else ''}",
                                             className="ts-mm-count")],
                                  className="ts-row ts-gap-2"),
                         html.P(ln["description"] or "No description.", className="ts-sub ts-mt-1"),
                         html.Div(_line_summary(ln["models"]), className="ts-fold-summary ts-mt-2")]
                    ),
                    html.Div(
                        [html.Button(fold_label(is_open), id={"type": "mm-fold-btn", "id": ln["id"]},
                                     n_clicks=1 if is_open else 0, type="button",
                                     className="ts-btn ts-btn-secondary ts-btn-sm ts-fold-btn",
                                     **{"aria-expanded": "true" if is_open else "false"}),
                         html.Button([icon("plus", 14), " Add model"],
                                     id={"type": "mm-line-add-model", "id": ln["id"]}, n_clicks=0,
                                     type="button", className="ts-btn ts-btn-secondary ts-btn-sm"),
                         _icon_btn("pencil", "Edit line", {"type": "mm-edit-line", "id": ln["id"]}),
                         _icon_btn("trash-2", "Delete line", {"type": "mm-del-line", "id": ln["id"]},
                                   danger=True)],
                        className="ts-row ts-gap-2",
                    ),
                ],
                className="ts-mm-line-head",
            ),
            html.Div(
                _models_table(ln["models"], "No models in this line yet. Use Add model to create one."),
                id={"type": "mm-fold-body", "id": ln["id"]}, style=show,
            ),
        ],
        className="ts-card ts-mm-line",
    )


SCHWAB = "Charles Schwab"
PROVIDERS = [
    (True, "Schwab Models",
     "Schwab Model Portfolios from Charles Schwab Asset Management. Allocations as of "
     "September 30, 2026."),
    (False, "Custom Models", "Lines built in the Model Builder or added here."),
]


def split_by_provider(cat: dict[str, Any]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """[(title, subtitle, categories)] — Schwab lines first, then custom lines (if any)."""
    out = []
    for schwab, title, sub in PROVIDERS:
        cats = [{**c, "lines": [ln for ln in c["lines"]
                                if (ln.get("provider", SCHWAB) == SCHWAB) == schwab],
                 "unassigned": c["unassigned"] if not schwab else []}
                for c in cat["categories"]]
        if schwab or any(c["lines"] or c["unassigned"] for c in cats):
            out.append((title, sub, cats))
    return out


def provider_heading(title: str, sub: str, n: int, extra_cls: str = "") -> html.Div:
    return html.Div(
        [html.Div([html.H2(title, className="ts-mm-provider-title"),
                   html.P(sub, className="ts-sub ts-mt-1")]),
         html.Span(f"{n} model{'s' if n != 1 else ''}", className="ts-mm-count")],
        className=f"ts-mm-provider ts-row ts-between ts-items-start {extra_cls}".strip(),
    )


def catalog_view(cat: dict[str, Any], open_lines: list[str] | None = None) -> list[Any]:
    """Schwab Models / Custom Models → category (Total Return / Income / Tax Efficient) → line
    → models. Empty categories are hidden under Custom Models."""
    out: list[Any] = []
    for k, (title, sub, cats) in enumerate(split_by_provider(cat)):
        n_all = sum(len(ln["models"]) for c in cats for ln in c["lines"]) + sum(
            len(c["unassigned"]) for c in cats)
        out.append(provider_heading(title, sub, n_all, "ts-mt-4" if k else ""))
        for c in cats:
            if k and not (c["lines"] or c["unassigned"]):
                continue
            out.append(_category_section(c, open_lines))
    return out


def _category_section(c: dict[str, Any], open_lines: list[str] | None) -> html.Section:
    n_models = sum(len(ln["models"]) for ln in c["lines"]) + len(c["unassigned"])
    body: list[Any] = [_line_card(ln, ln["id"] in (open_lines or [])) for ln in c["lines"]]
    if not c["lines"]:
        body.append(html.P("No lines in this category yet. Use Add line to create one.",
                           className="ts-mm-empty ts-card"))
    if c["unassigned"]:
        body.append(html.Div(
            [html.Div(html.H3("Not in a line", className="ts-mm-line-name"),
                      className="ts-mm-line-head"),
             _models_table(c["unassigned"], "")],
            className="ts-card ts-mm-line"))
    return html.Section(
        [
            html.Div(
                [html.Span(icon(CATEGORY_ICON[c["id"]], 18), className="ts-mm-cat-icon"),
                 html.H2(c["label"], className="ts-mm-cat-title"),
                 html.Span(f"{len(c['lines'])} line{'s' if len(c['lines']) != 1 else ''} · "
                           f"{n_models} model{'s' if n_models != 1 else ''}",
                           className="ts-sub")],
                className="ts-row ts-gap-3 ts-mb-4",
            ),
            html.Div(body, className="ts-stack-4"),
        ],
        className="ts-mb-8",
    )


def line_options(cat: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not cat:
        return []
    return [{"group": c["label"],
             "items": [{"value": ln["id"], "label": f"{ln['name']} ({c['label']})"}
                       for ln in c["lines"]]}
            for c in cat["categories"] if c["lines"]]


def weight_rows(cat: dict[str, Any], weights: dict[str, float]) -> list[Any]:
    rows = []
    for p in cat["products"]:
        w = weights.get(p["ticker"])
        rows.append(html.Div(
            [html.Div([html.Div(p["ticker"], className="ts-fw-600 ts-c-navy"),
                       html.Div(f"{p['name']} · {p['expense_ratio_bps']:g} bps",
                                className="ts-mm-prod-name")]),
             dmc.NumberInput(id={"type": "mm-w", "t": p["ticker"]},
                             value=round(w * 100, 4) if w else None, placeholder="0",
                             min=0, max=100, step=5, decimalScale=2, suffix="%", hideControls=True,
                             className="ts-num-input ts-mm-w", **{"aria-label": f"{p['ticker']} weight"})],
            className="ts-mm-w-row",
        ))
    return rows


# ------------------------------------------------------------------ dialogs
def line_modal() -> dmc.Modal:
    return dmc.Modal(
        id="mm-line-modal", size=520, **_MODAL,
        children=[
            dcc.Store(id="mm-line-target", data=None),
            _modal_head("Model line", "mm-line-title", "mm-line-close"),
            html.Div(
                [field("Line name", text_input("mm-line-name", "e.g. Core Models")),
                 field("Category", dcc.Dropdown(id="mm-line-cat", options=CATEGORY_OPTIONS,
                                                value="total_return", clearable=False,
                                                searchable=False, className="ts-select"),
                       hint="Moving a line to another category moves its models too."),
                 field("Description", text_input("mm-line-desc", "What this line is for"))],
                className="ts-stack-4",
            ),
            html.Div(id="mm-line-error"),
            html.Div(
                [html.Button("Cancel", id="mm-line-cancel", n_clicks=0, type="button",
                             className="ts-btn-plain"),
                 html.Button("Save line", id="mm-line-save", n_clicks=0, type="button",
                             className="ts-btn-modal-primary")],
                className="ts-modal-actions",
            ),
        ],
    )


def model_modal() -> dmc.Modal:
    return dmc.Modal(
        id="mm-model-modal", size=640, **_MODAL,
        children=[
            dcc.Store(id="mm-model-target", data=None),
            _modal_head("Target model", "mm-model-title", "mm-model-close"),
            html.Div(
                [
                    field("Model name", text_input("mm-model-name", "e.g. Core Models — Moderate")),
                    html.Div(
                        [field("Line", dmc.Select(id="mm-model-line", data=[], allowDeselect=False,
                                                  placeholder="Choose a line",
                                                  className="ts-mm-select",
                                                  comboboxProps={"withinPortal": True,
                                                                 "zIndex": 400})),
                         field("Risk profile", dmc.Select(id="mm-model-risk", data=[],
                                                          allowDeselect=False,
                                                          placeholder="Choose a risk profile",
                                                          className="ts-mm-select",
                                                          comboboxProps={"withinPortal": True,
                                                                         "zIndex": 400}))],
                        className="ts-grid-2",
                    ),
                    html.Div(
                        [field("Description", text_input("mm-model-desc", "Optional")),
                         field("Advisory fee", dmc.NumberInput(id="mm-model-fee", min=0, max=300,
                                                               step=1, suffix=" bps", value=0,
                                                               className="ts-num-input"))],
                        className="ts-grid-2",
                    ),
                    html.Div(
                        [html.Div([html.Span("Holdings", className="ts-mm-w-title"),
                                   html.Span(id="mm-w-total", className="ts-mm-w-total")],
                                  className="ts-row ts-between ts-mb-2"),
                         html.P("Weights must add up to 100%. Leave a product empty to exclude it.",
                                className="ts-sub ts-mb-2"),
                         html.Div(id="mm-w-rows", className="ts-mm-w-list")],
                    ),
                ],
                className="ts-stack-4",
            ),
            html.Div(id="mm-model-error"),
            html.Div(
                [html.Button("Cancel", id="mm-model-cancel", n_clicks=0, type="button",
                             className="ts-btn-plain"),
                 html.Button("Save model", id="mm-model-save", n_clicks=0, type="button",
                             className="ts-btn-modal-primary")],
                className="ts-modal-actions",
            ),
        ],
    )


def delete_confirm_modal() -> dmc.Modal:
    return dmc.Modal(
        id="mm-del-modal", size=460, **_MODAL,
        children=[
            dcc.Store(id="mm-del-target", data=None),
            html.H2(id="mm-del-title", className="ts-modal-title"),
            html.P(id="mm-del-body", className="ts-sub ts-mt-2"),
            html.Div(id="mm-del-error"),
            html.Div(
                [html.Button("Cancel", id="mm-del-cancel", n_clicks=0, type="button",
                             className="ts-btn-plain"),
                 html.Button("Delete", id="mm-del-confirm", n_clicks=0, type="button",
                             className="ts-btn-modal-danger")],
                className="ts-modal-actions",
            ),
        ],
    )
