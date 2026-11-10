"""Plaid Investments ingestion (Sandbox only) + an offline mock for demo mode.

Plaid returns positions (quantity, sometimes total cost basis) and investment transactions — not
tax lots. :func:`holdings_to_rows` rebuilds lots from buy transactions where it can and flags the
rest (``basis_estimated`` / missing date) so the advisor can upload a lot file or accept an
average-cost assumption.
"""

from __future__ import annotations

import zlib
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from app.core.config import get_settings

LOOKBACK_DAYS = 730  # Plaid investment transactions history window requested


class PlaidError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlaidHolding:
    ticker: str | None
    name: str | None
    quantity: float
    cost_basis: float | None  # total, often missing
    institution_value: float
    security_type: str | None = None


@dataclass(frozen=True, slots=True)
class PlaidTxn:
    txn_date: date
    type: str  # buy | sell | cash | fee | transfer
    ticker: str | None
    quantity: float
    price: float


@dataclass(slots=True)
class PlaidPortfolio:
    holdings: list[PlaidHolding]
    transactions: list[PlaidTxn]
    cash: float = 0.0
    institution: str = ""
    warnings: list[str] = field(default_factory=list)


class PlaidGateway(ABC):
    mode: str  # "sandbox" | "mock"

    @abstractmethod
    def create_link_token(self, client_user_id: str) -> tuple[str, str]:
        """(link_token, expiration ISO) for Plaid Link on the front end."""

    @abstractmethod
    def exchange_public_token(self, public_token: str) -> str:
        """Exchange Link's public token for an access token (never returned to the browser)."""

    @abstractmethod
    def fetch_portfolio(self, access_token: str, as_of: date) -> PlaidPortfolio:
        """Holdings + investment transactions for the linked item."""


# --------------------------------------------------------------------------- sandbox
class SandboxPlaidGateway(PlaidGateway):
    mode = "sandbox"

    def __init__(self, client_id: str, secret: str) -> None:
        import plaid
        from plaid.api import plaid_api

        cfg = plaid.Configuration(
            host=plaid.Environment.Sandbox,
            api_key={"clientId": client_id, "secret": secret},
        )
        self._plaid = plaid
        self.client = plaid_api.PlaidApi(plaid.ApiClient(cfg))

    def create_link_token(self, client_user_id: str) -> tuple[str, str]:
        from plaid.model.country_code import CountryCode
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.products import Products

        req = LinkTokenCreateRequest(
            products=[Products("investments")],
            client_name="Transition Studio (demo)",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=client_user_id),
        )
        try:
            resp = self.client.link_token_create(req)
        except self._plaid.ApiException as exc:
            raise PlaidError("Plaid link token request failed") from exc
        return str(resp["link_token"]), str(resp["expiration"])

    def exchange_public_token(self, public_token: str) -> str:
        from plaid.model.item_public_token_exchange_request import (
            ItemPublicTokenExchangeRequest,
        )

        try:
            resp = self.client.item_public_token_exchange(
                ItemPublicTokenExchangeRequest(public_token=public_token)
            )
        except self._plaid.ApiException as exc:
            raise PlaidError("Plaid public token exchange failed") from exc
        return str(resp["access_token"])

    def fetch_portfolio(self, access_token: str, as_of: date) -> PlaidPortfolio:
        from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
        from plaid.model.investments_transactions_get_request import (
            InvestmentsTransactionsGetRequest,
        )

        try:
            h = self.client.investments_holdings_get(
                InvestmentsHoldingsGetRequest(access_token=access_token)
            )
            t = self.client.investments_transactions_get(
                InvestmentsTransactionsGetRequest(
                    access_token=access_token,
                    start_date=as_of - timedelta(days=LOOKBACK_DAYS),
                    end_date=as_of,
                )
            )
        except self._plaid.ApiException as exc:
            raise PlaidError("Plaid investments request failed") from exc
        secs = {s["security_id"]: s for s in h["securities"]}
        holdings, cash = [], 0.0
        for x in h["holdings"]:
            s = secs.get(x["security_id"], {})
            if s.get("is_cash_equivalent") or s.get("type") == "cash":
                cash += float(x.get("institution_value") or 0.0)
                continue
            holdings.append(
                PlaidHolding(
                    ticker=s.get("ticker_symbol"),
                    name=s.get("name"),
                    quantity=float(x["quantity"]),
                    cost_basis=float(x["cost_basis"]) if x.get("cost_basis") is not None else None,
                    institution_value=float(x.get("institution_value") or 0.0),
                    security_type=str(s.get("type")) if s.get("type") else None,
                )
            )
        txns = [
            PlaidTxn(
                txn_date=tx["date"],
                type=str(tx["type"]),
                ticker=secs.get(tx.get("security_id"), {}).get("ticker_symbol"),
                quantity=float(tx.get("quantity") or 0.0),
                price=float(tx.get("price") or 0.0),
            )
            for tx in t["investment_transactions"]
        ]
        return PlaidPortfolio(holdings, txns, cash, institution="Plaid Sandbox")


# --------------------------------------------------------------------------- mock
MOCK_PUBLIC_TOKEN = "public-mock-transition-studio"


class MockPlaidGateway(PlaidGateway):
    """Deterministic synthetic brokerage (demo mode): positions in the synthetic universe, some
    with transaction history (lots can be rebuilt) and some without cost basis."""

    mode = "mock"

    def __init__(self, prices: Mapping[str, float], seed: int) -> None:
        self.prices = dict(prices)
        self.seed = seed

    def create_link_token(self, client_user_id: str) -> tuple[str, str]:
        exp = (date.today() + timedelta(hours=4)).isoformat()
        return f"link-mock-{zlib.crc32(client_user_id.encode()):08x}", exp

    def exchange_public_token(self, public_token: str) -> str:
        if not public_token.startswith("public-"):
            raise PlaidError("Invalid public token")
        return f"access-mock-{zlib.crc32(public_token.encode()):08x}"

    def fetch_portfolio(self, access_token: str, as_of: date) -> PlaidPortfolio:
        rng = np.random.default_rng([self.seed, zlib.crc32(access_token.encode())])
        tickers = sorted(self.prices)
        picks = rng.choice(tickers, size=24, replace=False)
        holdings: list[PlaidHolding] = []
        txns: list[PlaidTxn] = []
        for k, t in enumerate(picks):
            px = self.prices[str(t)]
            qty = float(np.round(rng.uniform(20_000, 120_000) / px, 3))
            kind = k % 3  # 0: full txn history, 1: basis but no history, 2: nothing
            if kind == 0:
                remaining, n = qty, int(rng.integers(1, 4))
                basis = 0.0
                for j in range(n):
                    q = (
                        remaining
                        if j == n - 1
                        else float(np.round(remaining * rng.uniform(0.2, 0.6), 3))
                    )
                    remaining -= q
                    d = as_of - timedelta(days=int(rng.integers(30, LOOKBACK_DAYS)))
                    p = px * float(np.exp(rng.normal(-0.05, 0.2)))
                    txns.append(PlaidTxn(d, "buy", str(t), q, p))
                    basis += q * p
                cost = basis
            elif kind == 1:
                cost = qty * px * float(np.exp(rng.normal(-0.2, 0.25)))
            else:
                cost = None
            holdings.append(PlaidHolding(str(t), None, qty, cost, qty * px, "equity"))
        cash = float(np.round(rng.uniform(5_000, 40_000), 2))
        return PlaidPortfolio(holdings, txns, cash, institution="Mock Brokerage (demo)")


# --------------------------------------------------------------------------- lots
def holdings_to_rows(portfolio: PlaidPortfolio, as_of: date) -> list[dict[str, object]]:
    """Rebuild tax lots from buy transactions (newest buys = remaining lots, FIFO sales);
    any unexplained quantity becomes one lot with an average-cost basis and no date."""
    rows: list[dict[str, object]] = []
    buys: dict[str, list[PlaidTxn]] = {}
    for tx in portfolio.transactions:
        if tx.type == "buy" and tx.ticker and tx.quantity > 0:
            buys.setdefault(tx.ticker, []).append(tx)
    for h in portfolio.holdings:
        remaining = h.quantity
        for tx in sorted(buys.get(h.ticker or "", []), key=lambda x: x.txn_date, reverse=True):
            if remaining <= 1e-9:
                break
            q = min(tx.quantity, remaining)
            rows.append(
                {
                    "ticker": h.ticker,
                    "description": h.name,
                    "quantity": q,
                    "acquired_date": tx.txn_date,
                    "cost_basis_total": q * tx.price,
                    "current_value": h.institution_value * q / h.quantity if h.quantity else None,
                    "basis_estimated": False,
                }
            )
            remaining -= q
        if remaining > 1e-6:
            share = remaining / h.quantity if h.quantity else 0.0
            rows.append(
                {
                    "ticker": h.ticker,
                    "description": h.name,
                    "quantity": remaining,
                    "acquired_date": None,
                    "cost_basis_total": h.cost_basis * share if h.cost_basis is not None else None,
                    "current_value": h.institution_value * share,
                    "basis_estimated": True,
                }
            )
    return rows


@lru_cache
def get_plaid_gateway() -> PlaidGateway:
    """Sandbox when credentials are configured and DEMO_MODE is off; otherwise the mock."""
    s = get_settings()
    if not s.DEMO_MODE and s.PLAID_CLIENT_ID and s.PLAID_SECRET:
        return SandboxPlaidGateway(s.PLAID_CLIENT_ID, s.PLAID_SECRET)
    from app.analytics.factory import get_provider
    from app.db.synthetic_market import SyntheticMarket

    provider = get_provider()
    market: SyntheticMarket | None = getattr(provider, "market", None)
    tickers = list(market.universe.index) if market is not None else []
    return MockPlaidGateway(provider.get_prices(tickers), seed=s.SYNTHETIC_SEED)
