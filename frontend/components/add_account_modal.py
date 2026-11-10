"""Add account modal (spec; same visual language as the onboard modal)."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash import dcc, html

from components.onboard_client_modal import field, text_input
from components.shell import icon

ACCOUNT_TYPES = [
    {"value": "individual_taxable", "label": "Individual taxable"},
    {"value": "joint_taxable", "label": "Joint"},
    {"value": "trust", "label": "Trust"},
    {"value": "ira", "label": "IRA"},
    {"value": "roth_ira", "label": "Roth IRA"},
]


def add_account_modal() -> dmc.Modal:
    form = html.Div(
        [
            html.Div(
                [
                    field("Account type",
                          dcc.Dropdown(id="aa-type", options=ACCOUNT_TYPES, value="individual_taxable",
                                       clearable=False, searchable=False, className="ts-select")),
                    field("Custodian", text_input("aa-custodian", "e.g. Schwab", value="Schwab"),
                          err_id="aa-custodian-err"),
                ],
                className="ts-grid-2",
            ),
            field("Nickname (optional)", text_input("aa-nickname", "e.g. Joint brokerage")),
            field("Target model (optional)",
                  dcc.Dropdown(id="aa-model", options=[], value=None, clearable=True,
                               searchable=False, placeholder="Choose later with the AI guide",
                               className="ts-select"),
                  "You can also pick a target during the transition."),
        ],
        id="aa-form", className="ts-stack-4",
    )
    done = html.Div(
        [
            html.Div(icon("circle-check", 28, "ts-c-positive"), className="ts-done-icon"),
            html.P(id="aa-done-text", className="ts-lede"),
            html.P("Import holdings and start the transition now?", className="ts-h3 ts-mt-3"),
        ],
        id="aa-done", className="ts-hidden",
    )
    return dmc.Modal(
        id="add-account-modal",
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
            dcc.Store(id="aa-client", data=None),
            dcc.Store(id="aa-created", data=None),
            html.Div(
                [
                    html.Div(
                        [
                            html.P(id="aa-eyebrow", className="ts-eyebrow"),
                            html.H2("Add an account", className="ts-modal-title"),
                            html.P("New accounts start empty — you'll import holdings in the "
                                   "transition workspace.", className="ts-sub-sm ts-mt-2"),
                        ]
                    ),
                    html.Button("×", id="aa-close", n_clicks=0, type="button", className="ts-modal-x",
                                **{"aria-label": "Close add account dialog"}),
                ],
                className="ts-row ts-between ts-items-start ts-mb-6",
            ),
            form, done,
            html.Div(id="aa-error"),
            html.Div(
                [
                    html.Button("Cancel", id="aa-cancel", n_clicks=0, type="button",
                                className="ts-btn-plain"),
                    html.Button("Add account", id="aa-save", n_clicks=0, type="button",
                                className="ts-btn-modal-primary"),
                    html.Button("Not now", id="aa-later", n_clicks=0, type="button",
                                className="ts-btn-plain ts-hidden"),
                    html.Button(["Import holdings and start transition ", icon("arrow-right", 16)],
                                id="aa-start", n_clicks=0, type="button",
                                className="ts-btn-modal-primary ts-hidden"),
                ],
                className="ts-modal-actions",
            ),
        ],
    )
