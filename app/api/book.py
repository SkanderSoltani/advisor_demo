"""Advisor landing page: book totals and book-level history."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics.types import Granularity as AGranularity
from app.api.deps import Service
from app.schemas.analytics import Activity, BookSummary, BookTrackingError, TaxImpact
from app.schemas.common import Granularity, TEWindow

router = APIRouter(prefix="/book", tags=["book"])


@router.get("/summary", response_model=BookSummary, summary="Advisor-level totals")
def summary(svc: Service) -> BookSummary:
    return svc.book_summary()


@router.get(
    "/analytics/tracking-error",
    response_model=BookTrackingError,
    summary="AUM-weighted average rolling TE across all accounts + 10th–90th percentile band",
)
def tracking_error(svc: Service, window: TEWindow = Query(TEWindow.d63)) -> BookTrackingError:
    return svc.book_tracking_error(int(window))


@router.get(
    "/analytics/tax-impact",
    response_model=TaxImpact,
    summary="Taxes saved, losses harvested and realized gains per period, with cumulative totals",
)
def tax_impact(svc: Service, granularity: Granularity = Granularity.month) -> TaxImpact:
    return svc.book_tax_impact(AGranularity(granularity.value))


@router.get(
    "/analytics/activity",
    response_model=Activity,
    summary="Management events per period by type, and AUM at period end",
)
def activity(svc: Service, granularity: Granularity = Granularity.month) -> Activity:
    return svc.book_activity(AGranularity(granularity.value))
