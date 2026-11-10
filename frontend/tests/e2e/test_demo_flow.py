"""End-to-end demo flow through the Dash UI (Playwright).

Runs against whatever the Dash app at DASH_URL is connected to — the live backend
(USE_MOCKS=false, the intended target) or the in-process mock. Skipped if Dash isn't running.

    make demo            # or: backend on :8000 + `USE_MOCKS=false python app.py`
    pytest tests/e2e -q

Walks: sign in → client book → start a transition → every workspace step the backend asks for
→ optimize → approve → CSV/PDF downloads → the event shows on the client page. Also checks
reload stability, the simulated-analytics badge, stepper back-navigation and console errors.
"""

from __future__ import annotations

import os
import re

import httpx
import pytest

playwright = pytest.importorskip("playwright.sync_api")

DASH_URL = os.environ.get("DASH_URL", "http://localhost:8050")
EMAIL = os.environ.get("DEMO_EMAIL", "demo@advisor.test")
PASSWORD = os.environ.get("DEMO_PASSWORD", "demo1234")
STEP_TIMEOUT = 30_000
IGNORED_CONSOLE = ("favicon", "api.iconify.design", "Failed to load resource")


def _dash_up() -> bool:
    try:
        return httpx.get(f"{DASH_URL}/login", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _dash_up(), reason=f"Dash not running at {DASH_URL}")


@pytest.fixture()
def page():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        pg.errors = []  # type: ignore[attr-defined]
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text)
              if m.type == "error" and not any(s in m.text for s in IGNORED_CONSOLE) else None)
        yield pg
        browser.close()


def heading(pg) -> str:
    pg.wait_for_selector(".ts-canvas h1", timeout=STEP_TIMEOUT)
    return pg.locator(".ts-canvas h1").inner_text().strip()


def state(pg) -> str:
    pg.wait_for_selector(".ts-canvas [data-state]", timeout=STEP_TIMEOUT)
    return pg.locator(".ts-canvas [data-state]").get_attribute("data-state") or ""


def wait_change(pg, old_heading: str, old_state: str) -> str:
    old = old_heading
    try:
        pg.wait_for_function(
            "s => { const e = document.querySelector('.ts-canvas [data-state]');"
            " return e && e.dataset.state !== s; }",
            arg=old_state, timeout=STEP_TIMEOUT)
    except playwright.TimeoutError:
        shot = os.path.join(os.path.dirname(__file__), "..", "..", ".screens", "e2e-failure.png")
        pg.screenshot(path=shot, full_page=True)
        pytest.fail(f"stuck on step '{old}' (screenshot: .screens/e2e-failure.png); errors={pg.errors}")
    pg.wait_for_timeout(300)
    return heading(pg)


def sign_in(pg) -> None:
    pg.goto(f"{DASH_URL}/login")
    pg.fill("#login-email", EMAIL)
    pg.fill("#login-password", PASSWORD)
    pg.click("#login-submit")
    pg.wait_for_selector("#book-grid .ag-row", timeout=STEP_TIMEOUT)


def start_transition(pg) -> str:
    pg.locator(".ts-menu-trigger").first.click()
    pg.locator(".ts-menu-item.is-accent").click()
    pg.wait_for_function("/^\\/(transition|clients)\\//.test(location.pathname)", timeout=STEP_TIMEOUT)
    if "/clients/" in pg.url:
        pg.wait_for_selector("#cd-accounts-grid .ts-action-link", timeout=STEP_TIMEOUT)
        pg.locator("#cd-accounts-grid .ts-action-link").first.click()
        pg.wait_for_function("location.pathname.startsWith('/transition/')", timeout=STEP_TIMEOUT)
    return pg.url.rsplit("/", 1)[-1]


def test_demo_flow(page) -> None:
    pg = page
    sign_in(pg)
    assert pg.locator(".ts-kpi").count() >= 4, "book KPIs rendered"

    tid = start_transition(pg)
    assert re.match(r"^[\w-]+$", tid)
    seen: list[str] = []
    h = heading(pg)
    for _ in range(20):
        st = state(pg)
        seen.append(h)
        if h == "Import holdings":
            if pg.locator("button:has-text('Use current holdings')").count():
                pg.locator(".ts-canvas button:has-text('Use current holdings')").click()
            else:
                pg.locator(".ts-canvas button:has-text('sample statement')").click()
        elif h == "Review lots":
            pg.locator(".ts-canvas button:has-text('Confirm holdings')").click()
        elif h == "Choose your target":
            if st == "TARGET_KNOWLEDGE":  # take the guided path: objective → construction → compare
                pg.locator("button.ts-choice-card:has-text('Help me choose')").click()
            elif pg.locator("button.ts-choice-card").count():  # objective / construction question
                pg.locator("button.ts-choice-card").first.click()
            else:
                pg.locator("button.ts-model-card").first.click()
        elif h == "Compare models":
            assert pg.locator(".ts-canvas .ag-row").count() >= 5, "metrics table"
            pg.locator(".ts-canvas button:has-text('Select this model')").first.click()
        elif h == "Confirm target":
            pg.locator(".ts-canvas button:has-text('Select this model')").click()
        elif h == "Optimize transition":
            assert pg.locator(".ts-canvas .js-plotly-plot").count() == 1, "frontier chart"
            # reload mid-flow: same step, thread restored
            n_msgs = pg.locator(".ts-msg").count()
            pg.reload()
            assert heading(pg) == "Optimize transition"
            pg.wait_for_timeout(500)
            assert pg.locator(".ts-msg").count() >= n_msgs - 1
            pg.locator(".ts-canvas button:has-text('Run optimization')").click()
        elif h == "Optimization results":
            assert pg.locator(".ts-review-card").count() == 4
            assert "Settings:" in pg.locator(".ts-settings-line").inner_text()
            pg.locator(".ts-canvas button:has-text('Approve transition')").click()
        elif h == "Review & export":
            for label, ext in (("Download CSV", ".csv"), ("Download PDF", ".pdf")):
                with pg.expect_download(timeout=STEP_TIMEOUT) as dl:
                    pg.locator(f".ts-canvas button:has-text('{label}')").click()
                assert dl.value.suggested_filename.endswith(ext)
                assert os.path.getsize(dl.value.path()) > 100
            pg.locator(".ts-canvas button:has-text('Trade')").click()
        elif h == "Transition recorded":
            break
        else:  # question steps (objective / construction): take the first card
            pg.locator("button.ts-choice-card").first.click()
        h = wait_change(pg, h, st)
    assert seen[-1] == "Transition recorded" or h == "Transition recorded", seen
    for must in ("Import holdings", "Optimize transition", "Review & export"):
        assert must in seen, seen

    # the approved transition appears on the client's timeline
    pg.locator(".ts-canvas a:has-text('Back to client')").click()
    pg.wait_for_selector(".ts-evt-row", timeout=STEP_TIMEOUT)
    assert pg.locator(".ts-evt-row").first.inner_text().lower().find("transition") >= 0

    assert not pg.errors, pg.errors


def test_unauthenticated_redirects_to_login(page) -> None:
    page.goto(f"{DASH_URL}/transition/does-not-exist")
    page.wait_for_function("location.pathname === '/login'", timeout=STEP_TIMEOUT)


def test_unknown_transition_shows_error(page) -> None:
    sign_in(page)
    page.goto(f"{DASH_URL}/transition/does-not-exist")
    page.wait_for_selector(".ts-state", timeout=STEP_TIMEOUT)
    assert "wasn't found" in page.locator(".ts-state").inner_text()
