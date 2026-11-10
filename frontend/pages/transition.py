"""/transition/<transition_id> — chat-led workspace. Port of reference/react-ui/app/transition/[id]/page.tsx.

Left: AI guide (chat). Right: canvas rendered from the ChatTurn's ``ui_payload`` (components/canvas).
The backend drives every step; this page never decides state or computes analytics.
"""

from __future__ import annotations

import dash
from dash import dcc, html

from components.chat_panel import chat_panel
from components.common import skeleton
from components.stepper import workspace_header

dash.register_page(__name__, path_template="/transition/<transition_id>",
                   title="Transition workspace · Transition Studio")


def layout(transition_id: str | None = None, **_: object) -> html.Main:
    return html.Main(
        [
            dcc.Store(id={"type": "page-load", "page": "transition"}, data=0),
            dcc.Store(id="ws-tid", data=transition_id),
            dcc.Store(id="ws-meta", data=None),     # client / account labels + ids
            dcc.Store(id="ws-turn", data=None),     # latest ChatTurn
            dcc.Store(id="ws-thread-data", data=[]),  # [{role, text}]
            dcc.Store(id="ws-extra", data={}),      # lots / frontier for the canvas
            dcc.Store(id="ws-plaid-link", data=None),    # live Plaid: link token → assets/plaid.js
            dcc.Store(id="ws-plaid-public", data=None),  # live Plaid: public token from Link
            dcc.Store(id="ws-scroll-sink"),
            dcc.Store(id="ws-plaid-sink"),
            dcc.Download(id="ws-download"),
            html.Div(workspace_header("", "Account", 1, "/"), id="ws-header"),
            html.Div(
                [
                    chat_panel(),
                    html.Section(
                        html.Div(
                            [html.Div(id="ws-error"),
                             html.Div([skeleton(14, "90px", "ts-mb-2"), skeleton(36, "320px"),
                                       skeleton(16, "420px", "ts-mt-2")], id="ws-canvas")],
                            className="ts-canvas-inner",
                        ),
                        className="ts-canvas",
                    ),
                ],
                className="ts-ws-body",
            ),
        ],
        className="ts-ws",
    )
