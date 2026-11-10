"""Client (household) and account schemas."""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.common import AnalyticsPayload, ClientStatus, Schema

ClientType = str  # "individual" | "couple" | "family" | "trust"


class TaxProfile(Schema):
    federal_st_rate: float = Field(ge=0, le=0.6, examples=[0.37])
    federal_lt_rate: float = Field(ge=0, le=0.4, examples=[0.238])
    state: str = Field(min_length=2, max_length=2, examples=["CA"])
    state_rate: float = Field(ge=0, le=0.2, examples=[0.133])


class TaxProfileOut(TaxProfile):
    st_rate: float = Field(description="Combined federal + state short-term rate")
    lt_rate: float = Field(description="Combined federal + state long-term rate")


class TaxProfileUpdate(Schema):
    federal_st_rate: float | None = Field(None, ge=0, le=0.6)
    federal_lt_rate: float | None = Field(None, ge=0, le=0.4)
    state: str | None = Field(None, min_length=2, max_length=2)
    state_rate: float | None = Field(None, ge=0, le=0.2)


class ClientCreate(Schema):
    name: str = Field(min_length=1, max_length=200, examples=["Rivera Household"])
    email: EmailStr = Field(examples=["rivera@example.com"])
    phone: str | None = Field(None, examples=["555-0199"])
    client_type: str = Field(pattern="^(individual|couple|family|trust)$", examples=["couple"])
    tax_profile: TaxProfile
    notes: str | None = None


class ClientUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = None
    client_type: str | None = Field(None, pattern="^(individual|couple|family|trust)$")
    notes: str | None = None
    tax_profile: TaxProfileUpdate | None = None


class AccountCreate(Schema):
    account_type: str = Field(
        pattern="^(individual_taxable|joint_taxable|trust|ira|roth_ira)$",
        examples=["joint_taxable"],
    )
    custodian: str = Field(min_length=1, examples=["Schwab"])
    nickname: str | None = Field(None, examples=["Joint brokerage"])
    target_model_id: str | None = Field(None, examples=["TR-MCF"])


class AccountSummary(Schema):
    """Account card used in client detail and account lists."""

    id: str
    client_id: str
    account_type: str
    taxable: bool
    custodian: str
    nickname: str | None
    target_model_id: str | None
    onboarding_date: date
    market_value: float
    cash: float
    n_positions: int
    n_lots: int
    ex_ante_te: float | None
    drift_tolerance_te: float
    outside_tolerance: bool
    taxes_saved_ytd: float
    taxes_saved_since_inception: float
    last_rebalance_date: date | None
    has_history: bool


class AccountList(AnalyticsPayload):
    items: list[AccountSummary]


class ClientSummaryRow(Schema):
    id: str
    name: str
    client_type: str
    n_accounts: int
    market_value: float
    target_models: list[str]
    ex_ante_te: float | None = Field(description="Value-weighted across accounts with a target")
    taxes_saved_ytd: float
    last_rebalance_date: date | None
    status: ClientStatus


class ClientList(AnalyticsPayload):
    total: int
    items: list[ClientSummaryRow]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "data_source": "mock_random",
                    "total": 1,
                    "items": [
                        {
                            "id": "cli_001",
                            "name": "Okafor Family",
                            "client_type": "family",
                            "n_accounts": 3,
                            "market_value": 11880693.12,
                            "target_models": ["INC-MC", "TR-MC", "TR-MCF"],
                            "ex_ante_te": 0.0091,
                            "taxes_saved_ytd": 61234.55,
                            "last_rebalance_date": "2026-10-16",
                            "status": "on_target",
                        }
                    ],
                }
            ]
        },
    )


class ClientMetrics(Schema):
    market_value: float
    cash: float
    n_accounts: int
    n_positions: int
    ex_ante_te: float | None
    taxes_saved_ytd: float
    taxes_saved_since_inception: float
    unrealized_gain: float
    last_rebalance_date: date | None
    first_onboarding_date: date | None


class ClientDetail(AnalyticsPayload):
    id: str
    name: str
    email: str | None
    phone: str | None
    client_type: str
    notes: str | None
    status: ClientStatus
    tax_profile: TaxProfileOut
    accounts: list[AccountSummary]
    metrics: ClientMetrics


class ClientOut(Schema):
    """Returned by create / update."""

    id: str
    name: str
    email: str | None
    phone: str | None
    client_type: str
    notes: str | None
    tax_profile: TaxProfileOut
    status: ClientStatus
