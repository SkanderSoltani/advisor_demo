"""Model management API: lines and models are saved to the JSON catalog and synced to the DB."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.factory import get_provider
from app.analytics.random_provider import RandomAnalyticsProvider
from app.core.config import get_settings
from app.db.catalog import load_catalog
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_db
from app.db.synthetic_market import SyntheticMarket
from app.main import create_app
from tests.conftest import TEST_SEED

API = "/api/v1"
URL = f"{API}/model-catalog"


@pytest.fixture(scope="module")
def catalog_file(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    s = get_settings()
    real = s.MODELS_FILE
    path = tmp_path_factory.mktemp("models") / "target_models.json"
    shutil.copy(real, path)
    s.MODELS_FILE = path  # never write the real catalog from tests
    yield path
    s.MODELS_FILE = real


@pytest.fixture(scope="module")
def client(
    market: SyntheticMarket, provider: RandomAnalyticsProvider, catalog_file: Path
) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with sessionmaker(bind=engine)() as s:
        seed_demo(s, engine, market, TEST_SEED, models_file=catalog_file)
    app = create_app(sync_catalog=False)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    def _db() -> Iterator[object]:
        with maker() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    with TestClient(app) as c:
        tok = c.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
        yield c


def _line(cat: dict, line_id: str) -> dict:
    return next(ln for c in cat["categories"] for ln in c["lines"] if ln["id"] == line_id)


def test_catalog_shape(client: TestClient) -> None:
    cat = client.get(URL).json()
    assert [c["id"] for c in cat["categories"]] == ["total_return", "income", "tax_efficient"]
    lines = {c["id"]: [ln["name"] for ln in c["lines"]] for c in cat["categories"]}
    assert lines == {
        "total_return": ["Core Models", "Core Enhanced Models", "Active-Passive Models"],
        "income": ["Income Models"],
        "tax_efficient": ["Core Enhanced Tax Aware Models"],
    }
    for c in cat["categories"]:
        for ln in c["lines"]:
            assert len(ln["models"]) in (6, 11, 12)
            profiles = [m["risk_profile"] for m in ln["models"]]
            assert profiles == sorted(profiles, key=lambda p: int(p.split("/")[0]))
            for m in ln["models"]:
                assert sum(h["weight"] for h in m["holdings"]) == pytest.approx(1)
                assert m["fee_bps"] is not None and m["risk_profile"]
    core = _line(cat, "TR-CORE")
    assert any(m["id"] == "TR-CORE-96-04" and m["n_accounts"] > 0 for m in core["models"])
    assert len(cat["products"]) == 87 and "Moderate" in cat["risk_profiles"]
    assert "40/60" in cat["risk_profiles"]


def test_add_edit_delete_model(client: TestClient, catalog_file: Path) -> None:
    body = {
        "name": "Total Return Core — Conservative",
        "line_id": "TR-CORE",
        "risk_profile": "Conservative",
        "holdings": [{"ticker": "SCHX", "weight": 0.6}, {"ticker": "SCHD", "weight": 0.4}],
    }
    r = client.post(f"{URL}/models", json=body)
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    # saved to the file, and usable everywhere else (GET /models reads the DB)
    assert any(m.id == mid for m in load_catalog(catalog_file).models)
    assert client.get(f"{API}/models/{mid}").json()["name"] == body["name"]

    r = client.patch(
        f"{URL}/models/{mid}",
        json={"holdings": [{"ticker": "SCHB", "weight": 1.0}], "risk_profile": "Moderate"},
    )
    assert r.status_code == 204, r.text
    detail = client.get(f"{API}/models/{mid}").json()
    assert [h["ticker"] for h in detail["holdings"]] == ["SCHB"]
    saved = next(m for m in json.loads(catalog_file.read_text())["models"] if m["id"] == mid)
    assert saved["risk_profile"] == "Moderate"

    assert client.delete(f"{URL}/models/{mid}").status_code == 204
    assert client.get(f"{API}/models/{mid}").status_code == 404
    assert all(m.id != mid for m in load_catalog(catalog_file).models)


def test_model_validation(client: TestClient) -> None:
    bad = {
        "name": "Bad weights",
        "line_id": "TR-CORE",
        "risk_profile": "Moderate",
        "holdings": [{"ticker": "SCHX", "weight": 0.5}],
    }
    r = client.post(f"{URL}/models", json=bad)
    assert r.status_code == 422 and "100%" in r.json()["detail"]
    bad["holdings"] = [{"ticker": "NOPE", "weight": 1.0}]
    assert client.post(f"{URL}/models", json=bad).status_code == 422
    bad["line_id"] = "MISSING"
    assert client.post(f"{URL}/models", json=bad).status_code == 404


def test_cannot_delete_targeted(client: TestClient) -> None:
    r = client.delete(f"{URL}/models/TR-CORE-96-04")
    assert r.status_code == 409 and "Move those accounts" in r.json()["detail"]
    assert client.delete(f"{URL}/lines/TR-CORE").status_code == 409


def test_lines(client: TestClient, catalog_file: Path) -> None:
    r = client.post(f"{URL}/lines", json={"name": "Tax-Managed Models", "objective": "income"})
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    body = {
        "name": "Tax-Managed — Moderate",
        "line_id": lid,
        "risk_profile": "Moderate",
        "holdings": [{"ticker": "SCHD", "weight": 1.0}],
    }
    mid = client.post(f"{URL}/models", json=body).json()["id"]
    # moving the line to total return moves its models too
    r = client.patch(f"{URL}/lines/{lid}", json={"name": "Tax-Aware", "objective": "total_return"})
    assert r.status_code == 204, r.text
    assert _line(client.get(URL).json(), lid)["name"] == "Tax-Aware"
    assert client.get(f"{API}/models/{mid}").json()["objective"] == "total_return"
    # deleting the line deletes its (untargeted) models
    assert client.delete(f"{URL}/lines/{lid}").status_code == 204
    assert client.get(f"{API}/models/{mid}").status_code == 404
    cat = load_catalog(catalog_file)
    assert all(ln.id != lid for ln in cat.lines) and all(m.id != mid for m in cat.models)
