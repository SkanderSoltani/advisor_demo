"""Steps where the guide asks a question (target knowledge, objective, construction): the canvas
shows the same choices as large cards."""

from __future__ import annotations

from typing import Any

from dash import html

from components.canvas.common import header, reply_actions
from components.shell import icon

CARD_COPY: dict[str, tuple[str, str, str]] = {
    "knows": ("list-checks", "I know my target", "Pick a model from the catalog."),
    "help": ("compass", "Help me choose", "Answer two questions and compare recommendations."),
    "objective:income": ("hand-coins", "Income", "Higher, more stable dividend yield."),
    "objective:total_return": ("trending-up", "Total return", "Long-term growth with broad market exposure."),
    "construction:market_cap": ("pie-chart", "Market cap",
                                "Cap-weighted core — lowest cost and tracking error."),
    "construction:market_cap_fundamental": ("chart-column-big", "Market cap + fundamental",
                                            "Tilts toward value, quality and profitability."),
    "construction:market_cap_fundamental_active": ("sparkles", "Market cap + fundamental + active",
                                                   "Adds a disciplined active overlay with a TE budget."),
}
TITLES = {
    "TARGET_KNOWLEDGE": ("Choose your target", "Select a model aligned to this client's objective."),
    "Q_OBJECTIVE": ("Choose your target", "Is the client focused on income or total return?"),
    "Q_CONSTRUCTION": ("Choose your target", "Pick a construction style for the target model."),
}


def render(turn: dict[str, Any], extra: dict[str, Any]) -> Any:
    state = turn["state"]
    title, lede = TITLES.get(state, ("Transition", "Continue with the guide."))
    cards = [r for r in turn.get("quick_replies", []) if r["id"] in CARD_COPY]
    others = {r["id"] for r in turn.get("quick_replies", [])} - {r["id"] for r in cards}
    grid = html.Div(
        [
            html.Button(
                [html.Div(icon(CARD_COPY[r["id"]][0], 22), className="ts-choice-icon"),
                 html.H2(CARD_COPY[r["id"]][1], className="ts-h2"),
                 html.P(CARD_COPY[r["id"]][2], className="ts-choice-text")],
                id={"type": "ws-act", "id": r["id"]}, n_clicks=0, type="button",
                className="ts-choice-card", title=CARD_COPY[r["id"]][2],
            )
            for r in cards
        ],
        className=f"ts-choice-grid ts-choice-grid--{min(len(cards), 3)}",
    ) if cards else None
    rest = reply_actions(turn, skip={r["id"] for r in cards}) if others else None
    return [header(state, title, lede), grid, rest]
