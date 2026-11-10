"""Render the sample tax-lot statement PDF for an account (default: the onboarding account).

Usage: uv run python scripts/make_sample_pdf.py [--account acc_022] [--out path.pdf]
Requires a seeded database (scripts/seed_demo.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.models import Account
from app.db.sample_pdf import render_statement_pdf
from app.db.session import get_sessionmaker


def main() -> None:
    s = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=None)
    parser.add_argument("--out", type=Path, default=s.DATA_DIR / "sample_statement.pdf")
    args = parser.parse_args()
    with get_sessionmaker()() as session:
        account_id = args.account
        if account_id is None:
            acct = session.query(Account).filter(Account.target_model_id.is_(None)).first()
            if acct is None:
                raise SystemExit("No onboarding account found — run scripts/seed_demo.py first.")
            account_id = acct.id
        path = render_statement_pdf(session, account_id, args.out, s.AS_OF_DATE)
    print("Wrote", path)


if __name__ == "__main__":
    main()
