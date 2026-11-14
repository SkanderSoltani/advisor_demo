"""The book file: ``data/book/book.json`` is the master copy of the client book.

It holds every client, account, tax lot and management event (with its trades). The database is
a working copy:

- **Startup**: when the file has changed since it was last loaded (or the database is empty) the
  book tables are reloaded from the file. In-progress transition drafts are dropped then.
- **Write-through**: every database commit that changes a client, account, lot or event rewrites
  the file, so new clients, imported lots and approved transitions (with their realized gains
  and losses) are recorded and come back the same way next time.
- **Reset** (``scripts/seed_demo.py``) reloads the file; ``--regenerate-book`` builds a new one.

Each client, account and the book carry a ``summary`` block (AUM at the as-of prices and the
realized gains/losses from the event history). Summaries are derived: they are rewritten on every
save, ignored when loading, and always add up (account → client → book).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, delete, event, insert, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models as m

FORMAT_VERSION = 1
# valuation prices: the app's analytics provider (``provider.get_prices``), so the file's AUM
# matches the screens; falls back to the securities table
PriceFn = Callable[[list[str]], dict[str, float]]
BOOK_TYPES = (m.Client, m.Account, m.Lot, m.ManagementEvent, m.EventTrade)
META_KEY = "book_sha256"
ABOUT = (
    "Transition Studio client book (SYNTHETIC DATA). Master copy: the app loads it at startup "
    "and rewrites it after every change. 'summary' blocks are derived (AUM and current holdings "
    "at as-of prices, realized gains/losses from events) and ignored when loading; edit the "
    "other fields — the lots are what define holdings."
)

_book_path: Path | None = None
_as_of: date | None = None
_price_fn: PriceFn | None = None
_engine: Any = None  # the database the book file mirrors
_listeners = False


# ------------------------------------------------------------------ (de)serialisation
def _jsonable(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date | datetime) else v


def _parse(model: type[Any], d: dict[str, Any]) -> dict[str, Any]:
    """Book-file dict → column values for ``model`` (unknown / derived keys are ignored)."""
    out: dict[str, Any] = {}
    for col in model.__table__.columns:
        if col.key not in d:
            continue
        v = d[col.key]
        if v is not None and isinstance(col.type, DateTime):
            v = datetime.fromisoformat(v)
        elif v is not None and isinstance(col.type, Date):
            v = date.fromisoformat(v)
        out[col.key] = v
    return out


def _realized(events: Iterable[dict[str, Any]]) -> dict[str, float]:
    t = dict.fromkeys(
        (
            "st_gain",
            "st_loss",
            "lt_gain",
            "lt_loss",
            "net_realized",
            "losses_harvested",
            "est_taxes_saved",
        ),
        0.0,
    )
    for e in events:
        t["st_gain"] += e["realized_st_gain"]
        t["lt_gain"] += e["realized_lt_gain"]
        t["st_loss"] += e["realized_st_loss"] or 0.0
        t["lt_loss"] += e["realized_lt_loss"] or 0.0
        t["losses_harvested"] += e["losses_harvested"]
        t["est_taxes_saved"] += e["est_taxes_saved"]
    t["net_realized"] = t["st_gain"] + t["lt_gain"] - t["st_loss"] - t["lt_loss"]
    return t


def _holdings(
    lots: Iterable[dict[str, Any]], prices: dict[str, float], names: dict[str, str], aum: float
) -> list[dict[str, Any]]:
    """Current positions (lots summed by ticker), largest first; weight = share of ``aum``."""
    by: dict[str, dict[str, Any]] = {}
    for x in lots:
        h = by.setdefault(
            x["ticker"], {"shares": 0.0, "cost_basis": 0.0, "n_lots": 0, "locked": False}
        )
        h["shares"] += x["quantity"]
        h["cost_basis"] += x["cost_basis_total"]
        h["n_lots"] += 1
        h["locked"] = h["locked"] or bool(x.get("locked"))
    out = []
    for t, h in by.items():
        px = float(prices.get(t) or 0.0)
        mv = h["shares"] * px
        out.append(
            {
                "ticker": t,
                "name": names.get(t),
                "shares": round(h["shares"], 3),
                "price": round(px, 4),
                "market_value": round(mv, 2),
                "weight": round(mv / aum, 6) if aum else 0.0,
                "cost_basis": round(h["cost_basis"], 2),
                "unrealized_gain": round(mv - h["cost_basis"], 2),
                "n_lots": h["n_lots"],
                "locked": h["locked"],
            }
        )
    return sorted(out, key=lambda h: (-h["market_value"], h["ticker"]))


def _add(into: dict[str, float], part: dict[str, float]) -> None:
    for k, v in part.items():
        into[k] = into.get(k, 0.0) + v


def _rounded(d: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 2) for k, v in d.items()}


def _rows(session: Session, model: type[Any], *order: Any) -> list[dict[str, Any]]:
    """All rows of a table as JSON-ready dicts (plain rows — much faster than ORM objects)."""
    res = session.execute(select(model.__table__).order_by(*order)).mappings()
    return [{k: _jsonable(v) for k, v in r.items()} for r in res]


def export_book(
    session: Session, as_of: date | None = None, price_fn: PriceFn | None = None
) -> dict[str, Any]:
    """The whole book as a JSON-ready dict (clients → accounts → lots / events → trades)."""
    prices: dict[str, float] = dict(
        session.execute(select(m.Security.ticker, m.Security.last_price)).all()
    )
    fn = price_fn or _price_fn
    if fn is not None:
        held = sorted(set(session.scalars(select(m.Lot.ticker).distinct())))
        prices.update(fn(held))
    names: dict[str, str] = dict(session.execute(select(m.Security.ticker, m.Security.name)).all())
    clients = _rows(session, m.Client, m.Client.id)
    accounts = _rows(session, m.Account, m.Account.id)
    lots = _rows(session, m.Lot, m.Lot.id)
    events = _rows(session, m.ManagementEvent, m.ManagementEvent.event_date, m.ManagementEvent.id)
    trades = _rows(session, m.EventTrade, m.EventTrade.id)

    def group(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(r.pop(key), []).append(r)
        return out

    trades_by = group(trades, "event_id")
    events_by = group(events, "account_id")
    lots_by = group(lots, "account_id")
    accounts_by = group(accounts, "client_id")

    book_real: dict[str, float] = {}
    book_aum = 0.0
    out_clients = []
    for c in clients:
        c_real: dict[str, float] = {}
        c_aum = 0.0
        c_cash = 0.0
        out_accounts = []
        c_accounts = accounts_by.get(c["id"], [])
        c_lots = [x for a in c_accounts for x in lots_by.get(a["id"], [])]
        for a in c_accounts:
            a_lots = lots_by.get(a["id"], [])
            a_events = events_by.get(a["id"], [])
            invested = sum(x["quantity"] * float(prices.get(x["ticker"]) or 0.0) for x in a_lots)
            aum = invested + a["cash"]
            real = _realized(a_events)
            c_aum += aum
            c_cash += a["cash"]
            _add(c_real, real)
            out_accounts.append(
                {
                    **a,
                    "summary": {
                        "aum": round(aum, 2),
                        "invested": round(invested, 2),
                        "n_lots": len(a_lots),
                        "n_events": len(a_events),
                        "realized": _rounded(real),
                        "cash": round(a["cash"], 2),
                        "holdings": _holdings(a_lots, prices, names, aum),
                    },
                    "lots": a_lots,
                    "events": [{**e, "trades": trades_by.get(e["id"], [])} for e in a_events],
                }
            )
        book_aum += c_aum
        _add(book_real, c_real)
        out_clients.append(
            {
                **c,
                "summary": {
                    "aum": round(c_aum, 2),
                    "n_accounts": len(c_accounts),
                    "realized": _rounded(c_real),
                    "cash": round(c_cash, 2),
                    "holdings": _holdings(c_lots, prices, names, c_aum),  # across accounts
                },
                "accounts": out_accounts,
            }
        )
    return {
        "_about": ABOUT,
        "format_version": FORMAT_VERSION,
        "as_of": as_of.isoformat() if as_of else None,
        "summary": {
            "n_clients": len(clients),
            "n_accounts": len(accounts),
            "total_aum": round(book_aum, 2),
            "realized": _rounded(book_real),
        },
        "clients": out_clients,
    }


def load_book(session: Session, data: dict[str, Any]) -> None:
    """Insert the book from a book-file dict (the book tables must be empty)."""
    clients, accounts, lots, events, trades = [], [], [], [], []
    for c in data.get("clients", []):
        clients.append(_parse(m.Client, c))
        for a in c.get("accounts", []):
            accounts.append({**_parse(m.Account, a), "client_id": c["id"]})
            lots += [{**_parse(m.Lot, x), "account_id": a["id"]} for x in a.get("lots", [])]
            for e in a.get("events", []):
                events.append({**_parse(m.ManagementEvent, e), "account_id": a["id"]})
                trades += [
                    {**_parse(m.EventTrade, t), "event_id": e["id"]} for t in e.get("trades", [])
                ]
    for model, rows in (
        (m.Client, clients),
        (m.Account, accounts),
        (m.Lot, lots),
        (m.ManagementEvent, events),
        (m.EventTrade, trades),
    ):
        if rows:
            session.execute(insert(model), rows)


def clear_book(session: Session) -> None:
    """Delete the book (and transition drafts, which point at accounts)."""
    for model in (m.Transition, m.EventTrade, m.ManagementEvent, m.Lot, m.Account, m.Client):
        session.execute(delete(model))


def check_book(data: dict[str, Any], tol: float = 0.05) -> list[str]:
    """Problems with the summaries (empty list = account → client → book sums all add up)."""
    problems: list[str] = []

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= tol * max(1, len(data.get("clients", [])))

    book = data["summary"]
    tot_aum = 0.0
    tot_real: dict[str, float] = {}
    for c in data["clients"]:
        for a in c["accounts"]:
            held = sum(h["market_value"] for h in a["summary"].get("holdings", []))
            if "holdings" in a["summary"] and not close(
                held + a["summary"]["cash"], a["summary"]["aum"]
            ):
                problems.append(f"{a['id']}: holdings + cash {held:,.2f} ≠ AUM")
        if "holdings" in c["summary"]:
            held = sum(h["market_value"] for h in c["summary"]["holdings"])
            if not close(held + c["summary"]["cash"], c["summary"]["aum"]):
                problems.append(f"{c['id']}: holdings + cash {held:,.2f} ≠ AUM")
        c_aum = sum(a["summary"]["aum"] for a in c["accounts"])
        c_real: dict[str, float] = {}
        for a in c["accounts"]:
            _add(c_real, a["summary"]["realized"])
        if not close(c_aum, c["summary"]["aum"]):
            problems.append(f"{c['id']}: accounts AUM {c_aum:,.2f} ≠ {c['summary']['aum']:,.2f}")
        for k, v in c_real.items():
            if not close(v, c["summary"]["realized"][k]):
                problems.append(f"{c['id']}: accounts {k} {v:,.2f} ≠ client total")
        tot_aum += c["summary"]["aum"]
        _add(tot_real, c["summary"]["realized"])
    if not close(tot_aum, book["total_aum"]):
        problems.append(f"book: clients AUM {tot_aum:,.2f} ≠ total {book['total_aum']:,.2f}")
    for k, v in tot_real.items():
        if not close(v, book["realized"][k]):
            problems.append(f"book: clients {k} {v:,.2f} ≠ book total {book['realized'][k]:,.2f}")
    return problems


# ------------------------------------------------------------------ file I/O
def _dumps(data: Any, indent: int = 0) -> str:
    """Pretty JSON where each lot / trade (a flat record) stays on one line."""
    pad, inner = "  " * indent, "  " * (indent + 1)
    if isinstance(data, dict):
        if data and all(not isinstance(v, dict | list) for v in data.values()) and indent >= 4:
            return json.dumps(data, ensure_ascii=False)
        items = [f"{inner}{json.dumps(k)}: {_dumps(v, indent + 1)}" for k, v in data.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}" if items else "{}"
    if isinstance(data, list):
        if not data:
            return "[]"
        items = [f"{inner}{_dumps(v, indent + 1)}" for v in data]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(data, ensure_ascii=False)


def write_book_file(path: Path, data: dict[str, Any]) -> str:
    """Write atomically; returns the file's sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (_dumps(data) + "\n").encode()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    return hashlib.sha256(body).hexdigest()


def read_book_file(path: Path) -> tuple[dict[str, Any], str]:
    body = path.read_bytes()
    return json.loads(body), hashlib.sha256(body).hexdigest()


def _set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(m.AppMeta, key)
    if row is None:
        session.add(m.AppMeta(key=key, value=value))
    else:
        row.value = value


def save_book(
    session: Session, path: Path, as_of: date | None = None, price_fn: PriceFn | None = None
) -> dict[str, Any]:
    """Export the database book to ``path`` and remember which file version the DB matches."""
    data = export_book(session, as_of, price_fn)
    sha = write_book_file(path, data)
    _set_meta(session, META_KEY, sha)
    return data


def sync_from_file(session: Session, path: Path, as_of: date | None = None) -> str:
    """Startup: make the database match the book file. Returns what happened."""
    if not path.exists():
        save_book(session, path, as_of)
        session.commit()
        return "created"
    data, sha = read_book_file(path)
    meta = session.get(m.AppMeta, META_KEY)
    if meta is not None and meta.value == sha:
        return "unchanged"
    clear_book(session)
    load_book(session, data)
    session.flush()
    save_book(session, path, as_of)  # rewrite so the summaries match the (edited) data
    session.commit()
    return "reloaded"


# ------------------------------------------------------------------ write-through
# changes to these also change book analytics (cached in app.services.book_cache)
CACHE_TYPES = (*BOOK_TYPES, m.ModelPortfolio, m.ModelHolding, m.Security)


TAX_FIELDS = ("federal_st_rate", "federal_lt_rate", "state", "state_rate")


def _tax_rates_changed(c: m.Client) -> bool:
    """True only when a tax-rate column really changed (a client is also "dirty" when, e.g., an
    account is added to it, which must not clear every account's cached analytics)."""
    from sqlalchemy import inspect

    st = inspect(c)
    return any(st.attrs[f].history.has_changes() for f in TAX_FIELDS)


def _touched(session: Session, objs: Iterable[Any]) -> None:
    """Record what a pending commit changes: book file dirty, and which accounts' cached
    analytics to drop (``everything`` when it can't be narrowed down)."""
    info = session.info
    touched: set[str] = info.setdefault("touched_accounts", set())
    deleted = set(session.deleted)
    for o in objs:
        if isinstance(o, BOOK_TYPES):
            info["book_dirty"] = True
        if isinstance(o, m.Account):
            touched.add(o.id)
        elif isinstance(o, m.Lot | m.ManagementEvent):
            touched.add(o.account_id)
        elif isinstance(o, m.EventTrade):
            pass  # trades feed no cached analytics (the loss split is stored on the event)
        elif isinstance(o, m.Client):
            if o not in deleted and o not in session.new and _tax_rates_changed(o):
                info["touch_everything"] = True  # tax rates feed the client's accounts' numbers
            else:
                info["cache_dirty"] = True  # client list / book totals change
        elif isinstance(o, CACHE_TYPES):  # models, holdings, securities
            info["touch_everything"] = True
    if touched:
        info["cache_dirty"] = True


def install_listeners() -> None:
    """Track commits that change the book: drop the affected cached analytics and, when enabled,
    rewrite the book file (in the background). Idempotent."""
    global _listeners
    if _listeners:
        return
    _listeners = True
    from app.services import book_cache

    @event.listens_for(Session, "before_flush")
    def _mark(session: Session, _ctx: Any, _inst: Any) -> None:
        _touched(session, (*session.new, *session.dirty, *session.deleted))

    @event.listens_for(Session, "do_orm_execute")
    def _mark_bulk(state: Any) -> None:
        if state.is_delete or state.is_update or state.is_insert:
            classes = {mp.class_ for mp in state.all_mappers}
            if classes & set(BOOK_TYPES):
                state.session.info["book_dirty"] = True
            if classes & set(CACHE_TYPES):
                state.session.info["touch_everything"] = True

    @event.listens_for(Session, "after_rollback")
    def _clear(session: Session) -> None:
        for k in ("book_dirty", "cache_dirty", "touch_everything", "touched_accounts"):
            session.info.pop(k, None)

    @event.listens_for(Session, "after_commit")
    def _after_commit(session: Session) -> None:
        everything = session.info.pop("touch_everything", False)
        accounts = session.info.pop("touched_accounts", set())
        if everything or accounts or session.info.pop("cache_dirty", False):
            book_cache.invalidate(accounts, everything=everything)
        if not session.info.pop("book_dirty", False) or _book_path is None:
            return
        if _engine is not None and session.get_bind() is not _engine:
            return  # another database (e.g. a test DB) — not the one the file mirrors
        if session.info.get("book_writer"):
            return
        _schedule_write(session.get_bind())


# ------------------------------------------------------------------ background writer
# Writing the ~15 MB file takes a couple of seconds, so it happens on a worker thread: the
# request returns right away, and several quick changes collapse into one write of the latest
# state. ``wait_for_book_writes`` blocks until the file is current (shutdown, tests).
_write_cv = threading.Condition()
_write_pending = False
_write_running = False
_write_bind: Any = None


def _schedule_write(bind: Any) -> None:
    global _write_pending, _write_bind
    with _write_cv:
        _write_pending, _write_bind = True, bind
        if not _write_running:
            threading.Thread(target=_write_loop, name="book-file-writer", daemon=True).start()
            _set_running(True)


def _set_running(value: bool) -> None:
    global _write_running
    _write_running = value


def _write_loop() -> None:
    global _write_pending
    log = get_logger("book")
    while True:
        with _write_cv:
            if not _write_pending or _book_path is None:
                _set_running(False)
                _write_cv.notify_all()
                return
            _write_pending = False
            bind, path = _write_bind, _book_path
        try:
            with Session(bind=bind) as s:
                s.info["book_writer"] = True
                save_book(s, path, _as_of)
                s.commit()
        except Exception as exc:  # keep the app running; the next change retries
            log.error("book file write failed", error=str(exc))


def wait_for_book_writes(timeout: float = 60.0) -> bool:
    """Block until pending book-file writes are done. Returns False on timeout."""
    with _write_cv:
        return _write_cv.wait_for(lambda: not _write_pending and not _write_running, timeout)


def set_price_source(price_fn: PriceFn | None) -> None:
    """Prices used to value the book in the file (normally ``provider.get_prices``)."""
    global _price_fn
    _price_fn = price_fn


def enable_write_through(
    path: Path,
    as_of: date | None = None,
    price_fn: PriceFn | None = None,
    engine: Any = None,
) -> None:
    """After every commit that touched the book, rewrite the book file."""
    global _book_path, _as_of, _engine
    _book_path, _as_of, _engine = path, as_of, engine
    if price_fn is not None:
        set_price_source(price_fn)
    install_listeners()


def disable_write_through() -> None:
    wait_for_book_writes()
    global _book_path, _engine
    _book_path, _engine = None, None
