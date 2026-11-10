"""Reset the database from the book file (data/book/book.json), then render the sample PDF.

The book file is the master copy of the client book. The first run (no file yet) generates the
book — 9 hand-written households plus BOOK_EXTRA_CLIENTS generated ones, about BOOK_TARGET_AUM in
total — and writes the file. Later runs reload the file, so everything recorded in it (new
clients, approved transitions, …) is kept.

Usage: uv run python scripts/seed_demo.py [--if-empty] [--regenerate-book]
  --if-empty         only seed when the database has no users (keeps data across restarts)
  --regenerate-book  build a brand-new book and overwrite the book file (loses recorded changes)
Login afterwards: demo@advisor.test / demo1234
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.book_store import check_book, read_book_file, save_book
from app.db.models import Account, Client, User
from app.db.sample_pdf import render_messy_statement_pdf, render_statement_pdf
from app.db.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.db.session import get_engine, get_sessionmaker
from app.db.synthetic_market import load_or_generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-empty", action="store_true")
    parser.add_argument("--regenerate-book", action="store_true")
    args = parser.parse_args()
    s = get_settings()
    if args.if_empty:
        from sqlalchemy import inspect

        engine = get_engine()
        if inspect(engine).has_table("users"):
            with get_sessionmaker()() as session:
                if session.query(User).count():
                    print("Database already seeded; skipping (--if-empty).")
                    return
    market = load_or_generate(
        s.DATA_DIR, s.SYNTHETIC_SEED, s.AS_OF_DATE, s.UNIVERSE_SIZE, s.PRICE_HISTORY_YEARS
    )
    engine = get_engine()
    book_data = None
    if s.BOOK_FILE.exists() and not args.regenerate_book:
        book_data, _ = read_book_file(s.BOOK_FILE)
        print("Loading the client book from", s.BOOK_FILE)
    else:
        print(f"Generating a new client book ({s.BOOK_EXTRA_CLIENTS} extra clients)…")
    with get_sessionmaker()() as session:
        summary = seed_demo(
            session,
            engine,
            market,
            s.SYNTHETIC_SEED,
            extra_clients=s.BOOK_EXTRA_CLIENTS,
            total_aum=s.BOOK_TARGET_AUM,
            book_data=book_data,
        )
        from app.analytics.factory import get_provider

        saved = save_book(session, s.BOOK_FILE, market.as_of, get_provider().get_prices)
        session.commit()
        problems = check_book(saved)
        # sample statement = the onboarding household's legacy account (the one to transition)
        acct = (
            session.query(Account)
            .join(Client)
            .filter(Account.target_model_id.is_(None))
            .order_by(Account.id)
            .first()
        )
        pdf = None
        if acct is not None:
            pdf = render_statement_pdf(
                session, acct.id, s.DATA_DIR / "sample_statement.pdf", market.as_of
            )
            render_messy_statement_pdf(
                session, acct.id, s.DATA_DIR / "sample_statement_messy.pdf", market.as_of
            )

    print("Seeded demo database:", s.DATABASE_URL)
    for k, v in asdict(summary).items():
        print(f"  {k:<11}{v}")
    bs = saved["summary"]
    print(
        f"Book file: {s.BOOK_FILE}  ({bs['n_clients']} clients, total AUM ${bs['total_aum']:,.0f})"
    )
    print("  totals check:", problems if problems else "OK — accounts → clients → book add up")
    if pdf:
        print("Sample PDF:", pdf)
    print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
