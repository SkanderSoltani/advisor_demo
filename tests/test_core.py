from __future__ import annotations

from datetime import date
from pathlib import Path

import jwt
import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db import models as m
from app.db.sample_pdf import BANNER, render_statement_pdf
from app.domain.entities import AccountType, HoldingPeriod, Lot, TaxProfile, holding_period
from app.main import create_app
from tests.conftest import TEST_AS_OF


def test_holding_period_boundary() -> None:
    as_of = date(2026, 10, 30)
    assert holding_period(date(2025, 10, 30), as_of) is HoldingPeriod.SHORT_TERM  # exactly 1y
    assert holding_period(date(2025, 10, 29), as_of) is HoldingPeriod.LONG_TERM


def test_lot_and_tax_profile_math() -> None:
    lot = Lot("l1", "a1", "XYZ", 10, 1000.0, date(2024, 1, 2))
    assert lot.market_value(120) == 1200
    assert lot.unrealized_gain(80) == -200
    assert lot.cost_per_share == 100
    tp = TaxProfile(0.37, 0.238, "CA", 0.133)
    assert tp.st_rate == pytest.approx(0.503) and tp.lt_rate == pytest.approx(0.371)
    assert not AccountType.ROTH_IRA.is_taxable and AccountType.TRUST.is_taxable


def test_password_and_jwt_roundtrip() -> None:
    h = hash_password("s3cret")
    assert verify_password("s3cret", h) and not verify_password("nope", h)
    tok = create_access_token("usr_001", {"role": "advisor"})
    claims = decode_access_token(tok)
    assert claims["sub"] == "usr_001" and claims["role"] == "advisor"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tok + "x")


def test_health_and_request_id() -> None:
    client = TestClient(create_app(sync_catalog=False))
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["X-Request-ID"]
    assert client.get("/health", headers={"X-Request-ID": "abc"}).headers["X-Request-ID"] == "abc"


def test_sample_pdf_renders_and_is_parseable(db: Session, tmp_path: Path) -> None:
    acct = db.query(m.Account).filter(m.Account.target_model_id.is_(None)).one()
    out = render_statement_pdf(db, acct.id, tmp_path / "s.pdf", TEST_AS_OF)
    with pdfplumber.open(out) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        rows = [r for p in pdf.pages for t in p.extract_tables() for r in t]
    assert BANNER in text
    data_rows = [r for r in rows if r and r[0] not in (None, "Symbol")]
    assert len(data_rows) == len(acct.lots)
    assert {r[0] for r in data_rows} == {lot.ticker for lot in acct.lots}


def test_request_log_has_id_and_no_pii(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import logging

    from app.core.config import get_settings

    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app(sync_catalog=False))
    finally:
        get_settings.cache_clear()
    client.get("/health?search=Okafor%20Family", headers={"X-Request-ID": "rid-42"})
    out = capsys.readouterr().out
    assert '"request_id": "rid-42"' in out and '"path": "/health"' in out
    assert "Okafor" not in out
    assert logging.getLogger("uvicorn.access").disabled
