# Port gaps — React (v0) reference vs the Dash port

Where the React app and the backend contract (`docs/openapi.json`) disagree, **openapi wins**.
Where something can't be reproduced exactly in Dash, the closest equivalent is used and logged here.

## A. Decisions (reviewed with the product owner)

| # | Topic | React | Spec | Dash |
|---|---|---|---|---|
| A1 | Logo | Charles Schwab logo chip, hot-linked from `cdn.jsdelivr.net/gh/glincker/thesvg/.../charles-schwab/default.svg` | "Wordmark only, don't use the Schwab logo" | **Kept, as in React** (owner decision). Same URL, so it needs internet access; there is no local copy |
| A2 | Delta lines ("↓ 0.14% vs. prior", "↓ 12 bps this year", "+$77,960 YTD") | Hard-coded | No analytics computed in the front end | Omitted where the API has no such value. "YTD" on the tax card uses `book/summary.taxes_saved_ytd` (an API value). Requested in `backend_issues.md` |
| A3 | Models in mock mode | 6 (`TR-MC` … `INC-MCFA`) | 6 | The live catalog's 2 placeholder Schwab models, so mock and live look the same |
| A4 | Workspace step indicator | Inline in the navy header | `dmc.Stepper` at the top | React's placement (header) |
| A6 | Workspace content | Static mockup: hard-coded lots, 3 models, slider $5k–$75k, decorative frontier dots, fixed review numbers | ChatTurn-driven canvases | React's chrome, spacing and copy for each step; every value from the ChatTurn / API. Extras kept in the same visual language: "Use current holdings" banner and "sample statement" button (step 1), editable parse-preview grid with issue highlighting (step 2), question cards for help-me-choose (step 3), model cards + sector/factor charts above the metrics table (step 4), lot-lock grid and account summary (step 5), results view with trades/frontier before approval, then React's step-6 layout |
| A5 | Font | `Inter, 'Helvetica Neue', Arial` declared but Inter never loaded (renders Helvetica Neue where Inter isn't installed) | Charles Modern if licensed, else Inter | Identical stack, no web font (parity). Hook for Charles Modern in `assets/theme.css` |

## B. Data contract: React `lib/api/types.ts` vs openapi

| React type.field | openapi | Notes |
|---|---|---|
| `BookSummary.clients` / `accounts` / `aum` | `n_clients` / `n_accounts` / `total_aum` | renamed |
| `BookSummary.average_te` (percent, 0.98) | `avg_ex_ante_te` (decimal, 0.0098) | **units**: all rates and TE are decimals in the API |
| `BookSummary.drifting_accounts` | `n_accounts_outside_tolerance` | |
| — | `BookSummary.clients_by_status`, `as_of`, `data_source` | extra in the API |
| `GET /clients` → `Client[]` | `ClientList {data_source, total, items: ClientSummaryRow[]}` | wrapped |
| `Client.account_count` | `ClientSummaryRow.n_accounts` | |
| `Client.tracking_error` (percent) | `ex_ante_te` (decimal, nullable) | units; null for onboarding clients |
| `Client.last_rebalance` | `last_rebalance_date` | |
| `Client.email`, `onboarding_date`, `tax_profile` (in list rows) | only in `ClientDetail` / `ClientOut` | the React table shows "type · email" under each name; the list API has no email → only the type is shown (`backend_issues.md` B2) |
| `Client.client_type`: `individual \| joint \| trust` | `individual \| couple \| family \| trust` | "Joint household" maps to `couple` |
| `Account.account_type`: `individual \| joint \| trust \| ira \| roth_ira` | `individual_taxable \| joint_taxable \| trust \| ira \| roth_ira` | |
| `Account.tracking_error`, `unrealized_gain` | `AccountSummary.ex_ante_te`; unrealized is in `AccountDetail.unrealized.net` | |
| `AnalyticsSeries {data_source, points[{date, value, lower, upper}]}` | `BookTrackingError.series[{date, avg_te, p10, p90, n_accounts}]`, `TrackingError.series[{date, te}]`, `TaxImpact.periods[...]` | different shapes per endpoint |
| `ManagementEvent.trades` (count), `.taxes_saved`, `.type` | `EventOut.n_trades`, `est_taxes_saved`, `type` | |
| `Model {id, name, objective, construction, fee (%), holdings (count)}` | `ModelSummary {…, fee_bps, stats.n_holdings, stats.n_underlying, expected_te, target_yield, …}` | fee in bps |
| `ChatTurn` | same, plus `transition_id`, `interpretation`, `llm_provider` | |
| `Transition.turns[]` | `GET /transitions/{id}/history` items | |
| `User {id, name, email}` | `UserOut {id, email, name, role, advisor_id, firm}` | |

## C. Generator and runtime notes

| # | Issue | Handling |
|---|---|---|
| C1 | openapi declares `created_at` / `updated_at` as `date-time`; the backend emits naive timestamps (no timezone) | `services/schemas.py` is generated with `--output-datetime-class datetime` (accepts naive). Logged as backend issue B1 |
| C2 | `datamodel-codegen` needs `email-validator` for `EmailStr` | added `pydantic[email]` |

## D. Visual / behavioural differences (accepted)

| # | Where | Difference | Why |
|---|---|---|---|
| D1 | Book, activity chart | React's chart renders blank (bug in the reference); Dash renders the data | the API has the data |
| D2 | Book charts | Shorter (React's fixed 48px placeholders vs. real Plotly charts); TE chart shows a p10–p90 band | real data |
| D3 | AG Grid tables | Fixed row heights; React's HTML table rows wrap at 1024px | AG Grid virtualization |
| D4 | Onboarding modal | Client-type pills use the neutral style; phone + notes added to step 1 | `ClientCreate` has these fields |
| D5 | Client detail KPI | "Rebalances, YTD" instead of "12m" | backend B7 |
| D6 | Icons | dash-iconify (lucide set) fetches icons from the Iconify API at runtime | needs internet, like the logo (A1) |
| D7 | Plaid | Mock mode: no Plaid UI (the backend returns a mock public token, exchanged server-side). Sandbox mode: `assets/plaid.js` loads Link from `cdn.plaid.com` | Plaid's terms require the CDN script |
| D8 | Client type | `couple` shows as "Joint" in lists, "Joint household" in forms | React wording |
| D9 | Model fee | Shown as a percent ("0.03% fee", React style); API sends `fee_bps` | formatting only |
| D10 | Parse-preview grid | Market value and per-row confidence columns dropped so the grid fits the 896px canvas; overall confidence is in the summary line and low-confidence rows are flagged as issues | width |
| D11 | Workspace thread | User actions show as a short user bubble (e.g. "Confirm holdings"); reloading rebuilds the thread from `/history` | React's thread is static |
