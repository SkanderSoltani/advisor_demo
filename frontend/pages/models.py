"""/models — Model management: categories → lines → target models (by risk profile)."""

from __future__ import annotations

import dash
from dash import dcc, html

from components.model_mgmt import (
    delete_confirm_modal,
    line_modal,
    model_modal,
)
from components.shell import footer, icon, left_rail, topbar_client

dash.register_page(__name__, path="/models", title="Model management · Transition Studio")


def layout(**_: object) -> html.Div:
    return html.Div(
        [
            topbar_client("Model management"),
            html.Div(
                [
                    left_rail("models"),
                    html.Main(
                        html.Div(
                            [
                                dcc.Store(id={"type": "page-load", "page": "models"}, data=0),
                                dcc.Store(id="mm-catalog", data=None),
                                dcc.Store(id="mm-version", data=0),
                                dcc.Store(id="mm-open", data=[]),
                                html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.P("Target models", className="ts-eyebrow"),
                                                html.H1("Model management", className="ts-h1 ts-mt-1"),
                                                html.P("Lines of models by category. Each line "
                                                       "holds models for different risk profiles. "
                                                       "Changes are saved to the model catalog "
                                                       "and apply right away.",
                                                       className="ts-sub-sm ts-mt-2"),
                                            ]
                                        ),
                                        html.Div(
                                            [
                                                dcc.Link([icon("blocks", 16), " Model builder"],
                                                         href="/model-builder",
                                                         className="ts-btn ts-btn-secondary "
                                                                   "ts-no-underline"),
                                                html.Button([icon("folder-plus", 16), " Add line"],
                                                            id="mm-add-line", n_clicks=0,
                                                            type="button",
                                                            className="ts-btn ts-btn-secondary"),
                                                html.Button([icon("plus", 17), " Add model"],
                                                            id="mm-add-model", n_clicks=0,
                                                            type="button",
                                                            className="ts-btn ts-btn-primary "
                                                                      "ts-shadow-sm"),
                                            ],
                                            className="ts-row ts-gap-3",
                                        ),
                                    ],
                                    className="ts-page-head",
                                ),
                                html.Div(id="mm-error"),
                                html.Div(id="mm-content",
                                         children=html.Div(className="ts-skeleton",
                                                           style={"height": "320px"})),
                                line_modal(),
                                model_modal(),
                                footer(),
                                delete_confirm_modal(),
                            ],
                            className="ts-container",
                        ),
                        className="ts-main",
                    ),
                ],
                className="ts-flex",
            ),
        ],
        className="ts-page",
    )
