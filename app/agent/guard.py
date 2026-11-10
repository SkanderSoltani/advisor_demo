"""Number guard: LLM-written text may only contain figures that came from tools or templates."""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterable
from typing import Any

_NUM = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(%|k|K|m|M)?")
SMALL_INT = 12  # step numbers, counts like "3 models", months — always allowed


def _numbers_with_precision(text: str) -> list[tuple[float, float]]:
    """(value, rounding half-step implied by how it is written), e.g. '4.2%' → (4.2, 0.05),
    '$25,000' → (25000, 0.5), '20k' → (20000, 500)."""
    out = []
    for m in _NUM.finditer(text):
        decimals = len(m.group(2)) if m.group(2) else 0
        v = float(m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else ""))
        step = 0.5 * 10.0**-decimals
        unit = m.group(3) or ""
        scale = 1_000 if unit in {"k", "K"} else 1_000_000 if unit in {"m", "M"} else 1
        out.append((v * scale, step * scale))
    return out


def numbers_in_text(text: str) -> list[float]:
    return [v for v, _ in _numbers_with_precision(text)]


def _walk(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _walk(v)
    elif isinstance(obj, str):
        yield from numbers_in_text(obj)


def allowed_numbers(*sources: Any) -> list[float]:
    """Every number in the sources, plus its percentage form (decimals × 100)."""
    vals: list[float] = []
    for src in sources:
        if isinstance(src, str):
            with contextlib.suppress(ValueError):
                src = json.loads(src)
        for v in _walk(src):
            vals.append(v)
            if abs(v) < 5:  # decimals such as 0.0415 are shown as 4.15%
                vals.append(v * 100)
    return vals


def _close(v: float, half_step: float, allowed: list[float]) -> bool:
    """True if ``v`` is some allowed value rounded to the precision ``v`` is written with."""
    return any(abs(v - abs(a)) <= half_step + 1e-9 for a in allowed)


def unverified_numbers(text: str, *sources: Any) -> list[float]:
    """Numbers in ``text`` not traceable to ``sources`` (empty list = text is safe)."""
    allowed = allowed_numbers(*sources)
    return [
        v
        for v, half in _numbers_with_precision(text)
        if not (v <= SMALL_INT and v == int(v)) and not _close(v, half, allowed)
    ]
