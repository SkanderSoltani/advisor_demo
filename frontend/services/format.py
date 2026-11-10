"""Number formatting — one module for every label, KPI and table (AG Grid uses the JS twins in
assets/format.js with the same rules). Matches the React reference's `money()` helpers.
"""

from __future__ import annotations

from datetime import date, datetime

DASH = "—"


def money(v: float | None) -> str:
    """$1.50B for ≥ $1B, $1.84M for ≥ $1M, else $12,345 (React app/page.tsx `money`)."""
    if v is None:
        return DASH
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{sign}${a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.2f}M"
    return f"{sign}${a:,.0f}"


def money_full(v: float | None) -> str:
    """$1,842,300 — always full (React client detail `money`)."""
    if v is None:
        return DASH
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def signed_money(v: float | None) -> str:
    if v is None:
        return DASH
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def pct(v: float | None, decimals: int = 2) -> str:
    """API decimals → percent text: 0.0072 → 0.72%."""
    return DASH if v is None else f"{v * 100:.{decimals}f}%"


def signed_pct(v: float | None, decimals: int = 2) -> str:
    return DASH if v is None else f"{'+' if v >= 0 else ''}{v * 100:.{decimals}f}%"


def bps(v: float | None) -> str:
    return DASH if v is None else f"{v:g} bps"


def rate(v: float | None) -> str:
    """Tax rate chips: 0.37 → 37%, 0.133 → 13.3%."""
    return DASH if v is None else f"{v * 100:g}%"


def number(v: float | None, decimals: int = 0) -> str:
    return DASH if v is None else f"{v:,.{decimals}f}"


def long_date(d: date | datetime | None = None) -> str:
    d = d or date.today()
    return f"{d:%A}, {d:%B} {d.day}, {d:%Y}"


def short_month(iso: str) -> str:
    """'2025-11-03' → 'Nov 25' (React chart axis labels)."""
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d:%y}"
