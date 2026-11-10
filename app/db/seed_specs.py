"""Specs that describe a demo household before it is built (used by the seed and generator)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities import AccountType, TaxProfile


@dataclass(frozen=True, slots=True)
class AccountSpec:
    account_type: AccountType
    custodian: str
    nickname: str
    target_model_id: (
        str | None
    )  # "TR" | "INC" (resolved by objective from the JSON catalog) or None
    market_value: float
    years_managed: float  # 0 → brand-new, no history
    locked_legacy: bool = False
    previous_model_id: str | None = None  # → a model_change event mid-history


@dataclass(frozen=True, slots=True)
class ClientSpec:
    name: str
    client_type: str
    email: str
    phone: str
    tax: TaxProfile
    notes: str
    accounts: list[AccountSpec] = field(default_factory=list)
