"""Start Transition Studio: API (http://localhost:8000) + UI (http://localhost:8050).

    python run.py

Works with any Python 3; dependencies are handled by uv. Press Ctrl+C to stop.
"""

import os
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def find_uv() -> str:
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if not Path(uv).exists():
        sys.exit("uv is required: https://docs.astral.sh/uv/")
    return uv


def wait_for(url: str, seconds: float = 30) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.Popen:
    # own process group, so stopping it also stops the server uv launched
    return subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)


def stop(p: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(p.pid, sig)
    except ProcessLookupError:
        pass


def _interrupt(*_: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _interrupt)  # `kill` stops cleanly too, like Ctrl+C
    uv = find_uv()
    print("▶ installing dependencies…")
    subprocess.run([uv, "sync", "-q"], cwd=ROOT, check=True)
    subprocess.run([uv, "sync", "-q", "--no-dev"], cwd=FRONTEND, check=True)
    subprocess.run([uv, "run", "python", "scripts/seed_demo.py", "--if-empty"], cwd=ROOT, check=True)

    procs = [start([uv, "run", "uvicorn", "app.main:app", "--port", "8000"], ROOT)]
    try:
        if not wait_for("http://localhost:8000/health"):
            sys.exit("API did not start")
        env = {**os.environ, "USE_MOCKS": "false", "DASH_DEBUG": "false",
               "API_BASE_URL": "http://localhost:8000/api/v1"}
        procs.append(start([uv, "run", "python", "app.py"], FRONTEND, env))
        wait_for("http://localhost:8050", 30)
        print("\n  Transition Studio is running")
        print("  UI   http://localhost:8050   (demo@advisor.test / demo1234)")
        print("  API  http://localhost:8000/docs")
        print("  Ctrl+C to stop\n")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            stop(p, signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stop(p, signal.SIGKILL)
        print("stopped")


if __name__ == "__main__":
    main()
