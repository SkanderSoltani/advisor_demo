"""Shared chrome: logo chip, top bars, left rail, footer, icons."""

from __future__ import annotations

from typing import Any

from dash import html
from dash_iconify import DashIconify

# Same asset the React reference hot-links (kept by owner decision; see docs/port_gaps.md A1)
SCHWAB_LOGO = (
    "https://cdn.jsdelivr.net/gh/glincker/thesvg@main/public/icons/charles-schwab/default.svg"
)
FOOTER_TEXT = "Internal prototype · Synthetic data · Not for client use."


def icon(name: str, size: int = 16, cls: str = "", **kw: Any) -> DashIconify:
    """lucide-react → dash-iconify (`lucide:<kebab-name>`, same names)."""
    return DashIconify(icon=f"lucide:{name}", width=size, height=size, className=cls, **kw)


def logo_chip(large: bool = False) -> html.Div:
    return html.Div(
        html.Img(src=SCHWAB_LOGO, alt="Charles Schwab", className="ts-logo-img"),
        className="ts-logo-chip" + (" ts-logo-chip--lg" if large else ""),
    )


def footer(extra_cls: str = "") -> html.Footer:
    return html.Footer(FOOTER_TEXT, className=f"ts-footer {extra_cls}".strip())


def topbar_book(date_text: str, initials: str) -> html.Header:
    """Client-book header (app/page.tsx)."""
    return html.Header(
        [
            html.Div(
                [
                    logo_chip(),
                    html.Span("Transition Studio", className="ts-topbar-title"),
                    html.Span("Prototype", className="ts-topbar-pill"),
                ],
                className="ts-row ts-gap-3",
            ),
            html.Div(
                [
                    html.Span(date_text, className="ts-topbar-date", id="topbar-date"),
                    html.Div(initials, className="ts-avatar", id="topbar-initials"),
                ],
                className="ts-row ts-gap-4 ts-text-sm",
            ),
        ],
        className="ts-topbar",
    )


def left_rail(active: str = "dashboard") -> html.Aside:
    def btn(key: str, name: str, label: str, href: str | None = None) -> Any:
        cls = "ts-rail-btn" + (" is-active" if key == active else "")
        inner = icon(name, 18)
        if href:
            return html.A(inner, href=href, className=cls, **{"aria-label": label}, title=label)
        return html.Button(inner, className=cls, **{"aria-label": label}, title=label)

    return html.Aside(
        [
            btn("dashboard", "layout-dashboard", "Dashboard", "/"),
            btn("clients", "users", "Clients"),
            btn("activity", "activity", "Activity"),
            html.Div([btn("help", "circle-help", "Help"), btn("settings", "settings-2", "Settings")],
                     className="ts-rail-bottom"),
        ],
        className="ts-rail",
    )


def topbar_client(client_name: str = "") -> html.Header:
    """Client-detail header (app/clients/[id]/page.tsx)."""
    return html.Header(
        [
            html.A([icon("arrow-left", 16), "Client book"], href="/", className="ts-topbar-back"),
            html.Span("Transition Studio", className="ts-topbar-center"),
            html.Span(client_name, className="ts-topbar-right", id="cd-topbar-name"),
        ],
        className="ts-topbar",
    )
