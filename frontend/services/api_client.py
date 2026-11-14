"""Typed API client — the only module that talks HTTP.

``USE_MOCKS=true`` routes every call to :mod:`services.mock_backend` (same shapes, seeded data).
Every method returns a Pydantic model generated from the backend's openapi.json
(:mod:`services.schemas`), so field names can't drift from the contract.
"""

from __future__ import annotations

import os
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from services import schemas as s

T = TypeVar("T", bound=BaseModel)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
USE_MOCKS = os.environ.get("USE_MOCKS", "true").lower() not in ("0", "false", "no")
TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class ApiError(Exception):
    """Non-2xx response (or network failure). ``status`` is 0 for network errors."""

    def __init__(self, status: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


class AuthError(ApiError):
    """401 — the session is missing or expired; the UI redirects to /login."""


def _message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and "message" in detail:
        return str(detail["message"])
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        return str(detail[0].get("msg", "Invalid request"))
    return "Something went wrong"


class ApiClient:
    def __init__(self, token: str | None = None, *, base_url: str | None = None,
                 use_mocks: bool | None = None) -> None:
        self.token = token
        self.base_url = (base_url or API_BASE_URL).rstrip("/")
        self.use_mocks = USE_MOCKS if use_mocks is None else use_mocks

    # ------------------------------------------------------------------ transport
    def _raw(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None,
             files: Any = None, data: Any = None) -> httpx.Response:
        if self.use_mocks:
            from services import mock_backend

            return mock_backend.handle(method, path, token=self.token, json=json, params=params,
                                       files=files, data=data)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.request(method, f"{self.base_url}{path}", json=json, params=clean,
                                   files=files, data=data, headers=headers)
        except httpx.HTTPError as exc:
            raise ApiError(0, "We couldn't reach the server. Check your connection and retry.") from exc
        return r

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        r = self._raw(method, path, **kw)
        if r.status_code == 401:
            raise AuthError(401, "Your session has expired. Please sign in again.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text
            raise ApiError(r.status_code, _message(detail), detail)
        if r.status_code == 204 or not r.content:
            return None
        ctype = r.headers.get("content-type", "")
        return r.json() if "json" in ctype else r.content

    def _model(self, model: type[T], method: str, path: str, **kw: Any) -> T:
        return model.model_validate(self._call(method, path, **kw))

    # ------------------------------------------------------------------ auth
    def login(self, email: str, password: str) -> s.TokenResponse:
        return self._model(s.TokenResponse, "POST", "/auth/login",
                           json={"email": email, "password": password})

    def me(self) -> s.UserOut:
        return self._model(s.UserOut, "GET", "/auth/me")

    # ------------------------------------------------------------------ book
    def book_summary(self) -> s.BookSummary:
        return self._model(s.BookSummary, "GET", "/book/summary")

    def book_tracking_error(self, window: int = 63) -> s.BookTrackingError:
        return self._model(s.BookTrackingError, "GET", "/book/analytics/tracking-error",
                           params={"window": window})

    def book_tax_impact(self, granularity: str = "month") -> s.TaxImpact:
        return self._model(s.TaxImpact, "GET", "/book/analytics/tax-impact",
                           params={"granularity": granularity})

    def book_activity(self, granularity: str = "month") -> s.Activity:
        return self._model(s.Activity, "GET", "/book/analytics/activity",
                           params={"granularity": granularity})

    def book_risk(self, refresh: bool = False) -> dict[str, Any]:
        return self._call("POST" if refresh else "GET",
                          "/book/risk/refresh" if refresh else "/book/risk")

    # ------------------------------------------------------------------ clients
    def client_risk(self, client_id: str, account_id: str | None = None,
                    refresh: bool = False) -> dict[str, Any]:
        return self._call("POST" if refresh else "GET",
                          f"/clients/{client_id}/risk" + ("/refresh" if refresh else ""),
                          params={"account_id": account_id})

    def clients(self, search: str | None = None, status: str | None = None) -> s.ClientList:
        return self._model(s.ClientList, "GET", "/clients",
                           params={"search": search, "status": status})

    def delete_client(self, client_id: str) -> None:
        self._call("DELETE", f"/clients/{client_id}")

    def create_client(self, body: dict[str, Any]) -> s.ClientOut:
        return self._model(s.ClientOut, "POST", "/clients", json=body)

    def client(self, client_id: str) -> s.ClientDetail:
        return self._model(s.ClientDetail, "GET", f"/clients/{client_id}")

    def update_client(self, client_id: str, body: dict[str, Any]) -> s.ClientOut:
        return self._model(s.ClientOut, "PATCH", f"/clients/{client_id}", json=body)

    def client_accounts(self, client_id: str) -> s.AccountList:
        return self._model(s.AccountList, "GET", f"/clients/{client_id}/accounts")

    def create_account(self, client_id: str, body: dict[str, Any]) -> s.AccountSummary:
        return self._model(s.AccountSummary, "POST", f"/clients/{client_id}/accounts", json=body)

    def client_tracking_error(self, client_id: str, window: int = 63,
                              account_id: str | None = None) -> s.TrackingError:
        return self._model(s.TrackingError, "GET", f"/clients/{client_id}/analytics/tracking-error",
                           params={"window": window, "account_id": account_id})

    def client_tax_savings(self, client_id: str, granularity: str = "month",
                           account_id: str | None = None) -> s.TaxSavings:
        return self._model(s.TaxSavings, "GET", f"/clients/{client_id}/analytics/tax-savings",
                           params={"granularity": granularity, "account_id": account_id})

    def client_summary(self, client_id: str, account_id: str | None = None
                       ) -> s.ClientAnalyticsSummary:
        return self._model(s.ClientAnalyticsSummary, "GET",
                           f"/clients/{client_id}/analytics/summary",
                           params={"account_id": account_id})

    def client_events(self, client_id: str, *, type_: str | None = None,
                      account_id: str | None = None) -> s.EventList:
        return self._model(s.EventList, "GET", f"/clients/{client_id}/events",
                           params={"type": type_, "account_id": account_id})

    def event(self, event_id: str) -> s.EventDetail:
        return self._model(s.EventDetail, "GET", f"/events/{event_id}")

    # ------------------------------------------------------------------ accounts
    def account(self, account_id: str) -> s.AccountDetail:
        return self._model(s.AccountDetail, "GET", f"/accounts/{account_id}")

    def account_exposures(self, account_id: str) -> s.ExposuresOut:
        return self._model(s.ExposuresOut, "GET", f"/accounts/{account_id}/analytics/exposures")

    # ------------------------------------------------------------------ models
    def models(self, objective: str | None = None) -> s.ModelList:
        return self._model(s.ModelList, "GET", "/models", params={"objective": objective})

    def model(self, model_id: str) -> s.ModelDetail:
        return self._model(s.ModelDetail, "GET", f"/models/{model_id}")

    # ------------------------------------------------------------------ model management
    def model_catalog(self) -> dict[str, Any]:
        return self._call("GET", "/model-catalog")

    # ------------------------------------------------------------------ model builder
    def mb_universe(self, q: str = "", limit: int = 400) -> list[dict[str, Any]]:
        return self._call("GET", "/model-builder/universe", params={"q": q, "limit": limit})

    def mb_analyze(self, holdings: dict[str, float], name: str) -> dict[str, Any]:
        return self._call("POST", "/model-builder/analyze",
                          json={"holdings": holdings, "name": name})

    def mb_import(self, filename: str, content_base64: str) -> dict[str, Any]:
        return self._call("POST", "/model-builder/import",
                          json={"filename": filename, "content_base64": content_base64})

    def mb_scale(self, holdings: dict[str, float], n: int, lo: int, hi: int) -> list[dict[str, Any]]:
        return self._call("POST", "/model-builder/scale",
                          json={"holdings": holdings, "n": n, "lo": lo, "hi": hi})

    def mb_assist(self, draft: dict[str, Any], message: str | None = None,
                  reply: str | None = None) -> dict[str, Any]:
        return self._call("POST", "/model-builder/assist",
                          json={"draft": draft, "message": message, "reply": reply})

    def mb_save(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/model-builder/save", json=draft)

    def mb_sample(self, fmt: str = "xlsx") -> bytes:
        return self._call("GET", "/model-builder/sample", params={"fmt": fmt})

    def create_line(self, body: dict[str, Any]) -> str:
        return self._call("POST", "/model-catalog/lines", json=body)["id"]

    def update_line(self, line_id: str, body: dict[str, Any]) -> None:
        self._call("PATCH", f"/model-catalog/lines/{line_id}", json=body)

    def delete_line(self, line_id: str) -> None:
        self._call("DELETE", f"/model-catalog/lines/{line_id}")

    def create_catalog_model(self, body: dict[str, Any]) -> str:
        return self._call("POST", "/model-catalog/models", json=body)["id"]

    def update_catalog_model(self, model_id: str, body: dict[str, Any]) -> None:
        self._call("PATCH", f"/model-catalog/models/{model_id}", json=body)

    def delete_catalog_model(self, model_id: str) -> None:
        self._call("DELETE", f"/model-catalog/models/{model_id}")

    def compare(self, model_ids: list[str], account_id: str) -> s.ComparisonPayload:
        return self._model(s.ComparisonPayload, "POST", "/models/compare",
                           json={"model_ids": model_ids, "account_id": account_id})

    # ------------------------------------------------------------------ transitions
    def create_transition(self, client_id: str, account_id: str,
                          fixes: list[str] | None = None) -> s.TransitionOut:
        return self._model(s.TransitionOut, "POST", "/transitions",
                           json={"client_id": client_id, "account_id": account_id,
                                 "fixes": fixes or []})

    def account_diagnosis(self, account_id: str) -> dict[str, Any]:
        return dict(self._call("GET", f"/accounts/{account_id}/diagnosis"))

    def client_diagnosis(self, client_id: str) -> dict[str, Any]:
        return dict(self._call("GET", f"/clients/{client_id}/diagnosis"))

    def transition(self, transition_id: str) -> s.TransitionOut:
        return self._model(s.TransitionOut, "GET", f"/transitions/{transition_id}")

    def chat(self, transition_id: str, *, message: str | None = None,
             quick_reply: str | None = None, action: str | None = None) -> s.ChatTurn:
        body = {k: v for k, v in {"message": message, "quick_reply": quick_reply,
                                  "action": action}.items() if v is not None}
        return self._model(s.ChatTurn, "POST", f"/transitions/{transition_id}/chat", json=body)

    def back(self, transition_id: str, to_state: str) -> s.ChatTurn:
        return self._model(s.ChatTurn, "POST", f"/transitions/{transition_id}/back",
                           json={"to_state": to_state})

    def history(self, transition_id: str) -> s.ChatHistory:
        return self._model(s.ChatHistory, "GET", f"/transitions/{transition_id}/history")

    def set_locks(self, transition_id: str, lot_ids: list[str]) -> s.TransitionOut:
        return self._model(s.TransitionOut, "PUT", f"/transitions/{transition_id}/locks",
                           json={"lot_ids": lot_ids})

    def optimize(self, transition_id: str, body: dict[str, Any]) -> s.OptimizationResult:
        return self._model(s.OptimizationResult, "POST", f"/transitions/{transition_id}/optimize",
                           json=body)

    def frontier(self, transition_id: str, body: dict[str, Any]) -> s.FrontierResult:
        return self._model(s.FrontierResult, "POST", f"/transitions/{transition_id}/frontier",
                           json=body)

    def transition_analytics(self, transition_id: str) -> dict[str, Any]:
        return dict(self._call("GET", f"/transitions/{transition_id}/analytics"))

    def trades_csv(self, transition_id: str) -> bytes:
        return bytes(self._call("GET", f"/transitions/{transition_id}/trades.csv"))

    def summary_pdf(self, transition_id: str) -> bytes:
        return bytes(self._call("GET", f"/transitions/{transition_id}/summary.pdf"))

    # ------------------------------------------------------------------ ingest
    def upload_pdf(self, transition_id: str, filename: str, content: bytes) -> s.ParsePreview:
        return self._model(s.ParsePreview, "POST", "/ingest/pdf",
                           files={"file": (filename, content, "application/pdf")},
                           data={"transition_id": transition_id})

    def plaid_link_token(self) -> s.LinkTokenOut:
        return self._model(s.LinkTokenOut, "POST", "/ingest/plaid/link-token")

    def plaid_exchange(self, transition_id: str, public_token: str) -> s.ParsePreview:
        return self._model(s.ParsePreview, "POST", "/ingest/plaid/exchange",
                           json={"public_token": public_token, "transition_id": transition_id})

    def confirm_ingest(self, transition_id: str, body: dict[str, Any]) -> s.ConfirmResult:
        return self._model(s.ConfirmResult, "POST", f"/ingest/{transition_id}/confirm", json=body)


def api(token: str | None) -> ApiClient:
    """Shorthand used by callbacks: ``api(token).book_summary()``."""
    return ApiClient(token)
