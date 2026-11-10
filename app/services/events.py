from __future__ import annotations

from app.db import models as m
from app.schemas.accounts import EventDetail, EventOut, TradeOut


def event_out(e: m.ManagementEvent) -> EventOut:
    return EventOut(
        id=e.id,
        account_id=e.account_id,
        account_nickname=e.account.nickname,
        date=e.event_date,
        type=e.event_type,
        trigger=e.trigger,
        n_trades=e.n_trades,
        turnover=e.turnover,
        realized_st_gain=e.realized_st_gain,
        realized_lt_gain=e.realized_lt_gain,
        losses_harvested=e.losses_harvested,
        est_taxes_saved=e.est_taxes_saved,
        te_before=e.te_before,
        te_after=e.te_after,
        cash_flow_amount=e.cash_flow_amount,
        note=e.note,
    )


def event_detail(e: m.ManagementEvent) -> EventDetail:
    return EventDetail(
        **event_out(e).model_dump(),
        client_id=e.account.client_id,
        trades=[
            TradeOut(
                ticker=t.ticker,
                side=t.side,
                shares=t.shares,
                price=t.price,
                value=t.value,
                realized_gain=t.realized_gain,
                term=t.term,
            )
            for t in e.trades
        ],
    )
