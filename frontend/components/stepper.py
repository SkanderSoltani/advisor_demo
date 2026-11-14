"""Workspace header + 6-step progress (React places the stepper inside the navy header)."""

from __future__ import annotations

from dash import html

from components.shell import icon

STEPS = ["Import holdings", "Review account", "Choose target", "Compare", "Optimize transition",
         "Review & export"]

# backend conversation state → React step (1-based). See docs/port_plan.md §8.
STATE_STEP = {
    "START": 1, "INGEST_CHOICE": 1, "INGEST_REVIEW": 2, "ACCOUNT_REVIEW": 2,
    "TARGET_KNOWLEDGE": 3, "TARGET_PICK_LIST": 3, "Q_OBJECTIVE": 3, "Q_CONSTRUCTION": 3,
    "TARGET_COMPARE": 4, "TARGET_CONFIRM": 4,
    "TRANSITION_SETUP": 5, "TRANSITION_RESULTS": 5,
    "TRANSITION_APPROVE": 6, "DONE": 6,
}
# where "go back to step N" lands (first visited candidate wins)
STEP_BACK_TARGETS = {
    1: ["INGEST_CHOICE"], 2: ["ACCOUNT_REVIEW", "INGEST_REVIEW", "INGEST_CHOICE"],
    3: ["TARGET_KNOWLEDGE"], 4: ["TARGET_COMPARE", "TARGET_CONFIRM", "TARGET_PICK_LIST"],
    5: ["TRANSITION_SETUP"], 6: ["TRANSITION_APPROVE"],
}


def step_of(state: str | None) -> int:
    return STATE_STEP.get(state or "", 1)


def stepper(current: int, done: bool = False) -> html.Nav:
    items = []
    for i, label in enumerate(STEPS, start=1):
        complete = i < current or (done and i == current)
        state = "done" if complete else "current" if i == current else "todo"
        circle = html.Span(icon("check", 13) if complete else str(i), className="ts-step-dot")
        items.append(
            html.Button(
                [circle, label],
                id={"type": "ws-step", "step": i},
                n_clicks=0,
                type="button",
                className=f"ts-step ts-step--{state}",
                disabled=not complete or done,
                **{"aria-current": "step" if state == "current" else None},
            )
        )
    return html.Nav(items, className="ts-steps", **{"aria-label": "Transition progress"})


def workspace_header(client_name: str, account_label: str, current: int, back_href: str,
                     done: bool = False) -> html.Header:
    return html.Header(
        [
            html.Div(
                [
                    html.A(icon("arrow-left", 18), href=back_href, className="ts-ws-back",
                           **{"aria-label": "Back to client"}),
                    html.Div([html.P(client_name, className="ts-ws-client"),
                              html.P(f"{account_label} · Transition workspace",
                                     className="ts-ws-account")]),
                ],
                className="ts-row ts-gap-4",
            ),
            stepper(current, done),
            html.A("Exit", href=back_href, className="ts-ws-exit"),
        ],
        className="ts-topbar ts-ws-header",
    )
