"""Transition analytics: the account today, after the proposed trades, and the target model, side by
side through the Model Builder lens. Every portfolio is measured against the target.

Data: GET /transitions/{id}/analytics (three Model Builder reports); only layout happens here.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
from dash import dcc, html

from components.common import graph, sim_badge
from components.model_builder import FACTOR_COLORS, _p
from components.risk_panel import _card
from services import format as fmt
from theme import tokens as t

KEYS = ("current", "transition", "target")
LABELS = {"current": "Current", "transition": "Transition", "target": "Target"}
# validated categorical set (CVD ΔE ≥ 19); values always also shown in tables
COLORS = {"current": "#C98A3E", "transition": t.BRAND_PRIMARY, "target": "#1A5E96"}
HIDDEN = {"height": "0", "overflow": "hidden", "visibility": "hidden"}  # same as ts.js
TABS = [{"label": "Overview", "value": "overview"}, {"label": "Equity", "value": "equity"},
        {"label": "Fixed income", "value": "fi"}, {"label": "Risk", "value": "risk"},
        {"label": "Performance", "value": "perf"}]


# ------------------------------------------------------------------ shell
def card(key: str, data_source: str | None) -> html.Div:
    """Placeholder in the results canvas; a callback fills it once the canvas mounts."""
    return html.Div(
        [html.Div([html.H2("Portfolio analytics", className="ts-h2"),
                   sim_badge(data_source)],
                  className="ts-row ts-gap-2"),
         html.P("Today's portfolio, the portfolio after the proposed trades, and the target "
                "model, side by side. The target is the reference for every comparison.",
                className="ts-sub ts-mt-1 ts-mb-4"),
         dcc.Store(id={"type": "ws-pa-key", "id": "c"}, data=key),
         dcc.RadioItems(id={"type": "ws-pa-tab", "id": "c"}, value="overview", options=TABS, inline=True,
                        className="ts-segmented ts-mb-4"),
         dcc.Loading(html.Div(html.P("Loading analytics…", className="ts-mm-empty"),
                              id={"type": "ws-pa", "id": "c"}, className="ts-pa-body"),
                     type="dot", color=t.BRAND_PRIMARY, delay_show=200)],
        className="ts-card ts-p-5 ts-mt-6 ts-pa",
    )


def legend(a: dict[str, Any]) -> html.Div:
    subs = {"current": "The account today",
            "transition": "After the proposed trades",
            "target": f"{a['target_model_id']} · {a['target_name']}"}
    return html.Div([html.Div([html.Span(className="ts-pa-swatch",
                                         style={"background": COLORS[k]}),
                               html.Span(LABELS[k], className="ts-fw-600 ts-c-navy"),
                               html.Span(subs[k], className="ts-c-ink600")],
                              className="ts-pa-key") for k in KEYS], className="ts-pa-legend")


def view(a: dict[str, Any]) -> list[html.Div]:
    """All five tabs, rendered once; the tab switch only toggles visibility (no reflow)."""
    return [legend(a), *[html.Div(_tab(a, x["value"]), id={"type": "ws-pa-pane", "id": x["value"]},
                                  style={} if x["value"] == "overview" else HIDDEN)
                         for x in TABS]]


# ------------------------------------------------------------------ building blocks
def _ths() -> list[html.Th]:
    return [html.Th([html.Span(className="ts-pa-dot", style={"background": COLORS[k]}), LABELS[k]],
                    className="ts-num") for k in KEYS]


def _head(first: str = "") -> html.Thead:
    return html.Thead(html.Tr([html.Th(first), *_ths()]))


def _table(rows: list[tuple[str, list[str]]], first: str = "", cls: str = "") -> html.Table:
    """Label + one value per portfolio (Current · Transition · Target)."""
    return html.Table([_head(first), html.Tbody([
        html.Tr([html.Td(lbl), *[html.Td(v, className="ts-num" + (" ts-fw-600" if i == 1 else ""))
                                 for i, v in enumerate(vals)]], className=cls)
        for lbl, vals in rows])], className="ts-risk-table ts-pa-table")


def _weights(reps: dict[str, dict[str, Any]], field: str) -> tuple[list[str], dict[str, list]]:
    """Union of category names (order: first seen, target first) and each portfolio's weights."""
    names: list[str] = []
    for k in ("target", "transition", "current"):
        for x in reps[k][field]:
            if x["name"] not in names:
                names.append(x["name"])
    vals = {k: [next((x["weight"] for x in reps[k][field] if x["name"] == n), 0.0) for n in names]
            for k in KEYS}
    keep = [i for i, _ in enumerate(names) if any(vals[k][i] > 1e-6 for k in KEYS)]
    return [names[i] for i in keep], {k: [vals[k][i] for i in keep] for k in KEYS}


def _grouped(names: list[str], vals: dict[str, list[float]]) -> go.Figure:
    fig = go.Figure()
    for k in KEYS:
        fig.add_bar(name=LABELS[k], y=names, x=vals[k], orientation="h",
                    marker=dict(color=COLORS[k], cornerradius=3),
                    hovertemplate=f"{LABELS[k]} · %{{y}}: %{{x:.1%}}<extra></extra>")
    fig.update_layout(barmode="group", bargap=0.28, bargroupgap=0.12, hovermode="closest",
                      margin=dict(l=4, r=12, t=4, b=24), showlegend=False,
                      xaxis=dict(tickformat=".0%", showgrid=True, gridcolor=t.SURFACE_100,
                                 rangemode="tozero"),
                      yaxis=dict(autorange="reversed", automargin=True, showgrid=False))
    return fig


def _bars(reps: dict[str, dict[str, Any]], field: str, title: str, sub: str,
          empty: str) -> html.Div:
    names, vals = _weights(reps, field)
    if not names:
        return _card(title, sub, html.P(empty, className="ts-sub"))
    return _card(title, sub, graph(_grouped(names, vals), 40 + 46 * len(names)))


def _char_rows(reps: dict[str, dict[str, Any]], field: str) -> list[tuple[str, list[str]]]:
    by = {k: {c["label"]: c["model"] for c in reps[k][field]} for k in KEYS}
    return [(lbl, [by[k].get(lbl, "—") for k in KEYS]) for lbl in by["target"]]


def _na(x: float | None, f: str) -> str:
    return "—" if x is None else f.format(x)


# ------------------------------------------------------------------ tabs
def _tab(a: dict[str, Any], tab: str) -> list[Any]:
    reps = a["reports"]
    if tab == "overview":
        return _overview(a, reps)
    if tab == "equity":
        return _equity(reps)
    if tab == "fi":
        return _fi(reps)
    if tab == "risk":
        return _risk(a, reps)
    return _perf(reps)


def _overview(a: dict[str, Any], reps: dict[str, dict[str, Any]]) -> list[Any]:
    te = a["te_ex_ante"]

    def row(lbl: str, fn: Any) -> tuple[str, list[str]]:
        return lbl, [fn(reps[k], k) for k in KEYS]

    rows = [
        row("Holdings", lambda r, _: str(r["n_holdings"])),
        row("Equity", lambda r, _: fmt.pct(r["equity_pct"], 1)),
        row("Fixed income", lambda r, _: fmt.pct(r["fixed_income_pct"], 1)),
        row("Cash", lambda r, _: fmt.pct(r["cash_pct"], 1)),
        row("Avg. duration", lambda r, _: _na(r["avg_duration"], "{:.1f} yrs")),
        row("P/E ratio", lambda r, _: _na(r["pe_ratio"], "{:.1f}x")),
        row("P/B ratio", lambda r, _: _na(r["pb_ratio"], "{:.2f}x")),
        row("Avg. net expense ratio", lambda r, _: f"{r['net_expense_ratio_bps'] / 100:.2f}%"),
        row("Yield", lambda r, _: fmt.pct(r["yield"], 2)),
        row("Volatility (ex-ante)", lambda r, _: fmt.pct(r["volatility"], 1)),
        row("Tracking error vs target", lambda _, k: fmt.pct(te[k], 2)),
        row("Beta to the market", lambda r, _: f"{r['beta']:.2f}"),
    ]
    return [
        html.Div([
            _card("Key characteristics", "Tracking error is the optimizer's ex-ante estimate",
                  _table(rows)),
            _bars(reps, "asset_allocation", "Asset allocation", "Share of each portfolio",
                  "No holdings"),
        ], className="ts-risk-grid-2 ts-mb-5"),
        _card("Holdings", "Weight in each portfolio; change = transition − current",
              html.Div(_holdings(reps), className="ts-table-scroll ts-pa-holdings")),
    ]


def _holdings(reps: dict[str, dict[str, Any]]) -> html.Table:
    info: dict[str, dict[str, Any]] = {}
    w = {k: {} for k in KEYS}
    for k in KEYS:
        for h in reps[k]["holdings"]:
            info.setdefault(h["ticker"], h)
            w[k][h["ticker"]] = h["weight"]
    order = sorted(info, key=lambda x: (-w["target"].get(x, 0), -w["transition"].get(x, 0),
                                        -w["current"].get(x, 0)))
    rows = []
    for tk in order:
        vals = [w[k].get(tk, 0.0) for k in KEYS]
        d = vals[1] - vals[0]
        rows.append(html.Tr([
            html.Td([html.Span(tk, className="ts-fw-600 ts-c-navy"),
                     html.Span(f" {info[tk]['name']}", className="ts-c-ink600")]),
            html.Td(info[tk]["asset_class"], className="ts-c-ink600"),
            *[html.Td("—" if v <= 0 else fmt.pct(v, 1),
                      className="ts-num" + (" ts-fw-600" if i == 1 else ""))
              for i, v in enumerate(vals)],
            html.Td("" if abs(d) < 5e-4 else fmt.signed_pct(d, 1),
                    className="ts-num " + ("ts-c-positive" if d > 0 else "ts-c-negative"))]))
    return html.Table([html.Thead(html.Tr([
        html.Th("Holding"), html.Th("Asset class"), *_ths(),
        html.Th("Change", className="ts-num")])), html.Tbody(rows)],
        className="ts-risk-table ts-pa-table")


def _equity(reps: dict[str, dict[str, Any]]) -> list[Any]:
    if all(reps[k]["equity_pct"] <= 0 for k in KEYS):
        return [html.P("None of the portfolios holds equity.", className="ts-sub")]
    sub = "Share of each portfolio's equity sleeve"
    none = "No equity"
    note = _absent(reps, "equity_pct", "equity")
    boxes = html.Div([html.Div([html.P(LABELS[k], className="ts-pa-box-title",
                                       style={"borderColor": COLORS[k]}),
                                _box(reps[k]["style_box"])], className="ts-pa-box")
                      for k in KEYS], className="ts-pa-boxes")
    return [
        note,
        html.Div([_bars(reps, "equity_size", "Equity size", sub, none),
                  _bars(reps, "equity_style", "Equity style", sub, none)],
                 className="ts-risk-grid-2 ts-mb-5"),
        _card("Style box", "Size × style, share of the equity sleeve", boxes, "ts-mb-5"),
        html.Div([_bars(reps, "equity_regions", "Equity region", sub, none),
                  _card("Equity characteristics", "Equity sleeve of each portfolio",
                        _table(_char_rows(reps, "equity_characteristics")))],
                 className="ts-risk-grid-2 ts-mb-5"),
        _bars(reps, "equity_sectors", "Equity sectors (GICS)", sub, none),
    ]


def _absent(reps: dict[str, dict[str, Any]], field: str, what: str) -> html.P | None:
    gone = [LABELS[k] for k in KEYS if reps[k][field] <= 0]
    if not gone:
        return None
    verb = "holds" if len(gone) == 1 else "hold"
    return html.P(f"{' and '.join(gone)} {verb} no {what}, so only the other portfolios appear "
                  "below.", className="ts-sub ts-mb-4")


def _box(box: list[list[float]]) -> html.Table:
    rows = []
    for size, r in zip(["Large", "Mid", "Small"], box, strict=True):
        rows.append(html.Tr([html.Th(size[0], className="ts-bld-box-h", title=size),
                             *[html.Td(fmt.pct(v, 0), className="ts-bld-box-cell",
                                       style={"background": f"rgba(0,61,92,{0.06 + 0.8 * v:.2f})",
                                              "color": "#fff" if v > 0.4 else t.INK_900})
                               for v in r]]))
    return html.Table([html.Thead(html.Tr([html.Th(""), html.Th("Val"), html.Th("Blend"),
                                           html.Th("Gro")])), html.Tbody(rows)],
                      className="ts-bld-box ts-pa-box-table")


def _fi(reps: dict[str, dict[str, Any]]) -> list[Any]:
    if all(reps[k]["fixed_income_pct"] <= 0 for k in KEYS):
        return [html.P("None of the portfolios holds fixed income.", className="ts-sub")]
    sub = "Share of each portfolio's bond sleeve"
    none = "No fixed income"
    return [
        _absent(reps, "fixed_income_pct", "fixed income"),
        html.Div([_bars(reps, "fi_rating", "Credit rating", sub, none),
                  _bars(reps, "fi_sectors", "Fixed income sector", sub, none)],
                 className="ts-risk-grid-2 ts-mb-5"),
        html.Div([_bars(reps, "fi_maturity", "Maturity", sub, none),
                  _bars(reps, "fi_regions", "Fixed income region", sub, none)],
                 className="ts-risk-grid-2 ts-mb-5"),
        _card("Fixed income characteristics", "Bond sleeve of each portfolio",
              _table(_char_rows(reps, "fi_characteristics"))),
    ]


def _risk(a: dict[str, Any], reps: dict[str, dict[str, Any]]) -> list[Any]:
    te = a["te_ex_ante"]
    kpis = _table([
        ("Volatility (ex-ante, annualized)", [fmt.pct(reps[k]["volatility"], 2) for k in KEYS]),
        ("Tracking error vs target (ex-ante)", [fmt.pct(te[k], 2) for k in KEYS]),
        ("Tracking error vs target (hypothetical)",
         [fmt.pct(reps[k]["tracking_error"], 2) for k in KEYS]),
        ("Beta to the market", [f"{reps[k]['beta']:.2f}" for k in KEYS]),
    ])
    factors: list[str] = []
    for k in KEYS:
        for f in reps[k]["factors"]:
            if f["factor"] not in factors:
                factors.append(f["factor"])
    fv = {k: {f["factor"]: f for f in reps[k]["factors"]} for k in KEYS}
    fig = go.Figure()
    ys = [LABELS[k] for k in KEYS]
    for i, name in enumerate(factors):
        fig.add_bar(name=name, y=ys, orientation="h",
                    x=[fv[k].get(name, {}).get("model_vol", 0.0) for k in KEYS],
                    customdata=[fv[k].get(name, {}).get("model_pct", 0.0) for k in KEYS],
                    marker=dict(color=FACTOR_COLORS[i % len(FACTOR_COLORS)],
                                line=dict(color="#fff", width=1)),
                    hovertemplate=f"<b>{name}</b><br>%{{y}}: %{{x:.2%}} of volatility"
                                  "<br>%{customdata:.1%} of variance<extra></extra>")
    fig.update_layout(barmode="relative", bargap=0.4, hovermode="closest", showlegend=False,
                      margin=dict(l=4, r=12, t=4, b=24),
                      xaxis=dict(tickformat=".0%", showgrid=True, gridcolor=t.SURFACE_100,
                                 zeroline=True, zerolinecolor=t.INK_300),
                      yaxis=dict(autorange="reversed", automargin=True, showgrid=False))
    f_rows = [html.Tr([html.Td([html.Span(className="ts-bld-swatch",
                                          style={"background": FACTOR_COLORS[i % len(
                                              FACTOR_COLORS)]}), name]),
                       *[html.Td(_p(fv[k].get(name, {}).get("model_vol", 0.0)),
                                 className="ts-num" + (" ts-fw-600" if j == 1 else ""))
                         for j, k in enumerate(KEYS)]]) for i, name in enumerate(factors)]
    f_rows.append(html.Tr([html.Td(html.Strong("Total volatility")),
                           *[html.Td(html.Strong(fmt.pct(reps[k]["volatility"], 2)),
                                     className="ts-num") for k in KEYS]],
                          className="ts-bld-total-row"))
    f_table = html.Table([_head("Factor"), html.Tbody(f_rows)],
                         className="ts-risk-table ts-pa-table")

    tails = {k: {(x["days"], x["confidence"]): x for x in reps[k]["tail"]} for k in KEYS}
    tail_rows = []
    for key, x in tails["target"].items():
        tail_rows.append((f"VaR · {x['horizon']} · {x['confidence']:.0%}",
                          [fmt.pct(tails[k].get(key, {}).get("var", 0.0), 2) for k in KEYS]))
        tail_rows.append((f"CVaR · {x['horizon']} · {x['confidence']:.0%}",
                          [fmt.pct(tails[k].get(key, {}).get("cvar", 0.0), 2) for k in KEYS]))
    stress = {k: {x["name"]: x for x in reps[k]["stress_tests"]} for k in KEYS}
    s_rows = []
    for name, x in stress["target"].items():
        cells = []
        for j, k in enumerate(KEYS):
            v = stress[k].get(name, {}).get("pnl_pct")
            cells.append(html.Td("—" if v is None else fmt.signed_pct(v, 1),
                                 className="ts-num " + ("ts-fw-600 " if j == 1 else "")
                                 + ("ts-c-negative" if (v or 0) < 0 else "ts-c-positive")))
        s_rows.append(html.Tr([html.Td([html.Div(name, className="ts-fw-500"),
                                        html.Div(x["description"], className="ts-stress-desc")]),
                               *cells]))
    return [
        _card("Risk summary", None, kpis, "ts-mb-5"),
        _card("Risk factor decomposition",
              "Volatility split into factor contributions (stacked) for each portfolio",
              html.Div([graph(fig, 190), html.Div(f_table, className="ts-table-scroll ts-mt-3")]),
              "ts-mb-5"),
        _card("Stress tests", "Estimated impact of hypothetical scenarios",
              html.Div(html.Table([_head("Scenario"), html.Tbody(s_rows)],
                                  className="ts-risk-table ts-pa-table"),
                       className="ts-table-scroll"), "ts-mb-5"),
        _card("Tail risk", "Historical simulation over the last 2 years (loss shown positive)",
              _table(tail_rows)),
    ]


def _perf(reps: dict[str, dict[str, Any]]) -> list[Any]:
    fig = go.Figure()
    for k in KEYS:
        p = reps[k]["performance"]
        fig.add_scatter(x=[q["d"] for q in p], y=[q["model"] for q in p], name=LABELS[k],
                        mode="lines", line=dict(color=COLORS[k], width=2,
                                                dash="dot" if k == "target" else "solid"),
                        hovertemplate=LABELS[k] + " $%{y:,.0f}<extra></extra>")
    fig.update_layout(margin=dict(l=56, r=12, t=8, b=28), hovermode="x unified",
                      legend=dict(orientation="h", y=1.08, x=0),
                      yaxis=dict(tickprefix="$", tickformat=",.0f"))
    stats = {k: {s["label"]: s["model"] for s in reps[k]["perf_stats"]} for k in KEYS}
    s_rows = [(lbl.replace("Tracking error", "Tracking error vs target"),
               [stats[k].get(lbl, "—") for k in KEYS]) for lbl in stats["target"]]
    years = {k: {y["year"]: y["model"] for y in reps[k]["calendar_years"]} for k in KEYS}
    y_rows = [(str(y), [fmt.signed_pct(years[k].get(y, 0.0), 1) for k in KEYS])
              for y in years["target"]]
    return [
        _card("Hypothetical growth of $10,000",
              "Each portfolio's weights held constant over the simulated history. "
              "Not a track record.", graph(fig, 300), "ts-mb-5"),
        html.Div([_card("Statistics", None, _table(s_rows)),
                  _card("Calendar-year returns", None, _table(y_rows, "Year"))],
                 className="ts-risk-grid-2"),
        html.Details([html.Summary("How these numbers are calculated"),
                      html.Ul([html.Li(x) for x in reps["target"]["methodology"]])],
                     className="ts-risk-method ts-mt-5"),
    ]
