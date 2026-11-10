"""Edit client (profile + tax profile) — PATCH /clients/{id}."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash import dcc, html

from components.onboard_client_modal import CLIENT_TYPES, field, text_input


def edit_client_modal() -> dmc.Modal:
    num = lambda id_, mx, step: dmc.NumberInput(id=id_, min=0, max=mx, step=step, suffix="%",  # noqa: E731
                                                decimalScale=2, className="ts-num-input")
    return dmc.Modal(
        id="edit-modal", opened=False, withCloseButton=False, centered=True, size=560, radius=12,
        padding=24, overlayProps={"color": "#003D5C", "backgroundOpacity": 0.35},
        classNames={"content": "ts-modal"},
        children=[
            html.Div(
                [html.Div([html.P("Client profile", className="ts-eyebrow"),
                           html.H2("Edit client", className="ts-modal-title")]),
                 html.Button("×", id="ed-close", n_clicks=0, type="button", className="ts-modal-x",
                             **{"aria-label": "Close edit dialog"})],
                className="ts-row ts-between ts-items-start ts-mb-6",
            ),
            html.Div(
                [
                    field("Client or household name", text_input("ed-name")),
                    html.Div([field("Email address", text_input("ed-email", type_="email")),
                              field("Phone", text_input("ed-phone", type_="tel"))],
                             className="ts-grid-2"),
                    html.Div([field("Client type", dcc.Dropdown(id="ed-type", options=CLIENT_TYPES,
                                                                 clearable=False, searchable=False,
                                                                 className="ts-select")),
                              field("Notes", text_input("ed-notes"))], className="ts-grid-2"),
                    html.Div([field("Federal short-term rate", num("ed-fst", 60, 1)),
                              field("Federal long-term rate", num("ed-flt", 40, 0.1))],
                             className="ts-grid-2"),
                    html.Div([field("State", text_input("ed-state", maxLength=2)),
                              field("State rate", num("ed-sr", 20, 0.1))], className="ts-grid-2"),
                ],
                className="ts-stack-4",
            ),
            html.Div(id="ed-error"),
            html.Div(
                [html.Button("Cancel", id="ed-cancel", n_clicks=0, type="button", className="ts-btn-plain"),
                 html.Button("Save changes", id="ed-save", n_clicks=0, type="button",
                             className="ts-btn-modal-primary")],
                className="ts-modal-actions",
            ),
        ],
    )
