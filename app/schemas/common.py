"""Shared schema building blocks.

Conventions for the whole API:
* Rates, weights, TE, yields and turnover are **decimals** (0.012 = 1.2%).
* Money is USD as a float rounded to cents.
* Dates are ISO ``YYYY-MM-DD``; period keys are ``YYYY-MM`` (month) or ``YYYY`` (year).
* Every analytics payload carries ``data_source`` ("mock_random" today) so the UI can badge it.
"""

from __future__ import annotations

from datetime import date
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER = "Illustrative, for advisor review. Not tax or investment advice."


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AnalyticsPayload(Schema):
    data_source: str = Field(
        "mock_random",
        description='Origin of the analytics numbers. "mock_random" = simulated analytics.',
        examples=["mock_random"],
    )


class DatedValueOut(Schema):
    date: date
    value: float


class Granularity(StrEnum):
    month = "month"
    year = "year"


class TEWindow(IntEnum):
    """Rolling TE window in trading days (63 ≈ 3 months, 252 ≈ 1 year)."""

    d63 = 63
    d252 = 252


class ClientStatus(StrEnum):
    on_target = "on_target"
    drifting = "drifting"
    needs_review = "needs_review"
    onboarding = "onboarding"


class EventTypeOut(StrEnum):
    transition = "transition"
    rebalance = "rebalance"
    tax_loss_harvest = "tax_loss_harvest"
    cash_flow = "cash_flow"
    model_change = "model_change"
