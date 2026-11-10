"""Generate the synthetic universe + 5y price history into DATA_DIR (deterministic).

Usage: uv run python scripts/generate_synthetic_data.py [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.synthetic_market import SyntheticMarket, generate_market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate even if files exist")
    args = parser.parse_args()
    s = get_settings()
    if SyntheticMarket.exists(s.DATA_DIR) and not args.force:
        print(f"Synthetic data already present in {s.DATA_DIR} (use --force to regenerate).")
        return
    mkt = generate_market(
        seed=s.SYNTHETIC_SEED,
        as_of=s.AS_OF_DATE,
        n_names=s.UNIVERSE_SIZE,
        years=s.PRICE_HISTORY_YEARS,
    )
    mkt.save(s.DATA_DIR)
    print(
        f"Wrote {len(mkt.universe)} securities × {len(mkt.prices)} days "
        f"({mkt.prices.index[0].date()} → {mkt.as_of}) to {s.DATA_DIR}"
    )


if __name__ == "__main__":
    main()
