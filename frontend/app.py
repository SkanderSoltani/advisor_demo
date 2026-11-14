"""Transition Studio — Dash front end (port of the v0 React reference).

Dev:   python app.py                      (http://localhost:8050)
Prod:  gunicorn app:server -b 0.0.0.0:8050
Env:   USE_MOCKS=true|false, API_BASE_URL=http://localhost:8000/api/v1
"""

from __future__ import annotations

import os

import dash
import dash._dash_renderer
import dash_mantine_components as dmc
from dash import Dash, dcc, html

from theme import plotly_template
from theme import tokens as t

# dash-mantine-components 3 requires React 19 (Dash ≥ 4.5 ships it, but defaults to 18)
dash._dash_renderer._set_react_version("19.2.4")
plotly_template.register()

app = Dash(
    __name__,
    use_pages=True,
    title="Transition Studio",
    update_title=None,
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": "AI-guided portfolio transitions for RIA advisors."},
    ],
)
server = app.server

MANTINE_THEME = {
    "fontFamily": t.FONT_FAMILY,
    "primaryColor": "brand",
    "primaryShade": 5,
    "colors": {"brand": t.BRAND_SCALE},
    "defaultRadius": "md",
    "radius": {"md": t.RADIUS_BUTTON, "lg": t.RADIUS_CARD},
    "black": t.INK_900,
    "components": {"Button": {"defaultProps": {"radius": "md"}}},
}

app.layout = dmc.MantineProvider(
    theme=MANTINE_THEME,
    forceColorScheme="light",
    children=[
        dcc.Location(id="url", refresh="callback-nav"),
        dcc.Location(id="redirect", refresh="callback-nav"),
        # auth token + user; session storage = cleared when the tab closes (React parity)
        dcc.Store(id="session", storage_type="session"),
        dcc.Store(id="auth-expired", data=None),  # any callback sets this on a 401
        dcc.Store(id="refresh", data=0),  # bump to reload the current page's data
        dmc.NotificationContainer(id="notify", position="top-right", autoClose=4000),
        html.Div(dash.page_container, id="page"),
    ],
)

# callbacks register on import
from callbacks import (  # noqa: E402,F401
    auth,
    book,
    client_detail,
    diagnosis,
    fold,
    modals,
    model_builder,
    models,
    risk,
    transition,
)

if __name__ == "__main__":
    app.run(debug=os.environ.get("DASH_DEBUG", "true").lower() == "true",
            host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8050")))
