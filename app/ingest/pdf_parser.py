"""PDF statement parsing: pdfplumber tables first, LLM extraction when confidence is low."""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import pdfplumber
from pdfplumber.pdf import PDF

from app.agent.llm import LLMClient, LLMError
from app.ingest.normalizer import (
    ESSENTIAL,
    SKIP_ROW_RE,
    NormalizedRow,
    SecurityRef,
    map_header,
    normalize_rows,
    parse_confidence,
    parse_date,
    parse_number,
)

MAX_PAGES = 60
LLM_THRESHOLD = 0.75  # below this table-parse confidence, run the LLM pass
LLM_METHOD_CONFIDENCE = 0.95  # LLM rows are discounted slightly vs a clean table parse
_CASH_LINE = re.compile(
    r"(cash\s*(&|and)?\s*(equivalents|money market)?|money market)[^\d$(]*\$?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_STATEMENT_DATE = re.compile(r"statement date:?\s*([\d/\-]+|[A-Z][a-z]+ \d{1,2},? \d{4})", re.I)


class PdfError(ValueError):
    pass


@dataclass(slots=True)
class ParseResult:
    method: str  # "table" | "llm"
    llm_provider: str | None
    confidence: float
    rows: list[NormalizedRow]
    cash: float | None
    statement_date: date | None
    notes: list[str] = field(default_factory=list)
    table_confidence: float | None = None


def _open(data: bytes) -> PDF:
    if not data.startswith(b"%PDF"):
        raise PdfError("Not a PDF file")
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises a variety of errors on corrupt files
        raise PdfError("Could not read the PDF") from exc
    if len(pdf.pages) > MAX_PAGES:
        pdf.close()
        raise PdfError(f"PDF has more than {MAX_PAGES} pages")
    return pdf


def _table_rows(pdf: PDF) -> tuple[list[dict[str, object]], set[str]]:
    """Find lot tables (a header row mapping ≥3 essential fields) and read their rows."""
    rows: list[dict[str, object]] = []
    mapped: set[str] = set()
    header: dict[int, str] | None = None
    for page in pdf.pages:
        for table in page.extract_tables():
            for cells in table:
                if not cells or all(not (c or "").strip() for c in cells):
                    continue
                candidate = map_header(cells)
                if sum(f in candidate.values() for f in ESSENTIAL) >= 3:
                    header = candidate  # (repeated) header row
                    mapped |= set(candidate.values())
                    continue
                if header is None:
                    continue
                first = " ".join((c or "") for c in cells[:2])
                if SKIP_ROW_RE.search(first):
                    continue
                rec: dict[str, object] = {
                    fld: (cells[i] if i < len(cells) else None) for i, fld in header.items()
                }
                if not any(v not in (None, "") for v in rec.values()):
                    continue
                rows.append(rec)
    return rows, mapped


def parse_pdf(
    data: bytes,
    securities: Mapping[str, SecurityRef],
    as_of: date,
    llm: LLMClient,
) -> ParseResult:
    """Parse a tax-lot statement. Nothing is persisted here."""
    pdf = _open(data)
    try:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        raw, mapped = _table_rows(pdf)
    finally:
        pdf.close()

    cash = None
    m = _CASH_LINE.search(text)
    if m:
        cash = parse_number(m.group(4))
    sd = _STATEMENT_DATE.search(text)
    statement_date = parse_date(sd.group(1)) if sd else None

    notes: list[str] = []
    table_rows = normalize_rows(raw, securities, as_of) if raw else []
    table_conf = parse_confidence(table_rows, mapped) if raw else 0.0
    if raw and table_conf >= LLM_THRESHOLD:
        return ParseResult(
            "table", None, table_conf, table_rows, cash, statement_date, notes, table_conf
        )

    notes.append(
        "No lot table found"
        if not raw
        else f"Table parse confidence {table_conf:.0%} is low; ran an LLM extraction pass"
    )
    try:
        ext = llm.extract_lots(data, text)
    except LLMError as exc:
        if raw:
            notes.append(f"LLM extraction failed ({exc}); showing the table parse")
            return ParseResult(
                "table", None, table_conf, table_rows, cash, statement_date, notes, table_conf
            )
        raise PdfError(f"Could not extract lots: {exc}") from exc
    llm_raw = [
        {
            "ticker": r.ticker,
            "description": r.description,
            "quantity": r.quantity,
            "acquired_date": r.acquired_date,
            "cost_basis_total": r.cost_basis_total,
            "current_value": r.market_value,
            "lot_ref": r.lot_id,
        }
        for r in ext.rows
    ]
    llm_rows = normalize_rows(llm_raw, securities, as_of, LLM_METHOD_CONFIDENCE)
    llm_conf = parse_confidence(llm_rows)
    if ext.notes:
        notes.append(ext.notes)
    if raw and table_conf >= llm_conf:
        notes.append("Kept the table parse (higher confidence than the LLM pass)")
        return ParseResult(
            "table", None, table_conf, table_rows, cash, statement_date, notes, table_conf
        )
    return ParseResult(
        method="llm",
        llm_provider=llm.provider,
        confidence=llm_conf,
        rows=llm_rows,
        cash=ext.cash if ext.cash is not None else cash,
        statement_date=parse_date(ext.statement_date) or statement_date,
        notes=notes,
        table_confidence=table_conf if raw else None,
    )
