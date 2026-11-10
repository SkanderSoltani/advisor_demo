"""Ingestion service: build previews (PDF / Plaid) and commit confirmed lots."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, select

from app.agent.llm import LLMClient
from app.db import models as m
from app.db.lot_refs import next_lot_refs
from app.ingest.normalizer import (
    Issue,
    NormalizedRow,
    SecurityRef,
    normalize_rows,
    parse_confidence,
)
from app.ingest.pdf_parser import PdfError, parse_pdf
from app.ingest.plaid_client import PlaidError, PlaidGateway, holdings_to_rows
from app.schemas import ingest as si
from app.services.transitions import TransitionService

STATE_REVIEW = "INGEST_REVIEW"
STATE_AFTER_INGEST = "TARGET_KNOWLEDGE"


class IngestService:
    def __init__(self, ts: TransitionService) -> None:
        self.ts = ts
        self.db = ts.db
        self.p = ts.p
        self.as_of = ts.ps.as_of

    # ------------------------------------------------------------------ helpers
    def securities(self) -> dict[str, SecurityRef]:
        rows = list(self.db.scalars(select(m.Security)))
        prices = self.p.get_prices([s.ticker for s in rows])
        return {s.ticker: SecurityRef(s.ticker, s.name, prices[s.ticker]) for s in rows}

    @staticmethod
    def _row_out(r: NormalizedRow) -> si.PreviewRow:
        return si.PreviewRow(
            row_id=r.row_id,
            lot_ref=r.lot_ref,
            ticker=r.ticker,
            description=r.description,
            quantity=r.quantity,
            acquired_date=r.acquired_date,
            cost_basis_total=r.cost_basis_total,
            statement_value=r.statement_value,
            current_price=r.current_price,
            market_value=r.market_value,
            unrealized_gain=r.unrealized_gain,
            holding_period=r.holding_period,
            basis_estimated=r.basis_estimated,
            confidence=r.confidence,
            issues=[
                si.IssueOut(code=i.code, severity=i.severity, message=i.message) for i in r.issues
            ],
            suggested_ticker=r.suggested_ticker,
            include=not r.has_errors,
        )

    def _preview(
        self,
        t: m.Transition,
        source: str,
        method: str,
        rows: list[NormalizedRow],
        confidence: float,
        cash: float | None,
        statement_date: object,
        notes: list[str],
        llm_provider: str | None = None,
    ) -> si.ParsePreview:
        out_rows = [self._row_out(r) for r in rows]
        summary = si.PreviewSummary(
            n_rows=len(rows),
            n_error_rows=sum(r.has_errors for r in rows),
            n_warning_rows=sum(
                (not r.has_errors) and any(i.severity == "warning" for i in r.issues) for r in rows
            ),
            n_basis_unknown=sum(r.cost_basis_total is None or r.basis_estimated for r in rows),
            n_missing_dates=sum(r.acquired_date is None for r in rows),
            total_market_value=round(sum(r.market_value or 0.0 for r in rows), 2),
            total_cost_basis=round(sum(r.cost_basis_total or 0.0 for r in rows), 2),
        )
        preview = si.ParsePreview(
            transition_id=t.id,
            account_id=t.account_id,
            source=source,
            method=method,
            llm_provider=llm_provider,
            confidence=confidence,
            statement_date=statement_date,
            cash_detected=cash,
            requires_basis_decision=summary.n_basis_unknown > 0 or summary.n_missing_dates > 0,
            summary=summary,
            rows=out_rows,
            notes=notes,
        )
        t.state = STATE_REVIEW
        self.ts._save(t, ingest_preview=preview.model_dump(mode="json"))
        return preview

    # ------------------------------------------------------------------ PDF
    def preview_pdf(self, t: m.Transition, data: bytes, llm: LLMClient) -> si.ParsePreview:
        try:
            r = parse_pdf(data, self.securities(), self.as_of, llm)
        except PdfError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        return self._preview(
            t,
            "pdf",
            r.method,
            r.rows,
            r.confidence,
            r.cash,
            r.statement_date,
            r.notes,
            r.llm_provider,
        )

    # ------------------------------------------------------------------ Plaid
    def preview_plaid(
        self, t: m.Transition, gateway: PlaidGateway, public_token: str
    ) -> si.ParsePreview:
        try:
            access = gateway.exchange_public_token(public_token)
            portfolio = gateway.fetch_portfolio(access, self.as_of)
        except PlaidError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        # the access token is used once here and never stored or returned
        raw = holdings_to_rows(portfolio, self.as_of)
        rows = normalize_rows(raw, self.securities(), self.as_of)
        notes = [f"Imported from {portfolio.institution} ({gateway.mode})", *portfolio.warnings]
        n_est = sum(r.basis_estimated for r in rows)
        if n_est:
            notes.append(
                f"{n_est} lots have no lot-level basis or date "
                "(Plaid reports positions, not lots). "
                "Upload a tax-lot statement or confirm with assume_average_cost=true."
            )
        return self._preview(
            t, "plaid", "plaid", rows, parse_confidence(rows), portfolio.cash, None, notes
        )

    # ------------------------------------------------------------------ confirm
    def confirm(self, t: m.Transition, req: si.ConfirmRequest) -> si.ConfirmResult:
        preview_raw = (t.data or {}).get("ingest_preview")
        if not preview_raw:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Nothing to confirm: upload or link first"
            )
        preview = si.ParsePreview.model_validate(preview_raw)
        secs = self.securities()
        included = [r for r in req.rows if r.include]
        if not included:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No rows included")

        assumptions: list[str] = []
        raw: list[dict[str, object]] = []
        n_assumed_basis = n_assumed_date = 0
        assumed_date = self.as_of - timedelta(days=366)
        for r in included:
            ticker = r.ticker.strip().upper()
            basis, acquired, estimated = r.cost_basis_total, r.acquired_date, False
            if req.assume_average_cost:
                if basis is None and ticker in secs:
                    basis = r.quantity * secs[ticker].price
                    n_assumed_basis += 1
                    estimated = True
                if acquired is None:
                    acquired = assumed_date
                    n_assumed_date += 1
                    estimated = True
            raw.append(
                {
                    "ticker": ticker,
                    "quantity": r.quantity,
                    "acquired_date": acquired,
                    "cost_basis_total": basis,
                    "basis_estimated": estimated,
                    "lot_ref": r.lot_ref,
                }
            )
        if n_assumed_basis:
            assumptions.append(f"{n_assumed_basis} lots: basis set to today's value (no gain)")
        if n_assumed_date:
            assumptions.append(f"{n_assumed_date} lots: acquired date assumed {assumed_date} (LT)")

        norm = normalize_rows(raw, secs, self.as_of)
        a = self.ts.account(t)
        kept_refs = set() if req.mode == "replace" else {lot.lot_ref for lot in a.lots}
        errors = []
        for cr, nr in zip(included, norm, strict=True):
            blocking = [i for i in nr.issues if i.severity == "error"]
            if nr.lot_ref and nr.lot_ref in kept_refs:
                blocking.append(
                    Issue(
                        "lot_id_exists", "error", f"Lot ID {nr.lot_ref} is already in the account"
                    )
                )
            if nr.cost_basis_total is None:
                blocking.append(
                    Issue(
                        "missing_basis",
                        "error",
                        "Cost basis required (or confirm with assume_average_cost=true)",
                    )
                )
            if blocking:
                errors.append(
                    si.RowError(
                        row_id=cr.row_id,
                        ticker=cr.ticker,
                        issues=[
                            si.IssueOut(code=i.code, severity="error", message=i.message)
                            for i in blocking
                        ],
                    ).model_dump(mode="json")
                )
        if errors:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"message": "Some included rows are invalid; fix or exclude them", "rows": errors},
            )

        if req.mode == "replace":
            self.db.execute(delete(m.Lot).where(m.Lot.account_id == a.id))
        # rows without a Lot ID get the next free one for the account
        new_refs = iter(
            next_lot_refs(
                a.id,
                kept_refs | {nr.lot_ref for nr in norm},
                sum(1 for nr in norm if not nr.lot_ref),
            )
        )
        total_mv = 0.0
        for cr, nr in zip(included, norm, strict=True):
            assert (
                nr.ticker and nr.quantity and nr.acquired_date and nr.cost_basis_total is not None
            )
            self.db.add(
                m.Lot(
                    id=f"lot_{uuid.uuid4().hex[:10]}",
                    account_id=a.id,
                    lot_ref=nr.lot_ref or next(new_refs),
                    ticker=nr.ticker,
                    quantity=nr.quantity,
                    cost_basis_total=nr.cost_basis_total,
                    acquired_date=nr.acquired_date,
                    locked=cr.locked,
                    source=preview.source,
                    basis_unknown=nr.basis_estimated,
                )
            )
            total_mv += nr.market_value or 0.0
        cash = req.cash if req.cash is not None else preview.cash_detected
        if cash is not None:
            a.cash = cash
        t.state = STATE_AFTER_INGEST
        self.db.flush()
        self.ts._save(
            t,
            drop=("ingest_preview", "optimization", "frontier"),
            ingested={"source": preview.source, "method": preview.method, "n_lots": len(norm)},
        )
        self.db.refresh(a)
        return si.ConfirmResult(
            transition_id=t.id,
            account_id=a.id,
            state=t.state,
            n_committed=len(norm),
            n_excluded=len(req.rows) - len(included),
            total_market_value=round(total_mv, 2),
            cash=round(a.cash, 2),
            assumptions=assumptions,
        )
