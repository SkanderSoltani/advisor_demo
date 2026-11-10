"""Onboard new client — two-step modal (step 1 ported from the React reference; step 2 per spec)."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash import dcc, html

from components.shell import icon

CLIENT_TYPES = [
    {"value": "individual", "label": "Individual"},
    {"value": "couple", "label": "Joint household"},
    {"value": "trust", "label": "Trust"},
]


def field(label: str, control: object, hint: str | None = None, err_id: str | None = None
          ) -> html.Label:
    return html.Label(
        [label, control,
         html.Span(hint, className="ts-hint") if hint else None,
         html.Span(id=err_id, className="ts-field-error") if err_id else None],
        className="ts-field ts-field--sm",
    )


def text_input(id_: str, placeholder: str = "", type_: str = "text", value: object = None,
               **kw: object) -> dcc.Input:
    return dcc.Input(id=id_, type=type_, placeholder=placeholder, value=value, debounce=False,
                     className="ts-input ts-input--sm", **kw)


def onboard_modal() -> dmc.Modal:
    step1 = html.Div(
        [
            field("Client or household name", text_input("ob-name", "e.g. Jordan Lee", autoFocus=True),
                  err_id="ob-name-err"),
            field("Email address", text_input("ob-email", "client@example.com", "email"),
                  err_id="ob-email-err"),
            html.Div(
                [
                    field("Client type",
                          dcc.Dropdown(id="ob-type", options=CLIENT_TYPES, value="individual",
                                       clearable=False, searchable=False, className="ts-select")),
                    field("State", text_input("ob-state", "CA", maxLength=2), err_id="ob-state-err"),
                ],
                className="ts-grid-2",
            ),
            html.Div(
                [field("Phone (optional)", text_input("ob-phone", "555-0100", "tel")),
                 field("Notes (optional)", text_input("ob-notes", "Anything the team should know"))],
                className="ts-grid-2",
            ),
        ],
        id="ob-step1", className="ts-stack-4",
    )
    step2 = html.Div(
        [
            html.Div(
                [
                    field("Federal short-term rate",
                          dmc.NumberInput(id="ob-fst", value=37, min=0, max=60, step=1, suffix="%",
                                          decimalScale=2, className="ts-num-input"),
                          "Ordinary income bracket"),
                    field("Federal long-term rate",
                          dmc.NumberInput(id="ob-flt", value=23.8, min=0, max=40, step=0.1, suffix="%",
                                          decimalScale=2, className="ts-num-input"),
                          "Incl. 3.8% NIIT where applicable"),
                ],
                className="ts-grid-2",
            ),
            html.Div(
                [
                    field("State", text_input("ob-state2", "CA", maxLength=2), err_id="ob-state2-err"),
                    field("State rate",
                          dmc.NumberInput(id="ob-sr", value=0, min=0, max=20, step=0.1, suffix="%",
                                          decimalScale=2, className="ts-num-input")),
                ],
                className="ts-grid-2",
            ),
        ],
        id="ob-step2", className="ts-stack-4 ts-hidden",
    )
    done = html.Div(
        [
            html.Div(icon("circle-check", 28, "ts-c-positive"), className="ts-done-icon"),
            html.P(id="ob-done-text", className="ts-lede"),
            html.P("Add the first account now?", className="ts-h3 ts-mt-3"),
        ],
        id="ob-done", className="ts-hidden",
    )
    return dmc.Modal(
        id="onboard-modal",
        opened=False,
        withCloseButton=False,
        centered=True,
        size=512,
        radius=12,
        padding=24,
        overlayProps={"color": "#003D5C", "backgroundOpacity": 0.35, "blur": 0},
        transitionProps={"transition": "pop", "duration": 180},
        classNames={"content": "ts-modal"},
        children=[
            dcc.Store(id="ob-step", data=1),
            dcc.Store(id="ob-created", data=None),
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Step 1 of 2", id="ob-eyebrow", className="ts-eyebrow"),
                            html.H2("Onboard a new client", id="ob-title", className="ts-modal-title"),
                            html.P("Add the household details to create their advisor profile.",
                                   id="ob-sub", className="ts-sub-sm ts-mt-2"),
                        ]
                    ),
                    html.Button("×", id="ob-close", n_clicks=0, type="button", className="ts-modal-x",
                                **{"aria-label": "Close onboarding dialog"}),
                ],
                className="ts-row ts-between ts-items-start ts-mb-6",
            ),
            step1, step2, done,
            html.Div(id="ob-error"),
            html.Div(
                [
                    html.Button("Cancel", id="ob-cancel", n_clicks=0, type="button",
                                className="ts-btn-plain"),
                    html.Button("Back", id="ob-back", n_clicks=0, type="button",
                                className="ts-btn-plain ts-hidden"),
                    html.Button(["Continue to tax profile ", icon("arrow-up-right", 16)], id="ob-next",
                                n_clicks=0, type="button", className="ts-btn-modal-primary"),
                    html.Button("Create client", id="ob-save", n_clicks=0, type="button",
                                className="ts-btn-modal-primary ts-hidden"),
                    html.Button("Go to client page", id="ob-goto", n_clicks=0, type="button",
                                className="ts-btn-plain ts-hidden"),
                    html.Button(["Add account ", icon("arrow-right", 16)], id="ob-add-account",
                                n_clicks=0, type="button", className="ts-btn-modal-primary ts-hidden"),
                ],
                className="ts-modal-actions",
            ),
        ],
    )
