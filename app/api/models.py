"""Target-model catalog, comparison and regime labels."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import delete

from app.analytics.regimes import RegimeCsvError, parse_regime_csv
from app.api.deps import DB, Service, account_or_404
from app.db import models as m
from app.schemas.models import (
    CompareRequest,
    ComparisonPayload,
    ModelDetail,
    ModelList,
    RegimeUploadResult,
)
from app.services.models import ModelService

router = APIRouter(tags=["models"])

MAX_REGIME_CSV_BYTES = 2 * 1024 * 1024


@router.get("/models", response_model=ModelList, summary="Target-model catalog")
def list_models(
    svc: Service,
    objective: Literal["total_return", "income", "tax_efficient"] | None = None,
    construction: str | None = Query(None, examples=["market_cap"]),
) -> ModelList:
    return ModelService(svc).list_models(objective, construction)


@router.get("/models/{model_id}", response_model=ModelDetail, summary="Model detail + holdings")
def get_model(model_id: str, svc: Service) -> ModelDetail:
    ms = ModelService(svc)
    mp = ms.get(model_id)
    if mp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model {model_id} not found")
    return ms.detail(mp)


@router.post(
    "/models/compare",
    response_model=ComparisonPayload,
    summary="Compare models for an account: stats, TE from current holdings, full-transition tax",
)
def compare_models(body: CompareRequest, svc: Service) -> ComparisonPayload:
    ms = ModelService(svc)
    unknown = [mid for mid in body.model_ids if ms.get(mid) is None]
    if unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown model(s): {', '.join(unknown)}")
    account = account_or_404(svc, body.account_id)
    ids = list(dict.fromkeys(body.model_ids))  # de-duplicate, keep order
    return ms.compare(ids, account)


@router.post(
    "/analytics/regimes",
    response_model=RegimeUploadResult,
    tags=["analytics"],
    summary="Upload macro-regime labels (CSV: date,regime). Replaces previous labels.",
)
async def upload_regimes(svc: Service, db: DB, file: UploadFile = File(...)) -> RegimeUploadResult:
    raw = await file.read(MAX_REGIME_CSV_BYTES + 1)
    if len(raw) > MAX_REGIME_CSV_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "CSV larger than 2 MB")
    try:
        labels = parse_regime_csv(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, RegimeCsvError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.execute(delete(m.RegimeLabel).where(m.RegimeLabel.advisor_id == svc.advisor_id))
    db.add_all(
        m.RegimeLabel(advisor_id=svc.advisor_id, label_date=d, regime=r) for d, r in labels.items()
    )
    db.commit()
    counts: dict[str, int] = {}
    for r in labels.values():
        counts[r] = counts.get(r, 0) + 1
    return RegimeUploadResult(
        n_dates=len(labels), first_date=min(labels), last_date=max(labels), regimes=counts
    )


@router.delete(
    "/analytics/regimes",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["analytics"],
    summary="Remove uploaded regime labels",
)
def clear_regimes(svc: Service, db: DB) -> None:
    db.execute(delete(m.RegimeLabel).where(m.RegimeLabel.advisor_id == svc.advisor_id))
    db.commit()
