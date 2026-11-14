"""Model management API: lines and target models, saved to the JSON catalog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, status

from app.api.deps import Service
from app.core.config import get_settings
from app.schemas import model_catalog as sc
from app.services.model_catalog import CatalogError, ModelCatalogService

router = APIRouter(prefix="/model-catalog", tags=["model management"])
T = TypeVar("T")


def _svc(svc: Service) -> ModelCatalogService:
    return ModelCatalogService(svc.db, svc.p, get_settings().MODELS_FILE)


def _run(fn: Callable[..., T], *args: Any) -> T:
    try:
        return fn(*args)
    except CatalogError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("", response_model=sc.ModelCatalog, summary="Categories → lines → models")
def get_catalog(svc: Service) -> sc.ModelCatalog:
    return _svc(svc).get()


@router.post(
    "/lines", response_model=sc.Created, status_code=status.HTTP_201_CREATED, summary="Add a line"
)
def create_line(body: sc.LineIn, svc: Service) -> sc.Created:
    return sc.Created(id=_run(_svc(svc).create_line, body))


@router.patch("/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Edit a line")
def update_line(line_id: str, body: sc.LinePatch, svc: Service) -> None:
    _run(_svc(svc).update_line, line_id, body)


@router.delete(
    "/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a line and its models (409 while an account targets one of them)",
)
def delete_line(line_id: str, svc: Service) -> None:
    _run(_svc(svc).delete_line, line_id)


@router.post(
    "/models",
    response_model=sc.Created,
    status_code=status.HTTP_201_CREATED,
    summary="Add a model to a line",
)
def create_model(body: sc.ModelIn, svc: Service) -> sc.Created:
    return sc.Created(id=_run(_svc(svc).create_model, body))


@router.patch("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Edit a model")
def update_model(model_id: str, body: sc.ModelPatch, svc: Service) -> None:
    _run(_svc(svc).update_model, model_id, body)


@router.delete(
    "/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a model (409 while an account targets it)",
)
def delete_model(model_id: str, svc: Service) -> None:
    _run(_svc(svc).delete_model, model_id)
