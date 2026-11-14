"""Model management schemas: categories → lines → models (risk profiles)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import Schema

Objective = Literal["total_return", "income", "tax_efficient"]


class CatalogHolding(Schema):
    ticker: str
    name: str
    weight: float


class CatalogModel(Schema):
    id: str
    name: str
    objective: Objective
    line_id: str | None
    risk_profile: str
    construction: str
    benchmark: str
    description: str
    advisory_fee_bps: float
    holdings: list[CatalogHolding]
    target_yield: float | None = Field(description="Look-through dividend yield")
    expected_te: float | None = Field(description="Ex-ante TE vs the model's benchmark")
    fee_bps: float | None = Field(description="Weighted product expense ratio + advisory fee")
    n_accounts: int = Field(description="Accounts targeting this model")


class CatalogLine(Schema):
    id: str
    name: str
    objective: Objective
    description: str
    provider: str = "Charles Schwab"
    models: list[CatalogModel]


class CatalogCategory(Schema):
    id: Objective
    label: str
    lines: list[CatalogLine]
    unassigned: list[CatalogModel] = Field(description="Models of this category with no line")


class CatalogProduct(Schema):
    ticker: str
    name: str
    asset_class: str
    expense_ratio_bps: float


class ModelCatalog(Schema):
    categories: list[CatalogCategory]
    products: list[CatalogProduct] = Field(description="Products a model can hold")
    risk_profiles: list[str]


class LineIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    objective: Objective
    description: str = ""


class LinePatch(Schema):
    name: str | None = Field(None, max_length=120)
    objective: Objective | None = None
    description: str | None = None


class HoldingIn(Schema):
    ticker: str
    weight: float = Field(ge=0, le=1, description="Fraction, 0.25 = 25%")


class ModelIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    line_id: str
    risk_profile: str = Field(min_length=1, max_length=60)
    description: str = ""
    advisory_fee_bps: float = Field(0.0, ge=0, le=300)
    holdings: list[HoldingIn] = Field(min_length=1)


class ModelPatch(Schema):
    name: str | None = Field(None, max_length=200)
    line_id: str | None = None
    risk_profile: str | None = Field(None, max_length=60)
    description: str | None = None
    advisory_fee_bps: float | None = Field(None, ge=0, le=300)
    holdings: list[HoldingIn] | None = None


class Created(Schema):
    id: str
