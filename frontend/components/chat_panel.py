"""AI guide panel: message thread, quick-reply chips, typing indicator, input."""

from __future__ import annotations

import re
from typing import Any

from dash import dcc, html

from components.shell import icon

QR_LABELS = {
    "use_existing": "Use current holdings", "upload_pdf": "Upload tax-lot PDF",
    "connect_plaid": "Connect brokerage", "upload_sample": "Use sample statement (demo)",
    "confirm": "Looks right — save", "accept_suggestions": "Accept suggestions & save",
    "assume_average_cost": "Accept average-cost assumption", "upload_again": "Upload a different file",
    "save_valid_only": "Save only the valid rows", "knows": "I know my target",
    "help": "Help me choose", "yes": "Yes, confirm", "no": "Choose another",
    "approve": "Approve", "adjust": "Change settings", "restart": "Start over",
    "confirm_pending": "Yes", "cancel_pending": "No",
}


def humanize_reply(raw: str) -> str:
    """'[budget:tax:20000]' (history form of a quick reply) → readable text."""
    m = re.fullmatch(r"\[(.+)\]", raw.strip())
    if not m:
        return raw
    rid = m.group(1)
    if rid in QR_LABELS:
        return QR_LABELS[rid]
    name, _, arg = rid.partition(":")
    if name == "choose":
        return f"Choose {arg}"
    if name == "objective":
        return {"income": "Income", "total_return": "Total return"}.get(arg, arg)
    if name == "construction":
        return arg.replace("market_cap", "Market cap").replace("_fundamental", " + fundamental") \
                  .replace("_active", " + active")
    if name == "budget":
        mode, _, val = arg.partition(":")
        if mode == "none" or not val:
            return "No limit (full transition)"
        label = "tax" if mode == "tax" else "net gain"
        return f"Up to ${float(val):,.0f} {label}"
    return rid.replace("_", " ").capitalize()


def bubble(role: str, text: str) -> html.Div:
    if role == "user":
        return html.Div(html.P(text), className="ts-msg ts-msg--user")
    return html.Div(dcc.Markdown(text, className="ts-md", link_target="_blank"),
                    className="ts-msg ts-msg--ai")


def chips(replies: list[dict[str, Any]]) -> html.Div:
    return html.Div(
        [html.Button(r["label"], id={"type": "ws-qr", "id": r["id"]}, n_clicks=0, type="button",
                     className="ts-chip-btn") for r in replies],
        className="ts-chips",
    )


def chat_panel() -> html.Aside:
    return html.Aside(
        [
            html.Div(
                [
                    html.Div([icon("sparkles", 15), "AI guide"], className="ts-ai-eyebrow"),
                    html.Div(id="ws-thread", className="ts-thread", **{"aria-live": "polite"}),
                    html.Div(
                        [html.Span(), html.Span(), html.Span()],
                        id="ws-typing", className="ts-typing ts-hidden", **{"aria-label": "Guide is typing"},
                    ),
                    html.Div(id="ws-chips"),
                ],
                id="ws-scroll", className="ts-chat-scroll",
            ),
            html.Div(
                html.Div(
                    [
                        icon("message-circle", 16, "ts-c-ink600"),
                        dcc.Input(id="ws-input", type="text", placeholder="Ask the guide anything…",
                                  debounce=False, n_submit=0, className="ts-chat-input",
                                  autoComplete="off"),
                        dcc.Upload(html.Button(icon("paperclip", 16), type="button",
                                               className="ts-chat-icon",
                                               title="Attach a tax-lot PDF"),
                                   id="ws-attach", accept="application/pdf", max_size=10 * 1024 * 1024),
                        html.Button(icon("send", 16), id="ws-send", n_clicks=0, type="button",
                                    className="ts-chat-icon ts-c-primary",
                                    **{"aria-label": "Send message"}),
                    ],
                    className="ts-chat-bar",
                ),
                className="ts-chat-foot",
            ),
        ],
        className="ts-chat",
    )
