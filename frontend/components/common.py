"""Small shared building blocks: simulated-analytics badge, KPI card, card shells, skeletons,
error/empty states, and API-error handling for callbacks."""

from __future__ import annotations

from typing import Any

from dash import dcc, html, no_update

from components.shell import icon
from services.api_client import ApiError, AuthError
from theme.plotly_template import GRAPH_CONFIG


def sim_badge(data_source: str | None) -> html.Span | None:
    """'Simulated analytics' pill — shown only when the API says the numbers are simulated."""
    if data_source != "mock_random":
        return None
    return html.Span("Simulated analytics", className="ts-sim-badge",
                     title="Analytics are simulated (data_source: mock_random)")


def kpi_card(label: str, value: Any, tone: str = "navy", *, sub: Any = None, id_: Any = None,
             tooltip: str | None = None, size: str = "xl", clickable: bool = False) -> html.Div:
    kw: dict[str, Any] = {"id": id_} if id_ is not None else {}
    cls = "ts-card ts-kpi" + (" is-clickable" if clickable else "")
    children = [
        html.P(label, className="ts-kpi-label", title=tooltip) if tooltip
        else html.P(label, className="ts-kpi-label"),
        html.P(value, className=f"ts-kpi-value ts-kpi-value--{size} ts-tone-{tone}"),
    ]
    if sub is not None:
        children.append(html.P(sub, className="ts-kpi-sub"))
    if clickable:
        return html.Button(children, className=cls, n_clicks=0, type="button", **kw)
    return html.Div(children, className=cls, **kw)


def skeleton(h: int, w: str = "100%", cls: str = "") -> html.Div:
    return html.Div(className=f"ts-skeleton {cls}".strip(), style={"height": f"{h}px", "width": w})


def kpi_skeleton(label: str) -> html.Div:
    return html.Div([html.P(label, className="ts-kpi-label"), skeleton(28, "60%", "ts-mt-2")],
                    className="ts-card ts-kpi")


def graph(fig: Any, height: int, id_: Any = None, cls: str = "") -> dcc.Graph:
    kw: dict[str, Any] = {"id": id_} if id_ is not None else {}
    return dcc.Graph(figure=fig, config=GRAPH_CONFIG, style={"height": f"{height}px"},
                     className=f"ts-graph {cls}".strip(), **kw)


def error_state(message: str, retry_id: Any | None = None) -> html.Div:
    return html.Div(
        [
            icon("circle-alert", 18, "ts-c-negative"),
            html.Div([html.P("We couldn’t load this.", className="ts-state-title"),
                      html.P(message, className="ts-state-text")]),
            html.Button("Retry", id=retry_id, n_clicks=0, className="ts-btn ts-btn-secondary ts-btn-sm")
            if retry_id is not None else None,
        ],
        className="ts-state ts-state--error",
        role="alert",
    )


def empty_state(title: str, text: str, actions: list[Any] | None = None, icon_name: str = "inbox"
                ) -> html.Div:
    return html.Div(
        [html.Div(icon(icon_name, 22), className="ts-empty-icon"),
         html.P(title, className="ts-state-title"), html.P(text, className="ts-state-text"),
         html.Div(actions or [], className="ts-row ts-gap-2 ts-mt-4")],
        className="ts-empty",
    )


def handle_api_error(exc: ApiError, n_outputs: int, error_index: int | None = None,
                     error_value: Any = None) -> tuple[Any, ...]:
    """Map an API error to callback outputs. Callers add a 'redirect' output last for 401s."""
    if isinstance(exc, AuthError):
        out = [no_update] * n_outputs
        out[-1] = "/login"
        return tuple(out)
    out = [no_update] * n_outputs
    if error_index is not None:
        out[error_index] = error_value
    return tuple(out)
