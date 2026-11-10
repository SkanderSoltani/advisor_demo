# Port plan: React (v0) → Plotly Dash

Source: `reference/react-ui/`, extracted unchanged from `~/Desktop/vise/transition-studio.zip`
(Next.js 16, React 19, Tailwind v4, shadcn base-nova, lucide icons).
Target: `frontend/` (Dash Pages, dash-mantine-components, dash-iconify, Plotly, dash-ag-grid),
talking to the finished backend at `/api/v1`.

## 0. What the reference actually is

The React app is a **high-fidelity visual mockup**, not a working client:

| Area | In the React app | Implication for the port |
|---|---|---|
| Design tokens | Real: `app/globals.css` `:root` + `@theme` (no `tailwind.config`; Tailwind v4) | Copy exactly → `theme/tokens.py`, `assets/theme.css` |
| Login | Real form; mock login | Port fully |
| Client book | KPI row and client table read the mock API; **chart numbers are hard-coded** (`0.98%`, `$246,180`, `↓ 12 bps`, hand-drawn SVG sparklines, CSS bars) | Keep the card design; drive every value from the API |
| Client detail | Header + account selector read the mock API; **KPIs partly hard-coded** (`$58,420`, `4` rebalances); charts are CSS bars with fixed heights; timeline is 4 fixed rows | Same as above |
| Transition workspace | **Static click-through**: local `step` state, 5 hard-coded lots, fake frontier dots, fixed compare table, chat shows 2 canned messages; no `ChatTurn` | Keep the layout, copy and look; drive it entirely by `ChatTurn` from `/transitions/{id}/chat` |
| Onboard modal | Step 1 only, no save | Port the look; build step 2 and the save flow from the spec |
| Add account, event drawer, compare charts, optimize controls, trade list, review summary | Absent or placeholder | Build from the spec in the same visual language |

So parity screenshots compare **layout and visual style**. The data will differ by design: React
shows its own mock values, Dash shows API values.

## 1. Global shell and design system

| Element | React | Dash equivalent |
|---|---|---|
| Tokens | `:root` vars: brand `#00A0DF` / `#0072AE` / `#003D5C`, ink `#1A1A1A` / `#5B6670` / `#C5CBD1`, surfaces `#FFFFFF` / `#F5F7F9` / `#EBEFF2`, positive `#2E8540`, negative `#C8102E`, warning `#E8A317`; radius 12px; `shadow-card` | `theme/tokens.py` (same hex), `assets/theme.css` `:root` vars, DMC `theme` (`primaryColor` = custom 10-shade `brand` scale anchored on `#00A0DF`, `fontFamily`, `defaultRadius`) |
| Font | `Inter, 'Helvetica Neue', Arial` | Same stack; Inter self-hosted in `assets/fonts/` (spec allows Charles Modern later) |
| Top bar | `h-16` navy; Schwab logo chip (CDN) + "Transition Studio" + "Prototype" pill; right: date + "AM" avatar | `html.Header` navy bar, wordmark only (**no Schwab logo** — spec rule; see §9), "Prototype" pill, date and initials **from `/auth/me`** |
| Left rail | `w-16` white rail; icons LayoutDashboard (active), Users, Activity; bottom CircleHelp, Settings2 | `html.Nav` with `DashIconify("lucide:*")` buttons; Dashboard → `/`; others inert (as in React), with tooltips |
| Footer | "Internal prototype · Synthetic data · Not for client use." centered `text-xs` | `components/footer.py` on every page |
| Buttons | primary: `bg-brand-primary text-brand-navy font-semibold h-10/11 rounded-lg`, hover → `bg-brand-primary-dark text-white`; secondary: white, `border-surface-100`, navy text | `dmc.Button` with CSS classes `ts-btn-primary` / `ts-btn-secondary` in `theme.css` (the navy-on-blue primary is non-default and must be overridden) |
| Cards | `rounded-xl border border-surface-100 bg-white shadow-card p-4/5` | `dmc.Paper(className="ts-card")` |
| Status pills | on_target green/10, drifting warning/15 + `#9A6A00` text, needs_review & onboarding negative/10 | `components/status_badge.py`, same colors; onboarding gets neutral (React has no style for it, it falls into the red branch) — logged in gaps |
| Eyebrows | `text-xs font-semibold uppercase tracking-widest text-brand-primary-dark` | `.ts-eyebrow` |
| Headings | H1 `text-3xl font-semibold tracking-tight text-brand-navy` | `.ts-h1` etc. from the spec type scale, tuned to match React's rendered sizes |
| Simulated badge | `rounded-full bg-surface-50 px-2 py-1 text-[10px] text-ink-600` "Simulated analytics" | `components/sim_badge.py`, shown when `data_source == "mock_random"` |
| Number format | `money()`: ≥1M → `$1.84M`, else `$12,345`; TE `0.72%` | `services/format.py` (one helper module) + matching AG Grid `valueFormatter`s |

## 2. Login (`/login`) — `app/login/page.tsx`

**Layout:** two columns `minmax(420px,.9fr) 1.1fr` (≥1024px); the right panel is hidden below `lg`.

| Element | Copy / behavior | Dash |
|---|---|---|
| Brand row | (logo chip) + "Transition Studio" | wordmark only |
| Eyebrow / title / lede | "Advisor workspace" · "Welcome back" · "Sign in to review client portfolios and guide their next transition." | `html` text with token classes |
| Email field | label "Email address", Mail icon, placeholder "you@firm.com", prefilled `demo@advisor.test` | `dmc.TextInput(leftSection=icon)` |
| Password field | label "Password", LockKeyhole icon, eye toggle, prefilled `demo1234` | `dmc.PasswordInput` (built-in toggle) |
| Row | "Remember me" checkbox (default on) · "Forgot password?" link (inert) | `dmc.Checkbox`, `dmc.Anchor` |
| Error | "Enter your email and password to continue." / "We couldn’t sign you in. Check your credentials and try again." in a red alert box | `dmc.Alert` styled to match, plus a DMC notification (spec) |
| Submit | "Sign in →"; loading "Signing in…" with spinner | `dmc.Button(loading=...)` |
| Demo hint | "Demo access" · "Use demo@advisor.test with password demo1234" | same |
| Footer | prototype line | same |
| Right panel | navy; two radial glows; SVG curves; ShieldCheck tile; "Precision for every transition"; "Transition client portfolios with precision."; "Minimize tracking error, control taxes, and make every recommendation easier to explain."; ticks "Tax-aware · Advisor-led · Transparent" | static `html` + `assets/login-art.svg` (the same paths) |
| Logic | redirect to `/` if a token exists; store token + user in session storage | `dcc.Store(storage_type="session")`, `dcc.Location` redirect; all other pages redirect to `/login` without a token, and on any 401 |

## 3. Client book (`/`) — `app/page.tsx`

| Element | React | Dash (data source) |
|---|---|---|
| Greeting | "Good morning, Alex" / "Your client book" / "A clear view of portfolio health and transition opportunities." | Greeting by time of day + first name from `/auth/me` |
| Primary action | "+ Onboard new client" | opens `onboard_client_modal` |
| KPI row (7 cards; 2/4/7 columns at sm/md/xl) | Clients, Accounts, Total AUM, Taxes saved YTD (green), Since inception (green), Average TE (+ "↓ 0.14% vs. prior"), Outside tolerance | `GET /book/summary`: `n_clients`, `n_accounts`, `total_aum`, `taxes_saved_ytd`, `taxes_saved_since_inception`, `avg_ex_ante_te`, `n_accounts_outside_tolerance`. The "vs. prior" delta is not in the API (gap). "Outside tolerance" is clickable and filters the grid (spec) |
| Chart card 1 | "Average tracking error" + badge · "AUM-weighted across all accounts" · "63-day ⌄" · big value · delta · sparkline · axis labels | Same chrome; big value = latest `series[-1].avg_te`; body = Plotly line + p10–p90 band (`fill="tonexty"`) + dashed target line (`drift_tolerance_te`, 1.5%); 63/252 toggle via `dmc.Select` styled as the React text button |
| Chart card 2 | "Cumulative tax impact" + badge · "Tax savings generated for the book" · "Monthly ⌄" · `$246,180` · `+$77,960 YTD` · green sparkline | `GET /book/analytics/tax-impact`: big value = last `cum_taxes_saved`; "YTD" = `book/summary.taxes_saved_ytd` (API value, no math); area + secondary lines; month → bars of period values when "Yearly" |
| Activity card | "Management activity" · "Events across the client book" · segmented 1Y / 3Y / Since inception · stacked bars (2 series) | `GET /book/analytics/activity`: stacked bars by event type + AUM line on y2; `dmc.SegmentedControl` filters the date window client-side (no new numbers) |
| Client table | "Clients" · "Monitor portfolio health and next best actions." · search "Search clients" · status select (All statuses / On target / Drifting / Needs review / Onboarding) · "Name A–Z/Z–A" toggle · columns Client name (+ type · email), Accounts, Market value, Target model, Current TE, Taxes saved YTD (green), Last rebalance, Status, ⋯ | `dash-ag-grid` (Quartz, restyled to the table look), `GET /clients?search=&status=`; row menu (View client · Add account · Start transition) via a cell renderer + `dmc.Menu`. **Email is not in the list API** (gap) |
| Onboard modal (step 1 only) | "Step 1 of 2" · "Onboard a new client" · "Add the household details to create their advisor profile." · fields: Client or household name ("e.g. Jordan Lee"), Email address ("client@example.com"), Client type (Individual / Joint household / Trust), State ("CA") · Cancel / "Continue to tax profile ↗" | `dmc.Modal` + `dmc.Stepper` (2 steps). Step 2 "Tax profile" (federal ST/LT, state, state rate) from the spec; `POST /clients`, notification, then "Add the first account now?" |
| States | (none) | skeleton KPIs/charts/grid; empty "Onboard your first client"; error + Retry |

## 4. Client detail (`/clients/<id>`) — `app/clients/[id]/page.tsx`

| Element | React | Dash |
|---|---|---|
| Header bar | navy: "← Client book" · "Transition Studio" · client name | Same top bar plus breadcrumb row (React swaps the shell; we keep the shell for consistency — gap) |
| Title block | "Client profile" · name · "{type} · Onboarded {date}" · chips "Federal ST 37%", "Federal LT 20%", "{state} state" | `GET /clients/{id}` (`tax_profile`, `metrics.first_onboarding_date`); add a state-rate chip (spec) |
| Actions | "+ Add account" (secondary) · "Start transition →" (primary) | + "Edit client" (spec) → `PATCH /clients/{id}` modal |
| Account selector | pill row: "All accounts $x" + one pill per account (nickname + value); active = navy pill | `dmc.SegmentedControl` restyled as the pill row; drives `account_id` everywhere |
| KPI row (6) | Market value, Current TE, Taxes saved YTD, Since inception, Rebalances 12m, Last rebalance | client `metrics` / account summary; "Rebalances, 12m" not in the API as trailing-12m (gap) |
| TE chart card | "Tracking error to target" · "Rolling 63-day history with target band" · "63-day ⌄" · bars | Plotly lines (63 and 252 per toggle) + target band + event markers (`events[]`) |
| Taxes saved card | "Taxes saved" · "Monthly realized impact" · TrendingDown icon · green bars | `GET …/analytics/tax-savings`: bars + cumulative line (y2) + month/year toggle |
| Management history | "Management history" · "Newest activity across selected accounts" · filter icon · rows: icon, type, "N days ago · account · trades", "+$x Tax savings" | `GET /clients/{id}/events`: icon per type (lucide), all spec fields; filter popover (type); click → `dmc.Drawer` with `GET /events/{id}` trades |
| Spec-only | Summary by year grid · Accounts grid · empty state "No management history yet" | `GET …/analytics/summary`, `GET /clients/{id}/accounts` |
| Loading | "Loading client profile…" centered | same copy + skeletons |

## 5. Add account modal (spec only)

Fields: Account type (Individual taxable · Joint · Trust · IRA · Roth IRA), Custodian, Nickname,
Target model (optional, `GET /models`). Saving calls `POST /clients/{id}/accounts`, then offers
"Import holdings and start transition", which calls `POST /transitions` and navigates to
`/transition/<id>`. Visual language: the onboard modal's.

## 6. Transition workspace (`/transition/<id>`) — `app/transition/[id]/page.tsx`

**Shell:** navy header: ← back · client name / "{account} · Transition workspace" · **6-step progress
inline in the header** (numbered circles; completed = filled blue with ✓, current = blue ring,
future = white/20) · "Exit". Body: left 38% chat (white), right 62% canvas (`max-w-4xl`).

| Element | React | Dash |
|---|---|---|
| Stepper | header buttons; completed clickable | `dmc.Stepper` restyled to the header look, **or** a custom `html` stepper if DMC can't match (decide during the port); clicking a completed step → `POST /transitions/{id}/back` with that step's first visited state |
| Chat panel | "✨ AI guide" eyebrow; assistant bubbles `bg-surface-50 rounded-xl rounded-tl-sm`; quick replies as outlined pills; input "Ask the guide anything…" with chat icon, paperclip (inert), send | `components/chat_panel.py`: `dcc.Markdown` bubbles, user bubbles (new; React has none), chips from `ChatTurn.quick_replies`, typing indicator, clientside auto-scroll (`assets/chat.js`); paperclip opens the PDF upload when the step allows it |
| Canvas header per step | "Step N of 6" eyebrow + H1 + lede | from the state → step mapping (§8) |
| Step 1 Import | "Import holdings" / "Bring in current tax lots to begin the transition analysis." · cards "Connect brokerage" ("Securely connect a custodian and sync positions and tax lots." → "Connect with Plaid →") and "Upload tax-lot PDF" ("Drop a statement here and we'll parse the holdings for review." → "Choose file →") | `canvas/ingest_choice.py`; the PDF card becomes a `dcc.Upload` drop zone; Plaid via `assets/plaid.js` + clientside callback (mock mode: 2-second simulated connect, backend mock exchange); "Use current holdings" card when `has_holdings`; demo "sample statement" chip |
| Step 2 Review | "Review lots" / "Confirm positions before selecting a target model." · "Confirm holdings →" · 3 stat tiles (Lots imported, Portfolio value, Issues remaining in warning color) · table Ticker / Shares / Cost basis / Unrealized / Term / Lock | `canvas/parse_preview.py`: AG Grid with the spec columns (+ acquired date, market value, confidence, issues), issue rows highlighted and editable; summary bar; Confirm → `POST /ingest/{id}/confirm` |
| Step 3 Choose | "Choose your target" / "Select a model aligned to this client's objective." · 3 model cards (id, objective, construction, "0.24% fee") · "Compare selected model →" | `canvas/model_list.py` (`ui_payload.data.models`); the knowledge question and objective/construction chips come from the chat |
| Step 4 Compare | "Compare models" / "See the trade-offs before optimizing the transition." · 4-column table Metric/Current/Model/Difference · "Select {model} →" | `canvas/model_comparison.py`: model cards + AG Grid metrics (highlight TE-from-current and tax cost) + sector-mix and factor charts; "Select this model" → confirm modal → chat `choose:<id>` |
| Step 5 Optimize | "Optimize transition" / "Tune the tax budget and choose the solution that fits best." · budget card ("Max tax cost", `$25,000`, slider 5k–75k, hint "A higher budget lowers expected tracking error and enables more tax-aware trades.", "Run optimization →") · "Efficient frontier" scatter with highlighted point, "Lower tax cost / Higher tax cost" | `canvas/transition_setup.py` (controls, constraints accordion, lock-lots grid → `PUT /locks`) and `canvas/transition_results.py` (frontier with clickData → re-optimize at that budget, KPI strip pre → post, sector active bars, trade grid, diagnostics callout, glide-path toggle). Slider max = `full_transition.est_tax` from the API instead of React's fixed 75k |
| Step 6 Review | "Review & export" / "Your recommended transition is ready for review." · 4 tiles (Target model, Resulting TE, Estimated tax, Trades) · Approve transition · Download CSV · Download PDF · disclaimer "Illustrative analysis for advisor review. Not tax or investment advice." | `canvas/transition_results.py` (approve mode): `dcc.Download` for `trades.csv` / `summary.pdf` (fetched server-side with the token), Approve → chat `action: approve`, then "Back to client" |

## 7. Data layer

- `services/schemas.py`: generated from `docs/openapi.json` with `datamodel-code-generator`
  (Pydantic v2). It is the source of truth for field names.
- `services/api_client.py`: the only place HTTP happens (httpx, Bearer token, typed returns). It
  raises `AuthError` on 401 (→ redirect to login) and `ApiError` otherwise (→ error + retry UI).
  `USE_MOCKS=true` routes every call to `services/mock_backend.py`.
- `services/mock_backend.py`: React's mock values and ranges (5 named clients, Alex Morgan,
  `TR-*` / `INC-*` models) expanded to the spec's mock contents, returned in the **openapi
  shapes**, seeded per id. Includes a scripted `ChatTurn` sequence for both paths.
- `docs/port_gaps.md`: every React-type vs openapi disagreement (see §9), with openapi winning.

## 8. ChatTurn → UI mapping

| Backend `state` | Step (React label) | Canvas (`ui_payload.type`) |
|---|---|---|
| `INGEST_CHOICE` | 1 Import holdings | `ingest_choice` |
| `INGEST_REVIEW` | 2 Review lots | `parse_preview` |
| `TARGET_KNOWLEDGE`, `TARGET_PICK_LIST`, `Q_OBJECTIVE`, `Q_CONSTRUCTION` | 3 Choose target | `none` / `model_list` |
| `TARGET_COMPARE`, `TARGET_CONFIRM` | 4 Compare | `model_comparison` / `model_list` |
| `TRANSITION_SETUP`, `TRANSITION_RESULTS` | 5 Optimize transition | `transition_setup` / `transition_results` |
| `TRANSITION_APPROVE`, `DONE` | 6 Review & export | `transition_results` |

The backend's own `progress` uses different labels (Holdings, Choose target, Confirm target, Set
budget, Review results, Approve). The Dash stepper shows React's six labels using the mapping
above (logged in gaps). The canvas registry lives in `components/canvas/__init__.py`
(`{type: render_fn}`); adding a step type = add a module + one dict entry.

## 9. Conflicts and gaps found so far (need a decision → see "Questions" below)

1. **Schwab logo:** React shows the Charles Schwab logo (hot-linked from a third-party CDN). The
   spec says to use the "Transition Studio" wordmark and not the Schwab logo.
2. **Hard-coded and derived numbers in React:** deltas such as "↓ 0.14% vs. prior", "↓ 12 bps
   this year" and "+$77,960 YTD" sit next to a cumulative figure. The API has no prior-period
   values, and the spec forbids computing analytics in Dash.
3. **React features absent from the spec, and vice versa:** inert left-rail icons, "Forgot
   password?" and the paperclip are kept as inert or with a sensible action. Spec-only features are
   built in React's visual language (no reference screenshot to compare against).
4. **Models in mock mode:** the spec lists 6 models (`TR-MC` … `INC-MCFA`, like React's mock), but
   the live backend serves your 2 Schwab placeholder models from the JSON catalog.
5. **Type mismatches** (openapi wins; full list goes into `docs/port_gaps.md` in step 3):
   - `BookSummary` field names (`clients` vs `n_clients`, `aum` vs `total_aum`, `average_te` in % vs decimal);
   - `/clients` returns `{total, items}` rather than an array;
   - account types `individual` / `joint` vs `individual_taxable` / `joint_taxable`;
   - client types `joint` vs `couple`;
   - TE in percent vs decimals;
   - `Client.email` and `onboarding_date` not in list rows;
   - `Model.fee` (%) vs `fee_bps`.
6. **API coverage the spec asks for** that the backend may not provide. These get verified during
   the port and logged in `docs/backend_issues.md`; I won't change the backend:
   - a model cumulative-growth series for the compare chart;
   - trailing-12-month rebalance count;
   - a client email in list rows;
   - sell "reason" tags (loss harvest / high basis).
7. **Screenshot parity:** running React needs `npm install` of its dependencies (pnpm and
   Playwright aren't installed yet). React will show its own mock data, so comparisons are
   visual and layout comparisons.

## 10. Build order (after this review)

1. Tokens → `theme/tokens.py`, `assets/theme.css`, `theme/plotly_template.py`.
2. Data layer → generated schemas, api client, mock backend, `docs/port_gaps.md`.
3. Screens in the prompt's order, each with 1440 / 1024 px Playwright screenshots of React and Dash
   compared and fixed: Login → Client book → Client detail → modals → Workspace shell →
   Import/Review → Choose/Compare → Optimize → Review & export.
4. Live wiring: `USE_MOCKS=false`, full walk, `tests/e2e/test_demo_flow.py`, error and loading
   states, downloads, `docs/backend_issues.md` if needed.
5. Root `docker-compose.yml` (backend + Dash), `make demo`, README.
