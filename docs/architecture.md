# Architecture

Transition Studio is an internal prototype of an AI-guided model-transition platform for RIA
advisors. It runs on **synthetic data only**. Analytics are **simulated**
(`data_source: "mock_random"`). Nothing here is tax or investment advice.

## Layers

```
            ┌──────────────────────────── FastAPI (app/api) ─────────────────────────────┐
  HTTP ───► │ auth · book · clients · accounts/events · models · transitions · ingest    │
            └───────┬────────────────────────────────────────────────────────────────────┘
                    │ Pydantic contract (app/schemas) — stable, versioned under /api/v1
            ┌───────▼──────────── services (app/services) ────────────────────────────────┐
            │ PortfolioService  ModelService  TransitionService  IngestService  approval │
            └──┬──────────────┬───────────────┬────────────────┬─────────────────────────┘
               │              │               │                │
     ┌─────────▼───┐  ┌───────▼──────┐  ┌─────▼─────────┐  ┌───▼──────────────────────┐
     │ analytics   │  │ optimizer    │  │ ingest        │  │ agent                    │
     │ provider    │  │ cvxpy QP,    │  │ pdfplumber,   │  │ state machine, tools,    │
     │ (random |   │  │ lot relief,  │  │ normalizer,   │  │ LLM adapter (Claude |    │
     │  aladdin)   │  │ tax netting  │  │ Plaid gateway │  │ mock), number guard      │
     └─────┬───────┘  └──────────────┘  └───────────────┘  └──────────────────────────┘
           │
     ┌─────▼──────────── data (app/db) ─────────────────────────────────────────────────┐
     │ SQLAlchemy models · seed · synthetic market · catalog JSON → DB · sample PDFs    │
     └──────────────────────────────────────────────────────────────────────────────────┘
```

| Package | Role |
|---|---|
| `app/core` | Settings (env / `.env`), mock JWT auth, structured JSON logging with request IDs |
| `app/domain` | Pure, framework-free domain objects, tax arithmetic and construction primitives (`mypy --strict`) |
| `app/analytics` | `AnalyticsProvider` interface, `RandomAnalyticsProvider`, `AladdinAnalyticsProvider` stub, roll-ups (`mypy --strict`) |
| `app/optimizer` | Transition optimizer, frontier, glide path, lot relief, full-transition estimate (`mypy --strict`) |
| `app/ingest` | PDF parser, row normalizer and validator, Plaid gateway (sandbox and mock) |
| `app/agent` | Conversation states, intents, tools, LLM adapter, number guard, engine |
| `app/services` | Business rules joining DB, provider, optimizer and agent; no HTTP |
| `app/api` | Thin routers: validation, auth, ownership, status codes |
| `app/db` | ORM models, sessions, synthetic market, seed, model catalog, sample PDFs |

## Data model

```
Advisor ─┬─ User (login)
         └─ Client (household; tax profile: federal ST/LT + state rates)
               └─ Account (type, custodian, target model, cash, drift tolerance)
                     ├─ Lot (ticker, qty, cost basis, acquired date, locked, source, basis_unknown)
                     └─ ManagementEvent (transition | rebalance | tax_loss_harvest | cash_flow |
                                         model_change) ─ EventTrade
Security (300 synthetic stocks + catalog products/ETFs)
ModelPortfolio ─ ModelHolding           (synced from data/models/target_models.json)
Transition (guided session: state + JSON data: path, history, preview, target, setup, results)
RegimeLabel (optional per-advisor date → regime)
```

SQLite by default. Set `DATABASE_URL` to use Postgres (SQLAlchemy 2.0, nothing SQLite-specific
except the FK pragma).

## Synthetic market

`app/db/synthetic_market.py` builds 300 names across 11 sectors with market cap, yield and value,
quality, profitability and momentum scores. It simulates 5 years of daily prices from a factor
model: market, plus 11 sector factors, plus 5 style factors, plus idiosyncratic noise. The
market's drift is pinned so every seed gives a plausible path, and a volatility-drag offset keeps
the median stock from decaying. Everything is deterministic from `SYNTHETIC_SEED` and
`AS_OF_DATE` (2026-10-30), regardless of the wall clock.

## Target-model catalog (editable)

`data/models/target_models.json` lists **products** (currently placeholder Schwab ETFs) and
**models** (weights over products). It is validated on load: weights sum to 1, and every
holding is a listed product. It is synced into the DB at seed time and on API startup, so
editing the JSON and restarting is enough.

There is no real ETF data, so each product is simulated by a **proxy rule** over the synthetic
universe (`large_cap`, `large_value`, `dividend`, …). All TE, tax and statistics use
**look-through** stock weights: product weights × the proxy's constituent weights.

## Analytics provider

`AnalyticsProvider` is the only source of analytics numbers. `ANALYTICS_PROVIDER=random|aladdin`
selects the implementation. Callers never branch on the provider; the only visible difference
is `data_source`.

| Method | Random provider (today) |
|---|---|
| `get_prices`, `get_risk_model` | Synthetic prices; factor model fitted to synthetic returns, PSD; funds via look-through `E (BFBᵀ+D) Eᵀ`, with the factor structure exposed for the optimizer |
| `get_ex_ante_te` | **Exact** risk-model TE of holdings vs target (the same number the optimizer uses) |
| `get_tracking_error_history` | Simulated daily path anchored on the account's events, ending at today's exact ex-ante TE; rolling 63/252-day RMS |
| `get_tax_history` | Aggregated from the account's (synthetic) events; losses netted |
| `get_aum_history` | Today's shares × price history + cash, backing out later cash flows |
| `get_exposures` | Look-through sector, security and factor weights vs target; concentration; yield; beta |
| `get_model_stats`, `get_regime_performance` | Backtest of the model's look-through weights on synthetic returns |

Book and client roll-ups (`app/analytics/aggregate.py`) are built from the same per-account
numbers, so the book always equals the sum (or AUM-weighted average) of its clients.
`AladdinAnalyticsProvider` raises `NotImplementedError`, with TODOs marking each Aladdin call.
Planned: Bloomberg for market data (real companies + all Schwab products) and Aladdin for portfolio
analytics (asset allocation, stress tests), behind one composite provider
(see [`data_roadmap.md`](data_roadmap.md)).

## Optimizer

`docs/optimizer.md` has the math exactly as implemented. In summary:

- It is a convex QP that minimizes ex-ante TE² plus small cost penalties.
- Decision variables: the fraction of each lot sold, and purchases of target products.
- Constraints:
  - a tax budget (two linear constraints that upper-bound the exact US-netted tax) or a net-gain budget;
  - locked lots are never sold;
  - a cash buffer is kept, with no shorts or leverage;
  - the wash-sale guard applies;
  - optional per-name caps and sector bands.
- Post-processing: max-names, min-trade, whole-share rounding, and lot relief (optimizer, tax-optimal or HIFO).
- If a problem is infeasible, constraints are relaxed in order: min-trade, then sector bands, then cash buffer.
- Each result explains what drives the remaining TE (locked lots, the budget, wash-sale holds).
- Speed: 300 names and 1,000 lots in about 0.2 s.

## Ingestion

```
PDF ──► pdfplumber tables ──► column mapping ──► normalize + validate ──┐
         │ (confidence < 0.75 or no table)                              ├─► preview (stored on the
         └──► LLM extraction (Claude: PDF document → structured JSON; ──┘   transition; nothing
              demo: rule-based line parser)                                 committed)
Plaid ──► holdings + investment txns ──► rebuild lots (FIFO) ──► flag basis/date unknown ─┘
preview ──► advisor edits / excludes / locks ──► POST /ingest/{id}/confirm ──► lots
```

Validation produces per-row issues (`error` blocks the commit, `warning` doesn't) and a
confidence score. Missing basis or dates block the commit unless the advisor uploads a lot file
or accepts `assume_average_cost`. The Plaid access token is used once and never stored.

## Guided conversation

`app/agent/engine.py` is a **deterministic state machine** (`app/agent/states.py`):

```
INGEST_CHOICE → INGEST_REVIEW → TARGET_KNOWLEDGE ─┬─ knows → TARGET_PICK_LIST ─────┐
                                                  └─ help  → Q_OBJECTIVE           │
                                                           → Q_CONSTRUCTION*       │
                                                           → TARGET_COMPARE ───────┤
                       TARGET_CONFIRM ◄──────────────────────────────────────────┘
                       → TRANSITION_SETUP → TRANSITION_RESULTS → TRANSITION_APPROVE → DONE
* skipped automatically when the catalog offers only one construction for the objective
```

The LLM has exactly three jobs:

1. **Interpret** free text into a structured `Intent` from the state's allowed list (Claude
   structured output, or offline rules). Below 0.75 confidence the engine asks the advisor to
   confirm before acting.
2. **Phrase** templated messages.
3. **Answer questions** with read-only tools (`get_account_summary`, `list_models`,
   `compare_models`, `te_to_model`, `estimate_transition_tax`, `explain_result`).

The engine itself calls the state-changing tools (`run_optimization`, `run_frontier`,
`lock_lots`).

**Number guard** (`app/agent/guard.py`): any LLM-written text containing a number that cannot be
traced to tool output or the template is discarded. Rounding is allowed only at the precision
shown. Going back clears data owned by later states. Approval applies the trades to the
(synthetic) account, sets its target, and records a `transition` event with the full trade list.

LLM: `LLM_PROVIDER=anthropic` with `DEMO_MODE=false` uses Claude through the official SDK
(`LLM_MODEL`, default `claude-opus-5-5`, with server-side refusal fallback). Otherwise
`MockLLM` runs offline and labels itself `llm_provider: "mock"`.

## Cross-cutting

- **Auth:** mock JWT (HS256) and bcrypt; every query is scoped to the user's advisor. Other advisors' ids return 404.
- **Logging:** JSON lines with request id, method, path, status and timing. No bodies, query values or names (no PII).
- **CORS:** `CORS_ORIGINS` (comma-separated).
- **Disclaimers:** every recommendation payload and export carries "Illustrative, for advisor review. Not tax or investment advice."; analytics carry `data_source`.

## Decisions log

| # | Decision | Why |
|---|---|---|
| 1 | Fixed as-of date 2026-10-30 | Reproducible demo |
| 2 | Market drift pinned in the generator | A random 5-year bear market made 75% of lots losers |
| 3 | Taxes saved = losses × blended rate + gains deferred × LT rate (history); full-transition tax − plan tax (approvals) | The spec says only "× rate" |
| 4 | Ex-ante TE always exact from the risk model (option b); history simulated but ending on it | Account pages and transition screens agree |
| 5 | Drift tolerance 1.5% kept | Advisor choice; statuses are mocked |
| 6 | Catalog = 2 placeholder Schwab-ETF models in JSON | Advisor choice; replaces 6 synthetic models |
| 7 | Tax constraint = two linear upper bounds on exact netted tax | Exact netting is non-convex; the bounds guarantee tax ≤ budget |
| 8 | Cost weight κ = 0.02 | Keeps costs as tie-breakers instead of dominating TE² |
| 9 | Wash sale: hold the loss lot back rather than block the buy; ETFs containing a sold stock are not "substantially identical" | Standard industry treatment |
| 10 | Buys only into target products | Clean trade lists |
| 11 | Average-cost assumption: basis = today's value, date = as-of − 366 days | Explicit, flagged; understates tax (documented) |
| 12 | Transitions always start at INGEST_CHOICE ("use current holdings" option) | Every flow follows the spec path |
| 13 | Approval applies trades to the synthetic account | Account and book pages reflect the transition |
