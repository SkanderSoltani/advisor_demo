"""Step 1 — Import holdings (port of the React step 1 cards)."""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from components.canvas.common import act, header
from components.shell import icon


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    data = turn["ui_payload"]["data"]
    ids = {r["id"] for r in turn.get("quick_replies", [])}
    plaid = html.Button(
        [html.Div(icon("wand-sparkles", 22), className="ts-import-icon ts-import-icon--blue"),
         html.H2("Connect brokerage", className="ts-h2"),
         html.P("Securely connect a custodian and sync positions and tax lots.",
                className="ts-import-text"),
         html.Span(["Connect with Plaid ", icon("arrow-right", 16)], className="ts-import-cta")],
        id={"type": "ws-plaid", "id": "c"}, n_clicks=0, type="button",
        className="ts-import-card is-selected",
    )
    pdf = dcc.Upload(
        html.Div(
            [html.Div(icon("upload", 22), className="ts-import-icon"),
             html.H2("Upload tax-lot PDF", className="ts-h2"),
             html.P("Drop a statement here and we'll parse the holdings for review.",
                    className="ts-import-text"),
             html.Span(["Choose file ", icon("arrow-right", 16)], className="ts-import-cta")],
            className="ts-import-card",
        ),
        id={"type": "ws-upload", "id": "c"}, accept="application/pdf",
        max_size=10 * 1024 * 1024, className="ts-upload", className_active="ts-upload is-drag",
    )
    extras = []
    if "use_existing" in ids:
        extras.append(html.Div(
            [html.Div([icon("briefcase", 18, "ts-c-primary"),
                       html.Span("This account already has holdings.", className="ts-fw-500")],
                      className="ts-row ts-gap-2"),
             act("use_existing", ["Use current holdings ", icon("arrow-right", 16)], primary=True)],
            className="ts-banner ts-mb-4"))
    if "upload_sample" in ids:
        extras.append(html.Div(act("upload_sample", [icon("file-text", 15), "Use sample statement (demo)"]),
                               className="ts-mt-4"))
    return [
        header(turn["state"], "Import holdings",
               "Bring in current tax lots to begin the transition analysis."),
        *([extras[0]] if "use_existing" in ids else []),
        html.Div([plaid, pdf], className="ts-import-grid"),
        html.Div(id={"type": "ws-ingest-status", "id": "c"}),
        *(extras[-1:] if "upload_sample" in ids else []),
        dcc.Store(id={"type": "ws-has-holdings", "id": "c"}, data=data.get("has_holdings")),
    ]
