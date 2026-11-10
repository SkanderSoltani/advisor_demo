"""Canvas registry: ``ui_payload.type`` → render function.

Each renderer takes ``(turn: dict, extra: dict)`` and returns a component. ``extra`` carries data
some canvases need beyond the ChatTurn (e.g. account lots for the lock grid). To add a step type:
create a module with ``render(turn, extra)`` and add one entry to ``REGISTRY``.
Canvas controls use dict ids ``{"type": ..., "id": "c"}`` so page callbacks can listen with ALL.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dash import html

from components.canvas import (
    ingest_choice,
    model_comparison,
    model_list,
    none,
    parse_preview,
    transition_results,
    transition_setup,
)

Renderer = Callable[[dict[str, Any], dict[str, Any]], Any]

REGISTRY: dict[str, Renderer] = {
    "none": none.render,
    "ingest_choice": ingest_choice.render,
    "parse_preview": parse_preview.render,
    "model_list": model_list.render,
    "model_comparison": model_comparison.render,
    "transition_setup": transition_setup.render,
    "transition_results": transition_results.render,
}


def render_canvas(turn: dict[str, Any] | None, extra: dict[str, Any] | None = None) -> Any:
    if not turn:
        return html.Div()
    kind = (turn.get("ui_payload") or {}).get("type", "none")
    return html.Div(REGISTRY.get(kind, none.render)(turn, extra or {}), className="ts-canvas-anim",
                    key=f"{turn.get('state')}-{kind}", **{"data-state": turn.get("state", "")})
