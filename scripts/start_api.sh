#!/bin/sh
# Container start for the API (Railway / Docker).
# The data folder may be an empty persistent volume: fill in any missing starter files (client
# book, model catalog, synthetic market) without overwriting what the app has already recorded
# there, seed the database on first start, then serve on $PORT (dual-stack for Railway's private
# network).
set -e
SEED_DIR="${SEED_DIR:-/srv/seed-data}" DATA_ROOT="${DATA_ROOT:-/srv/data}" python - <<'PY'
import os, shutil
from pathlib import Path

src, dst = Path(os.environ["SEED_DIR"]), Path(os.environ["DATA_ROOT"])
dst.mkdir(parents=True, exist_ok=True)
for f in sorted(src.rglob("*")):
    t = dst / f.relative_to(src)
    if f.is_dir():
        t.mkdir(parents=True, exist_ok=True)
    elif not t.exists():
        shutil.copy2(f, t)
        print("seeded", t)
PY
[ -n "$SEED_ONLY" ] && exit 0
python scripts/seed_demo.py --if-empty
exec uvicorn app.main:app --host :: --port "${PORT:-8000}" --proxy-headers \
  --forwarded-allow-ips '*' --timeout-keep-alive 75
