"""Approving a transition: apply the trade list to the account and record a management event."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from app.db import models as m
from app.db.lot_refs import next_lot_refs
from app.schemas.transitions import OptimizationResult
from app.services.transitions import TransitionService


def approve_transition(ts: TransitionService, t: m.Transition, naive_tax: float | None) -> str:
    """Execute the last optimization's trades on the account (synthetic) and log the event.

    ``naive_tax`` is the estimated tax of a full, unbudgeted transition; taxes saved is the
    difference to this plan's tax (the same "gains deferred vs a naive rebalance" definition the
    seeded history uses).
    """
    r: OptimizationResult = ts.last_result(t)
    a = ts.account(t)
    lots = {lot.id: lot for lot in a.lots}
    for s in r.trades.sells:
        lot = lots.get(s.lot_id)
        if lot is None or lot.quantity + 1e-6 < s.shares:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Holdings changed since the optimization; re-run it before approving",
            )
    for s in r.trades.sells:
        lot = lots[s.lot_id]
        remaining = lot.quantity - s.shares
        if remaining <= 1e-6:
            ts.db.delete(lot)
        else:
            lot.cost_basis_total *= remaining / lot.quantity
            lot.quantity = remaining
    buy_refs = iter(next_lot_refs(a.id, (lot.lot_ref for lot in a.lots), len(r.trades.buys)))
    for b in r.trades.buys:
        ts.db.add(
            m.Lot(
                id=f"lot_{uuid.uuid4().hex[:10]}",
                account_id=a.id,
                lot_ref=next(buy_refs),
                ticker=b.ticker,
                quantity=b.shares,
                cost_basis_total=b.value,
                acquired_date=r.as_of,
                locked=False,
                source="trade",
            )
        )
    a.cash = r.summary.cash_after
    a.target_model_id = r.target_model_id

    rz = r.realized
    saved = max((naive_tax or 0.0) - rz.est_tax, 0.0) if r.taxable else 0.0
    budget = (
        "no budget"
        if r.budget_value is None
        else f"{r.budget_mode.replace('_', ' ')} budget ${r.budget_value:,.0f}"
    )
    event = m.ManagementEvent(
        id=f"evt_{uuid.uuid4().hex[:10]}",
        account_id=a.id,
        event_date=r.as_of,
        event_type="transition",
        trigger="client_request",
        n_trades=len(r.trades.sells) + len(r.trades.buys),
        turnover=r.summary.turnover,
        realized_st_gain=rz.st_gain,
        realized_lt_gain=rz.lt_gain,
        losses_harvested=round(rz.st_loss + rz.lt_loss, 2),
        realized_st_loss=round(rz.st_loss, 2),
        realized_lt_loss=round(rz.lt_loss, 2),
        est_taxes_saved=round(saved, 2),
        te_before=r.pre.te,
        te_after=r.post.te,
        cash_flow_amount=0.0,
        note=f"Guided transition into {r.target_model_id} ({budget}); approved by advisor.",
        trades=[
            *[
                m.EventTrade(
                    ticker=s.ticker,
                    side="sell",
                    shares=s.shares,
                    price=s.price,
                    value=s.proceeds,
                    realized_gain=s.realized_gain if r.taxable else 0.0,
                    term=s.term if r.taxable else None,
                )
                for s in r.trades.sells
            ],
            *[
                m.EventTrade(
                    ticker=b.ticker,
                    side="buy",
                    shares=b.shares,
                    price=b.price,
                    value=b.value,
                    realized_gain=0.0,
                    term=None,
                )
                for b in r.trades.buys
            ],
        ],
    )
    ts.db.add(event)
    ts.db.flush()
    ts._save(t, approved_event_id=event.id)
    return event.id
