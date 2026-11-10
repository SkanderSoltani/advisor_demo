"""SQLAlchemy 2.0 ORM models. Works on SQLite (default) and Postgres (set DATABASE_URL)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Advisor(Base):
    __tablename__ = "advisors"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    firm: Mapped[str] = mapped_column(String(200))

    users: Mapped[list[User]] = relationship(back_populates="advisor")
    clients: Mapped[list[Client]] = relationship(back_populates="advisor")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40), default="advisor")
    advisor_id: Mapped[str] = mapped_column(ForeignKey("advisors.id"))

    advisor: Mapped[Advisor] = relationship(back_populates="users")


class Security(Base):
    """Synthetic universe reference data."""

    __tablename__ = "securities"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str] = mapped_column(String(80), index=True)
    market_cap: Mapped[float] = mapped_column(Float)
    dividend_yield: Mapped[float] = mapped_column(Float)
    value_score: Mapped[float] = mapped_column(Float)
    quality_score: Mapped[float] = mapped_column(Float)
    profitability_score: Mapped[float] = mapped_column(Float)
    momentum_score: Mapped[float] = mapped_column(Float)
    beta: Mapped[float] = mapped_column(Float)
    last_price: Mapped[float] = mapped_column(Float)
    security_type: Mapped[str] = mapped_column(String(10), default="equity")  # equity | fund
    issuer: Mapped[str | None] = mapped_column(String(120))
    asset_class: Mapped[str | None] = mapped_column(String(60))
    expense_ratio_bps: Mapped[float] = mapped_column(Float, default=0.0)


class ModelPortfolio(Base):
    __tablename__ = "model_portfolios"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. "SCHWAB-TR"
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(120), default="")
    advisory_fee_bps: Mapped[float] = mapped_column(Float, default=0.0)
    objective: Mapped[str] = mapped_column(String(40))
    construction: Mapped[str] = mapped_column(String(60))
    benchmark: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    target_yield: Mapped[float] = mapped_column(Float)
    expected_te: Mapped[float] = mapped_column(Float)
    fee_bps: Mapped[float] = mapped_column(Float)  # weighted product expense ratio + advisory fee
    regime_overlay: Mapped[bool] = mapped_column(Boolean, default=False)

    holdings: Mapped[list[ModelHolding]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class ModelHolding(Base):
    __tablename__ = "model_holdings"

    model_id: Mapped[str] = mapped_column(ForeignKey("model_portfolios.id"), primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("securities.ticker"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float)

    model: Mapped[ModelPortfolio] = relationship(back_populates="holdings")


class Client(Base):
    """A household. Tax profile lives here (shared by all the household's accounts)."""

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    advisor_id: Mapped[str] = mapped_column(ForeignKey("advisors.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    client_type: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    federal_st_rate: Mapped[float] = mapped_column(Float)
    federal_lt_rate: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(2))
    state_rate: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    advisor: Mapped[Advisor] = relationship(back_populates="clients")
    accounts: Mapped[list[Account]] = relationship(
        back_populates="client", cascade="all, delete-orphan", order_by="Account.id"
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(40))
    custodian: Mapped[str] = mapped_column(String(80))
    nickname: Mapped[str | None] = mapped_column(String(200))
    target_model_id: Mapped[str | None] = mapped_column(ForeignKey("model_portfolios.id"))
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    onboarding_date: Mapped[date] = mapped_column(Date)
    drift_tolerance_te: Mapped[float] = mapped_column(Float, default=0.015)

    client: Mapped[Client] = relationship(back_populates="accounts")
    target_model: Mapped[ModelPortfolio | None] = relationship()
    lots: Mapped[list[Lot]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="Lot.id"
    )
    events: Mapped[list[ManagementEvent]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="ManagementEvent.event_date",
    )


class Lot(Base):
    """A tax lot. Derived fields (holding period, MV, gain) are computed, not stored."""

    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("account_id", "lot_ref", name="uq_lots_account_lot_ref"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    # Lot ID shown to people (statement / custodian lot number), unique within the account
    lot_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("securities.ticker"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    cost_basis_total: Mapped[float] = mapped_column(Float)
    acquired_date: Mapped[date] = mapped_column(Date)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(10), default="seed")
    basis_unknown: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped[Account] = relationship(back_populates="lots")


class ManagementEvent(Base):
    __tablename__ = "management_events"
    __table_args__ = (Index("ix_events_account_date", "account_id", "event_date"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    event_date: Mapped[date] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    trigger: Mapped[str] = mapped_column(String(40))
    n_trades: Mapped[int] = mapped_column(Integer)
    turnover: Mapped[float] = mapped_column(Float)
    realized_st_gain: Mapped[float] = mapped_column(Float)
    realized_lt_gain: Mapped[float] = mapped_column(Float)
    losses_harvested: Mapped[float] = mapped_column(Float)
    # short- / long-term parts of losses_harvested (positive numbers)
    realized_st_loss: Mapped[float] = mapped_column(Float, default=0.0)
    realized_lt_loss: Mapped[float] = mapped_column(Float, default=0.0)
    est_taxes_saved: Mapped[float] = mapped_column(Float)
    te_before: Mapped[float] = mapped_column(Float)
    te_after: Mapped[float] = mapped_column(Float)
    cash_flow_amount: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")

    account: Mapped[Account] = relationship(back_populates="events")
    trades: Mapped[list[EventTrade]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="EventTrade.id"
    )


class EventTrade(Base):
    __tablename__ = "event_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("management_events.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(12))
    side: Mapped[str] = mapped_column(String(4))
    shares: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    realized_gain: Mapped[float] = mapped_column(Float, default=0.0)
    term: Mapped[str | None] = mapped_column(String(2))  # "ST" | "LT" for sells

    event: Mapped[ManagementEvent] = relationship(back_populates="trades")


class RegimeLabel(Base):
    """Optional macro-regime labels (date → regime) uploaded per advisor."""

    __tablename__ = "regime_labels"

    advisor_id: Mapped[str] = mapped_column(ForeignKey("advisors.id"), primary_key=True)
    label_date: Mapped[date] = mapped_column(Date, primary_key=True)
    regime: Mapped[str] = mapped_column(String(60))


class AppMeta(Base):
    """Small key/value store (e.g. which version of the book file the database holds)."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Transition(Base):
    """A guided transition session (state machine state + accumulated choices). Used from M6."""

    __tablename__ = "transitions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    state: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
