"""Normalisation and validation of ingested lot rows (PDF tables, LLM extraction, Plaid).

Every source produces :class:`RawRow` dicts; :func:`normalize_rows` turns them into
:class:`NormalizedRow` objects with parsed values, validation issues and a confidence score.
Nothing here touches the database — committing happens only on explicit confirmation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.entities import holding_period

# canonical field -> header synonyms (lower-case, punctuation stripped)
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ticker": ("symbol", "sym", "ticker", "ticker symbol", "security id", "symbol cusip"),
    "description": ("description", "security", "security description", "name", "security name"),
    "quantity": ("quantity", "qty", "shares", "units", "share quantity", "shares units"),
    "acquired_date": (
        "acquired",
        "date acquired",
        "acquisition date",
        "open date",
        "trade date",
        "purchase date",
        "acq date",
        "opened",
    ),
    "cost_basis_total": (
        "cost basis",
        "adj cost basis",
        "adjusted cost basis",
        "adj cost",
        "total cost",
        "cost",
        "basis",
        "cost basis total",
    ),
    "current_value": ("market value", "mkt value", "current value", "value", "market val"),
    "price": ("price", "last price", "current price", "closing price"),
    "gain": ("unrealized gl", "unrealized gain loss", "gain loss", "gl", "unrealized"),
    "term": ("term", "holding period", "st lt"),
    "lot_ref": ("lot id", "lot", "lot number", "lot no", "lot ref", "lot identifier"),
}
ESSENTIAL = ("ticker", "quantity", "acquired_date", "cost_basis_total")

DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%b %d, %Y",
    "%b %d %Y",
    "%B %d, %Y",
    "%d-%b-%Y",
    "%m-%d-%Y",
)
_NUM_RE = re.compile(r"^\(?-?\$?\s*[\d,]*\.?\d+\)?-?$")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
SKIP_ROW_RE = re.compile(r"\b(sub)?total\b|^cash\b|money market|page \d", re.IGNORECASE)

VALUE_TOLERANCE = 0.05  # statement value vs quantity × current price


def norm_header(h: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (h or "").lower()).strip().replace("  ", " ")


def map_header(cells: Sequence[str | None]) -> dict[int, str]:
    """Map column index → canonical field using exact-then-prefix synonym matching."""
    out: dict[int, str] = {}
    used: set[str] = set()
    for i, raw in enumerate(cells):
        h = " ".join(norm_header(raw).split())
        if not h:
            continue
        best = None
        for fld, syns in COLUMN_SYNONYMS.items():
            if fld in used:
                continue
            if h in syns:
                best = fld
                break
            if best is None and any(h.startswith(s) or s.startswith(h) for s in syns if len(h) > 2):
                best = fld
        if best is not None:
            out[i] = best
            used.add(best)
    return out


def parse_number(s: object) -> float | None:
    """'$1,234.50' → 1234.5; '(12.00)' or '12.00-' → -12.0; blanks/dashes → None."""
    if s is None:
        return None
    if isinstance(s, int | float):
        return float(s)
    t = str(s).strip().replace("−", "-")
    if t in {"", "-", "--", "—", "n/a", "N/A", "NA"}:
        return None
    t = t.replace(" ", "")
    if not _NUM_RE.match(t):
        return None
    neg = (t.startswith("(") and t.endswith(")")) or t.endswith("-") or t.startswith("-")
    t = t.strip("()-").replace("$", "").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def parse_date(s: object) -> date | None:
    if s is None:
        return None
    if isinstance(s, date):
        return s
    t = " ".join(str(s).strip().split())
    if not t:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class SecurityRef:
    ticker: str
    name: str
    price: float


@dataclass(slots=True)
class Issue:
    code: str
    severity: str  # "error" blocks commit unless the row is excluded; "warning" does not
    message: str


@dataclass(slots=True)
class NormalizedRow:
    row_id: int
    ticker: str | None
    description: str | None
    quantity: float | None
    acquired_date: date | None
    cost_basis_total: float | None
    statement_value: float | None
    current_price: float | None
    market_value: float | None
    unrealized_gain: float | None
    holding_period: str | None
    basis_estimated: bool
    confidence: float
    issues: list[Issue] = field(default_factory=list)
    suggested_ticker: str | None = None
    lot_ref: str | None = None  # Lot ID printed on the statement (None when not shown)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


RawRow = Mapping[str, object]


def _suggest(description: str | None, by_name: dict[str, str]) -> str | None:
    if not description:
        return None
    d = " ".join(description.lower().split())
    if d in by_name:
        return by_name[d]
    for name, t in by_name.items():
        if d.startswith(name) or name.startswith(d):
            return t
    return None


def normalize_rows(
    raw: Sequence[RawRow],
    securities: Mapping[str, SecurityRef],
    as_of: date,
    method_confidence: float = 1.0,
) -> list[NormalizedRow]:
    """Parse, validate and score rows. ``securities`` is the tradable universe (ticker → ref)."""
    by_name = {" ".join(s.name.lower().split()): s.ticker for s in securities.values()}
    seen: dict[tuple[str | None, date | None, float | None], int] = {}
    seen_refs: dict[str, int] = {}
    out: list[NormalizedRow] = []
    for i, r in enumerate(raw):
        issues: list[Issue] = []
        ticker_raw = str(r.get("ticker") or "").strip().upper() or None
        description = (str(r.get("description")).strip() or None) if r.get("description") else None
        qty = parse_number(r.get("quantity"))
        acquired = parse_date(r.get("acquired_date"))
        basis = parse_number(r.get("cost_basis_total"))
        value = parse_number(r.get("current_value"))
        estimated = bool(r.get("basis_estimated", False))
        lot_ref = " ".join(str(r.get("lot_ref") or "").split()) or None

        ref = securities.get(ticker_raw) if ticker_raw else None
        suggestion = None
        if ticker_raw is None:
            issues.append(Issue("missing_ticker", "error", "No ticker symbol"))
            suggestion = _suggest(description, by_name)
        elif ref is None:
            suggestion = _suggest(description, by_name)
            hint = f" — did you mean {suggestion}?" if suggestion else ""
            issues.append(Issue("unknown_ticker", "error", f"{ticker_raw} is not tradable{hint}"))
        if qty is None:
            issues.append(Issue("missing_quantity", "error", "No quantity"))
        elif qty < 0:
            issues.append(Issue("negative_quantity", "error", f"Negative quantity {qty:g}"))
        elif qty == 0:
            issues.append(Issue("zero_quantity", "error", "Quantity is zero"))
        raw_date = r.get("acquired_date")
        if acquired is None:
            code = "invalid_date" if raw_date not in (None, "") else "missing_date"
            issues.append(Issue(code, "error", "Acquisition date missing or unreadable"))
        elif acquired > as_of:
            issues.append(Issue("future_date", "error", f"Acquired {acquired} is after {as_of}"))
        if basis is None:
            issues.append(
                Issue(
                    "missing_basis",
                    "warning",
                    "Cost basis unknown — upload a lot file or accept an average-cost assumption",
                )
            )
        elif basis < 0:
            issues.append(Issue("negative_basis", "error", "Negative cost basis"))
        elif estimated:
            issues.append(Issue("estimated_basis", "warning", "Average-cost basis (not lot-level)"))

        price = ref.price if ref else None
        mv = qty * price if (qty is not None and price is not None) else None
        if mv and value and abs(value - mv) / max(abs(mv), 1e-9) > VALUE_TOLERANCE:
            issues.append(
                Issue(
                    "value_mismatch",
                    "warning",
                    f"Statement value ${value:,.2f} vs ${mv:,.2f} at today's price",
                )
            )
        key = (ticker_raw, acquired, qty)
        if key in seen:
            issues.append(Issue("duplicate_row", "warning", f"Same as row {seen[key]}"))
        else:
            seen[key] = i
        if lot_ref is not None:
            if lot_ref in seen_refs:
                issues.append(
                    Issue(
                        "duplicate_lot_id",
                        "error",
                        f"Lot ID {lot_ref} is also on row {seen_refs[lot_ref]}",
                    )
                )
            else:
                seen_refs[lot_ref] = i

        conf = 1.0
        for iss in issues:
            conf -= 0.45 if iss.severity == "error" else 0.12
        conf = max(0.0, min(1.0, conf)) * method_confidence
        out.append(
            NormalizedRow(
                row_id=i,
                ticker=ticker_raw,
                description=description or (ref.name if ref else None),
                quantity=qty,
                acquired_date=acquired,
                cost_basis_total=round(basis, 2) if basis is not None else None,
                statement_value=value,
                current_price=price,
                market_value=round(mv, 2) if mv is not None else None,
                unrealized_gain=round(mv - basis, 2)
                if (mv is not None and basis is not None)
                else None,
                holding_period=holding_period(acquired, as_of).value if acquired else None,
                basis_estimated=estimated or basis is None,
                confidence=round(conf, 3),
                issues=issues,
                suggested_ticker=suggestion,
                lot_ref=lot_ref,
            )
        )
    return out


def parse_confidence(rows: Sequence[NormalizedRow], mapped_fields: set[str] | None = None) -> float:
    """Overall confidence: mean row confidence × share of essential columns found."""
    if not rows:
        return 0.0
    mean = sum(r.confidence for r in rows) / len(rows)
    if mapped_fields is None:
        return round(mean, 3)
    coverage = sum(f in mapped_fields for f in ESSENTIAL) / len(ESSENTIAL)
    return round(mean * coverage, 3)
