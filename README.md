# Transition Studio

An internal prototype of an AI-guided direct-indexing / model-transition platform for RIA
advisors. It is a Python service exposing a versioned REST API (`/api/v1`), plus a Plotly Dash
front end (`frontend/`) ported from the v0 React design.

> **Synthetic data only. Analytics are simulated (`data_source: "mock_random"`).
> Illustrative, for advisor review. Not tax or investment advice.**

## Run the whole demo (backend + UI)

```bash
scripts/demo.sh          # Docker Compose if installed, otherwise both servers locally via uv
# or: make demo          (needs the Xcode command-line tools on macOS: xcode-select --install)
```

UI **http://localhost:8050** · API **http://localhost:8000/docs** · login **`demo@advisor.test` / `demo1234`**.
See [`frontend/README.md`](frontend/README.md) for the front end on its own (including mock mode).

## Deploy on Railway

One service: connect the GitHub repo, add `JWT_SECRET`, generate a domain. Details in [docs/deploy_railway.md](docs/deploy_railway.md).

## Quick start: backend only (offline demo)

```bash
cd transition-studio
uv sync                                            # Python 3.11+
cp .env.example .env                               # DEMO_MODE=true: Plaid + LLM run offline
uv run python scripts/generate_synthetic_data.py   # 300 stocks × 5y daily prices (deterministic)
uv run python scripts/seed_demo.py                 # resets the DB: 9 households, 17 accounts, history, sample PDFs
uv run uvicorn app.main:app --reload               # http://localhost:8000/docs
```

Login: **`demo@advisor.test` / `demo1234`**. If you don't use uv, `.venv/bin/python` works the
same way once dependencies are installed.

Docker: `docker compose up --build` starts the API (`:8000`) and the Dash UI (`:8050`); the API seeds
on the first start only and keeps its data in a volume.

## What's in the demo

- **Book:** 9 households (one onboarding with a legacy portfolio and no history), 17 accounts,
  about 1,750 tax lots, and about 300 management events over 1–3 years.
- **Target models:** two placeholder Schwab-ETF models in **`data/models/target_models.json`**
  (see below).
- **Sample statements:**
  - `data/synthetic/sample_statement.pdf` (clean table);
  - `data/synthetic/sample_statement_messy.pdf` (no grid, wrapped text, one ticker typo; exercises the extraction fallback).
- **Guided transition:** ingest → choose a target (with help) → set a tax budget in plain
  English → review trades, frontier and explanations → approve. The approval is recorded in the
  account history.

Try the guided flow from a shell (server running):

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"demo@advisor.test","password":"demo1234"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"
TID=$(curl -s localhost:8000/api/v1/transitions -H "$H" -H 'content-type: application/json' \
  -d '{"client_id":"cli_009","account_id":"acc_017"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["transition_id"])')
chat() { curl -s localhost:8000/api/v1/transitions/$TID/chat -H "$H" -H 'content-type: application/json' -d "$1" \
  | python3 -c 'import sys,json;t=json.load(sys.stdin);print("\n["+t["state"]+"]");print(t["assistant_message"]);print([q["id"] for q in t["quick_replies"]])'; }
chat '{"quick_reply":"use_existing"}'
chat '{"message":"not sure, help me choose"}'
chat '{"message":"total return"}'
chat '{"quick_reply":"choose:SCHWAB-TR"}'
chat '{"message":"yes"}'
chat '{"message":"I would rather not pay more than 25k in taxes"}'
chat '{"message":"why is tracking error not zero?"}'
chat '{"quick_reply":"approve"}'
chat '{"action":"approve"}'
```

## Target models (editable)

`data/models/target_models.json` holds **products** (e.g. Schwab ETFs) and **models** (weights
over products, which must sum to 1). The two current models are **placeholders**: real Schwab
tickers with illustrative weights, not Schwab-published models. Edit the file and restart the
API; it is re-validated and synced into the database on startup.

Products have no real market data, so each one is simulated from the synthetic universe by its
`proxy` rule: `broad_market`, `large_cap`, `mid_cap`, `small_cap`, `large_growth`,
`large_value` or `dividend`. Anything else falls back to `broad_market`. All TE, tax and
statistics are computed on look-through stock weights.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_MODE` | `true` | Plaid and LLM use offline mocks |
| `DATABASE_URL` | SQLite in `data/` | Any SQLAlchemy URL (e.g. Postgres) |
| `ANALYTICS_PROVIDER` | `random` | `aladdin` is a stub (raises "not connected") |
| `LLM_PROVIDER` / `LLM_MODEL` | `mock` / `claude-opus-5-5` | `anthropic` + `DEMO_MODE=false` uses Claude (official SDK; credentials from `ANTHROPIC_API_KEY` or an `ant auth login` profile) |
| `LLM_SERVER_FALLBACK` | `true` | Server-side refusal fallback; disable for models that don't support it |
| `PLAID_CLIENT_ID` / `PLAID_SECRET` | unset | Plaid **Sandbox** when set and `DEMO_MODE=false` |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated front-end origins |
| `JWT_SECRET` | demo value | Mock auth only — change it anyway |
| `SYNTHETIC_SEED` / `AS_OF_DATE` | `20240501` / `2026-10-30` | Reproducibility: everything is computed as of this date |
| `MODELS_FILE` | `data/models/target_models.json` | Target-model catalog |

## Development

```bash
uv run pytest                                   # 160+ tests, incl. the end-to-end happy path
uv run ruff check . && uv run ruff format --check .
uv run mypy app                                 # strict on domain/, analytics/, optimizer/
uv run python scripts/export_openapi.py         # → docs/openapi.json
uv run python scripts/make_sample_pdf.py        # re-render the clean sample statement
```

Intel macOS: `scs` and `cryptography` are capped (`[tool.uv] constraint-dependencies`) at the
last releases with x86_64 macOS wheels.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — layers, data model, providers, decisions log
- [`docs/optimizer.md`](docs/optimizer.md) — the optimizer math exactly as implemented
- [`docs/api.md`](docs/api.md) — API conventions and the guided-flow contract for the front end
- [`docs/openapi.json`](docs/openapi.json) — machine-readable contract (`/docs` when running)
- [`docs/data_roadmap.md`](docs/data_roadmap.md): moving from synthetic data to Bloomberg (market
  data: real companies + all Schwab products) and Aladdin (asset allocation, stress tests)
- [`docs/agent_roadmap.md`](docs/agent_roadmap.md): AI guide plans (position swaps, issue detection)
- [`docs/port_plan.md`](docs/port_plan.md), [`docs/port_gaps.md`](docs/port_gaps.md),
  [`docs/backend_issues.md`](docs/backend_issues.md) — the React → Dash port

## Status

| Milestone | Scope | Status |
|---|---|---|
| 1 | Scaffold, config, DB models, synthetic data, seed | ✅ |
| 2 | AnalyticsProvider (random + Aladdin stub); book, client, account and event endpoints | ✅ |
| 3 | Target-model catalog (JSON, Schwab-product placeholders) + comparison | ✅ |
| 4 | Optimizer, frontier, glide path, trade export (CSV/PDF) | ✅ |
| 5 | Ingestion: PDF (table + LLM fallback), Plaid sandbox/mock, preview + confirm | ✅ |
| 6 | Guided conversation: state machine, LLM adapter (Claude + offline mock), number guard, approval | ✅ |
| 7 | End-to-end happy path, OpenAPI export, docs | ✅ |
| UI | Dash port of the React design: login, client book, client detail, onboarding modals, transition workspace; live-backend e2e test; Compose + demo script | ✅ |

### Known limitations

- The real Claude and Plaid Sandbox integrations are written against the official SDKs and
  tested with fakes, but have not run against the live services in this environment.
- The Docker images (API and UI) have not been built here (no Docker available during
  development); `scripts/demo.sh --local` and the UI's production server (gunicorn) were tested.
- Front-end gaps and open backend items: [`docs/port_gaps.md`](docs/port_gaps.md),
  [`docs/backend_issues.md`](docs/backend_issues.md).
- Analytics history, events and statuses are simulated. Only the optimizer, tax arithmetic and
  look-through risk calculations are real computations, on synthetic data.
