"""Lot IDs: the identifier a person sees for a tax lot (like a custodian's lot number).

A lot keeps two identifiers:
- ``Lot.id`` — internal primary key (``lot_…``), used between the API and the optimizer.
- ``Lot.lot_ref`` — the **Lot ID** shown in the app, statements and exports. It is unique within
  an account. Lots imported from a statement keep the statement's Lot ID; lots without one
  (seed data, Plaid positions, buys from an approved transition) get ``L<account>-<nnnn>``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_GENERATED = re.compile(r"^L(\d+)-(\d+)$")


def account_code(account_id: str) -> str:
    """'acc_017' → '017' (digits of the account id; the id itself if it has none)."""
    digits = "".join(c for c in account_id if c.isdigit())
    return digits or account_id


def make_lot_ref(account_id: str, seq: int) -> str:
    return f"L{account_code(account_id)}-{seq:04d}"


def next_lot_refs(account_id: str, existing: Iterable[str | None], n: int) -> list[str]:
    """``n`` new Lot IDs for the account that don't clash with ``existing``."""
    taken = {r for r in existing if r}
    seq = max(
        (int(m.group(2)) for r in taken if (m := _GENERATED.match(r))),
        default=0,
    )
    out: list[str] = []
    while len(out) < n:
        seq += 1
        ref = make_lot_ref(account_id, seq)
        if ref not in taken:
            out.append(ref)
            taken.add(ref)
    return out
