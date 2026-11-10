"""Ingestion schemas: parse preview (nothing committed) and confirmation."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.common import Schema


class IssueOut(Schema):
    code: str = Field(
        examples=["unknown_ticker"],
        description="unknown_ticker | missing_ticker | missing_quantity | negative_quantity | "
        "zero_quantity | missing_date | invalid_date | future_date | missing_basis | "
        "estimated_basis | negative_basis | value_mismatch | duplicate_row | duplicate_lot_id | "
        "lot_id_exists",
    )
    severity: Literal["error", "warning"]
    message: str


class PreviewRow(Schema):
    row_id: int
    lot_ref: str | None = Field(
        None, description="Lot ID printed on the statement (one is assigned on confirm if missing)"
    )
    ticker: str | None
    description: str | None
    quantity: float | None
    acquired_date: date | None
    cost_basis_total: float | None
    statement_value: float | None = Field(description="Value printed on the statement")
    current_price: float | None
    market_value: float | None = Field(description="quantity × current price")
    unrealized_gain: float | None
    holding_period: Literal["ST", "LT"] | None
    basis_estimated: bool = Field(description="Basis missing or average-cost, not lot-level")
    confidence: float
    issues: list[IssueOut]
    suggested_ticker: str | None
    include: bool = Field(description="Default: rows without errors are included")


class PreviewSummary(Schema):
    n_rows: int
    n_error_rows: int
    n_warning_rows: int
    n_basis_unknown: int
    n_missing_dates: int
    total_market_value: float
    total_cost_basis: float


class ParsePreview(Schema):
    transition_id: str
    account_id: str
    source: Literal["pdf", "plaid"]
    method: Literal["table", "llm", "plaid"]
    llm_provider: str | None = Field(
        None, description='"anthropic" or "mock" (offline rule-based stand-in) when method=llm'
    )
    confidence: float
    statement_date: date | None
    cash_detected: float | None
    requires_basis_decision: bool = Field(
        description="True if some lots lack basis or dates: upload a lot file, or confirm with "
        "assume_average_cost=true"
    )
    summary: PreviewSummary
    rows: list[PreviewRow]
    notes: list[str]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "transition_id": "trn_1a2b3c4d",
                    "account_id": "acc_017",
                    "source": "pdf",
                    "method": "llm",
                    "llm_provider": "mock",
                    "confidence": 0.946,
                    "statement_date": "2026-10-30",
                    "cash_detected": 87517.86,
                    "requires_basis_decision": False,
                    "summary": {
                        "n_rows": 102,
                        "n_error_rows": 1,
                        "n_warning_rows": 0,
                        "n_basis_unknown": 0,
                        "n_missing_dates": 0,
                        "total_market_value": 2662482.03,
                        "total_cost_basis": 1972331.6,
                    },
                    "rows": [
                        {
                            "row_id": 34,
                            "ticker": "JUWQ",
                            "description": "Juniper Rail",
                            "quantity": 120.5,
                            "acquired_date": "2019-04-02",
                            "cost_basis_total": 5120.4,
                            "statement_value": 9876.1,
                            "current_price": None,
                            "market_value": None,
                            "unrealized_gain": None,
                            "holding_period": "LT",
                            "basis_estimated": False,
                            "confidence": 0.523,
                            "issues": [
                                {
                                    "code": "unknown_ticker",
                                    "severity": "error",
                                    "message": "JUWQ is not tradable — did you mean JUWL?",
                                }
                            ],
                            "suggested_ticker": "JUWL",
                            "include": False,
                        }
                    ],
                    "notes": ["No lot table found"],
                }
            ]
        },
    )


class ConfirmRow(Schema):
    row_id: int | None = None
    lot_ref: str | None = Field(
        None, max_length=40, description="Lot ID; one is assigned when missing"
    )
    ticker: str = Field(min_length=1, max_length=12)
    quantity: float
    acquired_date: date | None = None
    cost_basis_total: float | None = None
    include: bool = True
    locked: bool = False


class ConfirmRequest(Schema):
    rows: list[ConfirmRow] = Field(max_length=5000)
    mode: Literal["replace", "append"] = Field(
        "replace", description="replace = the statement becomes the account's holdings"
    )
    cash: float | None = Field(None, ge=0, description="Defaults to the detected cash, if any")
    assume_average_cost: bool = Field(
        False,
        description="Fill missing basis with today's value (no embedded gain) and missing dates "
        "with as-of − 366 days (long-term); affected lots are flagged basis_unknown",
    )


class RowError(Schema):
    row_id: int | None
    ticker: str
    issues: list[IssueOut]


class ConfirmResult(Schema):
    transition_id: str
    account_id: str
    state: str
    n_committed: int
    n_excluded: int
    total_market_value: float
    cash: float
    assumptions: list[str]


class LinkTokenOut(Schema):
    link_token: str
    expiration: str
    mode: Literal["sandbox", "mock"]
    mock_public_token: str | None = Field(
        None, description="Mock mode only: pass this to /ingest/plaid/exchange instead of Link"
    )


class PlaidExchangeRequest(Schema):
    public_token: str = Field(min_length=6)
    transition_id: str
