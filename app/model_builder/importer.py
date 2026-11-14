"""Read a model (ticker + weight rows) from an Excel, CSV or PDF file."""

from __future__ import annotations

import io
import re
from collections.abc import Callable

import pandas as pd
from pydantic import BaseModel

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
NUM_RE = re.compile(r"(-?\d{1,3}(?:[.,]\d+)?)\s*%?")


class ImportResult(BaseModel):
    holdings: dict[str, float]  # fractions, scaled to 100% when the file's total is off
    unmatched: list[str]  # tickers found in the file but not in the universe
    total_in_file: float  # sum of the file's weights (as fractions)
    rows_read: int
    note: str


def _to_fraction(vals: list[float]) -> tuple[list[float], float]:
    """Percent (sums near 100) or fraction (sums near 1) → fractions."""
    tot = sum(vals)
    if tot > 1.5:
        vals = [v / 100 for v in vals]
        tot /= 100
    return vals, tot


def _from_frame(df: pd.DataFrame) -> list[tuple[str, float]]:
    df = df.dropna(how="all").dropna(axis=1, how="all")
    cols = [str(c).strip().lower() for c in df.columns]
    tcol = next((i for i, c in enumerate(cols) if any(k in c for k in ("ticker", "symbol"))), None)
    wcol = next((i for i, c in enumerate(cols)
                 if any(k in c for k in ("weight", "allocation", "%", "pct", "percent"))), None)
    if tcol is None or wcol is None:  # no header: first text column + last numeric column
        df = df.T.reset_index().T if not all(c.startswith("unnamed") for c in cols) else df
        for i in range(df.shape[1]):
            col = df.iloc[:, i].astype(str).str.strip().str.upper()
            if tcol is None and col.str.match(TICKER_RE).mean() > 0.5:
                tcol = i
        nums = [i for i in range(df.shape[1])
                if pd.to_numeric(df.iloc[:, i].astype(str).str.rstrip("%"), errors="coerce")
                .notna().mean() > 0.5]
        wcol = nums[-1] if nums else None
    if tcol is None or wcol is None:
        raise ValueError("Couldn't find a ticker column and a weight column in the file")
    out = []
    for t, w in zip(df.iloc[:, tcol], df.iloc[:, wcol], strict=True):
        t = str(t).strip().upper()
        try:
            w = float(str(w).replace("%", "").replace(",", "").strip())
        except ValueError:
            continue
        if TICKER_RE.match(t) and w > 0:
            out.append((t, w))
    return out


def _from_pdf(data: bytes, known: Callable[[str], bool]) -> list[tuple[str, float]]:
    import pdfplumber

    rows: list[tuple[str, float]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                toks = line.replace(",", " ").split()
                tick = next((x for x in toks if TICKER_RE.match(x) and known(x)), None)
                if not tick:
                    continue
                nums = [float(m.group(1).replace(",", ".")) for m in NUM_RE.finditer(
                    line[line.index(tick) + len(tick):])]
                nums = [n for n in nums if 0 < n <= 100]
                if nums:
                    rows.append((tick, nums[-1]))
    return rows


def read_model_file(filename: str, data: bytes, known: Callable[[str], bool]) -> ImportResult:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        rows = _from_frame(pd.read_excel(io.BytesIO(data)))
    elif name.endswith((".csv", ".txt")):
        rows = _from_frame(pd.read_csv(io.BytesIO(data)))
    elif name.endswith(".pdf"):
        rows = _from_pdf(data, known)
    else:
        raise ValueError("Upload an Excel (.xlsx), CSV or PDF file")
    if not rows:
        raise ValueError("No ticker / weight rows found in the file")
    merged: dict[str, float] = {}
    for t, w in rows:
        merged[t] = merged.get(t, 0.0) + w
    vals, tot = _to_fraction(list(merged.values()))
    weights = dict(zip(merged, vals, strict=True))
    unmatched = sorted(t for t in weights if not known(t))
    kept = {t: w for t, w in weights.items() if known(t)}
    kept_tot = sum(kept.values())
    note = f"Read {len(rows)} rows: {len(kept)} holdings matched"
    if unmatched:
        note += f", {len(unmatched)} not in the universe ({', '.join(unmatched)})"
    if kept and abs(kept_tot - 1) > 1e-4:
        kept = {t: w / kept_tot for t, w in kept.items()}
        note += f"; weights added up to {kept_tot:.2%} and were scaled to 100%"
    return ImportResult(holdings={t: round(w, 6) for t, w in kept.items()}, unmatched=unmatched,
                        total_in_file=round(tot, 6), rows_read=len(rows), note=note + ".")
