"""Transition sessions: create, read, guided chat, back, locks, optimize, frontier, exports."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.agent.engine import ConversationEngine
from app.agent.llm import LLMClient, get_llm
from app.api.deps import Service
from app.ingest.plaid_client import PlaidGateway, get_plaid_gateway
from app.schemas.chat import BackRequest, ChatHistory, ChatHistoryItem, ChatRequest, ChatTurn
from app.schemas.transitions import (
    FrontierRequest,
    FrontierResult,
    LocksRequest,
    OptimizationResult,
    OptimizeRequest,
    TransitionCreate,
    TransitionOut,
)
from app.services.transitions import TransitionService

router = APIRouter(prefix="/transitions", tags=["transitions"])

LLM = Annotated[LLMClient, Depends(get_llm)]
Plaid = Annotated[PlaidGateway, Depends(get_plaid_gateway)]


@router.post(
    "",
    response_model=TransitionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a transition for an account (empty accounts start at INGEST_CHOICE)",
)
def create_transition(body: TransitionCreate, svc: Service) -> TransitionOut:
    ts = TransitionService(svc)
    return ts.out(ts.create(body.client_id, body.account_id))


@router.get("/{transition_id}", response_model=TransitionOut, summary="Transition session state")
def get_transition(transition_id: str, svc: Service) -> TransitionOut:
    ts = TransitionService(svc)
    return ts.out(ts.get(transition_id))


@router.post(
    "/{transition_id}/chat",
    response_model=ChatTurn,
    summary="Guided conversation turn: send a message, a quick reply, or an action",
)
def chat(transition_id: str, body: ChatRequest, svc: Service, llm: LLM, plaid: Plaid) -> ChatTurn:
    ts = TransitionService(svc)
    return ConversationEngine(ts, llm, plaid).turn(ts.get(transition_id), body)


@router.post(
    "/{transition_id}/back",
    response_model=ChatTurn,
    summary="Go back to an earlier visited state; downstream results are invalidated",
)
def back(transition_id: str, body: BackRequest, svc: Service, llm: LLM, plaid: Plaid) -> ChatTurn:
    ts = TransitionService(svc)
    return ConversationEngine(ts, llm, plaid).back(ts.get(transition_id), body.to_state)


@router.get(
    "/{transition_id}/history",
    response_model=ChatHistory,
    summary="Conversation history (to restore the chat after a reload)",
)
def history(transition_id: str, svc: Service) -> ChatHistory:
    t = TransitionService(svc).get(transition_id)
    items = [ChatHistoryItem(**h) for h in (t.data or {}).get("history", [])]
    return ChatHistory(transition_id=t.id, state=t.state, items=items)


@router.put(
    "/{transition_id}/locks",
    response_model=TransitionOut,
    summary="Set the lots locked for this transition (replaces previous locks)",
)
def set_locks(transition_id: str, body: LocksRequest, svc: Service) -> TransitionOut:
    ts = TransitionService(svc)
    return ts.set_locks(ts.get(transition_id), body.lot_ids)


@router.post(
    "/{transition_id}/optimize",
    response_model=OptimizationResult,
    summary="Run the tax-aware transition optimizer",
)
def optimize(transition_id: str, body: OptimizeRequest, svc: Service) -> OptimizationResult:
    ts = TransitionService(svc)
    return ts.optimize(ts.get(transition_id), body)


@router.post(
    "/{transition_id}/frontier",
    response_model=FrontierResult,
    summary="Efficient frontier: tax cost vs ex-ante TE across budgets",
)
def frontier(transition_id: str, body: FrontierRequest, svc: Service) -> FrontierResult:
    ts = TransitionService(svc)
    return ts.frontier(ts.get(transition_id), body)


@router.get(
    "/{transition_id}/trades.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
    summary="Trade list of the last optimization (CSV)",
)
def trades_csv(transition_id: str, svc: Service) -> Response:
    ts = TransitionService(svc)
    body = ts.trades_csv(ts.get(transition_id))
    return Response(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="trades_{transition_id}.csv"'},
    )


@router.get(
    "/{transition_id}/summary.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="PDF summary of the last optimization",
)
def summary_pdf(transition_id: str, svc: Service) -> Response:
    ts = TransitionService(svc)
    pdf = ts.summary_pdf(ts.get(transition_id))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="summary_{transition_id}.pdf"'},
    )
