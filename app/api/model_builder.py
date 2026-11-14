"""Model Builder API: search the universe, import a model file, analyse, scale into a line, save
the line to the model catalog, and the guide (rule-based assistant)."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import Service
from app.core.config import get_settings
from app.model_builder.analytics import BuilderData, BuilderReport, analyze
from app.model_builder.assistant import AssistTurn, Draft, Tools, assist
from app.model_builder.importer import ImportResult, read_model_file
from app.model_builder.samples import SAMPLE_NAME, sample_pdf, sample_xlsx
from app.model_builder.scaling import scale_line
from app.schemas.model_catalog import HoldingIn
from app.services.model_catalog import CatalogError, ModelCatalogService

router = APIRouter(prefix="/model-builder", tags=["model builder"])


class AnalyzeIn(BaseModel):
    name: str = "Draft model"
    holdings: dict[str, float] = Field(description="ticker → weight as a fraction")


class ImportIn(BaseModel):
    filename: str
    content_base64: str


class ScaleIn(BaseModel):
    holdings: dict[str, float]
    n: int = Field(10, ge=1, le=21)
    lo: int = Field(10, ge=0, le=100)
    hi: int = Field(100, ge=0, le=100)


class ScaledOut(BaseModel):
    equity_pct: int
    label: str
    holdings: dict[str, float]
    volatility: float
    yield_: float = Field(alias="yield")
    expense_ratio_bps: float
    benchmark: str

    model_config = {"populate_by_name": True}


class AssistIn(BaseModel):
    draft: Draft
    message: str | None = None
    reply: str | None = None


class Saved(BaseModel):
    line_id: str
    model_ids: list[str]


def _catalog(svc: Service) -> ModelCatalogService:
    return ModelCatalogService(svc.db, svc.p, get_settings().MODELS_FILE)


def _data(svc: Service) -> BuilderData:
    return BuilderData.get(svc.p)


def _analyze(svc: Service, holdings: dict[str, float], name: str) -> BuilderReport:
    try:
        return analyze(holdings, name, _data(svc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _base_name(line_name: str) -> str:
    n = line_name.strip()
    return n[: -len(" Models")] if n.lower().endswith(" models") else n


def save_draft(svc: Service, d: Draft) -> tuple[str, list[str]]:
    data = _data(svc)
    line = scale_line(d.holdings, d.scale_n, d.scale_lo, d.scale_hi, data.asset_class)
    base = _base_name(d.line_name or d.name)
    models = [(m.label, f"{base} {m.label}",
               [HoldingIn(ticker=t, weight=w) for t, w in m.holdings.items()]) for m in line]
    try:
        return _catalog(svc).create_line_with_models(
            d.line_name or d.name, d.objective,
            f"Custom line built in the Model Builder from “{d.name}”: {len(line)} models from "
            f"{line[0].label} to {line[-1].label}, same equity and bond mixes at each level.",
            models)
    except CatalogError as exc:
        raise ValueError(exc.message) from exc


@router.get("/universe", summary="Search funds and stocks a model can hold")
def universe(svc: Service, q: str = Query("", max_length=60),
             limit: int = Query(25, ge=1, le=400)) -> list[dict[str, Any]]:
    items = _data(svc).universe()
    s = q.strip().lower()
    if s:
        starts = [x for x in items if x["ticker"].lower().startswith(s)]
        rest = [x for x in items if x not in starts and s in f"{x['ticker']} {x['name']}".lower()]
        items = starts + rest
    return items[:limit]


@router.post("/analyze", response_model=BuilderReport, response_model_by_alias=True,
             summary="Characteristics, exposures, risk, benchmark and hypothetical performance")
def analyze_model(body: AnalyzeIn, svc: Service) -> BuilderReport:
    return _analyze(svc, body.holdings, body.name)


@router.post("/import", response_model=ImportResult, summary="Read a model from Excel, CSV or PDF")
def import_model(body: ImportIn, svc: Service) -> ImportResult:
    try:
        raw = base64.b64decode(body.content_base64.split(",", 1)[-1])
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "The file couldn't be decoded") from exc
    try:
        return read_model_file(body.filename, raw, _data(svc).known)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/scale", response_model=list[ScaledOut], response_model_by_alias=True,
             summary="Scale a model into a line of models by equity exposure")
def scale(body: ScaleIn, svc: Service) -> list[ScaledOut]:
    data = _data(svc)
    out = []
    for m in scale_line(body.holdings, body.n, body.lo, body.hi, data.asset_class):
        r = _analyze(svc, m.holdings, m.label)
        out.append(ScaledOut(equity_pct=m.equity_pct, label=m.label, holdings=m.holdings,
                             volatility=r.volatility, yield_=r.yield_,
                             expense_ratio_bps=r.net_expense_ratio_bps,
                             benchmark=r.benchmark.short))
    return out


@router.post("/save", response_model=Saved, status_code=status.HTTP_201_CREATED,
             summary="Save the scaled line under Custom Models")
def save(body: Draft, svc: Service) -> Saved:
    if not body.holdings:
        raise HTTPException(422, "Add holdings first")
    try:
        lid, ids = save_draft(svc, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Saved(line_id=lid, model_ids=ids)


@router.post("/assist", response_model=AssistTurn, summary="Guide turn (rule-based assistant)")
def assist_turn(body: AssistIn, svc: Service) -> AssistTurn:
    data = _data(svc)
    cat = _catalog(svc).get()
    models = [m.model_dump() for c in cat.categories for ln in c.lines for m in ln.models]
    tools = Tools(known=data.known, asset_class=data.asset_class, models=models,
                  analyze=lambda h, n: _analyze(svc, h, n), save=lambda d: save_draft(svc, d))
    return assist(body.draft, body.message, body.reply, tools)


@router.get("/sample", summary="Sample model file (xlsx or pdf) for the import demo")
def sample(svc: Service, fmt: str = Query("xlsx", pattern="^(xlsx|pdf)$")) -> Response:
    if fmt == "pdf":
        disp = f'attachment; filename="{SAMPLE_NAME}.pdf"'
        return Response(sample_pdf(), media_type="application/pdf",
                        headers={"Content-Disposition": disp})
    return Response(sample_xlsx(), media_type="application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{SAMPLE_NAME}.xlsx"'})
