# Transition Studio — front end (Plotly Dash)

A Dash port of the v0 React design in `../reference/react-ui/`. That React app is the visual
reference only and is never modified. Every number on screen comes from the backend API; the
front end only formats it. Synthetic data only.

Screens: login · client book · client detail (with onboarding / add-account / edit modals) ·
transition workspace (AI guide chat + step canvas, six steps from import to approval).

## Run

```bash
cd frontend
uv sync                                   # Python 3.11+; installs dev tools too

# against the real backend (start it first: `uv run uvicorn app.main:app` in the repo root)
USE_MOCKS=false uv run python app.py      # http://localhost:8050

# no backend needed: in-process mock with the same API shapes
USE_MOCKS=true uv run python app.py
```

Login: `demo@advisor.test` / `demo1234`. To run backend and UI together, use `scripts/demo.sh` in
the repo root (Docker Compose if installed, otherwise both locally).

Production: `gunicorn app:server -b 0.0.0.0:8050 --workers 1 --threads 8` (this is what the
Dockerfile runs). Keep one worker in mock mode, because the mock keeps its state in the process.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `USE_MOCKS` | `true` | `true`: `services/mock_backend.py` answers every API call in process. `false`: real HTTP to `API_BASE_URL` |
| `API_BASE_URL` | `http://localhost:8000/api/v1` | Backend base URL (Compose uses `http://api:8000/api/v1`) |
| `DASH_DEBUG` | `true` | Dash dev tools and hot reload (set `false` for demos) |
| `HOST` / `PORT` | `127.0.0.1` / `8050` | `python app.py` only |

Mock mode shows the same households, the 2 Schwab placeholder models and a scripted guide, so the
UI can be demoed or developed with no backend. The mock mirrors backend defaults that affect what
you see, such as the guided-optimization settings (`CHAT_DEFAULT_CONSTRAINTS`).

## Layout

```
app.py                  Dash app, Mantine theme, global stores (session, auth-expired, refresh)
pages/                  one module per route (login, clients = book, client_detail, transition)
callbacks/              callbacks per page; modals.py is shared by book + client detail
components/             shell (top bar, rail, footer), charts, modals, timeline, stepper, chat panel
components/canvas/      workspace step canvases + REGISTRY (see below)
services/api_client.py  typed API client (pydantic models in services/schemas.py, generated)
services/mock_backend.py
services/format.py      display formatting only (money, %, bps, dates)
theme/                  tokens.py (brand values), plotly_template.py ("schwab" template)
assets/                 theme.css (tokens + all styles), AG Grid formatters/renderers, Plaid loader
```

Conventions: API errors map to an inline error panel with Retry (or a notification for actions);
any 401 clears the session and returns to `/login`. Action callbacks ignore the initial page
render and only fire on real clicks.

## Brand tokens and fonts

Colors, radii and shadows are defined twice and must stay in sync:

- `assets/theme.css` `:root` (`--brand-primary`, `--brand-navy`, `--ink-*`, `--surface-*`, …), used
  by every style rule and by AG Grid (`--ag-*` variables on `.ts-grid`);
- `theme/tokens.py`, used by the Mantine theme (`BRAND_SCALE`) and Plotly (`COLORWAY`).

To rebrand, change both and restart. Charts pick up the colors through the "schwab" Plotly
template (`theme/plotly_template.py`).

Font: `--font-sans` in `theme.css` and `FONT_FAMILY` in `tokens.py`. The stack matches React
(`Inter, 'Helvetica Neue', Arial`, no web font loaded). For a licensed brand font, add an
`@font-face` at the top of `theme.css` (files in `assets/fonts/`) and put its name first in both.

The Schwab logo and the icons (dash-iconify, lucide set) load from CDNs, so the UI needs internet
access for them (`docs/port_gaps.md` A1, D6).

## The transition workspace

The backend drives the workspace. Every action (a chip, a canvas button, free text, an upload,
Plaid, a click on an earlier step) makes one API call and gets back a `ChatTurn`. The page then
re-renders the header stepper, the chat thread, the quick-reply chips and the canvas from that
turn. The canvas comes from `ui_payload.type` through `components/canvas/REGISTRY`.

### Adding a canvas (step) type

1. Create `components/canvas/my_type.py` with `render(turn, extra) -> component(s)`. Read from
   `turn["ui_payload"]["data"]`. Use `common.header(state, title, lede)` for the
   "Step N of 6" header.
2. Register it in `components/canvas/__init__.py`: `REGISTRY["my_type"] = my_type.render`.
3. Buttons that answer the guide: `common.act(reply_id, label)` (id `{"type": "ws-act", "id": reply_id}`)
   sends that quick reply, with no new callback needed. Use `common.reply_actions(turn)` to show
   every reply the backend offers.
4. Any other control: give it a dict id `{"type": "ws-<name>", "id": "c"}` and handle it in
   `callbacks/transition.py` with `ALL` wildcards, so the callback is valid when the control isn't
   on screen. Add a branch to `converse()` if it should advance the conversation.
5. If the canvas needs data that isn't in the ChatTurn, fetch it in `_extra()` (API calls only,
   never computed here).
6. Map new backend states to a step in `components/stepper.py` (`STATE_STEP`, `STEP_BACK_TARGETS`).

## Tests

```bash
uv run pytest -q tests/test_mock_backend.py   # mock API shapes + both chat paths
uv run pytest -q tests/e2e                    # Playwright demo flow; needs the UI running on :8050
uv run ruff check .
```

`tests/e2e/test_demo_flow.py` signs in, starts a transition from the book and walks every step the
backend asks for (dispatching on the canvas's `data-state`). It also reloads mid-flow, optimizes,
approves, downloads the CSV and PDF, and checks the event on the client page. Two more tests cover
the 401 redirect and the "transition not found" state. It works in mock and live mode; `DASH_URL`
points it elsewhere. One-time setup: `uv run playwright install chromium`.

Visual parity with the React reference (React dev server on `:3000`, Dash on `:8050`):

```bash
uv run python -m tests.visual.shoot book / / --auth     # → .screens/book-1440-{react,dash}.png
uv run python -m tests.visual.diff book                 # % differing pixels + diff image
```

## Docs

- `../docs/port_plan.md`: how the port was planned and the screen order
- `../docs/port_gaps.md`: every intentional difference from the React design
- `../docs/backend_issues.md`: backend gaps found while porting (and decisions, e.g. B5)
