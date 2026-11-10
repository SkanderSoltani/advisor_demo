"""Construction primitives, the JSON catalog, and the product (ETF) proxies."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.db.catalog import (
    CatalogFile,
    FundProxies,
    build_fund_proxies,
    load_catalog,
    universe_arrays,
)
from app.db.synthetic_market import SyntheticMarket
from app.domain import model_construction as mc


@pytest.fixture(scope="module")
def catalog() -> CatalogFile:
    return load_catalog(get_settings().MODELS_FILE)


@pytest.fixture(scope="module")
def funds(market: SyntheticMarket, catalog: CatalogFile) -> FundProxies:
    return build_fund_proxies(market, catalog)


def test_catalog_file_is_valid(catalog: CatalogFile) -> None:
    assert len(catalog.models) == 2
    assert {m.objective for m in catalog.models} == {"total_return", "income"}
    for m in catalog.models:
        assert sum(h.weight for h in m.holdings) == pytest.approx(1.0)


def test_catalog_validation_errors(catalog: CatalogFile) -> None:
    raw = json.loads(get_settings().MODELS_FILE.read_text())
    bad = json.loads(json.dumps(raw))
    bad["models"][0]["holdings"][0]["weight"] += 0.1
    with pytest.raises(ValidationError, match="sum to"):
        CatalogFile.model_validate(bad)
    bad = json.loads(json.dumps(raw))
    bad["models"][0]["holdings"].append({"ticker": "NOPE", "weight": 0.0001})
    with pytest.raises(ValidationError):
        CatalogFile.model_validate(bad)


def test_proxies_are_valid_portfolios(funds: FundProxies, market: SyntheticMarket) -> None:
    w = funds.weights
    assert (w.to_numpy() >= 0).all()
    np.testing.assert_allclose(w.sum(axis=1).to_numpy(), 1.0)
    assert list(w.columns) == list(market.universe.index)
    assert (funds.nav > 0).all().all() and len(funds.nav) == len(market.prices)
    # value and growth sleeves split the same large-cap set
    assert not set(w.columns[w.loc["SCHG"] > 0]) & set(w.columns[w.loc["SCHV"] > 0])


def test_dividend_proxy_yields_more(funds: FundProxies, market: SyntheticMarket) -> None:
    y = market.universe["dividend_yield"]
    assert float(funds.weights.loc["SCHD"] @ y) > float(funds.weights.loc["SCHX"] @ y) + 0.01
    sectors = pd.Series(funds.weights.loc["SCHD"].to_numpy(), index=market.universe["sector"])
    assert sectors.groupby(level=0).sum().max() <= 0.25 + 1e-9


def test_look_through(funds: FundProxies, market: SyntheticMarket) -> None:
    stock = str(market.universe.index[0])
    lt = funds.look_through({"SCHX": 0.5, stock: 0.5})
    assert sum(lt.values()) == pytest.approx(1.0)
    assert lt[stock] > 0.5  # direct holding plus its share inside SCHX


def test_unknown_proxy_falls_back(market: SyntheticMarket, catalog: CatalogFile) -> None:
    raw = catalog.model_dump()
    raw["products"].append({"ticker": "SCHZZ", "name": "New product", "proxy": "mystery"})
    fp = build_fund_proxies(market, CatalogFile.model_validate(raw))
    assert fp.rules["SCHZZ"] == "broad_market"


def test_load_catalog_roundtrip(tmp_path: Path, catalog: CatalogFile) -> None:
    p = tmp_path / "c.json"
    p.write_text(catalog.model_dump_json())
    assert load_catalog(p) == catalog


# ---------------------------------------------------------------- primitives
def test_covariance_is_psd(market: SyntheticMarket) -> None:
    cov = mc.shrunk_sample_covariance(market.returns.iloc[-504:].to_numpy())
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() > -1e-10


def test_tilt_is_bounded() -> None:
    base = np.array([0.4, 0.3, 0.2, 0.1])
    tilted = mc.apply_tilt(base, np.array([5.0, -5.0, 0.0, 1.0]))
    ratio = tilted / base
    assert ratio.max() / ratio.min() <= 1.5 / 0.5 + 1e-9
    assert tilted.sum() == pytest.approx(1.0)


def test_sector_cap_redistributes() -> None:
    w = np.array([0.5, 0.3, 0.1, 0.1])
    out = mc.apply_sector_cap(w, ["A", "A", "B", "C"], 0.5)
    assert out.sum() == pytest.approx(1.0)
    assert out[:2].sum() == pytest.approx(0.5)
    assert out[2] == pytest.approx(out[3])


def test_benchmarks(market: SyntheticMarket) -> None:
    b = mc.build_benchmarks(universe_arrays(market))
    assert set(b) == {mc.TR_BENCHMARK, mc.INC_BENCHMARK}
    for w in b.values():
        assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
