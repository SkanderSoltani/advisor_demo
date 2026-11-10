"""Write the OpenAPI schema to docs/openapi.json (the contract shared with the front-end team).

Usage: uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    out = ROOT / "docs" / "openapi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
    print("Wrote", out)


if __name__ == "__main__":
    main()
