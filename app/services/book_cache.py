"""Caches for book analytics, so 100+ clients stay fast.

Two levels, both kept until the data they depend on changes (see
``app.db.book_store.install_listeners``, which reports what each commit touched):

- **Book level** (book KPIs, book charts, client list rows): cleared by any change to the book.
  Rebuilding them is cheap when the per-account pieces below are still cached.
- **Account level** (an account's inputs, valuation, TE / AUM / tax history): cleared only for
  the accounts a commit touched — so deleting or editing one client doesn't recompute the other
  hundred. Changes that can affect every account (models, prices, client tax rates, bulk
  statements) clear everything.

Cache keys include the database (``id`` of the engine), so separate test databases never mix.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_version = 0  # book level: bumped on every book change
_global_rev = 0  # account level: bumped when every account may be affected
_acct_rev: dict[str, int] = {}  # account level: bumped per touched account
_cache: dict[tuple[Any, ...], Any] = {}
_acct_cache: dict[tuple[Any, ...], Any] = {}
_lock = threading.Lock()


def version() -> int:
    return _version


def invalidate(accounts: Iterable[str] | None = None, everything: bool = False) -> None:
    """A commit changed the book: drop book-level results, plus the touched accounts' results
    (or all account results when ``everything``)."""
    global _version, _global_rev
    with _lock:
        _version += 1
        _cache.clear()
        if everything:
            _global_rev += 1
            _acct_cache.clear()
        else:
            for a in accounts or ():
                _acct_rev[a] = _acct_rev.get(a, 0) + 1
    _schedule_rewarm()


def book_cached(fn: F) -> F:
    """Cache a PortfolioService method per (database, book version, advisor, arguments)."""

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        key = (
            id(self.db.get_bind()),
            _version,
            self.advisor_id,
            fn.__name__,
            args,
            tuple(sorted(kwargs.items())),
        )
        with _lock:
            if key in _cache:
                return _cache[key]
            flight = _inflight.setdefault(key, threading.Lock())
        # single flight: concurrent requests for the same numbers (several charts on one page)
        # wait for the first computation instead of each recomputing the whole book
        with flight:
            with _lock:
                if key in _cache:
                    return _cache[key]
            try:
                value = fn(self, *args, **kwargs)
                with _lock:
                    if key[1] == _version:  # don't store a result computed across a change
                        _cache[key] = value
            finally:
                with _lock:
                    _inflight.pop(key, None)
        return value

    return wrapper  # type: ignore[return-value]


_inflight: dict[tuple[Any, ...], threading.Lock] = {}
_rewarm: threading.Timer | None = None
_warmer: Callable[[], None] | None = None


def set_warmer(fn: Callable[[], None]) -> None:
    """Register the function that precomputes the landing-page numbers (app startup)."""
    global _warmer
    _warmer = fn


def _schedule_rewarm(delay: float = 1.0) -> None:
    """After a change, recompute the book numbers in the background (debounced), so the next
    page view finds them ready instead of waiting."""
    global _rewarm
    if _warmer is None:
        return
    if _rewarm is not None:
        _rewarm.cancel()
    _rewarm = threading.Timer(delay, _warmer)
    _rewarm.daemon = True
    _rewarm.start()


def account_cached(
    bind: Any, account_id: str, name: str, args: tuple[Any, ...], fn: Callable[[], Any]
) -> Any:
    """Per-account memo: ``fn()`` is recomputed only after that account (or everything) changed.
    Values must be immutable / never mutated by callers."""
    with _lock:
        key = (id(bind), _global_rev, account_id, _acct_rev.get(account_id, 0), name, args)
        if key in _acct_cache:
            return _acct_cache[key]
    value = fn()
    with _lock:
        if key[1] == _global_rev and key[3] == _acct_rev.get(account_id, 0):
            _acct_cache[key] = value
    return value
