# Data roadmap: from synthetic data to Bloomberg + Aladdin

**Status today:** every price, ticker and return is synthetic. `app/db/synthetic_market.py`
invents 300 companies and simulates 5 years of prices; the risk model is fitted to those simulated
returns, and the Schwab ETFs in `data/models/target_models.json` are placeholders whose holdings
also come from the synthetic universe.

**Plan (owner decisions, 2026-11-02):**

- **Bloomberg (BBG) provides data points:** prices, returns, fund holdings and reference and
  fundamental data for **real companies and the full Schwab product range**, used to build the
  risk model.
- **Aladdin provides portfolio analytics** on top: asset allocation, stress tests, and further
  risk and exposure analytics for the client portfolios.

## Who provides what

| Area | Source | Examples |
|---|---|---|
| Market and reference data | **Bloomberg** | Prices, total returns, dividends, GICS sectors, market cap, fundamentals, ETF/fund holdings for look-through |
| Risk model inputs | **Bloomberg** data → our factor model (or Aladdin's risk model, see below) | Factor returns, loadings, specific risk |
| Portfolio analytics | **Aladdin** | Asset allocation (asset class, region, sector, style), stress tests and historical/hypothetical scenarios, risk decomposition, factor exposures, VaR |
| Tax lots, transitions, optimizer, tax maths | **This app** | Lot relief, tax budget, trades, approvals |

## What changes

| Piece | Today | With Bloomberg |
|---|---|---|
| Universe | 300 invented tickers | Real US equities (e.g. Russell 3000 / S&P 1500) + **all Schwab ETFs and mutual funds** |
| Prices / returns | Simulated daily path | BBG daily prices and total returns (`PX_LAST`, `DAY_TO_DAY_TOT_RETURN_GROSS_DVDS`) |
| Fund look-through | Synthetic constituents | BBG fund holdings (`FUND_HOLDINGS` / ETF baskets), refreshed regularly |
| Sector / style data | Generated scores | GICS sector, market cap, value / quality / momentum inputs from BBG fundamentals |
| Risk model | Factor model fitted to synthetic returns | Same factor-model method (factor covariance + loadings + specific risk) fitted to real returns, or a vendor model (Barra / Axioma / BBG PORT) if licensed |
| Target models | 2 placeholder Schwab models, made-up weights | Real Schwab products and weights in `data/models/target_models.json` |
| Client holdings | Synthetic lots | Real lots via statement PDFs / custodian feeds (already supported by the ingest flow) |

## How it plugs in

- The optimizer, guide and UI only use the `AnalyticsProvider` interface
  (`app/analytics/provider.py`). With two sources, use a **composite provider**: market-data
  methods (`get_prices`, holdings, fundamentals, risk-model inputs) go to a Bloomberg client, and
  portfolio-analytics methods (`get_exposures`, asset allocation, stress tests) go to the
  Aladdin client (`app/analytics/aladdin_provider.py`, stub today). Select it with e.g.
  `ANALYTICS_PROVIDER=bbg_aladdin`. No optimizer changes.
- **New analytics to add to the API and UI with Aladdin:** an asset-allocation breakdown (account
  and book), stress-test / scenario results (e.g. "2008", "rates +200 bp"), shown on the client
  page and in the transition compare / results steps (before vs after the transition). The AI
  guide can then quote them; the number guard still applies.
- Methods it must implement: `get_prices`, `get_risk_model` (expose the factor structure; the
  optimizer uses it for speed), `get_exposures`, `get_model_stats`, plus the history methods.
- Data access: `blpapi` (Desktop API / B-PIPE) or Bloomberg Data License files. Cache prices and
  holdings in the database nightly; don't query BBG per request.
- Responses already carry `data_source`. Set it to e.g. `"bloomberg"` so the UI drops the
  "Simulated analytics" badge automatically.

## To decide when we get there

- Which BBG product and licence (Terminal Desktop API, B-PIPE, Data License): this affects
  automation and redistribution rights.
- Universe size and the covariance lookback / half-life.
- Risk model for the optimizer: our factor model on Bloomberg data, or Aladdin's risk model.
  Using Aladdin's would make the optimizer's tracking error match Aladdin's reported risk.
- Which Aladdin analytics are available via API (Aladdin Studio / Graph APIs) vs. files, and
  latency (the optimizer needs the risk model in-process; stress tests can be fetched per request).
- How often to refresh fund holdings and the risk model (daily prices, monthly holdings?).
