"""Model Builder: analytics, file import, scaling into a line, the guide, and saving a line."""

from __future__ import annotations

import base64
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
from app.model_builder.analytics import BuilderData, analyze, pick_benchmark
from app.model_builder.assistant import Draft, Tools, assist
from app.model_builder.importer import read_model_file
from app.model_builder.samples import SAMPLE, sample_pdf, sample_xlsx
from app.model_builder.scaling import scale_line, targets
from tests.conftest import TEST_SEED

API = "/api/v1"
URL = f"{API}/model-builder"
MODEL = {"SCHX": 0.40, "SCHF": 0.15, "SCHZ": 0.30, "SCHI": 0.10, "CASH": 0.05}


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Catalog and security master copies: tests never write the real files."""
    s = get_settings()
    real_models, real_master = s.MODELS_FILE, s.SECURITY_MASTER_FILE
    d = tmp_path_factory.mktemp("builder")
    shutil.copy(real_models, d / "target_models.json")
    s.MODELS_FILE = d / "target_models.json"
    s.SECURITY_MASTER_FILE = d / "security_master.json"
    BuilderData.reset()
    yield d
    s.MODELS_FILE, s.SECURITY_MASTER_FILE = real_models, real_master
    BuilderData.reset()


@pytest.fixture(scope="module")
def data(files: Path, provider: RandomAnalyticsProvider) -> BuilderData:
    return BuilderData.get(provider)


def test_benchmark_is_closest_blend() -> None:
    assert pick_benchmark(0.58, 0.0).short == "S&P/Agg 60/40"
    assert pick_benchmark(0.97, 0.0).short == "S&P 500"
    assert pick_benchmark(0.03, 0.0).short == "Agg"
    b = pick_benchmark(0.56, 0.8)
    assert b.short == "S&P/Muni 60/40" and set(b.holdings) == {"SCHX", "SCMB"}


def test_analyze(data: BuilderData) -> None:
    r = analyze(MODEL, "Test", data)
    assert r.equity_pct == pytest.approx(0.55) and r.cash_pct == pytest.approx(0.05)
    assert r.benchmark.short == "S&P/Agg 60/40"
    assert [a.name for a in r.asset_allocation][:2] == ["US Equity", "Non-US Stocks"]
    for part in (r.equity_size, r.equity_style, r.equity_regions, r.equity_sectors, r.fi_rating,
                 r.fi_sectors, r.fi_maturity, r.fi_regions):
        assert sum(x.weight for x in part) == pytest.approx(1.0, abs=1e-4)
    assert sum(sum(row) for row in r.style_box) == pytest.approx(1.0, abs=1e-4)
    assert r.avg_duration and 3 < r.avg_duration < 8 and r.pe_ratio and r.pb_ratio
    assert r.net_expense_ratio_bps == pytest.approx(0.40 * 3 + 0.15 * 3 + 0.30 * 3 + 0.10 * 3)
    assert 0 < r.volatility < r.bench_volatility * 2 and r.factors and r.tail and r.stress_tests
    assert r.performance[-1].model > 0 and len(r.calendar_years) >= 4
    # weights that don't add up are scaled, with a warning
    r2 = analyze({"SCHX": 0.5, "SCHZ": 0.3}, "Off", data)
    assert r2.normalized and r2.warnings and r2.equity_pct == pytest.approx(0.625)


@pytest.mark.parametrize("fmt", ["xlsx", "pdf", "csv"])
def test_import(data: BuilderData, fmt: str) -> None:
    raw = {"xlsx": sample_xlsx, "pdf": sample_pdf}.get(fmt, lambda: (
        "Ticker,Weight\n" + "\n".join(f"{t},{w}" for t, _, w in SAMPLE) + "\nNOPE,1\n").encode())()
    r = read_model_file(f"model.{fmt}", raw, data.known)
    assert set(r.holdings) == {t for t, _, _ in SAMPLE}
    assert sum(r.holdings.values()) == pytest.approx(1.0, abs=1e-5)
    if fmt == "csv":
        assert r.unmatched == ["NOPE"]


def test_scale_line(data: BuilderData) -> None:
    assert targets(10, 10, 100) == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    line = scale_line(MODEL, 10, 10, 100, data.asset_class)
    for m in line:
        eq = sum(w for t, w in m.holdings.items() if t in ("SCHX", "SCHF"))
        assert eq == pytest.approx(m.equity_pct / 100, abs=1e-5)
        assert sum(m.holdings.values()) == pytest.approx(1.0, abs=1e-6)
        if m.equity_pct < 95:  # mixes inside the sleeves are kept
            assert m.holdings["SCHX"] / m.holdings["SCHF"] == pytest.approx(40 / 15, rel=1e-3)
            assert m.holdings["SCHZ"] / m.holdings["SCHI"] == pytest.approx(3, rel=1e-3)
            assert m.holdings["CASH"] == pytest.approx(0.05, abs=1e-5)
    assert "CASH" not in line[-1].holdings or line[-1].holdings["CASH"] == 0  # 100/0
    # an all-equity model borrows SCHZ for its bond sleeve
    assert "SCHZ" in scale_line({"SCHX": 1.0}, 3, 20, 80, data.asset_class)[0].holdings


def test_guide_flow(data: BuilderData) -> None:
    saved: list[Draft] = []
    tools = Tools(data.known, data.asset_class, [], lambda h, n: analyze(h, n, data),
                  lambda d: (saved.append(d) or ("TR-X", ["TR-X-10-90", "TR-X-100-0"])))
    d = Draft()
    t = assist(d, "add SCHX 40%, SCHF 15%, SCHZ 40%, CASH 5%", None, tools)
    assert t.draft.holdings == {"SCHX": 0.4, "SCHF": 0.15, "SCHZ": 0.4, "CASH": 0.05}
    t = assist(t.draft, "run analytics", None, tools)
    assert t.draft.step == "analyze" and t.refresh_analytics and "S&P/Agg 60/40" in t.message
    t = assist(t.draft, None, "less_risk", tools)
    eq = sum(w for k, w in t.draft.holdings.items() if k in ("SCHX", "SCHF"))
    assert eq == pytest.approx(0.45, abs=1e-4)
    t = assist(t.draft, "replace SCHF with FNDF", None, tools)
    assert "FNDF" in t.draft.holdings and "SCHF" not in t.draft.holdings
    t = assist(t.draft, "scale to 8 models from 20/80 to 90/10", None, tools)
    assert (t.draft.step, t.draft.scale_n, t.draft.scale_lo, t.draft.scale_hi) == (
        "scale", 8, 20, 90)
    t = assist(t.draft, "save as My Growth Models", None, tools)
    assert t.draft.step == "save" and t.draft.line_name == "My Growth Models" and not saved
    t = assist(t.draft, None, "objective:income", tools)
    assert t.draft.step == "done" and saved and saved[0].objective == "income"


@pytest.fixture(scope="module")
def client(market: SyntheticMarket, provider: RandomAnalyticsProvider,
           files: Path) -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    with sessionmaker(bind=engine)() as s:
        seed_demo(s, engine, market, TEST_SEED, models_file=files / "target_models.json")
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


def test_api(client: TestClient, files: Path, market: SyntheticMarket) -> None:
    u = client.get(f"{URL}/universe", params={"q": "sch"}).json()
    assert u and u[0]["ticker"].startswith("SCH")
    r = client.post(f"{URL}/analyze", json={"holdings": MODEL, "name": "T"})
    assert r.status_code == 200 and r.json()["benchmark"]["short"] == "S&P/Agg 60/40"
    assert client.post(f"{URL}/analyze", json={"holdings": {}}).status_code == 422
    b64 = base64.b64encode(sample_xlsx()).decode()
    imp = client.post(f"{URL}/import", json={"filename": "m.xlsx", "content_base64": b64}).json()
    assert len(imp["holdings"]) == len(SAMPLE)
    line = client.post(f"{URL}/scale", json={"holdings": MODEL, "n": 5, "lo": 20, "hi": 100})
    assert [m["label"] for m in line.json()] == ["20/80", "40/60", "60/40", "80/20", "100/0"]
    t = client.post(f"{URL}/assist", json={"draft": {}, "message": None}).json()
    assert t["draft"]["step"] == "build" and t["quick_replies"]
    assert client.get(f"{URL}/sample", params={"fmt": "pdf"}).content[:4] == b"%PDF"

    # save a line holding a fund and a single stock → Custom Models, usable as targets
    stock = str(market.universe.index[0])
    draft = Draft(name="T", holdings={"SCHX": 0.5, stock: 0.1, "SCHZ": 0.4}, scale_n=3,
                  scale_lo=30, scale_hi=90, line_name="Test Builder Models",
                  objective="total_return").model_dump()
    res = client.post(f"{URL}/save", json=draft)
    assert res.status_code == 201, res.text
    ids = res.json()["model_ids"]
    assert ids == ["TR-TBM-30-70", "TR-TBM-60-40", "TR-TBM-90-10"]
    cat = load_catalog(files / "target_models.json")
    ln = next(x for x in cat.lines if x.id == res.json()["line_id"])
    assert ln.provider == "Custom" and stock in cat.stocks
    raw = json.loads((files / "target_models.json").read_text())
    assert raw["stocks"] == [stock]
    assert client.get(f"{API}/models/TR-TBM-60-40").status_code == 200
    mc = client.get(f"{API}/model-catalog").json()
    line = next(x for c in mc["categories"] for x in c["lines"] if x["id"] == "TR-TBM")
    assert line["provider"] == "Custom" and [m["risk_profile"] for m in line["models"]] == [
        "30/70", "60/40", "90/10"]
    assert client.post(f"{URL}/save", json=draft).status_code == 409  # same line name
