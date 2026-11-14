"""Step 2 — Account review: what the guide noticed in the holdings, with fixes to apply."""

from __future__ import annotations

from typing import Any

from dash import html

from components.canvas.common import act, header
from components.diagnosis import bench_line, workspace_findings
from components.shell import icon


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    d = turn["ui_payload"]["data"]
    applied = d.get("applied") or []
    cont = (f"Continue with {len(applied)} fix{'es' if len(applied) > 1 else ''}" if applied
            else "Looks fine — continue")
    return [
        header(turn["state"], "Account review",
               "What the guide noticed in this account before choosing a target."),
        html.Div([icon("sparkles", 16), html.Span(d["summary"], className="ts-fw-600"),
                  html.Span(bench_line(d), className="ts-c-ink600")],
                 className="ts-ai-banner ts-mb-4"),
        html.Div(workspace_findings(d), className="ts-ai-list") if d["findings"] else
        html.P("No findings: the account is close to its benchmark and has no tax flags.",
               className="ts-sub"),
        html.Div([act("continue", cont, primary=True)], className="ts-canvas-actions ts-mt-6"),
        html.P("Simulated analytics. Fixes become settings for this transition; nothing trades "
               "until you approve.", className="ts-disclaimer"),
    ]
