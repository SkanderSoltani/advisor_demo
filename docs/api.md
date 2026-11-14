# API guide (v1) — for the front-end team

The machine-readable contract is **`docs/openapi.json`**, and the interactive docs are at
**`/docs`** on a running server. This page covers the conventions and the flows.

## Conventions

- Base path `/api/v1`. JSON everywhere except uploads (multipart) and exports (CSV/PDF).
- **Auth:** `POST /auth/login {email, password}` → `{access_token, user}`. Send
  `Authorization: Bearer <token>` on every other call; 401 otherwise. Demo login:
  `demo@advisor.test` / `demo1234`.
- **Units:**
  - Rates, weights, TE, yields and turnover are **decimals** (0.0415 = 4.15%).
  - Money is USD.
  - Dates are ISO `YYYY-MM-DD`; period keys are `YYYY-MM` or `YYYY`.
- **`data_source`** is on every analytics payload (`"mock_random"` today). Show a
  "Simulated analytics" badge when it isn't a production source.
- **Disclaimers:** comparison, optimization, frontier and chat recommendations include
  `disclaimer` / footer text. Keep it visible.
- **Errors:** FastAPI's `{"detail": ...}`. Validation errors are 422 with field locations.
  Confirm errors return `{"detail": {"message", "rows": [{row_id, ticker, issues}]}}`. Other
  codes: 404 not found or not yours, 409 conflict (e.g. confirming twice, going back after
  approval), 413 upload too large, 502 Plaid failure.
- **Request ids:** send `X-Request-ID` to correlate; it is echoed back in the response header.

## Endpoints

| Area | Method & path | Notes |
|---|---|---|
| Auth | `POST /auth/login`, `GET /auth/me` | |
| Book | `GET /book/summary` | Totals plus `clients_by_status` |
| | `GET /book/analytics/tracking-error?window=63\|252` | AUM-weighted avg + p10/p90 band |
| | `GET /book/analytics/tax-impact?granularity=month\|year` | Period and cumulative values |
| | `GET /book/analytics/activity?granularity=month\|year` | Events by type + AUM |
| Clients | `GET /clients?search=&status=` | Summary rows |
| | `POST /clients`, `GET/PATCH /clients/{id}` | Onboard / detail / edit (partial tax profile ok) |
| | `GET/POST /clients/{id}/accounts` | New accounts start empty |
| | `GET /clients/{id}/analytics/{tracking-error\|tax-savings\|summary}?account_id=` | |
| | `GET /clients/{id}/events?type=&account_id=&from=&to=` | Newest first |
| Accounts | `GET /accounts/{id}` | Holdings, lots, unrealized ST/LT split |
| | `GET /accounts/{id}/analytics/{tax-history\|tracking-error\|exposures}` | |
| Events | `GET /events/{id}` | With full trade list |
| Models | `GET /models?objective=&construction=`, `GET /models/{id}` | Stats, holdings, regime perf |
| | `POST /models/compare {model_ids, account_id}` | **Key comparison**: TE from current + full-transition tax |
| Regimes | `POST /analytics/regimes` (CSV `date,regime`), `DELETE /analytics/regimes` | Optional |
| Transitions | `POST /transitions {client_id, account_id}`, `GET /transitions/{id}` | |
| | `POST /transitions/{id}/chat {message?, quick_reply?, action?}` → `ChatTurn` | Guided flow |
| | `POST /transitions/{id}/back {to_state}`, `GET /transitions/{id}/history` | |
| | `PUT /transitions/{id}/locks {lot_ids}` | Replaces locks; clears results |
| | `POST /transitions/{id}/optimize`, `POST /transitions/{id}/frontier` | Direct (non-chat) use |
| | `GET /transitions/{id}/trades.csv`, `GET /transitions/{id}/summary.pdf` | Last optimization |
| Ingest | `POST /ingest/pdf` (multipart `file`, `transition_id`) → `ParsePreview` | ≤10 MB |
| | `POST /ingest/plaid/link-token`, `POST /ingest/plaid/exchange {public_token, transition_id}` | Mock mode returns `mock_public_token` |
| | `POST /ingest/{transition_id}/confirm {rows, mode, cash?, assume_average_cost}` | Commits lots |

## The guided flow (driving the UI from `ChatTurn`)

Every chat response looks like this:

```json
{
  "transition_id": "trn_…", "state": "TRANSITION_SETUP",
  "assistant_message": "markdown…",
  "quick_replies": [{"id": "budget:tax:0", "label": "$0 tax (harvest only)"}],
  "ui_payload": {"type": "transition_setup", "data": {…}},
  "allowed_actions": ["back", "restart"],
  "progress": {"step": 4, "total": 6, "label": "Set budget"},
  "interpretation": {"intent": "set_budget", "confidence": 0.9, "slots": {…},
                     "needs_confirmation": false},
  "llm_provider": "mock"
}
```

Render `assistant_message`, show `quick_replies` as buttons (send back `{"quick_reply": id}`),
and draw the panel for `ui_payload.type`:

| `ui_payload.type` | Panel | Data |
|---|---|---|
| `ingest_choice` | Upload / Plaid / "use current holdings" | `pdf_upload_url`, `has_holdings`, `plaid.{link_token, exchange_url}` |
| `parse_preview` | Editable lot table with issues and confidence | a full `ParsePreview` |
| `model_list` | Catalog cards | `models[]` |
| `model_comparison` | Side-by-side comparison | a full `ComparisonPayload` |
| `transition_setup` | Budget slider, lock picker, cash buffer | `full_transition`, `account`, `setup`, `locks_url` |
| `transition_results` | Trades, before/after, frontier chart, exports | `optimization`, `frontier`, `exports`, `event_id` |
| `none` | Chat only | |

Typical sequence:

1. `POST /transitions` → `POST …/chat {}` renders the first turn.
2. **Holdings.**
   - Upload: `POST /ingest/pdf`, then `POST …/chat {}` to render the preview.
   - Plaid: run Link with `link_token`, then `POST /ingest/plaid/exchange`, then `POST …/chat {}`.
   - The table UI can call `POST /ingest/{id}/confirm` with edited rows, or use the chat's
     confirm quick replies.
3. Target questions, then comparison, then confirm (all via chat).
4. Setup: quick replies like `budget:tax:20000`, or free text ("don't pay more than 20k in
   taxes", "don't sell MSFT", "keep 2% cash"). Choosing a budget runs the optimizer and frontier.
5. Results: re-run with other budgets, ask "why isn't TE zero?", then `approve`.
6. Approve: export via `exports.trades_csv` / `exports.summary_pdf`, then `{"action": "approve"}`
   to record the transition.

Free text with `interpretation.needs_confirmation = true` comes back with
`confirm_pending` / `cancel_pending` quick replies. Questions don't change the state.
`POST …/back {to_state}` works for any earlier visited state and clears later results.
`{"action": "restart"}` starts over.

## Mocking without the backend

The main payloads in `openapi.json` carry full examples: `ChatTurn`, `ParsePreview`,
`ComparisonPayload`, `OptimizationResult`, `ClientList` and `TrackingError`. Every other field
is typed and described, so a mock server such as Prism (`prism mock docs/openapi.json`) can
generate the rest. For realistic data, run the backend in demo mode; it needs no external
services.
