# AI guide: roadmap

What the guide does today, and the two features requested for when real analytics are available.

## Today

- Walks the fixed transition flow (import → review → target → compare → optimize → approve).
- Free text is mapped to the actions allowed at the current step; questions are answered from the
  analytics tools, and any figure the tools didn't produce is blocked (number guard).
- **Small talk** (added 2026-11-02): "hey are you here?", hello, thanks, "how are you", "what can
  you do?" get a friendly reply, plus where we are and what can be done at this step. Messages it
  doesn't understand get the same step help instead of a bare "didn't catch that".
- Runs on the offline rule-based stand-in by default (`DEMO_MODE=true`). With a Claude key
  (`DEMO_MODE=false`, `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`), it understands free-form
  wording; the steps and guardrails stay the same.

## 1. Switch positions from the chat

> "Swap ARVX for SCHX", "replace the two tech names with the core ETF", "sell half of JUP".

- **New intents** at the optimize / results steps: `swap` (from tickers → to ticker),
  `trim` (ticker, fraction or amount), `exclude` (never buy), `force_sell`.
- **How it executes:** never as a hand-written trade. Each instruction becomes an optimizer
  constraint (forced sale / no-buy list / minimum or maximum holding), and the optimizer re-runs,
  so taxes, tracking error, cash and wash-sale rules stay consistent. The guide then shows the
  before/after (tax, TE, trades) and asks the advisor to confirm.
- **Backend work:** add these constraint types to `Constraints` and the optimizer; new intents in
  `app/agent/intents.py`; the guide's tools gain `propose_swap`. This also needs the chat to accept
  constraint changes (same gap as B5).
- **Guardrails:** the advisor confirms every change; changes are recorded in the transition history
  and the approval event; the guide only proposes and never approves on its own.

## 2. Auto-detect portfolio issues

When holdings are imported (and again before approval), the guide runs a set of checks and raises
the findings in the chat and as cards on the canvas, each with a suggested action.

| Check | Example finding | Suggested action |
|---|---|---|
| Single-name concentration | "NVDA is 18% of the account (look-through)" | Lock-and-trim plan, or set a max weight |
| Sector concentration | "Tech is 41% vs 29% in the target" | Sector band in the optimizer |
| Overlap via funds | "AAPL held directly and inside 3 ETFs" | Look-through view; consolidate |
| Embedded gains | "62% of the gain sits in 3 lots" | Lock, glide path over 2–3 years |
| Losses to harvest | "$14k of short-term losses available" | Harvest within the budget |
| Wash-sale risk | "Bought VTI 12 days ago; selling at a loss would wash" | Delay or substitute |
| Missing data | "4 lots lack basis or dates" | Upload lot detail or assume average cost |
| Cash drag | "6% cash vs 0.5% buffer" | Invest in the transition |

- **Where the numbers come from:** an analytics `checks` endpoint (e.g.
  `GET /accounts/{id}/analytics/checks`) computed in the backend from holdings and the risk model,
  with configurable thresholds. The guide words the findings; it never computes them, so the number
  guard still applies.
- **UI:** a "Findings" card list on the review and optimize steps, a badge on the stepper step, and
  a one-line summary from the guide ("I found 2 things worth a look…").

## Suggested order

1. Checks endpoint plus the concentration and missing-data checks: the most visible value, and
   read-only.
2. Findings in the chat and on the canvas.
3. Constraint support in the chat (closes B5), then swaps, trims and exclusions on top of it.
