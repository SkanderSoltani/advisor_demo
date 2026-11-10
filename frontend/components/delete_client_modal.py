"""Confirm before deleting a client (opened from the client book row menu)."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash import dcc, html


def delete_client_modal() -> dmc.Modal:
    return dmc.Modal(
        id="delete-client-modal",
        opened=False,
        withCloseButton=False,
        centered=True,
        size=440,
        radius=12,
        padding=24,
        overlayProps={"color": "#003D5C", "backgroundOpacity": 0.35, "blur": 0},
        transitionProps={"transition": "pop", "duration": 180},
        classNames={"content": "ts-modal"},
        children=[
            dcc.Store(id="dc-client", data=None),
            html.H2("Delete client?", id="dc-title", className="ts-modal-title"),
            html.P(id="dc-body", className="ts-sub ts-mt-2"),
            html.Div(
                [
                    html.Button("Cancel", id="dc-cancel", n_clicks=0, type="button",
                                className="ts-btn-plain"),
                    html.Button("Delete client", id="dc-confirm", n_clicks=0, type="button",
                                className="ts-btn-modal-danger"),
                ],
                className="ts-modal-actions",
            ),
        ],
    )
