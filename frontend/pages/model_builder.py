"""/model-builder — build a model, analyse it, scale it into a line and save it (guided)."""

from __future__ import annotations

import dash
from dash import dcc, html

from components.model_builder import (
    analytics_card,
    build_card,
    builder_header,
    guide_panel,
    scale_card,
)

dash.register_page(__name__, path="/model-builder", title="Model Builder · Transition Studio")


def layout(**_: object) -> html.Main:
    return html.Main(
        [
            dcc.Store(id={"type": "page-load", "page": "model-builder"}, data=0),
            dcc.Store(id="mb-draft", data=None),
            dcc.Store(id="mb-report", data=None),
            dcc.Store(id="mb-names", data={}),  # ticker → {name, asset_class, expense_ratio_bps}
            dcc.Store(id="mb-thread-data", data=[]),
            dcc.Store(id="mb-refresh", data=0),  # bump → re-run analytics
            dcc.Store(id="mb-scale-go", data=0),  # bump → re-preview the line
            dcc.Store(id="mb-scroll-sink"),
            dcc.Download(id="mb-download"),
            html.Div(builder_header("build"), id="mb-header"),
            html.Div(
                [guide_panel(),
                 html.Section(html.Div([build_card(), analytics_card(), scale_card()],
                                       className="ts-canvas-inner ts-bld-canvas"),
                              className="ts-canvas")],
                className="ts-ws-body",
            ),
        ],
        className="ts-ws",
    )
