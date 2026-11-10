"""Ingestion: PDF upload, Plaid (sandbox / mock), preview confirmation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.agent.llm import LLMClient, get_llm
from app.api.deps import CurrentUser, Service
from app.core.config import get_settings
from app.ingest.plaid_client import (
    MOCK_PUBLIC_TOKEN,
    PlaidError,
    PlaidGateway,
    get_plaid_gateway,
)
from app.schemas.ingest import (
    ConfirmRequest,
    ConfirmResult,
    LinkTokenOut,
    ParsePreview,
    PlaidExchangeRequest,
)
from app.services.ingest import IngestService
from app.services.transitions import TransitionService

router = APIRouter(prefix="/ingest", tags=["ingest"])

LLM = Annotated[LLMClient, Depends(get_llm)]
Plaid = Annotated[PlaidGateway, Depends(get_plaid_gateway)]


@router.post(
    "/pdf",
    response_model=ParsePreview,
    summary="Upload a tax-lot statement PDF (≤10 MB). Returns a preview; nothing is committed.",
)
async def upload_pdf(
    svc: Service,
    llm: LLM,
    file: UploadFile = File(...),
    transition_id: str = Form(...),
) -> ParsePreview:
    limit = get_settings().MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "PDF larger than the upload limit")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Empty file")
    ts = TransitionService(svc)
    return IngestService(ts).preview_pdf(ts.get(transition_id), data, llm)


@router.post(
    "/plaid/link-token",
    response_model=LinkTokenOut,
    summary="Create a Plaid Link token (Sandbox; mock in demo mode)",
)
def plaid_link_token(user: CurrentUser, plaid: Plaid) -> LinkTokenOut:
    try:
        token, exp = plaid.create_link_token(user.id)
    except PlaidError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return LinkTokenOut(
        link_token=token,
        expiration=exp,
        mode=plaid.mode,
        mock_public_token=MOCK_PUBLIC_TOKEN if plaid.mode == "mock" else None,
    )


@router.post(
    "/plaid/exchange",
    response_model=ParsePreview,
    summary="Exchange a Link public token and preview holdings + rebuilt lots",
)
def plaid_exchange(body: PlaidExchangeRequest, svc: Service, plaid: Plaid) -> ParsePreview:
    ts = TransitionService(svc)
    return IngestService(ts).preview_plaid(ts.get(body.transition_id), plaid, body.public_token)


@router.post(
    "/{transition_id}/confirm",
    response_model=ConfirmResult,
    summary="Commit the (edited) preview rows as the account's lots",
)
def confirm(transition_id: str, body: ConfirmRequest, svc: Service) -> ConfirmResult:
    ts = TransitionService(svc)
    return IngestService(ts).confirm(ts.get(transition_id), body)
