# Transition optimizer

Source: `app/optimizer/problem.py` (solver), `app/optimizer/lots.py` (lot relief),
`app/domain/tax.py` (tax arithmetic), `app/optimizer/transition_cost.py` (full-transition
reference used by `/models/compare`). Everything below is what the code does.

> Illustrative, for advisor review. Not tax or investment advice. Synthetic data only.

## 1. Inputs

| Symbol | Meaning |
|---|---|
| S | securities = held securities ∪ target-model products (e.g. ETFs) |
| p_i | price of security i |
| lots l | quantity q_l, cost per share c_l, acquisition date, locked flag, security i(l) |
| h_i | shares held of i = Σ_{l∈i} q_l |
| cash | account cash |
| V | account value = cash + Σ_i h_i p_i (fixed during the trade) |
| w*_i | target weight of i (products of the chosen model; 0 for everything else) |
| Σ | annualised covariance over S, from the analytics provider |
| τ_ST, τ_LT | household combined (federal + state) ST and LT rates |

ST/LT: a lot is long-term if held **more than 365 days** at the as-of date.

**Covariance.** Products are expanded to their constituents (look-through matrix E, rows =
securities in S, columns = base stocks). With the stock factor model
Σ_stock = B F Bᵀ + diag(D), the covariance over S is exactly

  Σ = E (B F Bᵀ + diag D) Eᵀ.

The optimizer never forms Σ densely when the factor structure is available. It uses
M₁ = Qᵀ Bᵀ Eᵀ (k × |S|, F = Q Qᵀ, k ≈ 17) and M₂ = diag(√D) Eᵀ (sparse), so
(x − w*)ᵀ Σ (x − w*) = ‖M₁ d‖² + ‖M₂ d‖². If a provider supplies only Σ, a dense factor
G with GᵀG = Σ (eigendecomposition) is used instead. Both forms give the same optimum
(tested).

## 2. Decision variables

The variables are scaled for numerical stability:

* u_l ∈ [0, ub_l]: **fraction** of lot l sold (shares sold s_l = u_l q_l).
* v_i ≥ 0: purchase of security i as a **fraction of V** (buy value b_i p_i = v_i V).

Only target products are buyable (v_i = 0 when w*_i = 0). Upper bounds are ub_l = 1,
except ub_l = 0 for locked lots and wash-sale-blocked lots (§4).

## 3. Model

Post-trade weights:

  x_i = h_i p_i / V − Σ_{l∈i} u_l q_l p_i / V + v_i,  and d = x − w*.

Objective:

  minimise ‖M₁ d‖² + ‖M₂ d‖² + κ · (c_tc + λ_turn) · (Σ_l u_l q_l p_l / V + Σ_i v_i)

* c_tc = transaction cost in bps / 10⁴ (default 5 bps); λ_turn is an optional turnover
  penalty (default 0).
* κ = 0.02 expresses trading cost in TE² (variance) units. This makes costs the "small
  penalties" the spec asks for: they break ties and suppress pointless trades without
  dominating tracking error. Without κ, a 1% residual TE (TE² = 1e-4) is outweighed by
  5 bps on full turnover (1e-3), and the optimizer stops short of the target.

Constraints:

1. Bounds: 0 ≤ u_l ≤ ub_l and v_i ≥ 0. With these, x ≥ 0 automatically (long-only, no shorts).
2. **Cash:** cash/V + Σ_l u_l q_l p_l / V ≥ Σ_i v_i + buffer (default buffer 0.5%). This also
   implies Σx ≤ 1 (no leverage).
3. **Gain budget.** Let g_l = q_l (p_l − c_l) be the gain from selling all of lot l,
   ST = Σ_{l∈ST} g_l u_l and LT = Σ_{l∈LT} g_l u_l. Losses net within each bucket. Then:
   * `net_gain` mode: ST + LT ≤ G_max.
   * `tax` mode: **τ_ST·ST + τ_LT·LT ≤ T_max and τ_LT·(ST + LT) ≤ T_max.**

   The exact tax after US netting (net each bucket; a net loss in one bucket offsets a net
   gain in the other) is f(ST, LT) = τ_ST·ST⁺ + τ_LT·LT⁺ after cross-netting. This f is
   **not convex**. The two linear constraints bound it from above in every region, so the
   exact tax never exceeds T_max:
   * Both buckets ≥ 0: f = τ_ST·ST + τ_LT·LT. The first constraint is exact.
   * ST < 0 < LT: f = τ_LT·(ST + LT)⁺. The second constraint is exact.
   * LT < 0 < ST: f = τ_ST·(ST + LT)⁺. Since LT < 0 and τ_LT ≤ τ_ST, we have
     τ_LT·LT ≥ τ_ST·LT, so τ_ST·ST + τ_LT·LT ≥ τ_ST·(ST + LT). The first constraint is
     therefore an upper bound here. It is conservative: it may over-state the tax, which
     only means the optimizer realizes slightly less than it could.
   * Both < 0: f = 0.

   Tax-deferred accounts (IRA / Roth) ignore the budget.
4. Optional per-security cap: x_i ≤ max(max_weight, weight held in unsellable lots of i).
5. Optional sector band: |Lᵀx − Lᵀw*| ≤ band, where L holds the look-through sector
   loadings (the provider's `sector:*` factor loadings).

Solver: CLARABEL, then OSQP, then SCS as fallbacks. The problem is a convex QP.

## 4. Wash-sale guard (taxable accounts)

A lot sold at a loss is **blocked** (ub_l = 0) when its security
(a) is a target product bought in this rebalance, or
(b) had any lot acquired in the prior 30 days.

This is the per-lot form of the spec's rule "if any lot of i is sold at a loss, b_i = 0".
We keep the purchase and hold the loss lot back, and the blocked lots are reported.
Buying a product (ETF) that **contains** a stock sold at a loss is **not** treated as a wash
sale ("not substantially identical", the standard industry treatment).

## 5. Infeasibility

Relaxed in this order, with each relaxation reported in `diagnostics.relaxations`:
min-trade size → sector bounds → cash buffer.

## 6. Post-processing (`finalize=True`)

1. **Max names** (optional): if more than `max_names` positions remain, fully exit the
   smallest non-target unlocked positions and re-solve.
2. **Min trade size** (optional): zero out per-security sells and buys below the minimum,
   then re-solve once. If that is infeasible, the previous solution is kept and
   "min-trade size" is reported as relaxed.
3. **Rounding:** sells round down to 0.001 share; buys round down to whole shares, so cash
   always suffices. Trades under $1 (solver dust) are dropped.
4. **Lot relief:** the optimizer's per-lot choice is the default. With `lot_relief =
   tax_optimal | hifo`, each security's total sold shares are re-attributed to lots by
   that method. `lot_relief_check` reports the tax under the optimizer's lots and under the
   chosen method.
5. All reported numbers (TE, realized ST/LT gains and losses, exact netted tax, turnover)
   are recomputed from the final rounded trades.

## 7. Outputs

* Trade list: per-lot sells (shares, proceeds, cost basis, realized gain, ST/LT) and buys.
* Pre/post snapshots: TE, holdings count, yield, beta, sector and factor active weights.
* Realized summary with the exact tax and the share of the budget used.
* Diagnostics: solver, status, solve time, binding constraints, relaxations, notes, TE
  contributions and a plain-English explanation. Contribution of security i:
  c_i = d_i (Σd)_i / TE, and Σ c_i = TE. Each contribution is tagged *locked*,
  *wash_sale*, *budget* (overweight non-target position while the budget binds),
  *underweight* or *other*.

## 8. Frontier and glide path

* **Frontier:** solve once with no budget to get the full-transition level (tax or net
  gain), then solve at `n_points` budgets evenly spaced from 0 to that level, without
  rounding or min-trade. TE is non-increasing and tax non-decreasing in the budget (tested).
  `chosen_index` marks the point nearest the last optimization's budget.
* **Glide path** (1–3 years): solve year 1 with its budget, then apply the trades (buys
  become new lots on the as-of date). Advance the date by 366 days with prices held
  constant and solve the next year.

## 9. Performance

300 names, 1,000 lots, 4 target ETFs, tax budget: about 0.2 s on a laptop. The test
asserts under 2 s. A 15-point frontier on a demo account takes about 0.3–0.5 s.
