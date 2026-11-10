# Backend issues found while porting the front end

The front end works around each of these without changing the backend; each needs the product
owner's review before the backend is touched.

| # | Severity | Issue | Front-end workaround |
|---|---|---|---|
| B1 | Low | `TransitionOut.created_at` / `updated_at` are declared `date-time` in openapi but returned without a timezone (`2026-11-02T23:17:34`). Strict clients (e.g. pydantic `AwareDatetime`) reject them. Fix: return UTC with `Z` (timezone-aware columns or serialize with `tz=UTC`). | Schemas generated with naive datetimes |
| B2 | Low | The client list rows (`ClientSummaryRow`) have no `email`; the React design shows "type · email" under each client name. | Show the type only |
| B3 | Low (enhancement) | No prior-period values for KPI deltas ("↓ 0.14% vs. prior", "↓ 12 bps this year") shown in the React design. Would need e.g. `avg_ex_ante_te_prior` on `/book/summary`, or a delta on the TE series. | Deltas omitted |
| B4 | Low | `POST /transitions/{id}/chat` with an empty body (the only way to get the current `ChatTurn` with its `ui_payload`, e.g. after a reload) **logs the assistant message to history again**, so `GET /history` grows a duplicate on every reload. Fix: a side-effect-free `GET /transitions/{id}/turn`, or don't log when the body is empty. | The thread collapses consecutive identical assistant messages |
| B5 | Medium → **decided** | The chat path can only set the budget and the cash buffer; `Constraints` and `glide_path_budgets` are only on `POST /optimize`, which doesn't advance the conversation. **Owner decision (2026-11-02):** the guided optimization runs with a reasonable default set, and settings get exposed as we go. **Done:** `app/agent/engine.py` `DEFAULT_CONSTRAINTS` = cash buffer 0.5%, trading cost 5 bps, no turnover penalty, **min trade $250**, whole shares, optimizer-chosen lots; no max weight or sector band (the ETF-only models would become infeasible). Anything set in the chat (e.g. the cash buffer) overrides the defaults. API contract unchanged; backend tests pass. Open: glide path and the other constraints in the workspace. | The results screen shows the settings actually used (from `OptimizationResult.constraints`); the mock mirrors the defaults |
| B6 | Low (enhancement) | `/compare` has no current-portfolio return, volatility, Sharpe, drawdown or expected TE, so the "Current" column in React's compare table can only show dividend yield and holdings. | Other "Current" cells show "—"; React's "Difference" column omitted (A2) |
| B7 | Low (enhancement) | No trailing-12-month rebalance count: the React KPI says "Rebalances, 12m"; the API's client summary only has year buckets. | KPI relabelled "Rebalances, YTD" |
| B8 | Low (enhancement) | No book-level drift tolerance on `/book/summary` (the tolerance is per account). React's book TE chart draws a tolerance line. | Band (p10–p90) and average only |
| B9 | Info | `RealizedSummary.budget_used_pct` is a 0–100 percentage while every other rate in the API is a decimal. Not wrong, but inconsistent. | Divided by 100 for display |
