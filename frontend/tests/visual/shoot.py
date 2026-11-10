"""Side-by-side parity screenshots: React reference (:3000) vs Dash (:8050).

Usage: python -m tests.visual.shoot <name> <react_path> <dash_path> [--widths 1440 1024]
                                     [--auth] [--wait-react SEL] [--wait-dash SEL]
Writes .screens/<name>-<width>-react.png and -dash.png (full page).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[2] / ".screens"
REACT, DASH = "http://localhost:3000", "http://localhost:8050"
MOCK_USER = {"id": "usr-001", "email": "demo@advisor.test", "name": "Alex Morgan", "role": "advisor",
             "advisor_id": "adv-001", "firm": "Harborview Wealth Partners (demo)"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("react_path")
    ap.add_argument("dash_path")
    ap.add_argument("--widths", nargs="+", type=int, default=[1440, 1024])
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--dash-token", default="mock-advisor-token")
    ap.add_argument("--wait-react", default="body")
    ap.add_argument("--wait-dash", default="body")
    ap.add_argument("--settle", type=int, default=1200)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    react_init = "sessionStorage.setItem('transition_token','mock-advisor-token');" if a.auth else ""
    session = json.dumps({"token": a.dash_token, "user": MOCK_USER})
    dash_init = (f"sessionStorage.setItem('session', {json.dumps(session)});"
                 f"sessionStorage.setItem('session-timestamp', '{1}');") if a.auth else ""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w in a.widths:
            for which, base, path, init, wait in (
                ("react", REACT, a.react_path, react_init, a.wait_react),
                ("dash", DASH, a.dash_path, dash_init, a.wait_dash),
            ):
                ctx = browser.new_context(viewport={"width": w, "height": 900}, device_scale_factor=1)
                if init:
                    ctx.add_init_script(init)
                page = ctx.new_page()
                page.goto(base + path, wait_until="networkidle")
                page.wait_for_selector(wait, timeout=20000)
                if which == "react":  # hide the Next.js dev-mode badge (not part of the app)
                    page.add_style_tag(content="nextjs-portal{display:none!important}")
                page.wait_for_timeout(a.settle)
                f = OUT / f"{a.name}-{w}-{which}.png"
                page.screenshot(path=str(f), full_page=True)
                print(f)
                ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
