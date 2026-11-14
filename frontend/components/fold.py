"""Show / hide for the page sections below Analytics (Clients, Holdings, history, …).

Each section keeps its title and a one-line summary visible; the details (tables, lists and
their filters) open with the section's button. Closed by default, like Analytics.
"""

from __future__ import annotations

from typing import Any

from dash import html

from components.shell import icon


def fold_label(is_open: bool, noun: str) -> list[Any]:
    return ([icon("chevron-up", 16), f" Hide {noun}"] if is_open
            else [icon("chevron-down", 16), f" Show {noun}"])


def fold_button(key: str, noun: str) -> html.Button:
    return html.Button(fold_label(False, noun), id={"type": "fold-btn", "key": key}, n_clicks=0,
                       type="button", className="ts-btn ts-btn-secondary ts-btn-sm ts-fold-btn",
                       **{"aria-expanded": "false"})


def fold_extra(key: str, children: Any = None) -> html.Div:
    """Header controls (search, filters) that only make sense while the details are open."""
    return html.Div(children, id={"type": "fold-extra", "key": key}, style={"display": "none"})


def fold_body(key: str, children: Any) -> html.Div:
    return html.Div(children, id={"type": "fold-body", "key": key}, style={"display": "none"})


def fold_summary(id_: str) -> html.Div:
    return html.Div(id=id_, className="ts-fold-summary ts-mt-2")
