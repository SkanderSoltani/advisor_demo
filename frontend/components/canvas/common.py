"""Shared canvas pieces."""

from __future__ import annotations

from typing import Any

from dash import html

from components.chat_panel import QR_LABELS
from components.shell import icon
from components.stepper import STEPS, step_of

DISCLAIMER = "Illustrative analysis for advisor review. Not tax or investment advice."


def header(state: str, title: str, lede: str, action: Any = None) -> html.Div:
    n = step_of(state)
    head = html.Div(
        [html.P(f"Step {n} of {len(STEPS)}", className="ts-eyebrow ts-mb-2"),
         html.H1(title, className="ts-h1"),
         html.P(lede, className="ts-sub-sm ts-mt-2")]
    )
    if action is None:
        return html.Div(head, className="ts-mb-8")
    return html.Div([head, action], className="ts-canvas-head ts-mb-6")


def act(reply_id: str, label: Any, primary: bool = False, extra_cls: str = "") -> html.Button:
    """A canvas button that sends a quick reply to the guide (mirrors the chat chips)."""
    return html.Button(label, id={"type": "ws-act", "id": reply_id}, n_clicks=0, type="button",
                       className=("ts-btn-cta" if primary else "ts-btn-outline") + f" {extra_cls}".rstrip())


def reply_actions(turn: dict[str, Any], skip: set[str] | None = None, primary: str | None = None
                  ) -> html.Div | None:
    """Every quick reply the assistant offers is also available on the canvas."""
    replies = [r for r in turn.get("quick_replies", []) if r["id"] not in (skip or set())]
    if not replies:
        return None
    return html.Div(
        [act(r["id"], r["label"] or QR_LABELS.get(r["id"], r["id"]), primary=r["id"] == primary)
         for r in replies],
        className="ts-canvas-actions",
    )


def stat(label: str, value: Any, tone: str = "navy", tip: str | None = None) -> html.Div:
    return html.Div([html.P(label, className="ts-kpi-label", title=tip),
                     html.P(value, className=f"ts-stat-value ts-tone-{tone}")],
                    className="ts-stat")


def arrow(label: str) -> list[Any]:
    return [label, icon("arrow-right", 16)]
