"""In-process mock of the Transition Studio API (``USE_MOCKS=true``).

Ported from reference/react-ui/lib/mock/data.ts: the same named households, advisor, value ranges
and percent-to-decimal conventions, expanded to the spec's mock contents. Every response has the
exact openapi shape (validated in tests/test_mock_backend.py). Values are seeded per id, so they
are stable across refreshes. Models mirror the live backend's two Schwab placeholder models.
"""

from __future__ import annotations

import io
import math
import random
import re
import uuid
from datetime import date, timedelta
from typing import Any

import httpx

AS_OF = date(2026, 10, 30)
SEED = 20240501
TOKEN = "mock-advisor-token"
USER = {"id": "usr-001", "email": "demo@advisor.test", "name": "Alex Morgan", "role": "advisor",
        "advisor_id": "adv-001", "firm": "Harborview Wealth Partners (demo)"}
DISCLAIMER = "Illustrative, for advisor review. Not tax or investment advice."
EVENT_TYPES = ["transition", "rebalance", "tax_loss_harvest", "cash_flow", "model_change"]


def rng(*key: object) -> random.Random:
    return random.Random(f"{SEED}:" + ":".join(map(str, key)))


# ================================================================ reference data (React mocks)
_CLIENTS: list[dict[str, Any]] = [
    # React lib/mock/data.ts (TE in percent there → decimals here; "joint" → "couple")
    dict(id="cl-001", name="Maya & Daniel Chen", email="chen@example.com", client_type="couple",
         n_accounts=3, market_value=1842300, target="SCHWAB-TR", te=0.0072, ytd=18420,
         last_rebalance="2026-09-18", status="on_target", onboarded="2021-04-12",
         tax=(0.37, 0.2, "CA", 0.133)),
    dict(id="cl-002", name="Robert Williams", email="robert@example.com", client_type="individual",
         n_accounts=2, market_value=967450, target="SCHWAB-INC", te=0.0118, ytd=9210,
         last_rebalance="2026-06-04", status="drifting", onboarded="2022-01-08",
         tax=(0.32, 0.2, "NY", 0.109)),
    dict(id="cl-003", name="Priya Shah Family Trust", email="shah@example.com", client_type="trust",
         n_accounts=1, market_value=3215800, target="SCHWAB-TR", te=0.0054, ytd=32760,
         last_rebalance="2026-10-07", status="on_target", onboarded="2019-10-23",
         tax=(0.37, 0.2, "MA", 0.09)),
    dict(id="cl-004", name="Eleanor Foster", email="eleanor@example.com", client_type="individual",
         n_accounts=2, market_value=741200, target="SCHWAB-TR", te=0.0164, ytd=4680,
         last_rebalance="2025-12-11", status="needs_review", onboarded="2023-07-17",
         tax=(0.24, 0.15, "TX", 0.0)),
    dict(id="cl-005", name="James & Ava Rodriguez", email="rodriguez@example.com",
         client_type="couple", n_accounts=3, market_value=1289400, target="SCHWAB-INC",
         te=0.0081, ytd=12890, last_rebalance="2026-08-22", status="on_target",
         onboarded="2020-05-29", tax=(0.35, 0.2, "IL", 0.0495)),
    # spec: 8–10 clients incl. one newly onboarded with no history
    dict(id="cl-006", name="Hannah Okonkwo", email="okonkwo@example.com", client_type="individual",
         n_accounts=1, market_value=612900, target="SCHWAB-TR", te=0.0093, ytd=5140,
         last_rebalance="2026-09-02", status="on_target", onboarded="2024-02-14",
         tax=(0.32, 0.15, "WA", 0.0)),
    dict(id="cl-007", name="Marcus & Lena Becker", email="becker@example.com", client_type="couple",
         n_accounts=2, market_value=2408700, target="SCHWAB-TR", te=0.0139, ytd=21330,
         last_rebalance="2026-07-15", status="drifting", onboarded="2021-11-03",
         tax=(0.37, 0.2, "NJ", 0.1075)),
    dict(id="cl-008", name="Sophia Martinez", email="martinez@example.com",
         client_type="individual", n_accounts=1, market_value=455300, target="SCHWAB-INC",
         te=0.0066, ytd=2980, last_rebalance="2026-10-01", status="on_target",
         onboarded="2025-03-21", tax=(0.24, 0.15, "FL", 0.0)),
    dict(id="cl-009", name="Noah & Grace Patel", email="patel@example.com", client_type="couple",
         n_accounts=1, market_value=1975000, target=None, te=None, ytd=0,
         last_rebalance=None, status="onboarding", onboarded="2026-10-26",
         tax=(0.35, 0.238, "CO", 0.044)),
]

MODELS: list[dict[str, Any]] = [
    dict(id="SCHWAB-TR", name="Schwab Core Equity — Total Return", provider="Charles Schwab",
         objective="total_return", construction="market_cap",
         benchmark="SYN-LMC (Synthetic US Large/Mid Cap Index)",
         description="Core US equity built from low-cost Schwab ETFs: large-cap core with growth, "
                     "value and mid-cap sleeves.",
         rationale="Broad, low-cost market exposure for long-term growth.",
         target_yield=0.0179, expected_te=0.0129, fee_bps=3.45,
         holdings=[("SCHX", "Schwab U.S. Large-Cap ETF", 3, 0.55),
                   ("SCHG", "Schwab U.S. Large-Cap Growth ETF", 4, 0.15),
                   ("SCHV", "Schwab U.S. Large-Cap Value ETF", 4, 0.15),
                   ("SCHM", "Schwab U.S. Mid-Cap ETF", 4, 0.15)]),
    dict(id="SCHWAB-INC", name="Schwab Dividend Income", provider="Charles Schwab",
         objective="income", construction="market_cap_fundamental",
         benchmark="SYN-DIV (Synthetic US Dividend Index)",
         description="Income-oriented US equity anchored on a quality dividend ETF.",
         rationale="Higher portfolio yield from companies with the quality to sustain dividends.",
         target_yield=0.0349, expected_te=0.0302, fee_bps=5.05,
         holdings=[("SCHD", "Schwab U.S. Dividend Equity ETF", 6, 0.60),
                   ("SCHV", "Schwab U.S. Large-Cap Value ETF", 4, 0.25),
                   ("SCHX", "Schwab U.S. Large-Cap ETF", 3, 0.15)]),
]
FUND_PRICE = {"SCHX": 27.22, "SCHG": 24.86, "SCHV": 30.99, "SCHM": 38.06, "SCHD": 33.52}
SECTORS = ["Information Technology", "Health Care", "Financials", "Consumer Discretionary",
           "Communication Services", "Industrials", "Consumer Staples", "Energy", "Utilities",
           "Real Estate", "Materials"]
_TICKERS = [  # synthetic names (no real securities)
    ("ARVX", "Aster Systems"), ("BLNQ", "Brightwater Bancorp"), ("CDRM", "Calder Medical"),
    ("DLTN", "Dunmore Logistics"), ("EMBR", "Ember Energy"), ("FNWK", "Fenwick Foods"),
    ("GRNT", "Granite Materials"), ("HLCY", "Halcyon Health"), ("IRWD", "Ironwood Rail"),
    ("JNPR", "Juniper Power"), ("KSTL", "Kestrel Media"), ("LMNX", "Lumen Networks"),
    ("MRDN", "Meridian Realty"), ("NTHG", "Northgate Capital"), ("OKHV", "Oakhaven Brands"),
    ("PNCR", "Pinecrest Pharma"), ("QRRY", "Quarry Industries"), ("RWNS", "Rowan Software"),
    ("SLVR", "Silverline Insurance"), ("THSL", "Thistle Household"), ("UPLD", "Upland Utilities"),
    ("VRDT", "Verdant Chemicals"), ("WSTM", "Westmark Retail"), ("XENO", "Xeno Therapeutics"),
    ("YRRW", "Yarrow Leisure"), ("ZPHR", "Zephyr Aerospace"), ("ALDR", "Alder Digital"),
    ("BCNX", "Beacon Semiconductor"), ("CRVD", "Corvid Interactive"), ("DNMR", "Dunmore Water"),
    ("ESTL", "Eastlake Petroleum"), ("FXGL", "Foxglove Biosciences"), ("GLNT", "Galen Trust"),
    ("HRRW", "Harrow Machinery"), ("IONC", "Ionic Packaging"), ("JSPR", "Jasper Grocers"),
    ("KYST", "Keystone Electric"), ("LRKS", "Larkspur Apparel"), ("MRLW", "Marlow Properties"),
    ("NMBS", "Nimbus Communications"), ("ORRN", "Orrin Metals"), ("PLCD", "Pellucid Digital"),
    ("QUIL", "Quill Chemicals"), ("RDFN", "Redfern Financial"), ("SOLC", "Solace Health"),
    ("TMSN", "Tamsin Midstream"), ("UMBR", "Umber Motors"), ("VNTR", "Vantor Aerospace"),
    ("WLLW", "Willow Beverage"), ("ASHB", "Ashby Land Trust"), ("BRYN", "Bryn Capital"),
    ("CBLT", "Cobalt Software"), ("DRVR", "Drover Networks"), ("ELMS", "Elmsford Medical"),
    ("FRTH", "Forthright Rail"), ("GLDN", "Golden Mile Retail"), ("HRZN", "Horizon Power"),
    ("IVRY", "Ivory Insurance"), ("JLLY", "Jolly Foods"), ("KNSG", "Kinsing Industries"),
]
SECURITIES = {
    t: dict(name=n, sector=SECTORS[i % len(SECTORS)],
            price=round(rng("px", t).uniform(18, 420), 2),
            dy=round(rng("dy", t).uniform(0.0, 0.045), 4), beta=round(rng("b", t).uniform(.6, 1.5), 2))
    for i, (t, n) in enumerate(_TICKERS)
}
for _t, _p in FUND_PRICE.items():
    SECURITIES[_t] = dict(name=next(h[1] for m in MODELS for h in m["holdings"] if h[0] == _t),
                          sector="Fund", price=_p, dy=0.02, beta=1.0)

_ACCOUNT_KIND = [("individual_taxable", "Core portfolio"), ("ira", "Account 2"),
                 ("joint_taxable", "Account 3")]

# ================================================================ mutable state (per process)
STATE: dict[str, Any] = {"clients": {}, "accounts": {}, "events": {}, "transitions": {},
                         "regimes": {}}


def _bootstrap() -> None:
    if STATE["clients"]:
        return
    for c in _CLIENTS:
        STATE["clients"][c["id"]] = dict(c, notes=None, phone=None)
        per = c["market_value"] / c["n_accounts"]
        for i in range(c["n_accounts"]):
            kind, nick = _ACCOUNT_KIND[i]
            aid = f"{c['id']}-acct-{i + 1}"
            STATE["accounts"][aid] = dict(
                id=aid, client_id=c["id"], account_type=kind,
                custodian="Fidelity" if i % 2 else "Schwab", nickname=nick,
                target_model_id=c["target"], market_value=per,
                te=(c["te"] + i * 0.0008) if c["te"] is not None else None,
                onboarding_date=c["onboarded"], lots=_lots(aid, per, c["onboarded"]),
                cash=round(per * rng("cash", aid).uniform(.005, .03), 2),
            )
            if c["status"] != "onboarding":
                for e in _events(aid, c, per):
                    STATE["events"][e["id"]] = e


def _lots(aid: str, value: float, onboarded: str) -> list[dict[str, Any]]:
    r = rng("lots", aid)
    n_pos = r.randint(20, 60)
    picks = r.sample(list(_TICKERS), min(n_pos, len(_TICKERS)))
    weights = [r.lognormvariate(0, .6) for _ in picks]
    tot = sum(weights)
    lots = []
    k = 0
    for (t, _), w in zip(picks, weights, strict=True):
        px = SECURITIES[t]["price"]
        shares = value * 0.97 * w / tot / px
        n_lots = r.randint(1, 3)
        for j in range(n_lots):
            q = round(shares / n_lots, 3)
            days = r.randint(20, 3000)
            k += 1
            lots.append(dict(
                lot_id=f"{aid}-lot-{k:03d}", lot_ref=_lot_ref(aid, k), ticker=t, quantity=q,
                cost_basis_total=round(q * px * r.uniform(.55, 1.25), 2),
                acquired_date=(AS_OF - timedelta(days=days)).isoformat(),
                locked=(j == 0 and k % 37 == 0),
            ))
    return lots


def _lot_ref(aid: str, k: int) -> str:
    """Lot ID like the backend's: L<account digits>-<nnnn>."""
    return f"L{''.join(ch for ch in aid if ch.isdigit()) or aid}-{k:04d}"


def _events(aid: str, c: dict[str, Any], value: float) -> list[dict[str, Any]]:
    r = rng("events", aid)
    start = max(date.fromisoformat(c["onboarded"]), AS_OF - timedelta(days=3 * 365))
    out, d, n = [], start, 0
    te = 0.006
    while d < AS_OF:
        n += 1
        kind = "transition" if n == 1 else r.choices(
            EVENT_TYPES[1:], weights=[45, 30, 15, 3])[0]
        st = round(value * r.uniform(0, .01), 2) if kind != "cash_flow" else 0.0
        lt = round(value * r.uniform(0, .02), 2) if kind in ("transition", "rebalance") else 0.0
        losses = round(value * r.uniform(.001, .012), 2) if kind == "tax_loss_harvest" else 0.0
        te_before = te + r.uniform(.001, .006) if kind != "transition" else r.uniform(.03, .06)
        te = r.uniform(.003, .009)
        out.append(dict(
            id=f"{aid}-evt-{n:03d}", account_id=aid, date=d.isoformat(), type=kind,
            trigger={"transition": "client_request", "rebalance": r.choice(["scheduled", "drift"]),
                     "tax_loss_harvest": "harvest_opportunity", "cash_flow": "client_request",
                     "model_change": "client_request"}[kind],
            n_trades=r.randint(4, 40), turnover=round(r.uniform(.01, .6 if n == 1 else .1), 4),
            realized_st_gain=st, realized_lt_gain=lt, losses_harvested=losses,
            est_taxes_saved=round(losses * .4 + (st + lt) * r.uniform(.1, .4), 2),
            te_before=round(te_before, 5), te_after=round(te, 5),
            cash_flow_amount=round(value * r.uniform(-.05, .08), 2) if kind == "cash_flow" else 0.0,
            note={"transition": "Initial transition into the target model.",
                  "rebalance": "Scheduled quarterly rebalance.",
                  "tax_loss_harvest": "Harvested losses; reinvested in correlated replacements.",
                  "cash_flow": "Client cash flow invested toward target.",
                  "model_change": "Model changed at client request."}[kind],
        ))
        d += timedelta(days=r.randint(25, 75))
    return out


# ================================================================ view helpers
def _price(t: str) -> float:
    return float(SECURITIES[t]["price"])


def _account_mv(a: dict[str, Any]) -> float:
    return a["cash"] + sum(lot["quantity"] * _price(lot["ticker"]) for lot in a["lots"])


def _acct_events(aid: str) -> list[dict[str, Any]]:
    return sorted((e for e in STATE["events"].values() if e["account_id"] == aid),
                  key=lambda e: e["date"])


def _account_summary(a: dict[str, Any]) -> dict[str, Any]:
    evs = _acct_events(a["id"])
    rebal = [e["date"] for e in evs if e["type"] in ("rebalance", "transition", "model_change")]
    te = a["te"]
    return dict(
        id=a["id"], client_id=a["client_id"], account_type=a["account_type"],
        taxable=a["account_type"] not in ("ira", "roth_ira"), custodian=a["custodian"],
        nickname=a["nickname"], target_model_id=a["target_model_id"],
        onboarding_date=a["onboarding_date"], market_value=round(_account_mv(a), 2),
        cash=a["cash"], n_positions=len({lot["ticker"] for lot in a["lots"]}),
        n_lots=len(a["lots"]), ex_ante_te=te, drift_tolerance_te=0.015,
        outside_tolerance=bool(te and te > 0.015),
        taxes_saved_ytd=round(sum(e["est_taxes_saved"] for e in evs
                                  if e["date"].startswith(str(AS_OF.year))), 2),
        taxes_saved_since_inception=round(sum(e["est_taxes_saved"] for e in evs), 2),
        last_rebalance_date=max(rebal) if rebal else None, has_history=bool(evs),
    )


def _client_accounts(cid: str) -> list[dict[str, Any]]:
    return [a for a in STATE["accounts"].values() if a["client_id"] == cid]


def _tax_profile(c: dict[str, Any]) -> dict[str, Any]:
    fst, flt, state, sr = c["tax"]
    return dict(federal_st_rate=fst, federal_lt_rate=flt, state=state, state_rate=sr,
                st_rate=round(fst + sr, 5), lt_rate=round(flt + sr, 5))


def _client_row(c: dict[str, Any]) -> dict[str, Any]:
    accts = [_account_summary(a) for a in _client_accounts(c["id"])]
    mv = sum(a["market_value"] for a in accts)
    tes = [(a["ex_ante_te"], a["market_value"]) for a in accts if a["ex_ante_te"] is not None]
    te = round(sum(t * w for t, w in tes) / sum(w for _, w in tes), 5) if tes else None
    last = [a["last_rebalance_date"] for a in accts if a["last_rebalance_date"]]
    return dict(id=c["id"], name=c["name"], client_type=c["client_type"], n_accounts=len(accts),
                market_value=round(mv, 2),
                target_models=sorted({a["target_model_id"] for a in accts if a["target_model_id"]}),
                ex_ante_te=te, taxes_saved_ytd=round(sum(a["taxes_saved_ytd"] for a in accts), 2),
                last_rebalance_date=max(last) if last else None, status=c["status"])


def _client_out(c: dict[str, Any]) -> dict[str, Any]:
    return dict(id=c["id"], name=c["name"], email=c["email"], phone=c.get("phone"),
                client_type=c["client_type"], notes=c.get("notes"),
                tax_profile=_tax_profile(c), status=c["status"])


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _key(d: str, gran: str) -> str:
    return d[:7] if gran == "month" else d[:4]


def _periods(start: date, gran: str) -> list[str]:
    ms = _months(start, AS_OF)
    return ms if gran == "month" else sorted({m[:4] for m in ms})


def _te_series(aid: str, window: int) -> list[dict[str, Any]]:
    a = STATE["accounts"][aid]
    evs = _acct_events(aid)
    if not evs or a["te"] is None:
        return []
    r = rng("te", aid, window)
    start = date.fromisoformat(evs[0]["date"])
    out, d, v = [], start + timedelta(days=21 if window == 63 else 63), evs[0]["te_after"]
    while d <= AS_OF:
        if d.weekday() < 5:
            v = max(0.003, v + r.gauss(0, .00025 if window == 63 else .00012))
            drift = (a["te"] - v) * (0.01 if window == 63 else 0.005)
            v = v + drift
            out.append({"date": d.isoformat(), "te": round(v, 5)})
        d += timedelta(days=1)
    if out:
        out[-1]["te"] = a["te"]
    return out


MOCK_ST_LOSS_SHARE = 0.4  # mock events have no trade-level terms: split losses 40/60


def _tax_periods(aids: list[str], gran: str, start: date) -> list[dict[str, Any]]:
    keys = _periods(start, gran)
    acc = {k: [0.0] * 6 for k in keys}
    for aid in aids:
        for e in _acct_events(aid):
            k = _key(e["date"], gran)
            if k in acc:
                acc[k][0] += e["est_taxes_saved"]
                acc[k][1] += e["losses_harvested"]
                acc[k][2] += e["realized_st_gain"]
                acc[k][3] += e["realized_lt_gain"]
                acc[k][4] += e["losses_harvested"] * MOCK_ST_LOSS_SHARE
                acc[k][5] += e["losses_harvested"] * (1 - MOCK_ST_LOSS_SHARE)
    return [dict(period=k, saved=round(v[0], 2), losses=round(v[1], 2), st=round(v[2], 2),
                 lt=round(v[3], 2), st_loss=round(v[4], 2), lt_loss=round(v[5], 2))
            for k, v in acc.items()]


def _event_out(e: dict[str, Any]) -> dict[str, Any]:
    a = STATE["accounts"][e["account_id"]]
    return dict(id=e["id"], account_id=e["account_id"], account_nickname=a["nickname"],
                date=e["date"], type=e["type"], trigger=e["trigger"], n_trades=e["n_trades"],
                turnover=e["turnover"], realized_st_gain=e["realized_st_gain"],
                realized_lt_gain=e["realized_lt_gain"], losses_harvested=e["losses_harvested"],
                est_taxes_saved=e["est_taxes_saved"], te_before=e["te_before"],
                te_after=e["te_after"], cash_flow_amount=e["cash_flow_amount"], note=e["note"])


def _event_trades(e: dict[str, Any]) -> list[dict[str, Any]]:
    r = rng("trades", e["id"])
    names = r.sample(list(_TICKERS), min(e["n_trades"], len(_TICKERS)))
    out = []
    for i, (t, _) in enumerate(names):
        px = _price(t)
        sh = round(r.uniform(5, 400), 3)
        sell = i % 2 == 0
        gain = round(sh * px * r.uniform(-.15, .3), 2) if sell else 0.0
        out.append(dict(ticker=t, side="sell" if sell else "buy", shares=sh, price=px,
                        value=round(sh * px, 2), realized_gain=gain,
                        term=r.choice(["ST", "LT"]) if sell else None))
    return out


def _model_summary(mp: dict[str, Any]) -> dict[str, Any]:
    r = rng("model", mp["id"])
    sectors = [s for s in SECTORS]
    w = [r.uniform(.5, 2) for _ in sectors]
    tw = sum(w)
    return dict(
        id=mp["id"], name=mp["name"], provider=mp["provider"], objective=mp["objective"],
        construction=mp["construction"], benchmark=mp["benchmark"],
        description=mp["description"], rationale=mp["rationale"],
        target_yield=mp["target_yield"], expected_te=mp["expected_te"], fee_bps=mp["fee_bps"],
        regime_overlay=False,
        stats=dict(
            annualized_return=round(r.uniform(.06, .11), 5), volatility=round(r.uniform(.12, .17), 5),
            sharpe=round(r.uniform(.3, 1.2), 3), max_drawdown=round(r.uniform(.15, .25), 5),
            dividend_yield=mp["target_yield"], beta=round(r.uniform(.9, 1.1), 4),
            n_holdings=len(mp["holdings"]), n_underlying=r.randint(140, 300),
            sector_mix={s: round(x / tw, 6) for s, x in zip(sectors, w, strict=True)},
            factor_exposures={f: round(r.uniform(-.5, .8), 4)
                              for f in ("value", "quality", "momentum", "size")},
            history_start="2021-12-31", history_end=AS_OF.isoformat(),
        ),
    )


def _model(mid: str) -> dict[str, Any] | None:
    return next((m for m in MODELS if m["id"] == mid), None)


def _exposures(a: dict[str, Any], target: str | None) -> dict[str, Any]:
    mv = _account_mv(a)
    by_t: dict[str, float] = {}
    for lot in a["lots"]:
        by_t[lot["ticker"]] = by_t.get(lot["ticker"], 0.0) + lot["quantity"] * _price(lot["ticker"])
    w = {t: v / mv for t, v in by_t.items()} if mv else {}
    sec: dict[str, float] = {}
    for t, x in w.items():
        sec[SECURITIES[t]["sector"]] = sec.get(SECURITIES[t]["sector"], 0.0) + x
    r = rng("tsec", target)
    tsec = {s: r.uniform(.5, 2) for s in SECTORS} if target else {}
    ts = sum(tsec.values()) or 1
    tsec = {k: v / ts for k, v in tsec.items()}
    sectors = [dict(sector=s, portfolio_weight=round(sec.get(s, 0), 6),
                    target_weight=round(tsec.get(s, 0), 6),
                    active_weight=round(sec.get(s, 0) - tsec.get(s, 0), 6))
               for s in sorted(set(sec) | set(tsec))]
    if mv:
        sectors.append(dict(sector="Cash", portfolio_weight=round(a["cash"] / mv, 6),
                            target_weight=0.0, active_weight=round(a["cash"] / mv, 6)))
    top = sorted(w.items(), key=lambda kv: -kv[1])
    fr = rng("fx", a["id"])
    return dict(
        sectors=sectors,
        top_active_weights=[dict(ticker=t, name=SECURITIES[t]["name"],
                                 sector=SECURITIES[t]["sector"], portfolio_weight=round(x, 6),
                                 target_weight=0.0, active_weight=round(x, 6))
                            for t, x in top[:10]],
        factor_exposures=[dict(factor=f, portfolio=round(p := fr.uniform(-.6, .9), 4),
                               target=round(q := fr.uniform(-.3, .6), 4), active=round(p - q, 4))
                          for f in ("value", "quality", "momentum", "size")],
        top10_weight=round(sum(x for _, x in top[:10]), 6),
        hhi=round(sum(x * x for x in w.values()) / (sum(w.values()) ** 2 or 1), 6),
        n_positions=len(w),
        dividend_yield=round(sum(x * SECURITIES[t]["dy"] for t, x in w.items()), 6),
        target_dividend_yield=_model(target)["target_yield"] if target else None,  # type: ignore[index]
        beta=round(sum(x * SECURITIES[t]["beta"] for t, x in w.items()), 4),
        target_beta=1.0 if target else None,
    )


# ================================================================ optimizer stand-in
def _full_tax(a: dict[str, Any], c: dict[str, Any]) -> tuple[float, float, dict[str, float]]:
    taxable = a["account_type"] not in ("ira", "roth_ira")
    tp = _tax_profile(c)
    st = lt = stl = ltl = 0.0
    for lot in a["lots"]:
        g = lot["quantity"] * _price(lot["ticker"]) - lot["cost_basis_total"]
        term = _term(lot)
        if term == "ST":
            st, stl = (st + g, stl) if g >= 0 else (st, stl - g)
        else:
            lt, ltl = (lt + g, ltl) if g >= 0 else (lt, ltl - g)
    tax = max(st - stl, 0) * tp["st_rate"] + max(lt - ltl, 0) * tp["lt_rate"] if taxable else 0.0
    return round(tax, 2), round(st + lt - stl - ltl, 2), dict(st=st, stl=stl, lt=lt, ltl=ltl)


def _term(lot: dict[str, Any]) -> str:
    return "LT" if (AS_OF - date.fromisoformat(lot["acquired_date"])).days > 365 else "ST"


# mirrors app/agent/engine.py DEFAULT_CONSTRAINTS (guided-chat optimization defaults, B5)
CHAT_DEFAULT_CONSTRAINTS: dict[str, Any] = dict(
    min_cash_buffer=0.005, transaction_cost_bps=5.0, turnover_penalty=0.0, min_trade_value=250.0,
    round_shares=True, lot_relief="optimizer")


def _optimize(t: dict[str, Any], mode: str, budget: float | None,
              constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    a = STATE["accounts"][t["account_id"]]
    c = STATE["clients"][a["client_id"]]
    target = t["target_model_id"]
    mp = _model(target) or MODELS[0]
    taxable = a["account_type"] not in ("ira", "roth_ira")
    full_tax, _, _ = _full_tax(a, c)
    locks = set(t["locks"]) | {lot["lot_id"] for lot in a["lots"] if lot["locked"]}
    tp = _tax_profile(c)
    te_pre = 0.06 + rng("tepre", a["id"]).uniform(0, .03) if a["te"] is None else max(a["te"] * 4, .03)
    frac = 1.0 if (mode == "none" or not taxable or budget is None) else min(budget / max(full_tax, 1), 1)
    # sells: losses first, then lowest tax per share, until the budget is used (like the backend)
    cand = sorted((lot for lot in a["lots"] if lot["lot_id"] not in locks),
                  key=lambda lot: (lot["quantity"] * _price(lot["ticker"]) - lot["cost_basis_total"])
                  / max(lot["quantity"] * _price(lot["ticker"]), 1))
    sells, spent, rz = [], 0.0, dict(st_gain=0.0, st_loss=0.0, lt_gain=0.0, lt_loss=0.0)
    for lot in cand:
        px = _price(lot["ticker"])
        gain = lot["quantity"] * px - lot["cost_basis_total"]
        term = _term(lot)
        tax = max(gain, 0) * (tp["st_rate"] if term == "ST" else tp["lt_rate"]) if taxable else 0
        if gain > 0 and frac < 1 and spent + tax > (budget or 0) + 1e-6:
            continue
        spent += tax
        key = ("st" if term == "ST" else "lt") + ("_gain" if gain >= 0 else "_loss")
        rz[key] += abs(gain)
        sells.append(dict(lot_id=lot["lot_id"], lot_ref=lot.get("lot_ref"), ticker=lot["ticker"],
                          shares=lot["quantity"],
                          price=px, proceeds=round(lot["quantity"] * px, 2),
                          cost_basis=lot["cost_basis_total"], realized_gain=round(gain, 2),
                          term=term, acquired_date=lot["acquired_date"]))
    proceeds = sum(s["proceeds"] for s in sells)
    buys = []
    for tk, _, _, w in mp["holdings"]:
        sh = math.floor(proceeds * 0.995 * w / FUND_PRICE[tk])
        if sh > 0:
            buys.append(dict(ticker=tk, shares=float(sh), price=FUND_PRICE[tk],
                             value=round(sh * FUND_PRICE[tk], 2)))
    purchases = sum(b["value"] for b in buys)
    est_tax = (max(rz["st_gain"] - rz["st_loss"], 0) * tp["st_rate"]
               + max(rz["lt_gain"] - rz["lt_loss"], 0) * tp["lt_rate"]) if taxable else 0.0
    if budget is not None and mode == "tax" and taxable:
        est_tax = min(est_tax, budget)
    locked_share = sum(lot["quantity"] * _price(lot["ticker"]) for lot in a["lots"]
                       if lot["lot_id"] in locks) / max(_account_mv(a), 1)
    te_post = te_pre * (0.08 + 0.55 * math.exp(-3 * frac)) + locked_share * 0.2
    mv = _account_mv(a)
    net = rz["st_gain"] - rz["st_loss"] + rz["lt_gain"] - rz["lt_loss"]
    snap = lambda te, n: dict(te=round(te, 5), n_holdings=n,  # noqa: E731
                              dividend_yield=round(mp["target_yield"] * (0.6 if n > 10 else .95), 6),
                              beta=1.04 if n > 10 else 1.0,
                              sector_active={s: round(rng("sa", s, n).uniform(-.04, .04)
                                                      * (1 if n > 10 else .25), 5)
                                             for s in SECTORS},
                              factor_active={f: round(rng("fa", f, n).uniform(-.3, .3), 4)
                                             for f in ("value", "quality", "momentum", "size")})
    explanation = []
    if locked_share > 0:
        explanation.append(f"Locked lots contribute {locked_share * 0.2:.2%} of the "
                           f"{te_post:.2%} residual TE.")
    if frac < 1:
        explanation.append(f"The {'tax' if mode == 'tax' else 'net-gain'} budget of "
                           f"${budget:,.0f} is fully used: legacy positions with embedded gains "
                           "stay overweight.")
    if not explanation:
        explanation.append(f"The portfolio closely matches the target (residual TE {te_post:.2%}).")
    return dict(
        data_source="mock_random", transition_id=t["id"], account_id=a["id"],
        target_model_id=target, as_of=AS_OF.isoformat(), taxable=taxable,
        budget_mode=mode, budget_value=budget,
        constraints=dict(dict(min_cash_buffer=0.005, transaction_cost_bps=5.0,
                              turnover_penalty=0.0, min_trade_value=0.0, max_names=None,
                              max_weight=None, sector_band=None, round_shares=True,
                              lot_relief="optimizer"), **(constraints or {})),
        trades=dict(sells=sells, buys=buys),
        summary=dict(n_lot_sells=len(sells), n_buys=len(buys), proceeds=round(proceeds, 2),
                     purchases=round(purchases, 2), turnover=round((proceeds + purchases) / 2 / mv, 4),
                     cash_before=a["cash"], cash_after=round(a["cash"] + proceeds - purchases, 2),
                     total_value=round(mv, 2)),
        realized=dict(st_gain=round(rz["st_gain"], 2), st_loss=round(rz["st_loss"], 2),
                      lt_gain=round(rz["lt_gain"], 2), lt_loss=round(rz["lt_loss"], 2),
                      net_gain=round(net, 2), est_tax=round(est_tax, 2),
                      budget_used_pct=round(100 * est_tax / budget, 2) if budget else None),
        pre=snap(te_pre, len({lot["ticker"] for lot in a["lots"]})),
        post=snap(te_post, len(buys) + len({lot["ticker"] for lot in a["lots"]
                                            if lot["lot_id"] in locks})),
        glide_path=None,
        diagnostics=dict(solver="MOCK", status="optimal", solve_ms=12.0,
                         binding_constraints=(["tax budget"] if frac < 1 else []) + ["cash buffer"],
                         relaxations=[], notes=[], explanation=explanation,
                         te_contributions=[], wash_blocked_lot_ids=[],
                         lot_relief_check={"optimizer_tax": round(est_tax, 2)}),
        disclaimer=DISCLAIMER,
    )


def _frontier(t: dict[str, Any], mode: str, n: int) -> dict[str, Any]:
    a = STATE["accounts"][t["account_id"]]
    c = STATE["clients"][a["client_id"]]
    full_tax, _, _ = _full_tax(a, c)
    pts = []
    for i in range(n):
        b = full_tax * i / (n - 1)
        o = _optimize(t, "tax", b)
        pts.append(dict(budget=round(b, 2), est_tax=o["realized"]["est_tax"],
                        net_gain=o["realized"]["net_gain"], te=o["post"]["te"],
                        turnover=o["summary"]["turnover"]))
    last = t.get("optimization")
    chosen = None
    if last and last["budget_value"] is not None:
        chosen = min(range(n), key=lambda i: abs(pts[i]["budget"] - last["budget_value"]))
    return dict(data_source="mock_random", transition_id=t["id"], target_model_id=t["target_model_id"],
                budget_mode=mode, max_budget=full_tax,
                te_before=_optimize(t, "tax", 0)["pre"]["te"], points=pts, chosen_index=chosen,
                disclaimer=DISCLAIMER)


# ================================================================ ingest stand-in
def _preview(t: dict[str, Any], source: str) -> dict[str, Any]:
    r = rng("preview", t["id"], source)
    lots = _lots(f"import-{t['account_id']}", r.uniform(1.2e6, 2.6e6), "2018-01-01")
    rows = []
    for i, lot in enumerate(lots):
        px = _price(lot["ticker"])
        issues = []
        ticker = lot["ticker"]
        suggestion = None
        acquired: str | None = lot["acquired_date"]
        basis: float | None = lot["cost_basis_total"]
        if source == "pdf" and i == 7:
            suggestion, ticker = ticker, ticker[:-1] + "Q"
            issues.append(dict(code="unknown_ticker", severity="error",
                               message=f"{ticker} is not tradable — did you mean {suggestion}?"))
        if source == "plaid" and i % 3 == 2:
            acquired, basis = None, None
            issues += [dict(code="missing_date", severity="error",
                            message="Acquisition date missing or unreadable"),
                       dict(code="missing_basis", severity="warning",
                            message="Cost basis unknown — upload a lot file or accept an "
                                    "average-cost assumption")]
        mv = lot["quantity"] * px
        err = any(x["severity"] == "error" for x in issues)
        rows.append(dict(
            row_id=i, lot_ref=lot.get("lot_ref") if source == "pdf" else None,
            ticker=ticker, description=SECURITIES[lot["ticker"]]["name"],
            quantity=lot["quantity"], acquired_date=acquired, cost_basis_total=basis,
            statement_value=round(mv, 2), current_price=None if suggestion else px,
            market_value=None if suggestion else round(mv, 2),
            unrealized_gain=None if (suggestion or basis is None) else round(mv - basis, 2),
            holding_period=None if acquired is None else _term(lot), basis_estimated=basis is None,
            confidence=round(max(0.0, 1 - .45 * err - .12 * (len(issues) - err))
                             * (.95 if source == "pdf" else 1), 3),
            issues=issues, suggested_ticker=suggestion, include=not err,
        ))
    n_err = sum(not x["include"] for x in rows)
    preview = dict(
        transition_id=t["id"], account_id=t["account_id"], source=source,
        method="llm" if source == "pdf" else "plaid", llm_provider="mock" if source == "pdf" else None,
        confidence=round(sum(x["confidence"] for x in rows) / len(rows), 3),
        statement_date=AS_OF.isoformat() if source == "pdf" else None,
        cash_detected=round(r.uniform(5_000, 60_000), 2),
        requires_basis_decision=any(x["basis_estimated"] or x["acquired_date"] is None for x in rows),
        summary=dict(n_rows=len(rows), n_error_rows=n_err, n_warning_rows=0,
                     n_basis_unknown=sum(x["basis_estimated"] for x in rows),
                     n_missing_dates=sum(x["acquired_date"] is None for x in rows),
                     total_market_value=round(sum(x["market_value"] or 0 for x in rows), 2),
                     total_cost_basis=round(sum(x["cost_basis_total"] or 0 for x in rows), 2)),
        rows=rows,
        notes=(["No lot table found",
                "Extracted offline by the demo rule-based parser (no AI model was called)."]
               if source == "pdf" else ["Imported from Mock Brokerage (demo) (mock)"]),
    )
    t["preview"] = preview
    t["state"] = "INGEST_REVIEW"
    return preview


def _confirm(t: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    pv = t.get("preview")
    if not pv:
        raise _Http(409, "Nothing to confirm: upload or link first")
    a = STATE["accounts"][t["account_id"]]
    rows = [r for r in body.get("rows", []) if r.get("include", True)]
    if not rows:
        raise _Http(422, "No rows included")
    bad = [dict(row_id=r.get("row_id"), ticker=r["ticker"],
                issues=[dict(code="unknown_ticker", severity="error",
                             message=f"{r['ticker']} is not tradable")])
           for r in rows if r["ticker"].upper() not in SECURITIES]
    assumptions = []
    for r in rows:
        if r.get("acquired_date") is None or r.get("cost_basis_total") is None:  # noqa: SIM102
            if not body.get("assume_average_cost"):
                bad.append(dict(row_id=r.get("row_id"), ticker=r["ticker"],
                                issues=[dict(code="missing_basis", severity="error",
                                             message="Cost basis required (or confirm with "
                                                     "assume_average_cost=true)")]))
    if bad:
        raise _Http(422, {"message": "Some included rows are invalid; fix or exclude them",
                          "rows": bad})
    lots = []
    keep = [] if body.get("mode", "replace") == "replace" else a["lots"]
    taken = {x.get("lot_ref") for x in keep} | {r.get("lot_ref") for r in rows}
    seq = len(keep) + len(rows)
    for i, r in enumerate(rows):
        t_ = r["ticker"].upper()
        ref = r.get("lot_ref")
        while not ref:
            seq += 1
            ref = _lot_ref(a["id"], seq) if _lot_ref(a["id"], seq) not in taken else None
        lots.append(dict(lot_id=f"{a['id']}-imp-{i:03d}", lot_ref=ref, ticker=t_,
                         quantity=r["quantity"],
                         cost_basis_total=r.get("cost_basis_total") or r["quantity"] * _price(t_),
                         acquired_date=r.get("acquired_date")
                         or (AS_OF - timedelta(days=366)).isoformat(),
                         locked=bool(r.get("locked"))))
    if body.get("assume_average_cost"):
        assumptions.append("Missing basis set to today's value; missing dates assumed LT")
    a["lots"] = lots if body.get("mode", "replace") == "replace" else a["lots"] + lots
    if body.get("cash") is not None or pv.get("cash_detected"):
        a["cash"] = body.get("cash") or pv["cash_detected"]
    t.pop("preview", None)
    t["state"] = "TARGET_KNOWLEDGE"
    return dict(transition_id=t["id"], account_id=a["id"], state=t["state"],
                n_committed=len(lots), n_excluded=len(body.get("rows", [])) - len(rows),
                total_market_value=round(sum(x["quantity"] * _price(x["ticker"]) for x in lots), 2),
                cash=a["cash"], assumptions=assumptions)


# ================================================================ scripted conversation
STEP = {"INGEST_CHOICE": (1, "Holdings"), "INGEST_REVIEW": (1, "Holdings"),
        "TARGET_KNOWLEDGE": (2, "Choose target"), "TARGET_PICK_LIST": (2, "Choose target"),
        "Q_OBJECTIVE": (2, "Choose target"), "Q_CONSTRUCTION": (2, "Choose target"),
        "TARGET_COMPARE": (2, "Choose target"), "TARGET_CONFIRM": (3, "Confirm target"),
        "TRANSITION_SETUP": (4, "Set budget"), "TRANSITION_RESULTS": (5, "Review results"),
        "TRANSITION_APPROVE": (6, "Approve"), "DONE": (6, "Done")}
ORDER = list(STEP)


def _qr(i: str, label: str) -> dict[str, str]:
    return {"id": i, "label": label}


def _goto(t: dict[str, Any], s: str) -> None:
    t["state"] = s
    if s in t["path"]:
        t["path"] = t["path"][: t["path"].index(s) + 1]
    else:
        t["path"].append(s)


def _models_list() -> list[dict[str, Any]]:
    return [dict(model_id=m["id"], name=m["name"], objective=m["objective"],
                 construction=m["construction"], target_yield=m["target_yield"],
                 expected_te_vs_benchmark=m["expected_te"], fee_bps=m["fee_bps"]) for m in MODELS]


def _compare(model_ids: list[str], aid: str) -> dict[str, Any]:
    a = STATE["accounts"][aid]
    c = STATE["clients"][a["client_id"]]
    x = _exposures(a, None)
    full_tax, net, rz = _full_tax(a, c)
    mv = _account_mv(a)
    comps = []
    for mid in model_ids:
        mp = _model(mid)
        if mp is None:
            continue
        te = None if not a["lots"] else round(rng("te2m", aid, mid).uniform(.03, .09), 5)
        comps.append(dict(
            model=_model_summary(mp), te_from_current=te,
            yield_change=round(mp["target_yield"] - x["dividend_yield"], 5),
            full_transition=dict(est_tax=full_tax, realized_st_gain=round(rz["st"], 2),
                                 realized_st_loss=round(rz["stl"], 2),
                                 realized_lt_gain=round(rz["lt"], 2),
                                 realized_lt_loss=round(rz["ltl"], 2), net_realized_gain=net,
                                 n_lot_sales=len(a["lots"]), n_buys=len(mp["holdings"]),
                                 turnover=0.95, locked_value_retained=round(sum(
                                     lot["quantity"] * _price(lot["ticker"]) for lot in a["lots"]
                                     if lot["locked"]), 2),
                                 post_te=0.002 if not any(lot["locked"] for lot in a["lots"]) else 0.011),
        ))
    return dict(data_source="mock_random", as_of=AS_OF.isoformat(),
                taxable=a["account_type"] not in ("ira", "roth_ira"),
                current=dict(account_id=aid, market_value=round(mv, 2), cash=a["cash"],
                             n_positions=x["n_positions"], target_model_id=a["target_model_id"],
                             dividend_yield=x["dividend_yield"], beta=x["beta"],
                             sector_mix={s["sector"]: s["portfolio_weight"] for s in x["sectors"]},
                             factor_exposures={f["factor"]: f["portfolio"]
                                               for f in x["factor_exposures"]},
                             unrealized_gain=round(sum(lot["quantity"] * _price(lot["ticker"])
                                                       - lot["cost_basis_total"] for lot in a["lots"]), 2),
                             locked_value=0.0),
                comparisons=comps, disclaimer=DISCLAIMER)


def _render(t: dict[str, Any], prefix: str = "", interp: dict[str, Any] | None = None) -> dict[str, Any]:
    s = t["state"]
    a = STATE["accounts"][t["account_id"]]
    msg, replies, ui, actions = "", [], {"type": "none", "data": {}}, ["back", "restart"]
    if s == "INGEST_CHOICE":
        has = bool(a["lots"])
        msg = ("Let's set up the transition. "
               + (f"This account already holds {len({x['ticker'] for x in a['lots']})} positions. "
                  if has else "This account has no holdings yet. ")
               + "How should I get the tax lots?")
        replies = ([_qr("use_existing", "Use current holdings")] if has else []) + [
            _qr("upload_pdf", "Upload tax-lot PDF"), _qr("connect_plaid", "Connect via Plaid"),
            _qr("upload_sample", "Use sample statement (demo)")]
        ui = {"type": "ingest_choice", "data": {"transition_id": t["id"], "account_id": a["id"],
                                                "has_holdings": has,
                                                "pdf_upload_url": "/api/v1/ingest/pdf"}}
    elif s == "INGEST_REVIEW":
        pv = t["preview"]
        sm = pv["summary"]
        msg = (f"I read **{sm['n_rows']} lots** (confidence {pv['confidence']:.0%}), worth "
               f"${sm['total_market_value']:,.0f}.")
        replies = [_qr("confirm", "Looks right — save")]
        if any(r["suggested_ticker"] for r in pv["rows"]):
            replies.insert(0, _qr("accept_suggestions", "Accept suggestions & save"))
        if pv["requires_basis_decision"]:
            replies.insert(0, _qr("assume_average_cost", "Accept average-cost assumption"))
        replies.append(_qr("upload_again", "Upload a different file"))
        ui = {"type": "parse_preview", "data": pv}
    elif s == "TARGET_KNOWLEDGE":
        msg = "Do you already know the target model, or would you like help choosing?"
        replies = [_qr("knows", "I know the target"), _qr("help", "Help me choose")]
    elif s == "TARGET_PICK_LIST":
        msg = "Here is the model catalog. Which one is the target?"
        replies = [_qr(f"choose:{m['id']}", m["name"]) for m in MODELS]
        ui = {"type": "model_list", "data": {"models": _models_list()}}
    elif s == "Q_OBJECTIVE":
        msg = "Is the goal **income** or **total return**?"
        replies = [_qr("objective:income", "Income"), _qr("objective:total_return", "Total return")]
    elif s == "Q_CONSTRUCTION":
        msg = "Which construction style?"
        replies = [_qr("construction:market_cap", "Market cap"),
                   _qr("construction:market_cap_fundamental", "Market cap + Fundamental"),
                   _qr("construction:market_cap_fundamental_active",
                       "Market cap + Fundamental + Active")]
    elif s == "TARGET_COMPARE":
        obj = t.get("objective")
        ids = sorted((m["id"] for m in MODELS), key=lambda i: _model(i)["objective"] != obj)  # type: ignore[index]
        cmp = _compare(ids, a["id"])
        lines = ["Here are the closest options for this account (illustrative):"]
        for cc in cmp["comparisons"]:
            te = cc["te_from_current"]
            lines.append(f"- **{cc['model']['id']}** — yield {cc['model']['target_yield']:.2%}, "
                         f"TE from today {'n/a' if te is None else f'{te:.2%}'}, full-transition "
                         f"tax ${cc['full_transition']['est_tax']:,.0f}")
        lines.append(f"\n_{DISCLAIMER}_")
        msg = "\n".join(lines)
        replies = [_qr(f"choose:{i}", f"Choose {i}") for i in ids]
        ui = {"type": "model_comparison", "data": cmp}
    elif s == "TARGET_CONFIRM":
        mp = _model(t["target_model_id"])
        msg = f"Use **{mp['id']}** ({mp['name']}) as the target for this account?"  # type: ignore[index]
        replies = [_qr("yes", "Yes, confirm"), _qr("no", "Choose another")]
        ui = {"type": "model_list", "data": {"models": [m for m in _models_list()
                                                        if m["model_id"] == t["target_model_id"]]}}
    elif s == "TRANSITION_SETUP":
        c = STATE["clients"][a["client_id"]]
        full_tax, net, _ = _full_tax(a, c)
        acct = _account_summary(a)
        msg = (f"Moving fully into **{t['target_model_id']}** today would cost about "
               f"**${full_tax:,.0f}** in tax (net gain ${net:,.0f}).\n\nHow much tax are you "
               "willing to pay this year? You can also lock positions (e.g. “don't sell ARVX”) "
               "or change the cash buffer.")
        replies = [_qr("budget:tax:0", "$0 tax (harvest only)")]
        for f in (.25, .5):
            v = round(full_tax * f / 1000) * 1000
            if v > 0:
                replies.append(_qr(f"budget:tax:{v:.0f}", f"Up to ${v:,.0f} tax"))
        replies.append(_qr("budget:none", "No limit (full transition)"))
        ui = {"type": "transition_setup", "data": {
            "target_model_id": t["target_model_id"], "setup": t.get("setup") or {
                "budget_mode": None, "budget_value": None, "constraints": {}},
            "full_transition": _compare([t["target_model_id"]], a["id"])["comparisons"][0][
                "full_transition"],
            "taxable": acct["taxable"], "account": dict(
                account_id=a["id"], account_type=a["account_type"], taxable=acct["taxable"],
                market_value=acct["market_value"], cash=a["cash"], n_positions=acct["n_positions"],
                n_lots=acct["n_lots"],
                unrealized_gain=round(sum(x["quantity"] * _price(x["ticker"]) - x["cost_basis_total"]
                                          for x in a["lots"]), 2),
                locked_value=round(sum(x["quantity"] * _price(x["ticker"]) for x in a["lots"]
                                       if x["locked"] or x["lot_id"] in t["locks"]), 2),
                st_rate=_tax_profile(c)["st_rate"], lt_rate=_tax_profile(c)["lt_rate"],
                current_target_model_id=a["target_model_id"]),
            "locked_lot_ids": t["locks"], "locks_url": f"/api/v1/transitions/{t['id']}/locks"}}
    elif s == "TRANSITION_RESULTS":
        o = t["optimization"]
        msg = (f"Tracking error falls from **{o['pre']['te']:.2%}** to **{o['post']['te']:.2%}** "
               f"with an estimated tax of **${o['realized']['est_tax']:,.0f}**.\n"
               + "\n".join(f"- {x}" for x in o["diagnostics"]["explanation"])
               + f"\n\n_{DISCLAIMER}_")
        replies = [_qr("approve", "Approve trades"), _qr("adjust", "Change settings")]
        ui = {"type": "transition_results", "data": {"optimization": o, "frontier": t.get("frontier")}}
        actions = ["back", "restart", "approve"]
    elif s == "TRANSITION_APPROVE":
        o = t["optimization"]
        msg = (f"Ready to approve **{o['summary']['n_lot_sells']} lot sales** and "
               f"**{o['summary']['n_buys']} buys** into {o['target_model_id']} (estimated tax "
               f"${o['realized']['est_tax']:,.0f}).\n\n_{DISCLAIMER}_")
        replies = [_qr("approve", "Approve & record"), _qr("adjust", "Change settings")]
        ui = {"type": "transition_results", "data": {"optimization": o, "exports": {
            "trades_csv": f"/api/v1/transitions/{t['id']}/trades.csv",
            "summary_pdf": f"/api/v1/transitions/{t['id']}/summary.pdf"}}}
        actions = ["back", "restart", "approve"]
    elif s == "DONE":
        msg = (f"Done. The transition into **{t['target_model_id']}** is recorded "
               f"(event {t['event_id']}); the account now targets it.")
        replies = [_qr("restart", "Start another transition")]
        ui = {"type": "transition_results", "data": {
            "event_id": t["event_id"], "event_url": f"/api/v1/events/{t['event_id']}",
            "exports": {"trades_csv": f"/api/v1/transitions/{t['id']}/trades.csv",
                        "summary_pdf": f"/api/v1/transitions/{t['id']}/summary.pdf"}}}
        actions = ["restart"]
    step, label = STEP[s]
    text = f"{prefix}\n\n{msg}" if prefix else msg
    t["history"] += [{"role": "assistant", "text": text, "state": s}]
    return dict(transition_id=t["id"], state=s, assistant_message=text, quick_replies=replies,
                ui_payload=ui, allowed_actions=actions,
                progress=dict(step=step, total=6, label=label), interpretation=interp,
                llm_provider="mock")


# mirrors app/agent/intents.py smalltalk_kind + engine._smalltalk (greetings, thanks, "are you there?")
_SMALLTALK = [
    ("capabilities", r"\b(who are you|what are you|what can you do|what do you do|how can you help)\b"),
    ("how_are_you", r"\b(how are you|how's it going)\b"),
    ("thanks", r"\b(thanks|thank you|thx|cheers)\b"),
    ("greeting", r"^(hi|hello|hey|hiya|yo|good (morning|afternoon|evening))\b"
                 r"|\b(are you|you) (there|here|around|awake|online)\b"),
]
_SMALLTALK_OPENERS = {
    "greeting": "Yes, I'm here! How can I help?",
    "how_are_you": "Doing well, thanks, and ready when you are. How can I help?",
    "thanks": "You're welcome!",
    "capabilities": "I'm the transition guide. I walk you through importing the holdings, choosing a "
                    "target model, and finding the best trade-off between tracking error and taxes, "
                    "then I prepare the trades for your approval.",
}


def _smalltalk_kind(text: str) -> str | None:
    if len(text.split()) > 12:
        return None
    return next((k for k, pat in _SMALLTALK if re.search(pat, text.strip(), re.IGNORECASE)), None)


def _intent(t: dict[str, Any], text: str) -> tuple[str, str]:
    """Tiny keyword interpreter for mock free text → (quick-reply id, arg)."""
    q = text.lower()
    amount = re.search(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m)?\b", q)
    if "back" in q:
        return "back", ""
    if "restart" in q or "start over" in q:
        return "restart", ""
    if amount and ("tax" in q or t["state"] in ("TRANSITION_SETUP", "TRANSITION_RESULTS")):
        v = float(amount.group(1).replace(",", "")) * {"k": 1e3, "m": 1e6}.get(amount.group(2) or "", 1)
        return "budget", f"tax:{v:.0f}"
    kind = _smalltalk_kind(text)
    if kind:
        return "smalltalk", kind
    for word, rid in (("existing", "use_existing"), ("current holdings", "use_existing"),
                      ("plaid", "connect_plaid"), ("upload", "upload_pdf"), ("pdf", "upload_pdf"),
                      ("help", "help"), ("know", "knows"), ("income", "objective:income"),
                      ("total return", "objective:total_return"), ("approve", "approve"),
                      ("yes", "yes"), ("no", "no"), ("confirm", "confirm")):
        if word in q:
            name, _, arg = rid.partition(":")
            return name, arg
    return "unknown", ""


def _chat(t: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    a = STATE["accounts"][t["account_id"]]
    interp = None
    if body.get("action") == "restart":
        _goto(t, "INGEST_CHOICE")
        return _render(t, "Starting over.")
    if body.get("action") == "back":
        prev = t["path"][-2] if len(t["path"]) > 1 else "INGEST_CHOICE"
        _goto(t, prev)
        return _render(t, "Going back — later results were cleared.")
    if body.get("action") == "approve":
        body = {"quick_reply": "approve"}
    if body.get("message"):
        t["history"].append({"role": "user", "text": body["message"], "state": t["state"]})
        name, arg = _intent(t, body["message"])
        interp = dict(intent=name, confidence=0.85, slots={}, needs_confirmation=False)
    elif body.get("quick_reply"):
        t["history"].append({"role": "user", "text": f"[{body['quick_reply']}]", "state": t["state"]})
        name, _, arg = body["quick_reply"].partition(":")
    else:
        return _render(t)
    s, prefix = t["state"], ""
    if name == "back":
        return _chat(t, {"action": "back"})
    if name == "restart":
        return _chat(t, {"action": "restart"})
    if name == "smalltalk":
        step, label = STEP[t["state"]]
        return _render(t, f"{_SMALLTALK_OPENERS[arg]}\n\nWe're on step {step} of 6 ({label.lower()}). "
                          "Use the buttons, type what you'd like, or ask me a question.", interp)
    if s == "INGEST_CHOICE":
        if name == "use_existing" and a["lots"]:
            _goto(t, "TARGET_KNOWLEDGE")
        elif name in ("upload_sample", "connect_plaid"):
            _preview(t, "pdf" if name == "upload_sample" else "plaid")
            _goto(t, "INGEST_REVIEW")
            prefix = ("Parsed the sample statement (SAMPLE — SYNTHETIC DATA)."
                      if name == "upload_sample" else "Connected the demo brokerage (mock Plaid).")
    elif s == "INGEST_REVIEW" and name in ("confirm", "accept_suggestions", "assume_average_cost"):
        rows = [dict(row_id=r["row_id"], lot_ref=r.get("lot_ref"),
                     ticker=(r["suggested_ticker"] if name == "accept_suggestions"
                                                 and r["suggested_ticker"] else r["ticker"]),
                     quantity=r["quantity"], acquired_date=r["acquired_date"],
                     cost_basis_total=r["cost_basis_total"],
                     include=r["include"] or name != "confirm")
                for r in t["preview"]["rows"]]
        try:
            res = _confirm(t, {"rows": rows, "assume_average_cost": name == "assume_average_cost"})
            _goto(t, "TARGET_KNOWLEDGE")
            prefix = f"Saved {res['n_committed']} lots (${res['total_market_value']:,.0f})."
        except _Http as exc:
            prefix = f"I couldn't save yet: {exc.message}."
    elif s == "TARGET_KNOWLEDGE":
        _goto(t, {"knows": "TARGET_PICK_LIST", "help": "Q_OBJECTIVE"}.get(name, s))
    elif s == "Q_OBJECTIVE" and name == "objective":
        t["objective"] = arg
        _goto(t, "Q_CONSTRUCTION")
    elif s == "Q_CONSTRUCTION" and name == "construction":
        t["construction"] = arg
        _goto(t, "TARGET_COMPARE")
    elif s in ("TARGET_PICK_LIST", "TARGET_COMPARE") and name == "choose" and _model(arg):
        t["target_model_id"] = arg
        _goto(t, "TARGET_CONFIRM")
    elif s == "TARGET_CONFIRM":
        _goto(t, {"yes": "TRANSITION_SETUP", "no": "TARGET_KNOWLEDGE"}.get(name, s))
    elif s in ("TRANSITION_SETUP", "TRANSITION_RESULTS") and name == "budget":
        mode, _, val = arg.partition(":")
        budget = float(val) if val else None
        t["setup"] = {"budget_mode": mode, "budget_value": budget, "constraints": {}}
        t["optimization"] = _optimize(t, mode, budget, CHAT_DEFAULT_CONSTRAINTS)
        t["frontier"] = _frontier(t, "tax", 15)
        _goto(t, "TRANSITION_RESULTS")
        prefix = "Ran the optimizer with " + (
            "no budget." if budget is None else f"a ${budget:,.0f} tax budget.")
    elif s == "TRANSITION_RESULTS" and name in ("approve", "adjust"):
        _goto(t, "TRANSITION_APPROVE" if name == "approve" else "TRANSITION_SETUP")
    elif s == "TRANSITION_APPROVE" and name in ("approve", "adjust"):
        if name == "adjust":
            _goto(t, "TRANSITION_SETUP")
        else:
            t["event_id"] = _approve(t)
            _goto(t, "DONE")
            prefix = f"Approved and recorded as event **{t['event_id']}** in the account history."
    elif s == "DONE" and name == "restart":
        _goto(t, "INGEST_CHOICE")
    else:
        prefix = "Sorry, I didn't catch that. You can use the buttons, or ask me a question."
    return _render(t, prefix, interp)


def _approve(t: dict[str, Any]) -> str:
    o = t["optimization"]
    a = STATE["accounts"][t["account_id"]]
    sold = {s["lot_id"] for s in o["trades"]["sells"]}
    a["lots"] = [x for x in a["lots"] if x["lot_id"] not in sold] + [
        dict(lot_id=f"{a['id']}-buy-{b['ticker']}", ticker=b["ticker"], quantity=b["shares"],
             cost_basis_total=b["value"], acquired_date=AS_OF.isoformat(), locked=False)
        for b in o["trades"]["buys"]]
    a["cash"] = o["summary"]["cash_after"]
    a["target_model_id"] = o["target_model_id"]
    a["te"] = o["post"]["te"]
    eid = f"evt-{uuid.uuid4().hex[:8]}"
    STATE["events"][eid] = dict(
        id=eid, account_id=a["id"], date=AS_OF.isoformat(), type="transition",
        trigger="client_request", n_trades=o["summary"]["n_lot_sells"] + o["summary"]["n_buys"],
        turnover=o["summary"]["turnover"], realized_st_gain=o["realized"]["st_gain"],
        realized_lt_gain=o["realized"]["lt_gain"],
        losses_harvested=o["realized"]["st_loss"] + o["realized"]["lt_loss"],
        est_taxes_saved=0.0, te_before=o["pre"]["te"], te_after=o["post"]["te"],
        cash_flow_amount=0.0, note=f"Guided transition into {o['target_model_id']}; approved.")
    c = STATE["clients"][a["client_id"]]
    if c["status"] == "onboarding":
        c["status"] = "on_target"
    return eid


# ================================================================ routing
class _Http(Exception):  # noqa: N818 — internal control flow, not an API error type
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status = status
        self.detail = detail
        self.message = detail if isinstance(detail, str) else detail.get("message", "Error")


def _client_or_404(cid: str) -> dict[str, Any]:
    c = STATE["clients"].get(cid)
    if c is None:
        raise _Http(404, f"Client {cid} not found")
    return c


def _account_or_404(aid: str) -> dict[str, Any]:
    a = STATE["accounts"].get(aid)
    if a is None:
        raise _Http(404, f"Account {aid} not found")
    return a


def _transition_or_404(tid: str) -> dict[str, Any]:
    t = STATE["transitions"].get(tid)
    if t is None:
        raise _Http(404, f"Transition {tid} not found")
    return t


def _scope(cid: str, account_id: str | None) -> list[str]:
    ids = [a["id"] for a in _client_accounts(cid)]
    if account_id:
        if account_id not in ids:
            raise _Http(404, f"Account {account_id} not found for client {cid}")
        return [account_id]
    return ids


def _transition_out(t: dict[str, Any]) -> dict[str, Any]:
    a = STATE["accounts"][t["account_id"]]
    return dict(transition_id=t["id"], client_id=t["client_id"], account_id=t["account_id"],
                state=t["state"], target_model_id=t.get("target_model_id"),
                locked_lot_ids=sorted(t["locks"]),
                account_locked_lot_ids=sorted(x["lot_id"] for x in a["lots"] if x["locked"]),
                has_optimization=bool(t.get("optimization")), has_frontier=bool(t.get("frontier")),
                created_at=f"{AS_OF}T09:00:00Z", updated_at=f"{AS_OF}T09:00:00Z")


def _route(method: str, path: str, body: Any, params: dict[str, Any], files: Any, data: Any) -> Any:
    p = path.rstrip("/")
    g = lambda k, d=None: (params or {}).get(k, d)  # noqa: E731
    if method == "GET" and p == "/auth/me":
        return USER
    # ---- book
    if p == "/book/summary":
        accts = [_account_summary(a) for a in STATE["accounts"].values()]
        tes = [(a["ex_ante_te"], a["market_value"]) for a in accts if a["ex_ante_te"] is not None]
        statuses = {k: 0 for k in ("on_target", "drifting", "needs_review", "onboarding")}
        for c in STATE["clients"].values():
            statuses[c["status"]] += 1
        return dict(data_source="mock_random", as_of=AS_OF.isoformat(),
                    n_clients=len(STATE["clients"]), n_accounts=len(accts),
                    total_aum=round(sum(a["market_value"] for a in accts), 2),
                    taxes_saved_ytd=round(sum(a["taxes_saved_ytd"] for a in accts), 2),
                    taxes_saved_since_inception=round(sum(a["taxes_saved_since_inception"]
                                                          for a in accts), 2),
                    avg_ex_ante_te=round(sum(t * w for t, w in tes) / sum(w for _, w in tes), 5),
                    n_accounts_outside_tolerance=sum(a["outside_tolerance"] for a in accts),
                    clients_by_status=statuses)
    if p == "/book/analytics/tracking-error":
        window = int(g("window", 63))
        series: dict[str, list[float]] = {}
        for aid in STATE["accounts"]:
            for pt in _te_series(aid, window):
                series.setdefault(pt["date"], []).append(pt["te"])
        out = []
        for d in sorted(series):
            v = sorted(series[d])
            q = lambda f, v=v: v[min(len(v) - 1, int(f * (len(v) - 1) + .5))]  # noqa: E731
            out.append(dict(date=d, avg_te=round(sum(v) / len(v), 5), p10=q(.1), p90=q(.9),
                            n_accounts=len(v)))
        return dict(data_source="mock_random", window=window, series=out)
    if p == "/book/analytics/tax-impact":
        gran = g("granularity", "month")
        per = _tax_periods(list(STATE["accounts"]), gran, AS_OF - timedelta(days=3 * 365))
        cum = [0.0] * 6
        rows = []
        for x in per:
            cum = [cum[0] + x["saved"], cum[1] + x["losses"], cum[2] + x["st"], cum[3] + x["lt"],
                   cum[4] + x["st_loss"], cum[5] + x["lt_loss"]]
            rows.append(dict(period=x["period"], taxes_saved=x["saved"], losses_harvested=x["losses"],
                             realized_st_gain=x["st"], realized_lt_gain=x["lt"],
                             realized_st_loss=x["st_loss"], realized_lt_loss=x["lt_loss"],
                             cum_taxes_saved=round(cum[0], 2), cum_losses_harvested=round(cum[1], 2),
                             cum_realized_st_gain=round(cum[2], 2),
                             cum_realized_lt_gain=round(cum[3], 2),
                             cum_realized_st_loss=round(cum[4], 2),
                             cum_realized_lt_loss=round(cum[5], 2)))
        return dict(data_source="mock_random", granularity=gran, periods=rows)
    if p == "/book/analytics/activity":
        gran = g("granularity", "month")
        keys = _periods(AS_OF - timedelta(days=3 * 365), gran)
        counts = {k: dict.fromkeys(EVENT_TYPES, 0) for k in keys}
        for e in STATE["events"].values():
            k = _key(e["date"], gran)
            if k in counts:
                counts[k][e["type"]] += 1
        total_aum = sum(_account_mv(a) for a in STATE["accounts"].values())
        n = len(keys)
        return dict(data_source="mock_random", granularity=gran, periods=[
            dict(period=k, counts=counts[k], total=sum(counts[k].values()),
                 aum=round(total_aum * (0.7 + 0.3 * (i + 1) / n), 2)) for i, k in enumerate(keys)])
    # ---- clients
    if method == "GET" and p == "/clients":
        rows = [_client_row(c) for c in STATE["clients"].values()]
        if g("search"):
            rows = [r for r in rows if g("search").lower() in r["name"].lower()]
        if g("status"):
            rows = [r for r in rows if r["status"] == g("status")]
        rows.sort(key=lambda r: r["name"])
        return dict(data_source="mock_random", total=len(rows), items=rows)
    if method == "POST" and p == "/clients":
        cid = f"cl-{uuid.uuid4().hex[:6]}"
        tp = body["tax_profile"]
        STATE["clients"][cid] = dict(
            id=cid, name=body["name"], email=body["email"], client_type=body["client_type"],
            phone=body.get("phone"), notes=body.get("notes"), status="onboarding",
            onboarded=AS_OF.isoformat(), last_rebalance=None, target=None, te=None, ytd=0,
            tax=(tp["federal_st_rate"], tp["federal_lt_rate"], tp["state"].upper(), tp["state_rate"]))
        return 201, _client_out(STATE["clients"][cid])
    m = re.fullmatch(r"/clients/([^/]+)", p)
    if m:
        c = _client_or_404(m.group(1))
        if method == "DELETE":
            ids = {a["id"] for a in _client_accounts(c["id"])}
            for aid in ids:
                STATE["accounts"].pop(aid, None)
            for eid in [k for k, e in STATE["events"].items() if e["account_id"] in ids]:
                STATE["events"].pop(eid)
            for tid in [k for k, t in STATE["transitions"].items() if t["account_id"] in ids]:
                STATE["transitions"].pop(tid)
            STATE["clients"].pop(c["id"])
            return 204, None
        if method == "PATCH":
            for k in ("name", "email", "phone", "client_type", "notes"):
                if body.get(k) is not None:
                    c[k] = body[k]
            if body.get("tax_profile"):
                f, lt_, st_, sr = c["tax"]
                tpb = body["tax_profile"]
                c["tax"] = (tpb.get("federal_st_rate", f), tpb.get("federal_lt_rate", lt_),
                            tpb.get("state", st_), tpb.get("state_rate", sr))
            return _client_out(c)
        accts = [_account_summary(a) for a in _client_accounts(c["id"])]
        row = _client_row(c)
        return dict(data_source="mock_random", **{k: v for k, v in _client_out(c).items()},
                    accounts=accts, metrics=dict(
                        market_value=row["market_value"], cash=round(sum(a["cash"] for a in accts), 2),
                        n_accounts=len(accts), n_positions=sum(a["n_positions"] for a in accts),
                        ex_ante_te=row["ex_ante_te"], taxes_saved_ytd=row["taxes_saved_ytd"],
                        taxes_saved_since_inception=round(sum(a["taxes_saved_since_inception"]
                                                              for a in accts), 2),
                        unrealized_gain=0.0, last_rebalance_date=row["last_rebalance_date"],
                        first_onboarding_date=min((a["onboarding_date"] for a in accts), default=None)))
    m = re.fullmatch(r"/clients/([^/]+)/accounts", p)
    if m:
        c = _client_or_404(m.group(1))
        if method == "POST":
            aid = f"{c['id']}-acct-{uuid.uuid4().hex[:4]}"
            STATE["accounts"][aid] = dict(
                id=aid, client_id=c["id"], account_type=body["account_type"],
                custodian=body["custodian"], nickname=body.get("nickname"),
                target_model_id=body.get("target_model_id"), market_value=0.0, te=None,
                onboarding_date=AS_OF.isoformat(), lots=[], cash=0.0)
            return 201, _account_summary(STATE["accounts"][aid])
        return dict(data_source="mock_random",
                    items=[_account_summary(a) for a in _client_accounts(c["id"])])
    m = re.fullmatch(r"/clients/([^/]+)/analytics/(tracking-error|tax-savings|summary)", p)
    if m:
        c = _client_or_404(m.group(1))
        ids = _scope(c["id"], g("account_id"))
        kind = m.group(2)
        if kind == "tracking-error":
            window = int(g("window", 63))
            per_date: dict[str, list[float]] = {}
            for aid in ids:
                for pt in _te_series(aid, window):
                    per_date.setdefault(pt["date"], []).append(pt["te"])
            accts = [_account_summary(STATE["accounts"][i]) for i in ids]
            tes = [a["ex_ante_te"] for a in accts if a["ex_ante_te"] is not None]
            return dict(data_source="mock_random", window=window, account_id=g("account_id"),
                        series=[dict(date=d, te=round(sum(v) / len(v), 5))
                                for d, v in sorted(per_date.items())],
                        ex_ante_te=round(sum(tes) / len(tes), 5) if tes else None,
                        events=[dict(event_id=e["id"], account_id=e["account_id"], date=e["date"],
                                     type=e["type"]) for i in ids for e in _acct_events(i)])
        start = min(date.fromisoformat(STATE["accounts"][i]["onboarding_date"]) for i in ids) \
            if ids else AS_OF
        start = max(start, AS_OF - timedelta(days=3 * 365))
        if kind == "tax-savings":
            gran = g("granularity", "month")
            per = _tax_periods(ids, gran, start)
            cum, rows = 0.0, []
            for x in per:
                cum += x["saved"]
                rows.append(dict(period=x["period"], taxes_saved=x["saved"],
                                 losses_harvested=x["losses"], cum_taxes_saved=round(cum, 2),
                                 realized_st_gain=x["st"], realized_lt_gain=x["lt"],
                                 realized_st_loss=x["st_loss"], realized_lt_loss=x["lt_loss"]))
            accts = [_account_summary(STATE["accounts"][i]) for i in ids]
            return dict(data_source="mock_random", granularity=gran, account_id=g("account_id"),
                        periods=rows,
                        taxes_saved_ytd=round(sum(a["taxes_saved_ytd"] for a in accts), 2),
                        taxes_saved_since_inception=round(sum(a["taxes_saved_since_inception"]
                                                              for a in accts), 2))
        years: dict[int, dict[str, float]] = {}
        for i in ids:
            for e in _acct_events(i):
                y = years.setdefault(int(e["date"][:4]), dict(st=0, lt=0, losses=0, saved=0,
                                                               n=0, turn=0))
                y["st"] += e["realized_st_gain"]
                y["lt"] += e["realized_lt_gain"]
                y["losses"] += e["losses_harvested"]
                y["saved"] += e["est_taxes_saved"]
                y["turn"] += e["turnover"]
                y["n"] += e["type"] == "rebalance"
        mv_now = sum(_account_mv(STATE["accounts"][i]) for i in ids)
        ms = _months(start, AS_OF)
        hist = [dict(date=f"{k}-28", value=round(mv_now * (0.75 + 0.25 * j / max(len(ms) - 1, 1)), 2))
                for j, k in enumerate(ms)] if ids else []
        return dict(data_source="mock_random", account_id=g("account_id"), aum_history=hist,
                    by_year=[dict(year=y, realized_st_gain=round(v["st"], 2),
                                  realized_lt_gain=round(v["lt"], 2),
                                  losses_harvested=round(v["losses"], 2),
                                  taxes_saved=round(v["saved"], 2), n_rebalances=int(v["n"]),
                                  turnover=round(v["turn"] / max(len(ids), 1), 4))
                             for y, v in sorted(years.items())],
                    avg_annual_turnover=0.42 if years else None)
    m = re.fullmatch(r"/clients/([^/]+)/events", p)
    if m:
        c = _client_or_404(m.group(1))
        ids = _scope(c["id"], g("account_id"))
        evs = [e for i in ids for e in _acct_events(i)
               if (not g("type") or e["type"] == g("type"))
               and (not g("from") or e["date"] >= g("from")) and (not g("to") or e["date"] <= g("to"))]
        evs.sort(key=lambda e: e["date"], reverse=True)
        return dict(total=len(evs), items=[_event_out(e) for e in evs])
    m = re.fullmatch(r"/events/([^/]+)", p)
    if m:
        e = STATE["events"].get(m.group(1))
        if e is None:
            raise _Http(404, f"Event {m.group(1)} not found")
        return dict(_event_out(e), client_id=STATE["accounts"][e["account_id"]]["client_id"],
                    trades=_event_trades(e))
    # ---- accounts
    m = re.fullmatch(r"/accounts/([^/]+)(?:/analytics/(exposures|tracking-error|tax-history))?", p)
    if m:
        a = _account_or_404(m.group(1))
        if m.group(2) == "exposures":
            return dict(data_source="mock_random", account_id=a["id"],
                        target_model_id=a["target_model_id"], **_exposures(a, a["target_model_id"]))
        if m.group(2) == "tracking-error":
            window = int(g("window", 63))
            return dict(data_source="mock_random", window=window, account_id=a["id"],
                        series=_te_series(a["id"], window), ex_ante_te=a["te"],
                        events=[dict(event_id=e["id"], account_id=a["id"], date=e["date"],
                                     type=e["type"]) for e in _acct_events(a["id"])])
        if m.group(2) == "tax-history":
            gran = g("granularity", "month")
            per = _tax_periods([a["id"]], gran, date.fromisoformat(a["onboarding_date"]))
            rows = [dict(period=x["period"], realized_st_gain=x["st"], realized_lt_gain=x["lt"],
                         losses_harvested=x["losses"], est_tax_paid=round(x["st"] * .3 + x["lt"] * .2, 2),
                         taxes_saved=x["saved"]) for x in per]
            tot = {k: round(sum(r[k] for r in rows), 2) for k in
                   ("realized_st_gain", "realized_lt_gain", "losses_harvested", "est_tax_paid",
                    "taxes_saved")}
            return dict(data_source="mock_random", account_id=a["id"], granularity=gran,
                        taxable=a["account_type"] not in ("ira", "roth_ira"), periods=rows,
                        totals=dict(period="total", **tot))
        summary = _account_summary(a)
        tw = {h[0]: h[3] for h in (_model(a["target_model_id"]) or {"holdings": []})["holdings"]}
        lots, holdings, split = [], {}, dict(st_gains=0.0, st_losses=0.0, lt_gains=0.0, lt_losses=0.0)
        for lot in a["lots"]:
            px = _price(lot["ticker"])
            mv = lot["quantity"] * px
            gain = mv - lot["cost_basis_total"]
            term = _term(lot)
            split[f"{term.lower()}_{'gains' if gain >= 0 else 'losses'}"] += gain
            lots.append(dict(lot_id=lot["lot_id"], lot_ref=lot.get("lot_ref"), account_id=a["id"],
                             ticker=lot["ticker"],
                             quantity=lot["quantity"], cost_basis_total=lot["cost_basis_total"],
                             acquired_date=lot["acquired_date"], holding_period=term,
                             current_price=px, market_value=round(mv, 2),
                             unrealized_gain=round(gain, 2), locked=lot["locked"], source="seed",
                             basis_unknown=False))
            h = holdings.setdefault(lot["ticker"], dict(q=0.0, cost=0.0, n=0, locked=False))
            h["q"] += lot["quantity"]
            h["cost"] += lot["cost_basis_total"]
            h["n"] += 1
            h["locked"] |= lot["locked"]
        tot = summary["market_value"] or 1
        return dict(data_source="mock_random", account=summary,
                    client_name=STATE["clients"][a["client_id"]]["name"],
                    unrealized=dict({k: round(v, 2) for k, v in split.items()},
                                    net=round(sum(split.values()), 2)),
                    holdings=sorted([dict(ticker=t_, name=SECURITIES[t_]["name"],
                                          sector=SECURITIES[t_]["sector"], quantity=round(h["q"], 3),
                                          price=_price(t_), market_value=round(h["q"] * _price(t_), 2),
                                          weight=round(h["q"] * _price(t_) / tot, 6),
                                          target_weight=tw.get(t_, 0.0),
                                          cost_basis_total=round(h["cost"], 2),
                                          unrealized_gain=round(h["q"] * _price(t_) - h["cost"], 2),
                                          n_lots=h["n"], locked=h["locked"])
                                     for t_, h in holdings.items()], key=lambda x: -x["market_value"]),
                    lots=lots)
    # ---- models
    if p == "/models":
        items = [_model_summary(mp) for mp in MODELS
                 if not g("objective") or mp["objective"] == g("objective")]
        return dict(data_source="mock_random", total=len(items), items=items)
    if p == "/models/compare":
        unknown = [i for i in body["model_ids"] if not _model(i)]
        if unknown:
            raise _Http(404, f"Unknown model(s): {', '.join(unknown)}")
        _account_or_404(body["account_id"])
        return _compare(list(dict.fromkeys(body["model_ids"])), body["account_id"])
    m = re.fullmatch(r"/models/([^/]+)", p)
    if m:
        mp = _model(m.group(1))
        if mp is None:
            raise _Http(404, f"Model {m.group(1)} not found")
        return dict(_model_summary(mp), data_source="mock_random",
                    holdings=[dict(ticker=t_, name=n, security_type="fund", asset_class="US Equity",
                                   expense_ratio_bps=er, weight=w) for t_, n, er, w in mp["holdings"]],
                    regime_performance=None)
    # ---- transitions
    if method == "POST" and p == "/transitions":
        c = _client_or_404(body["client_id"])
        a = _account_or_404(body["account_id"])
        if a["client_id"] != c["id"]:
            raise _Http(404, f"Account {a['id']} not found for {c['id']}")
        tid = f"trn-{uuid.uuid4().hex[:8]}"
        STATE["transitions"][tid] = dict(id=tid, client_id=c["id"], account_id=a["id"],
                                         state="INGEST_CHOICE", path=["INGEST_CHOICE"], locks=[],
                                         target_model_id=a["target_model_id"], history=[])
        return 201, _transition_out(STATE["transitions"][tid])
    m = re.fullmatch(r"/transitions/([^/]+)"
                     r"(?:/(chat|back|history|locks|optimize|frontier|trades\.csv|summary\.pdf))?", p)
    if m:
        t = _transition_or_404(m.group(1))
        sub = m.group(2)
        if sub is None:
            return _transition_out(t)
        if sub == "chat":
            return _chat(t, body or {})
        if sub == "back":
            to = body["to_state"]
            if to not in t["path"]:
                raise _Http(422, f"Can only go back to a visited earlier step: {to}")
            for k in (("optimization", "frontier")
                      if ORDER.index(to) < ORDER.index("TRANSITION_RESULTS") else ()):
                t.pop(k, None)
            _goto(t, to)
            return _render(t, "Going back — later results were cleared.")
        if sub == "history":
            return dict(transition_id=t["id"], state=t["state"], items=t["history"])
        if sub == "locks":
            a = STATE["accounts"][t["account_id"]]
            known = {x["lot_id"] for x in a["lots"]}
            bad = sorted(set(body["lot_ids"]) - known)
            if bad:
                raise _Http(422, f"Lots not in account {a['id']}: {', '.join(bad[:10])}")
            t["locks"] = sorted(set(body["lot_ids"]))
            t.pop("optimization", None)
            t.pop("frontier", None)
            return _transition_out(t)
        if sub == "optimize":
            target = body.get("target_model_id") or t.get("target_model_id")
            if not target:
                raise _Http(422, "No target model: choose one (target_model_id) before optimizing")
            t["target_model_id"] = target
            t["optimization"] = _optimize(t, body.get("budget_mode", "tax"), body.get("budget_value"),
                                          body.get("constraints"))
            return t["optimization"]
        if sub == "frontier":
            target = body.get("target_model_id") or t.get("target_model_id")
            if not target:
                raise _Http(422, "No target model: choose one (target_model_id) before optimizing")
            t["target_model_id"] = target
            t["frontier"] = _frontier(t, body.get("budget_mode", "tax"), int(body.get("n_points", 15)))
            return t["frontier"]
        o = t.get("optimization")
        if not o:
            raise _Http(404, "No optimization yet for this transition")
        if sub == "trades.csv":
            buf = io.StringIO()
            buf.write(f'"# Transition Studio — {DISCLAIMER} SYNTHETIC DATA."\n')
            buf.write("side,ticker,lot_id,shares,price,value,cost_basis,realized_gain,term,acquired_date\n")
            for s_ in o["trades"]["sells"]:
                buf.write(f"SELL,{s_['ticker']},{s_['lot_id']},{s_['shares']},{s_['price']},"
                          f"{s_['proceeds']},{s_['cost_basis']},{s_['realized_gain']},{s_['term']},"
                          f"{s_['acquired_date']}\n")
            for b in o["trades"]["buys"]:
                buf.write(f"BUY,{b['ticker']},,{b['shares']},{b['price']},{b['value']},,,,\n")
            return ("text/csv", buf.getvalue().encode())
        return ("application/pdf", _tiny_pdf(f"Transition summary (mock) - {o['target_model_id']} - "
                                             f"est. tax ${o['realized']['est_tax']:,.0f}"))
    # ---- ingest
    if p == "/ingest/pdf":
        t = _transition_or_404((data or {}).get("transition_id", ""))
        content = files["file"][1] if files else b""
        if not content.startswith(b"%PDF"):
            raise _Http(422, "Not a PDF file")
        return _preview(t, "pdf")
    if p == "/ingest/plaid/link-token":
        return dict(link_token="link-mock-000000", expiration=(AS_OF + timedelta(days=1)).isoformat(),
                    mode="mock", mock_public_token="public-mock-transition-studio")
    if p == "/ingest/plaid/exchange":
        t = _transition_or_404(body["transition_id"])
        if not body["public_token"].startswith("public-"):
            raise _Http(502, "Invalid public token")
        return _preview(t, "plaid")
    m = re.fullmatch(r"/ingest/([^/]+)/confirm", p)
    if m:
        return _confirm(_transition_or_404(m.group(1)), body or {})
    raise _Http(404, "Not Found")


def _tiny_pdf(text: str) -> bytes:
    safe = text.replace("(", "[").replace(")", "]")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
             b"/Resources << /Font << /F1 5 0 R >> >> >>"),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def handle(method: str, path: str, *, token: str | None, json: Any = None,
           params: dict[str, Any] | None = None, files: Any = None, data: Any = None) -> httpx.Response:
    """Entry point used by ApiClient when USE_MOCKS=true."""
    _bootstrap()
    req = httpx.Request(method, f"http://mock{path}")
    if path == "/auth/login":
        if (json or {}).get("email") == USER["email"] and (json or {}).get("password") == "demo1234":
            return httpx.Response(200, json={"access_token": TOKEN, "token_type": "bearer",
                                             "user": USER}, request=req)
        return httpx.Response(401, json={"detail": "Invalid email or password"}, request=req)
    if token != TOKEN:
        return httpx.Response(401, json={"detail": "Not authenticated"}, request=req)
    try:
        out = _route(method.upper(), path, json, params or {}, files, data)
    except _Http as exc:
        return httpx.Response(exc.status, json={"detail": exc.detail}, request=req)
    status = 200
    if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], int):
        status, out = out
    if isinstance(out, tuple):  # (content-type, bytes)
        return httpx.Response(200, content=out[1], headers={"content-type": out[0]}, request=req)
    return httpx.Response(status, json=out, request=req)
