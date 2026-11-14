"""Saved reports: numbers are generated once, written to JSON, then read back.

``data/analytics/risk_snapshot.json`` holds one report per client and one per advisor book. A
report is re-generated only when

* someone presses **Recalculate** (``refresh=True``),
* the client's accounts change (an account is added or removed) or the book's clients change
  (onboarded / deleted client), or
* the data source or as-of date changes (e.g. switching from mock to Aladdin).

Trades inside an account do not re-generate anything on their own: the report is a point-in-time
snapshot and shows when it was generated.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

from app.risk_analytics.types import RiskReport

FORMAT_VERSION = 6  # bump when the report shape or taxonomy changes


def signature(ids: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:16]


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None

    # ------------------------------------------------------------------ file
    def _load(self) -> dict[str, Any]:
        if self._data is None:
            data: dict[str, Any] = {}
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text())
                except (OSError, ValueError):
                    data = {}
            if data.get("format_version") != FORMAT_VERSION:
                data = {}
            data.setdefault("format_version", FORMAT_VERSION)
            data.setdefault("books", {})
            data.setdefault("clients", {})
            data.setdefault("accounts", {})
            self._data = data
        return self._data

    def _save(self) -> None:
        data = self._load()
        data["_about"] = ("Point-in-time portfolio analytics, generated once and reused. Delete "
                          "this file (or press Recalculate in the app) to regenerate.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(self.path)

    # ------------------------------------------------------------------ access
    def _get(self, kind: str, key: str, sig: str, source: str, as_of: date) -> RiskReport | None:
        with self._lock:
            entry = self._load()[kind].get(key)
            if not entry or entry.get("signature") != sig:
                return None
            rep = RiskReport.model_validate(entry["report"])
            if rep.data_source != source or rep.as_of != as_of:
                return None
            return rep

    def _put(self, kind: str, key: str, sig: str, report: RiskReport) -> None:
        with self._lock:
            self._load()[kind][key] = {"signature": sig,
                                       "report": report.model_dump(mode="json")}
            self._save()

    def get_client(self, client_id: str, sig: str, source: str, as_of: date) -> RiskReport | None:
        return self._get("clients", client_id, sig, source, as_of)

    def put_client(self, client_id: str, sig: str, report: RiskReport) -> None:
        self._put("clients", client_id, sig, report)

    def get_account(self, account_id: str, sig: str, source: str, as_of: date
                    ) -> RiskReport | None:
        return self._get("accounts", account_id, sig, source, as_of)

    def put_account(self, account_id: str, sig: str, report: RiskReport) -> None:
        self._put("accounts", account_id, sig, report)

    def get_book(self, advisor_id: str, sig: str, source: str, as_of: date) -> RiskReport | None:
        return self._get("books", advisor_id, sig, source, as_of)

    def put_book(self, advisor_id: str, sig: str, report: RiskReport) -> None:
        self._put("books", advisor_id, sig, report)

    def prune(self, clients: set[str], accounts: set[str]) -> None:
        """Forget reports of clients / accounts that no longer exist."""
        with self._lock:
            data = self._load()
            changed = False
            for kind, keep in (("clients", clients), ("accounts", accounts)):
                for k in [k for k in data[kind] if k not in keep]:
                    del data[kind][k]
                    changed = True
            if changed:
                self._save()
