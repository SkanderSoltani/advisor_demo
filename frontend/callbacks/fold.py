"""Show / hide the sections below Analytics, and the one-line summaries shown while closed."""

from __future__ import annotations

from collections import Counter
from typing import Any

from dash import MATCH, Input, Output, State, callback, html
from dash.exceptions import PreventUpdate

from components.fold import fold_label
from services import format as fmt

NOUNS = {"book-clients": "clients", "cd-holdings": "holdings", "cd-history": "history",
         "cd-years": "summary", "cd-accounts": "accounts"}


@callback(
    Output({"type": "fold-body", "key": MATCH}, "style"),
    Output({"type": "fold-extra", "key": MATCH}, "style"),
    Output({"type": "fold-btn", "key": MATCH}, "children"),
    Output({"type": "fold-btn", "key": MATCH}, "aria-expanded"),
    Input({"type": "fold-btn", "key": MATCH}, "n_clicks"),
    State({"type": "fold-btn", "key": MATCH}, "id"),
)
def toggle(n, id_):  # type: ignore[no-untyped-def]
    o = bool((n or 0) % 2)
    show = {"display": "block" if o else "none"}
    return show, show, fold_label(o, NOUNS.get(id_["key"], "details")), "true" if o else "false"


def _items(*parts: Any) -> list[html.Span]:
    """[(strong, rest), …] → summary spans; None parts are skipped."""
    return [html.Span([html.Strong(s), f" {r}"]) for p in parts if p for s, r in [p]]


# ------------------------------------------------------------------ book: clients
@callback(Output("book-clients-summary", "children"), Input("book-clients", "data"))
def clients_summary(rows):  # type: ignore[no-untyped-def]
    if rows is None:
        raise PreventUpdate
    st = Counter(r.get("status") for r in rows)
    n = len(rows)
    return _items(
        (fmt.number(n), "client" + ("" if n == 1 else "s")),
        (fmt.money(sum(r.get("market_value") or 0 for r in rows)), "AUM"),
        (fmt.number(st["on_target"]), "on target") if st["on_target"] else None,
        (fmt.number(st["drifting"]), "drifting") if st["drifting"] else None,
        (fmt.number(st["needs_review"]), "need review") if st["needs_review"] else None,
        (fmt.number(st["onboarding"]), "onboarding") if st["onboarding"] else None,
    )


# ------------------------------------------------------------------ client page
@callback(Output("cd-years-summary", "children"), Input("cd-years", "rowData"))
def years_summary(rows):  # type: ignore[no-untyped-def]
    if not rows:
        return html.Span("No history yet")
    years = sorted(r["year"] for r in rows)
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
    return _items(
        (fmt.money_full(sum(r.get("taxes_saved") or 0 for r in rows)), f"taxes saved, {span}"),
        (fmt.money_full(sum(r.get("losses_harvested") or 0 for r in rows)), "losses harvested"),
        (fmt.number(sum(r.get("n_rebalances") or 0 for r in rows)), "rebalances"),
    )


@callback(Output("cd-accounts-summary", "children"), Input("cd-detail", "data"))
def accounts_summary(detail):  # type: ignore[no-untyped-def]
    if not detail:
        raise PreventUpdate
    accts = detail["accounts"]
    n = len(accts)
    with_target = sum(1 for a in accts if a.get("target_model_id"))
    return _items(
        (fmt.number(n), "account" + ("" if n == 1 else "s")),
        (fmt.money_full(sum(a.get("market_value") or 0 for a in accts)), "market value"),
        (f"{with_target} of {n}", "with a target model") if n else None,
    )
