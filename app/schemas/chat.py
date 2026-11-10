"""Guided-conversation schemas (ChatTurn is the main contract with the front end)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import Schema

UiType = Literal[
    "none",
    "ingest_choice",
    "parse_preview",
    "model_list",
    "model_comparison",
    "transition_setup",
    "transition_results",
]


class ChatRequest(Schema):
    message: str | None = Field(None, max_length=2000, description="Free text from the advisor")
    quick_reply: str | None = Field(None, max_length=120, description="id of a quick reply")
    action: Literal["restart", "back", "approve"] | None = None


class BackRequest(Schema):
    to_state: str = Field(examples=["TRANSITION_SETUP"])


class QuickReply(Schema):
    id: str
    label: str


class UiPayload(Schema):
    type: UiType = "none"
    data: dict[str, Any] = Field(default_factory=dict)


class Progress(Schema):
    step: int
    total: int
    label: str


class Interpretation(Schema):
    """How free text was understood (shown for transparency; None for button clicks)."""

    intent: str
    confidence: float
    slots: dict[str, Any]
    needs_confirmation: bool


class ChatTurn(Schema):
    transition_id: str
    state: str
    assistant_message: str = Field(description="Markdown")
    quick_replies: list[QuickReply]
    ui_payload: UiPayload
    allowed_actions: list[str]
    progress: Progress
    interpretation: Interpretation | None = None
    llm_provider: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "transition_id": "trn_1a2b3c4d",
                    "state": "Q_OBJECTIVE",
                    "assistant_message": "Is the goal **income** or **total return**?",
                    "quick_replies": [
                        {"id": "income", "label": "Income"},
                        {"id": "total_return", "label": "Total return"},
                    ],
                    "ui_payload": {"type": "none", "data": {}},
                    "allowed_actions": ["back", "restart"],
                    "progress": {"step": 2, "total": 6, "label": "Choose target"},
                    "interpretation": None,
                    "llm_provider": "mock",
                }
            ]
        },
    )


class ChatHistoryItem(Schema):
    role: Literal["user", "assistant"]
    text: str
    state: str


class ChatHistory(Schema):
    transition_id: str
    state: str
    items: list[ChatHistoryItem]
