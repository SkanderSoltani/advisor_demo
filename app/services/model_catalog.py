"""Model management: add / edit / delete model lines and target models.

The JSON catalog (``data/models/target_models.json``) is the master copy. Every change is
validated, written to the file, then synced into the database (``sync_catalog``) so the rest of
the app (client targets, analytics, the transition flow) sees it immediately.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.catalog import (
    CATEGORIES,
    RISK_PROFILES,
    CatalogFile,
    ModelHoldingSpec,
    ModelLineSpec,
    TargetModelSpec,
    build_fund_proxies,
    load_catalog,
    save_catalog,
)
from app.db.catalog_sync import sync_catalog
from app.schemas import model_catalog as sc

BENCHMARKS = {
    "total_return": "SYN-LMC (Synthetic US Large/Mid Cap Index)",
    "income": "SYN-DIV (Synthetic US Dividend Index)",
    "tax_efficient": "SYN-LMC (Synthetic US Large/Mid Cap Index)",
}
CONSTRUCTION = {
    "total_return": "market_cap",
    "income": "market_cap_fundamental",
    "tax_efficient": "market_cap_fundamental",
}
LINE_PREFIX = {"total_return": "TR", "income": "INC", "tax_efficient": "TAX"}
_ALLOC = re.compile(r"^\s*(\d{1,3})\s*/\s*(\d{1,3})\s*$")


def risk_key(profile: str) -> tuple[int, float]:
    """Sort key: "40/60"-style allocations by equity share, then the named profiles."""
    m_ = _ALLOC.match(profile or "")
    if m_:
        return (0, float(m_.group(1)))
    names = {r: i for i, r in enumerate(RISK_PROFILES)}
    return (1, float(names.get(profile, 99)))
_lock = threading.Lock()


class CatalogError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _code(text: str, size: int = 4) -> str:
    """Short upper-case code from a name: "Core Enhanced Models" → "CEM"."""
    words = re.findall(r"[A-Za-z0-9]+", text)
    initials = "".join(w[0] for w in words if w.lower() not in {"and", "the", "of"})
    return (initials or "X").upper()[:size]


def _unique(base: str, taken: set[str]) -> str:
    base = base[:17].strip("-") or "X"
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


class ModelCatalogService:
    def __init__(self, db: Session, provider: Any, path: Path) -> None:
        self.db = db
        self.p = provider
        self.path = path

    # ------------------------------------------------------------------ read
    def _n_accounts(self) -> dict[str, int]:
        rows = self.db.execute(
            select(m.Account.target_model_id, func.count())
            .where(m.Account.target_model_id.is_not(None))
            .group_by(m.Account.target_model_id)
        )
        return {mid: n for mid, n in rows}

    def get(self) -> sc.ModelCatalog:
        cat = load_catalog(self.path)
        n_acc = self._n_accounts()
        db_models = {mp.id: mp for mp in self.db.scalars(select(m.ModelPortfolio))}
        names = {p.ticker: p.name for p in cat.products}
        stock_names = {
            s.ticker: s.name
            for s in self.db.scalars(select(m.Security).where(m.Security.ticker.in_(cat.stocks)))
        } if cat.stocks else {}
        names.update(stock_names)

        def item(spec: TargetModelSpec) -> sc.CatalogModel:
            mp = db_models.get(spec.id)
            return sc.CatalogModel(
                id=spec.id,
                name=spec.name,
                objective=spec.objective,
                line_id=spec.line_id,
                risk_profile=spec.risk_profile,
                construction=spec.construction,
                benchmark=spec.benchmark,
                description=spec.description,
                advisory_fee_bps=spec.advisory_fee_bps,
                holdings=[
                    sc.CatalogHolding(
                        ticker=h.ticker, name=names.get(h.ticker, ""), weight=h.weight
                    )
                    for h in sorted(spec.holdings, key=lambda h: -h.weight)
                ],
                target_yield=mp.target_yield if mp else None,
                expected_te=mp.expected_te if mp else None,
                fee_bps=mp.fee_bps if mp else None,
                n_accounts=n_acc.get(spec.id, 0),
            )

        def ordered(models: list[TargetModelSpec]) -> list[sc.CatalogModel]:
            key = lambda s: (risk_key(s.risk_profile), s.name)  # noqa: E731
            return [item(s) for s in sorted(models, key=key)]

        used = {s.risk_profile for s in cat.models if s.risk_profile}
        profiles = sorted(used | set(RISK_PROFILES), key=lambda r: (risk_key(r), r))

        categories = []
        for obj, label in CATEGORIES.items():
            lines = [
                sc.CatalogLine(
                    id=ln.id,
                    name=ln.name,
                    objective=ln.objective,
                    description=ln.description,
                    provider=ln.provider,
                    models=ordered([s for s in cat.models if s.line_id == ln.id]),
                )
                for ln in cat.lines
                if ln.objective == obj
            ]
            unassigned = ordered(
                [s for s in cat.models if s.objective == obj and s.line_id is None]
            )
            categories.append(
                sc.CatalogCategory(id=obj, label=label, lines=lines, unassigned=unassigned)
            )
        return sc.ModelCatalog(
            categories=categories,
            products=[
                sc.CatalogProduct(
                    ticker=p.ticker,
                    name=p.name,
                    asset_class=p.asset_class,
                    expense_ratio_bps=p.expense_ratio_bps,
                )
                for p in cat.products
            ] + [
                sc.CatalogProduct(ticker=t, name=stock_names.get(t, t), asset_class="US Equity",
                                  expense_ratio_bps=0.0)
                for t in cat.stocks
            ],
            risk_profiles=profiles,
        )

    # ------------------------------------------------------------------ write helpers
    def _commit(self, cat: CatalogFile) -> None:
        """Validate, save the file, then sync the database."""
        try:
            cat = CatalogFile.model_validate(cat.model_dump(by_alias=True))
        except ValueError as exc:
            raise CatalogError(422, _clean(str(exc))) from exc
        save_catalog(self.path, cat)
        market = getattr(self.p, "market", None)
        funds = getattr(self.p, "funds", None)
        if market is None:
            raise CatalogError(503, "Model sync needs the synthetic market data provider")
        if funds is None:
            funds = build_fund_proxies(market, cat)
        sync_catalog(self.db, cat, market, funds)

    def _holdings(self, cat: CatalogFile, rows: list[sc.HoldingIn]) -> list[ModelHoldingSpec]:
        known = {p.ticker for p in cat.products} | set(cat.stocks)
        merged: dict[str, float] = {}
        for r in rows:
            if r.weight <= 0:
                continue
            if r.ticker not in known:
                raise CatalogError(422, f"Unknown product {r.ticker}")
            merged[r.ticker] = merged.get(r.ticker, 0.0) + r.weight
        if not merged:
            raise CatalogError(422, "Add at least one holding with a weight above 0%")
        total = sum(merged.values())
        if abs(total - 1.0) > 0.0005:
            raise CatalogError(422, f"Weights add up to {total:.2%}; they must add up to 100%")
        # absorb rounding so the stored weights sum to exactly 1
        top = max(merged, key=lambda t: merged[t])
        merged[top] = round(merged[top] + 1.0 - total, 6)
        return [ModelHoldingSpec(ticker=t, weight=round(w, 6)) for t, w in merged.items()]

    def _targeted(self, model_ids: list[str]) -> dict[str, int]:
        n = self._n_accounts()
        return {mid: n[mid] for mid in model_ids if n.get(mid)}

    @staticmethod
    def _line(cat: CatalogFile, line_id: str) -> ModelLineSpec:
        ln = next((x for x in cat.lines if x.id == line_id), None)
        if ln is None:
            raise CatalogError(404, f"Model line {line_id} not found")
        return ln

    @staticmethod
    def _model(cat: CatalogFile, model_id: str) -> TargetModelSpec:
        spec = next((x for x in cat.models if x.id == model_id), None)
        if spec is None:
            raise CatalogError(404, f"Model {model_id} not found")
        return spec

    # ------------------------------------------------------------------ lines
    def create_line(self, body: sc.LineIn) -> str:
        with _lock:
            cat = load_catalog(self.path)
            name = body.name.strip()
            if any(
                ln.name.lower() == name.lower() and ln.objective == body.objective
                for ln in cat.lines
            ):
                raise CatalogError(409, f"{CATEGORIES[body.objective]} already has a line “{name}”")
            prefix = LINE_PREFIX[body.objective]
            lid = _unique(f"{prefix}-{_code(name)}", {ln.id for ln in cat.lines})
            cat.lines.append(
                ModelLineSpec(
                    id=lid, name=name, objective=body.objective, description=body.description
                )
            )
            self._commit(cat)
            return lid

    def update_line(self, line_id: str, body: sc.LinePatch) -> None:
        with _lock:
            cat = load_catalog(self.path)
            ln = self._line(cat, line_id)
            if body.name is not None:
                name = body.name.strip()
                if not name:
                    raise CatalogError(422, "The line needs a name")
                ln.name = name
            if body.description is not None:
                ln.description = body.description
            if body.objective is not None and body.objective != ln.objective:
                ln.objective = body.objective
                for spec in cat.models:  # the line's models move to the new category
                    if spec.line_id == line_id:
                        spec.objective = body.objective
                        spec.benchmark = BENCHMARKS[body.objective]
            self._commit(cat)

    def delete_line(self, line_id: str) -> int:
        """Delete a line and its models. Refused while any of its models is a client target."""
        with _lock:
            cat = load_catalog(self.path)
            ln = self._line(cat, line_id)
            ids = [s.id for s in cat.models if s.line_id == line_id]
            used = self._targeted(ids)
            if used:
                raise CatalogError(409, _in_use(used, f"the line “{ln.name}”"))
            if len(ids) == len(cat.models):
                raise CatalogError(409, "The catalog needs at least one model")
            cat.lines = [x for x in cat.lines if x.id != line_id]
            cat.models = [s for s in cat.models if s.line_id != line_id]
            self._commit(cat)
            return len(ids)

    def create_line_with_models(
        self, name: str, objective: str, description: str,
        models: list[tuple[str, str, list[sc.HoldingIn]]], provider: str = "Custom",
    ) -> tuple[str, list[str]]:
        """Add a line and its models in one save (Model Builder). ``models``: (risk profile
        label such as "40/60", model name, holdings). Returns (line id, model ids)."""
        with _lock:
            cat = load_catalog(self.path)
            name = name.strip()
            if not name:
                raise CatalogError(422, "The line needs a name")
            if any(ln.name.lower() == name.lower() and ln.objective == objective
                   for ln in cat.lines):
                raise CatalogError(409, f"{CATEGORIES[objective]} already has a line “{name}”")
            lid = _unique(f"{LINE_PREFIX[objective]}-{_code(name)}", {ln.id for ln in cat.lines})
            cat.lines.append(ModelLineSpec(id=lid, name=name, objective=objective,  # type: ignore[arg-type]
                                           description=description, provider=provider))
            # single stocks from the synthetic universe are declared once in the catalog
            market = getattr(self.p, "market", None)
            universe = set(map(str, market.universe.index)) if market is not None else set()
            products = {p.ticker for p in cat.products}
            for _, _, rows in models:
                for r in rows:
                    t = r.ticker
                    if t not in products and t not in cat.stocks and t in universe:
                        cat.stocks.append(t)
            taken = {s.id for s in cat.models}
            names = {s.name.lower() for s in cat.models}
            ids = []
            for risk, mname, rows in models:
                if mname.lower() in names:
                    raise CatalogError(409, f"A model named “{mname}” already exists")
                code = risk.replace("/", "-") if "/" in risk else _code(risk, 3)
                mid = _unique(f"{lid}-{code}", taken)
                taken.add(mid)
                names.add(mname.lower())
                cat.models.append(TargetModelSpec(
                    id=mid, name=mname, provider=provider, objective=objective,  # type: ignore[arg-type]
                    construction=CONSTRUCTION[objective], benchmark=BENCHMARKS[objective],
                    description=description, line_id=lid, risk_profile=risk,
                    holdings=self._holdings(cat, rows),
                ))
                ids.append(mid)
            self._commit(cat)
            return lid, ids

    # ------------------------------------------------------------------ models
    def create_model(self, body: sc.ModelIn) -> str:
        with _lock:
            cat = load_catalog(self.path)
            ln = self._line(cat, body.line_id)
            name = body.name.strip()
            if any(s.name.lower() == name.lower() for s in cat.models):
                raise CatalogError(409, f"A model named “{name}” already exists")
            risk = body.risk_profile.strip()
            mid = _unique(f"{ln.id}-{_code(risk, 3) or 'M'}", {s.id for s in cat.models})
            cat.models.append(
                TargetModelSpec(
                    id=mid,
                    name=name,
                    provider="Charles Schwab",
                    objective=ln.objective,
                    construction=CONSTRUCTION[ln.objective],
                    benchmark=BENCHMARKS[ln.objective],
                    advisory_fee_bps=body.advisory_fee_bps,
                    description=body.description,
                    line_id=ln.id,
                    risk_profile=risk,
                    holdings=self._holdings(cat, body.holdings),
                )
            )
            self._commit(cat)
            return mid

    def update_model(self, model_id: str, body: sc.ModelPatch) -> None:
        with _lock:
            cat = load_catalog(self.path)
            spec = self._model(cat, model_id)
            if body.name is not None:
                name = body.name.strip()
                if not name:
                    raise CatalogError(422, "The model needs a name")
                if any(s.name.lower() == name.lower() and s.id != model_id for s in cat.models):
                    raise CatalogError(409, f"A model named “{name}” already exists")
                spec.name = name
            if body.line_id is not None and body.line_id != spec.line_id:
                ln = self._line(cat, body.line_id)
                spec.line_id = ln.id
                if ln.objective != spec.objective:
                    spec.objective = ln.objective
                    spec.benchmark = BENCHMARKS[ln.objective]
            if body.risk_profile is not None:
                spec.risk_profile = body.risk_profile.strip()
            if body.description is not None:
                spec.description = body.description
            if body.advisory_fee_bps is not None:
                spec.advisory_fee_bps = body.advisory_fee_bps
            if body.holdings is not None:
                spec.holdings = self._holdings(cat, body.holdings)
            self._commit(cat)

    def delete_model(self, model_id: str) -> None:
        with _lock:
            cat = load_catalog(self.path)
            spec = self._model(cat, model_id)
            used = self._targeted([model_id])
            if used:
                raise CatalogError(409, _in_use(used, f"“{spec.name}”"))
            if len(cat.models) == 1:
                raise CatalogError(409, "The catalog needs at least one model")
            cat.models = [s for s in cat.models if s.id != model_id]
            self._commit(cat)


def _in_use(used: dict[str, int], what: str) -> str:
    n = sum(used.values())
    acc = "account targets" if n == 1 else "accounts target"
    return (
        f"Can't delete {what}: {n} {acc} it ({', '.join(sorted(used))}). "
        "Move those accounts to another model first."
    )


def _clean(msg: str) -> str:
    """Last line of a pydantic error, without the docs link."""
    lines = [x.strip() for x in msg.splitlines() if x.strip() and "errors.pydantic" not in x]
    return lines[-1] if lines else msg
