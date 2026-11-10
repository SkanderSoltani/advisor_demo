"""Engine / session factory.

SQLite by default; any SQLAlchemy URL (e.g. Postgres) via DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base


def make_engine(url: str) -> Engine:
    """Create an engine; enables FK enforcement on SQLite."""
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        future=True,
    )
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # type: ignore[no-untyped-def]
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().DATABASE_URL)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_db(engine: Engine | None = None) -> None:
    """Create all tables (idempotent) and apply small in-place upgrades."""
    eng = engine or get_engine()
    Base.metadata.create_all(eng)
    _add_lot_refs(eng)
    _add_event_term_losses(eng)


def _add_event_term_losses(engine: Engine) -> None:
    """Databases created before events stored their ST/LT loss split: add and backfill it."""
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine).get_columns("management_events")}
    if "realized_st_loss" in cols:
        return
    with engine.begin() as conn:
        for c in ("realized_st_loss", "realized_lt_loss"):
            conn.execute(text(f"ALTER TABLE management_events ADD COLUMN {c} FLOAT DEFAULT 0.0"))
        conn.execute(
            text(
                "UPDATE management_events SET "
                "realized_st_loss = COALESCE((SELECT -SUM(realized_gain) FROM event_trades t "
                "WHERE t.event_id = management_events.id AND t.realized_gain < 0 "
                "AND t.term = 'ST'), 0), "
                "realized_lt_loss = COALESCE((SELECT -SUM(realized_gain) FROM event_trades t "
                "WHERE t.event_id = management_events.id AND t.realized_gain < 0 "
                "AND t.term = 'LT'), 0)"
            )
        )


def _add_lot_refs(engine: Engine) -> None:
    """Databases created before Lot IDs existed: add ``lots.lot_ref`` and fill it in."""
    from sqlalchemy import inspect, text

    from app.db.lot_refs import make_lot_ref

    if "lot_ref" in {c["name"] for c in inspect(engine).get_columns("lots")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE lots ADD COLUMN lot_ref VARCHAR(40)"))
        rows = conn.execute(
            text("SELECT id, account_id FROM lots ORDER BY account_id, ticker, acquired_date, id")
        ).all()
        seq: dict[str, int] = {}
        for lot_id, account_id in rows:
            seq[account_id] = seq.get(account_id, 0) + 1
            conn.execute(
                text("UPDATE lots SET lot_ref = :r WHERE id = :i"),
                {"r": make_lot_ref(account_id, seq[account_id]), "i": lot_id},
            )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lots_account_lot_ref "
                "ON lots (account_id, lot_ref)"
            )
        )


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
