"""Account detail + account analytics, and single-event lookup."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.analytics.types import Granularity as AGranularity
from app.api.deps import DB, Service, account_or_404
from app.db import models as m
from app.model_builder.diagnosis import Diagnosis
from app.schemas.accounts import AccountDetail, EventDetail
from app.schemas.analytics import ExposuresOut, TaxHistory, TrackingError
from app.schemas.common import Granularity, TEWindow
from app.services.diagnosis import DiagnosisService
from app.services.events import event_detail

router = APIRouter(tags=["accounts"])


@router.get(
    "/accounts/{account_id}", response_model=AccountDetail, summary="Holdings, lots, metrics"
)
def get_account(account_id: str, svc: Service) -> AccountDetail:
    return svc.account_detail(account_or_404(svc, account_id))


@router.get(
    "/accounts/{account_id}/analytics/tax-history",
    response_model=TaxHistory,
    summary="Realized ST/LT gains, harvested losses, estimated tax paid and saved",
)
def tax_history(
    account_id: str, svc: Service, granularity: Granularity = Granularity.month
) -> TaxHistory:
    return svc.account_tax_history(account_or_404(svc, account_id), AGranularity(granularity.value))


@router.get(
    "/accounts/{account_id}/analytics/tracking-error",
    response_model=TrackingError,
    summary="Rolling ex-post TE vs target, plus ex-ante TE today",
)
def tracking_error(
    account_id: str, svc: Service, window: TEWindow = Query(TEWindow.d63)
) -> TrackingError:
    a = account_or_404(svc, account_id)
    return svc.tracking_error([a], int(window), a.id)


@router.get(
    "/accounts/{account_id}/diagnosis",
    response_model=Diagnosis,
    summary="AI review checks: concentration, sector/region tilts, risk vs benchmark, tax & cash",
)
def diagnosis(account_id: str, svc: Service,
              target_model_id: str | None = Query(None, description="compare against this model "
                                                  "(default: the account's own target)"),
              use_target: bool = Query(True, description="false = always the auto blend"),
              ) -> Diagnosis:
    return DiagnosisService(svc).account(account_or_404(svc, account_id), target_model_id,
                                         use_target)


@router.get(
    "/accounts/{account_id}/analytics/exposures",
    response_model=ExposuresOut,
    summary="Sector weights vs target, top active weights, concentration, yield, beta, factors",
)
def exposures(account_id: str, svc: Service) -> ExposuresOut:
    return svc.account_exposures(account_or_404(svc, account_id))


@router.get(
    "/events/{event_id}", response_model=EventDetail, tags=["events"], summary="Event + trade list"
)
def get_event(event_id: str, svc: Service, db: DB) -> EventDetail:
    e = db.get(m.ManagementEvent, event_id)
    if e is None or e.account.client.advisor_id != svc.advisor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Event {event_id} not found")
    return event_detail(e)
