"""Conversation states, their order, progress labels and what each one owns."""

from __future__ import annotations

from enum import StrEnum


class State(StrEnum):
    START = "START"
    INGEST_CHOICE = "INGEST_CHOICE"
    INGEST_REVIEW = "INGEST_REVIEW"
    TARGET_KNOWLEDGE = "TARGET_KNOWLEDGE"
    TARGET_PICK_LIST = "TARGET_PICK_LIST"
    Q_OBJECTIVE = "Q_OBJECTIVE"
    Q_CONSTRUCTION = "Q_CONSTRUCTION"
    TARGET_COMPARE = "TARGET_COMPARE"
    TARGET_CONFIRM = "TARGET_CONFIRM"
    TRANSITION_SETUP = "TRANSITION_SETUP"
    TRANSITION_RESULTS = "TRANSITION_RESULTS"
    TRANSITION_APPROVE = "TRANSITION_APPROVE"
    DONE = "DONE"


ORDER: list[State] = list(State)
RANK = {s: i for i, s in enumerate(ORDER)}

# (step, label) shown in the progress bar; 6 steps in total
PROGRESS: dict[State, tuple[int, str]] = {
    State.START: (1, "Holdings"),
    State.INGEST_CHOICE: (1, "Holdings"),
    State.INGEST_REVIEW: (1, "Holdings"),
    State.TARGET_KNOWLEDGE: (2, "Choose target"),
    State.TARGET_PICK_LIST: (2, "Choose target"),
    State.Q_OBJECTIVE: (2, "Choose target"),
    State.Q_CONSTRUCTION: (2, "Choose target"),
    State.TARGET_COMPARE: (2, "Choose target"),
    State.TARGET_CONFIRM: (3, "Confirm target"),
    State.TRANSITION_SETUP: (4, "Set budget"),
    State.TRANSITION_RESULTS: (5, "Review results"),
    State.TRANSITION_APPROVE: (6, "Approve"),
    State.DONE: (6, "Done"),
}
TOTAL_STEPS = 6

# session data keys produced in each state; going back to a state clears keys of later states
OWNS: dict[State, tuple[str, ...]] = {
    State.INGEST_REVIEW: ("ingest_preview",),
    State.Q_OBJECTIVE: ("objective",),
    State.Q_CONSTRUCTION: ("construction",),
    State.TARGET_COMPARE: ("candidates", "comparison"),
    State.TARGET_PICK_LIST: (),
    State.TARGET_CONFIRM: ("target_confirmed",),
    State.TRANSITION_SETUP: ("setup",),
    State.TRANSITION_RESULTS: ("optimization", "frontier"),
    State.TRANSITION_APPROVE: ("approved_event_id",),
}


def keys_after(state: State) -> list[str]:
    """Data keys owned by states strictly after ``state`` (invalidated when going back)."""
    out: list[str] = []
    for s in ORDER[RANK[state] + 1 :]:
        out.extend(OWNS.get(s, ()))
    return out
