"""Macro-regime hook.

Two pieces, both deliberately minimal for now:

* :class:`RegimeOverlay` — interface for a regime-aware model variant (``regime_overlay=True`` on a
  model). :class:`PassThroughRegimeOverlay` is the stub: it returns the base weights unchanged.
* :func:`parse_regime_csv` — reads a ``date,regime`` CSV so per-regime model performance can be
  shown (computed by the analytics provider's ``get_regime_performance``).
"""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date

MAX_REGIME_ROWS = 50_000


class RegimeOverlay(ABC):
    """Adjusts model weights for the current macro regime."""

    @abstractmethod
    def adjust(self, weights: Mapping[str, float], regime: str | None) -> dict[str, float]:
        """Return regime-adjusted weights (must stay long-only and sum to 1)."""


class PassThroughRegimeOverlay(RegimeOverlay):
    """Stub overlay: no adjustment. Replace with a real regime model later."""

    def adjust(self, weights: Mapping[str, float], regime: str | None) -> dict[str, float]:
        return dict(weights)


class RegimeCsvError(ValueError):
    pass


def parse_regime_csv(text: str) -> dict[date, str]:
    """Parse ``date,regime`` rows (header optional; ISO dates). Later rows win on duplicates."""
    out: dict[date, str] = {}
    reader = csv.reader(io.StringIO(text))
    for i, row in enumerate(reader, start=1):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) < 2:
            raise RegimeCsvError(f"line {i}: expected 'date,regime'")
        raw_date, regime = row[0].strip(), row[1].strip()
        if i == 1 and raw_date.lower() in {"date", "dt", "day"}:
            continue
        try:
            d = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise RegimeCsvError(f"line {i}: invalid date {raw_date!r} (use YYYY-MM-DD)") from exc
        if not regime:
            raise RegimeCsvError(f"line {i}: empty regime label")
        out[d] = regime[:60]
        if len(out) > MAX_REGIME_ROWS:
            raise RegimeCsvError(f"too many rows (max {MAX_REGIME_ROWS})")
    if not out:
        raise RegimeCsvError("no regime rows found")
    return out
