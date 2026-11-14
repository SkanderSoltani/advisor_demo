"""Model Builder pieces: header + stepper, guide panel, build card, analytics tabs, scale card.

Analytics come from POST /model-builder/analyze; nothing is computed here except layout.
"""

from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
import plotly.graph_objects as go
from dash import dcc, html

from components.common import graph
from components.risk_panel import _allocation, _bar_list, _card, _hist_figure, _tail_table
from components.shell import icon
from services import format as fmt
from theme import tokens as t

STEPS = ["Build", "Analyze & refine", "Scale into a line", "Save"]
STEP_INDEX = {"build": 1, "analyze": 2, "scale": 3, "save": 4, "done": 4}
TABS = [{"label": "Overview", "value": "overview"}, {"label": "Equity", "value": "equity"},
        {"label": "Fixed income", "value": "fi"}, {"label": "Risk", "value": "risk"},
        {"label": "Performance", "value": "perf"}]
OBJECTIVE_OPTIONS = [{"value": "total_return", "label": "Total Return"},
                     {"value": "income", "label": "Income"},
                     {"value": "tax_efficient", "label": "Tax Efficient"}]
# factor stack: fixed categorical order (navy → blues → teal → warm gray; specific last, gray)
FACTOR_COLORS = [t.BRAND_NAVY, t.BRAND_PRIMARY, t.TEAL, "#7FCFEF", "#8C8279", t.BRAND_PRIMARY_DARK,
                 "#99DBF2", "#5B8A72", t.INK_300]
SIZE_COLORS = {"Large": t.BRAND_NAVY, "Mid": t.BRAND_PRIMARY, "Small": "#7FCFEF"}
STYLE_COLORS = {"Value": t.TEAL, "Blend": t.BRAND_PRIMARY, "Growth": t.BRAND_NAVY}


# ------------------------------------------------------------------ header
def builder_header(step: str) -> html.Header:
    cur = STEP_INDEX.get(step, 1)
    done = step == "done"
    items = []
    for i, label in enumerate(STEPS, start=1):
        complete = i < cur or (done and i == cur)
        state = "done" if complete else "current" if i == cur else "todo"
        items.append(html.Span([html.Span(icon("check", 13) if complete else str(i),
                                          className="ts-step-dot"), label],
                               className=f"ts-step ts-step--{state}"))
    return html.Header(
        [html.Div([html.A(icon("arrow-left", 18), href="/models", className="ts-ws-back",
                          **{"aria-label": "Back to model management"}),
                   html.Div([html.P("Model Builder", className="ts-ws-client"),
                             html.P("Build · analyze · scale into a line",
                                    className="ts-ws-account")])],
                  className="ts-row ts-gap-4"),
         html.Nav(items, className="ts-steps", **{"aria-label": "Model builder progress"}),
         html.A("Exit", href="/models", className="ts-ws-exit")],
        className="ts-topbar ts-ws-header",
    )


# ------------------------------------------------------------------ guide
def guide_panel() -> html.Aside:
    return html.Aside(
        [
            html.Div(
                [html.Div([icon("sparkles", 15), "AI guide"], className="ts-ai-eyebrow"),
                 html.Div(id="mb-thread", className="ts-thread", **{"aria-live": "polite"}),
                 html.Div([html.Span(), html.Span(), html.Span()], id="mb-typing",
                          className="ts-typing ts-hidden"),
                 html.Div(id="mb-chips")],
                id="mb-scroll", className="ts-chat-scroll",
            ),
            html.Div(html.Div(
                [icon("message-circle", 16, "ts-c-ink600"),
                 dcc.Input(id="mb-input", type="text", debounce=False, n_submit=0,
                           placeholder="e.g. add SCHX 30% · less risk · scale to 10 models",
                           className="ts-chat-input", autoComplete="off"),
                 html.Button(icon("send", 16), id="mb-send", n_clicks=0, type="button",
                             className="ts-chat-icon ts-c-primary",
                             **{"aria-label": "Send message"})],
                className="ts-chat-bar"), className="ts-chat-foot"),
        ],
        className="ts-chat ts-chat--narrow",
    )


def chips(replies: list[dict[str, Any]]) -> html.Div:
    return html.Div([html.Button(r["label"], id={"type": "mb-qr", "id": r["id"]}, n_clicks=0,
                                 type="button", className="ts-chip-btn") for r in replies],
                    className="ts-chips")


# ------------------------------------------------------------------ build card
def _section(title: str, sub: str, body: Any, id_: str | None = None,
             right: Any = None) -> html.Section:
    kw = {"id": id_} if id_ else {}
    return html.Section(
        [html.Div([html.Div([html.H2(title, className="ts-h2"),
                             html.P(sub, className="ts-sub ts-mt-1")]), right],
                  className="ts-row ts-between ts-items-start ts-gap-3 ts-mb-4"),
         body],
        className="ts-card ts-p-5 ts-mb-6", **kw)


def build_card() -> html.Section:
    tools = html.Div(
        [
            html.Div([html.Label("Model name", className="ts-bld-label"),
                      dcc.Input(id="mb-name", type="text", value="My model", debounce=True,
                                className="ts-input")], className="ts-bld-field"),
            html.Div([html.Label("Start from a model", className="ts-bld-label"),
                      dmc.Select(id="mb-start", data=[], searchable=True, clearable=True,
                                 placeholder="Copy an existing model…", className="ts-mm-select",
                                 comboboxProps={"withinPortal": True, "zIndex": 400})],
                     className="ts-bld-field"),
            html.Div([html.Label("Import a file", className="ts-bld-label"),
                      dcc.Upload(html.Div([icon("upload", 16), html.Span(" Excel, CSV or PDF")],
                                          className="ts-bld-upload"),
                                 id="mb-upload", accept=".xlsx,.xls,.csv,.pdf",
                                 max_size=5 * 1024 * 1024),
                      html.Div(["Sample: ",
                                html.Button("Excel", id="mb-sample-xlsx", n_clicks=0,
                                            type="button", className="ts-link-btn"), " · ",
                                html.Button("PDF", id="mb-sample-pdf", n_clicks=0, type="button",
                                            className="ts-link-btn")],
                               className="ts-sub ts-mt-1")],
                     className="ts-bld-field"),
        ],
        className="ts-bld-tools",
    )
    add = html.Div(
        [dmc.Select(id="mb-search", data=[], searchable=True, clearable=True, limit=40,
                    placeholder="Search tickers — funds and stocks in the universe",
                    nothingFoundMessage="No match", className="ts-bld-search",
                    leftSection=icon("search", 15),
                    comboboxProps={"withinPortal": True, "zIndex": 400}),
         dmc.NumberInput(id="mb-add-w", value=5, min=0, max=100, step=1, decimalScale=2,
                         suffix="%", className="ts-num-input ts-bld-addw",
                         **{"aria-label": "Weight to add"}),
         html.Button([icon("plus", 15), " Add"], id="mb-add", n_clicks=0, type="button",
                     className="ts-btn ts-btn-secondary")],
        className="ts-bld-addrow",
    )
    foot = html.Div(
        [html.Span(id="mb-total", className="ts-mm-w-total"),
         html.Div([html.Button("Normalize to 100%", id="mb-normalize", n_clicks=0, type="button",
                               className="ts-btn ts-btn-secondary ts-btn-sm"),
                   html.Button("Clear", id="mb-clear", n_clicks=0, type="button",
                               className="ts-btn ts-btn-secondary ts-btn-sm"),
                   html.Button([icon("chart-pie", 15), " Run analytics"], id="mb-run", n_clicks=0,
                               type="button", className="ts-btn ts-btn-primary ts-btn-sm")],
                  className="ts-row ts-gap-2 ts-wrap")],
        className="ts-row ts-between ts-items-center ts-mt-3 ts-wrap ts-gap-2",
    )
    return _section("1 · Build the model",
                    "Import a file, copy an existing model, or search the universe and add "
                    "holdings. Edit weights directly.",
                    html.Div([tools, html.Div(id="mb-import-note"), add,
                              html.Div(id="mb-holdings", className="ts-mt-3"), foot]))


def holdings_editor(holdings: dict[str, float], names: dict[str, dict[str, Any]]) -> Any:
    if not holdings:
        return html.P("No holdings yet. Add a ticker above, import a file or start from a model.",
                      className="ts-mm-empty")
    rows = []
    for tk, w in sorted(holdings.items(), key=lambda kv: -kv[1]):
        info = names.get(tk, {})
        rows.append(html.Tr([
            html.Td([html.Div(tk, className="ts-fw-600 ts-c-navy"),
                     html.Div(info.get("name", ""), className="ts-mm-prod-name")]),
            html.Td(info.get("asset_class", ""), className="ts-c-ink600"),
            html.Td(f"{info.get('expense_ratio_bps', 0):g} bps", className="ts-num ts-c-ink600"),
            html.Td(dmc.NumberInput(id={"type": "mb-w", "t": tk}, value=round(w * 100, 4),
                                    min=0, max=100, step=1, decimalScale=2, suffix="%",
                                    hideControls=True, className="ts-num-input ts-bld-w",
                                    **{"aria-label": f"{tk} weight"}), className="ts-num"),
            html.Td(html.Button(icon("x", 14), id={"type": "mb-rm", "t": tk}, n_clicks=0,
                                type="button", className="ts-icon-btn is-danger",
                                title=f"Remove {tk}", **{"aria-label": f"Remove {tk}"}),
                    className="ts-num"),
        ]))
    return html.Div(html.Table(
        [html.Thead(html.Tr([html.Th("Holding"), html.Th("Asset class"),
                             html.Th("Expense", className="ts-num"),
                             html.Th("Weight", className="ts-num"), html.Th("")])),
         html.Tbody(rows)], className="ts-mm-table ts-bld-table"), className="ts-mm-table-wrap")


# ------------------------------------------------------------------ analytics
def analytics_card() -> html.Section:
    return _section("2 · Analytics",
                    "Simulated numbers from the synthetic market — not real data. Re-run after "
                    "each change.",
                    html.Div([html.Div(id="mb-bench"),
                              dcc.RadioItems(id="mb-tab", value="overview", options=TABS,
                                             inline=True, className="ts-segmented ts-mb-4"),
                              dcc.Loading(html.Div(id="mb-analytics",
                                                   children=_empty_analytics()),
                                          type="dot", color=t.BRAND_PRIMARY, delay_show=300,
                                          overlay_style={"visibility": "visible",
                                                         "opacity": .5})]),
                    right=html.Span(id="mb-sim"))


def _empty_analytics() -> html.P:
    return html.P("Run analytics to see characteristics, exposures, risk and hypothetical "
                  "performance.", className="ts-mm-empty")


def bench_banner(r: dict[str, Any]) -> html.Div:
    b = r["benchmark"]
    warn = [html.P(w, className="ts-bld-warn") for w in r["warnings"]]
    return html.Div(
        [html.Div([icon("target", 16), html.Span("Benchmark: "), html.Strong(b["name"]),
                   html.Span(f" · auto-selected, closest to the model's "
                             f"{fmt.pct(r['equity_pct'], 0)} equity", className="ts-c-ink600")],
                  className="ts-bld-bench"), *warn],
        className="ts-mb-4")


def _kpi(label: str, value: str, sub: str | None = None) -> html.Div:
    return html.Div([html.P(label, className="ts-kpi-label"),
                     html.P(value, className="ts-kpi-value ts-kpi-value--lg ts-tone-navy"),
                     html.P(sub, className="ts-kpi-sub") if sub else None],
                    className="ts-card ts-kpi")


def _donut(items: list[dict[str, Any]], colors: dict[str, str], center: str) -> go.Figure:
    items = [x for x in items if x["weight"] > 0]
    fig = go.Figure(go.Pie(
        labels=[x["name"] for x in items], values=[x["weight"] for x in items], hole=0.62,
        sort=False, direction="clockwise",
        marker=dict(colors=[colors.get(x["name"], t.INK_300) for x in items],
                    line=dict(color="#fff", width=2)),
        textinfo="none", hovertemplate="%{label}: %{percent}<extra></extra>"))
    fig.update_layout(margin=dict(l=4, r=4, t=4, b=4), showlegend=True, hovermode="closest",
                      legend=dict(orientation="v", x=1.02, y=0.5, yanchor="middle"),
                      annotations=[dict(text=center, showarrow=False,
                                        font=dict(size=13, color=t.INK_600))])
    return fig


def _legend_values(items: list[dict[str, Any]]) -> html.Div:
    return html.Div([html.Div([html.Span(x["name"]), html.Span(fmt.pct(x["weight"], 1),
                                                                className="ts-num ts-fw-600")],
                              className="ts-bld-legrow") for x in items], className="ts-bld-leg")


def _style_box(box: list[list[float]]) -> html.Table:
    top = max((v for r in box for v in r), default=0) or 1
    rows = []
    for size, r in zip(["Large", "Mid", "Small"], box, strict=True):
        cells = [html.Td(fmt.pct(v, 0), className="ts-bld-box-cell",
                         style={"background": f"rgba(0,61,92,{0.08 + 0.75 * v / top:.2f})",
                                "color": "#fff" if v / top > 0.45 else t.INK_900})
                 for v in r]
        rows.append(html.Tr([html.Th(size, className="ts-bld-box-h"), *cells]))
    return html.Table([html.Thead(html.Tr([html.Th(""), html.Th("Value"), html.Th("Blend"),
                                           html.Th("Growth")])), html.Tbody(rows)],
                      className="ts-bld-box")


def _cmp_table(rows: list[dict[str, Any]], bench: str) -> html.Table:
    return html.Table(
        [html.Thead(html.Tr([html.Th(""), html.Th("Model", className="ts-num"),
                             html.Th(bench, className="ts-num")])),
         html.Tbody([html.Tr([html.Td(x["label"]), html.Td(x["model"], className="ts-num ts-fw-600"),
                              html.Td(x["benchmark"], className="ts-num ts-c-ink600")])
                     for x in rows])],
        className="ts-risk-table")


def _holdings_table(r: dict[str, Any]) -> html.Table:
    rows = [html.Tr([html.Td([html.Span(h["ticker"], className="ts-fw-600 ts-c-navy"),
                              html.Span(f" {h['name']}", className="ts-c-ink600")]),
                     html.Td(h["asset_class"], className="ts-c-ink600"),
                     html.Td(fmt.pct(h["weight"], 1), className="ts-num ts-fw-500"),
                     html.Td(f"{h['expense_ratio_bps'] / 100:.2f}%", className="ts-num"),
                     html.Td(f"{h['er_contribution_bps']:.2f} bps", className="ts-num ts-c-ink600")])
            for h in r["holdings"]]
    rows.append(html.Tr([html.Td(html.Strong("Total")), html.Td(""),
                         html.Td(html.Strong("100.0%"), className="ts-num"),
                         html.Td(html.Strong(f"{r['net_expense_ratio_bps'] / 100:.2f}%"),
                                 className="ts-num"),
                         html.Td(f"{r['net_expense_ratio_bps']:.2f} bps", className="ts-num")],
                        className="ts-bld-total-row"))
    return html.Table([html.Thead(html.Tr([html.Th("Holding"), html.Th("Asset class"),
                                           html.Th("Weight", className="ts-num"),
                                           html.Th("Net expense ratio", className="ts-num"),
                                           html.Th("Contribution", className="ts-num")])),
                       html.Tbody(rows)], className="ts-risk-table")


def _factor_figure(r: dict[str, Any]) -> go.Figure:
    fig = go.Figure()
    names = ["Model", r["benchmark"]["short"]]
    for i, f in enumerate(r["factors"]):
        fig.add_bar(name=f["factor"], y=names, x=[f["model_vol"], f["bench_vol"]],
                    orientation="h", marker=dict(color=FACTOR_COLORS[i % len(FACTOR_COLORS)],
                                                 line=dict(color="#fff", width=1)),
                    customdata=[f["model_pct"], f["bench_pct"]],
                    hovertemplate=f"<b>{f['factor']}</b><br>%{{y}}: %{{x:.2%}} of volatility"
                                  "<br>%{customdata:.1%} of variance<extra></extra>")
    fig.update_layout(barmode="relative", margin=dict(l=4, r=12, t=4, b=24), bargap=0.45,
                      hovermode="closest", showlegend=False,
                      xaxis=dict(tickformat=".0%", showgrid=True, gridcolor=t.SURFACE_100,
                                 zeroline=True, zerolinecolor=t.INK_300),
                      yaxis=dict(autorange="reversed", automargin=True, showgrid=False))
    return fig


def _p(x: float, n: int = 2) -> str:
    return fmt.pct(0.0 if abs(x) < 0.5 * 10 ** -(n + 2) else x, n)


def _factor_table(r: dict[str, Any]) -> html.Table:
    rows = [html.Tr([html.Td([html.Span(className="ts-bld-swatch",
                                        style={"background": FACTOR_COLORS[i % len(FACTOR_COLORS)]}),
                              f["factor"]]),
                     html.Td(_p(f["model_vol"]), className="ts-num ts-fw-600"),
                     html.Td(_p(f["model_pct"], 0), className="ts-num ts-c-ink600"),
                     html.Td(_p(f["bench_vol"]), className="ts-num"),
                     html.Td(_p(f["bench_pct"], 0), className="ts-num ts-c-ink600")])
            for i, f in enumerate(r["factors"])]
    rows.append(html.Tr([html.Td(html.Strong("Total volatility")),
                         html.Td(html.Strong(fmt.pct(r["volatility"], 2)), className="ts-num"),
                         html.Td("100%", className="ts-num ts-c-ink600"),
                         html.Td(html.Strong(fmt.pct(r["bench_volatility"], 2)),
                                 className="ts-num"),
                         html.Td("100%", className="ts-num ts-c-ink600")],
                        className="ts-bld-total-row"))
    return html.Table([html.Thead(html.Tr([html.Th("Factor"), html.Th("Model", className="ts-num"),
                                           html.Th("of var.", className="ts-num"),
                                           html.Th("Bench.", className="ts-num"),
                                           html.Th("of var.", className="ts-num")])),
                       html.Tbody(rows)], className="ts-risk-table")


def _stress_table(r: dict[str, Any]) -> html.Table:
    bs = r["bench_stress"]
    rows = []
    for x in r["stress_tests"]:
        b = bs.get(x["name"])
        rows.append(html.Tr([
            html.Td([html.Div(x["name"], className="ts-fw-500"),
                     html.Div(x["description"], className="ts-stress-desc")]),
            html.Td(fmt.signed_pct(x["pnl_pct"], 1), className="ts-num ts-fw-600 " + (
                "ts-c-negative" if x["pnl_pct"] < 0 else "ts-c-positive")),
            html.Td(fmt.signed_money(x["pnl_usd"]), className="ts-num ts-c-ink600"),
            html.Td("—" if b is None else fmt.signed_pct(b, 1), className="ts-num")]))
    return html.Table([html.Thead(html.Tr([html.Th("Scenario"), html.Th("Model", className="ts-num"),
                                           html.Th("per $1M", className="ts-num"),
                                           html.Th(r["benchmark"]["short"], className="ts-num")])),
                       html.Tbody(rows)], className="ts-risk-table")


def _perf_figure(r: dict[str, Any]) -> go.Figure:
    p = r["performance"]
    x = [q["d"] for q in p]
    fig = go.Figure()
    fig.add_scatter(x=x, y=[q["model"] for q in p], name="Model", mode="lines",
                    line=dict(color=t.BRAND_PRIMARY, width=2),
                    hovertemplate="Model $%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=x, y=[q["benchmark"] for q in p], name=r["benchmark"]["short"],
                    mode="lines", line=dict(color=t.BRAND_NAVY, width=2, dash="dot"),
                    hovertemplate=r["benchmark"]["short"] + " $%{y:,.0f}<extra></extra>")
    fig.update_layout(margin=dict(l=56, r=12, t=8, b=28), hovermode="x unified",
                      legend=dict(orientation="h", y=1.08, x=0),
                      yaxis=dict(tickprefix="$", tickformat=",.0f"))
    return fig


def _years_table(r: dict[str, Any]) -> html.Table:
    return html.Table(
        [html.Thead(html.Tr([html.Th("Year"), html.Th("Model", className="ts-num"),
                             html.Th(r["benchmark"]["short"], className="ts-num"),
                             html.Th("Difference", className="ts-num")])),
         html.Tbody([html.Tr([html.Td(str(y["year"])),
                              html.Td(fmt.signed_pct(y["model"], 1), className="ts-num ts-fw-600"),
                              html.Td(fmt.signed_pct(y["benchmark"], 1), className="ts-num"),
                              html.Td(fmt.signed_pct(y["model"] - y["benchmark"], 1),
                                      className="ts-num ts-c-ink600")])
                     for y in r["calendar_years"]])], className="ts-risk-table")


def _na(text: str) -> html.P:
    return html.P(text, className="ts-sub")


def analytics_view(r: dict[str, Any], tab: str) -> list[Any]:
    b = r["benchmark"]["short"]
    if tab == "overview":
        d = r["avg_duration"]
        kpis = html.Div([
            _kpi("Holdings", str(r["n_holdings"]), f"{r['n_underlying']} look-through"),
            _kpi("Equity / FI / cash", f"{r['equity_pct'] * 100:.0f} / "
                 f"{r['fixed_income_pct'] * 100:.0f} / {r['cash_pct'] * 100:.0f}"),
            _kpi("Avg. duration", "—" if d is None else f"{d:.1f} yrs", "bond sleeve"),
            _kpi("P/E ratio", "—" if r["pe_ratio"] is None else f"{r['pe_ratio']:.1f}x",
                 "equity sleeve"),
            _kpi("P/B ratio", "—" if r["pb_ratio"] is None else f"{r['pb_ratio']:.2f}x",
                 "equity sleeve"),
            _kpi("Avg. net expense ratio", f"{r['net_expense_ratio_bps'] / 100:.2f}%",
                 f"{r['net_expense_ratio_bps']:.1f} bps"),
            _kpi("Yield", fmt.pct(r["yield"], 2)),
            _kpi("Volatility", fmt.pct(r["volatility"], 1), f"{b}: {fmt.pct(r['bench_volatility'], 1)}"),
        ], className="ts-bld-kpis ts-mb-5")
        perf = {s["label"]: s for s in r["perf_stats"]}
        eq = {c["label"]: c for c in r["equity_characteristics"]}
        fi = {c["label"]: c for c in r["fi_characteristics"]}
        vs = [{"label": "Equity share", "model": fmt.pct(r["equity_pct"], 0),
               "benchmark": f"{r['benchmark']['equity_pct']}%"},
              {"label": "Volatility", "model": fmt.pct(r["volatility"], 1),
               "benchmark": fmt.pct(r["bench_volatility"], 1)},
              {"label": "Annualized return (hyp.)", "model": perf["Annualized return"]["model"],
               "benchmark": perf["Annualized return"]["benchmark"]},
              {"label": "Max drawdown (hyp.)", "model": perf["Max drawdown"]["model"],
               "benchmark": perf["Max drawdown"]["benchmark"]},
              {"label": "Duration", "model": fi["Effective duration"]["model"],
               "benchmark": fi["Effective duration"]["benchmark"]},
              {"label": "P/E ratio", "model": eq["P/E ratio"]["model"],
               "benchmark": eq["P/E ratio"]["benchmark"]},
              {"label": "Tracking error", "model": fmt.pct(r["tracking_error"], 2),
               "benchmark": "—"}]
        return [kpis,
                _card("Holdings", "Weight and net expense ratio of each holding",
                      html.Div(_holdings_table(r), className="ts-table-scroll"), "ts-mb-5"),
                html.Div([
                    _card("Asset allocation", "Look-through, share of the model",
                          _allocation(r["asset_allocation"])),
                    _card("Model vs benchmark", r["benchmark"]["name"], _cmp_table(vs, b)),
                ], className="ts-risk-grid-2")]
    if tab == "equity":
        if r["equity_pct"] <= 0:
            return [_na("This model holds no equity.")]
        donuts = html.Div([
            _card("Equity size", "Share of the equity sleeve", html.Div(
                [graph(_donut(r["equity_size"], SIZE_COLORS, "Size"), 170),
                 _legend_values(r["equity_size"])])),
            _card("Equity style", "Share of the equity sleeve", html.Div(
                [graph(_donut(r["equity_style"], STYLE_COLORS, "Style"), 170),
                 _legend_values(r["equity_style"])])),
            _card("Style box", "Size × style, share of the equity sleeve",
                  _style_box(r["style_box"])),
        ], className="ts-risk-grid-3 ts-mb-5")
        return [donuts, html.Div([
            _card("Equity region", "Share of the equity sleeve", _bar_list(r["equity_regions"])),
            _card("Equity sectors (GICS)", "Share of the equity sleeve",
                  _bar_list(r["equity_sectors"])),
            _card("Equity characteristics", f"Model vs {b}",
                  _cmp_table(r["equity_characteristics"], b)),
        ], className="ts-risk-grid-3")]
    if tab == "fi":
        if r["fixed_income_pct"] <= 0:
            return [_na("This model holds no fixed income.")]
        return [html.Div([
            _card("Credit rating", "Share of the bond sleeve", _bar_list(r["fi_rating"])),
            _card("Fixed income sector", "Share of the bond sleeve", _bar_list(r["fi_sectors"])),
            _card("Maturity", "Share of the bond sleeve", _bar_list(r["fi_maturity"], tone="navy")),
        ], className="ts-risk-grid-3 ts-mb-5"), html.Div([
            _card("Fixed income region", "Share of the bond sleeve", _bar_list(r["fi_regions"])),
            _card("Fixed income characteristics", f"Model vs {b}",
                  _cmp_table(r["fi_characteristics"], b)),
        ], className="ts-risk-grid-2")]
    if tab == "risk":
        kpis = html.Div([
            _kpi("Volatility", fmt.pct(r["volatility"], 1), "ex-ante, annualised"),
            _kpi(f"{b} volatility", fmt.pct(r["bench_volatility"], 1)),
            _kpi("Tracking error", fmt.pct(r["tracking_error"], 2), f"vs {b}"),
            _kpi("Beta", f"{r['beta']:.2f}", "to the market"),
        ], className="ts-bld-kpis ts-mb-5")
        return [kpis,
                _card("Risk factor decomposition",
                      "Volatility split into factor contributions (stacked), model vs benchmark",
                      html.Div([graph(_factor_figure(r), 150),
                                html.Div(_factor_table(r), className="ts-table-scroll")],
                               className="ts-bld-factor"), "ts-mb-5"),
                _card("Tail risk", "Daily returns of today's weights over the last 2 years",
                      html.Div([graph(_hist_figure(r), 220),
                                html.Div(_tail_table(r), className="ts-table-scroll")],
                               className="ts-bld-factor"), "ts-mb-5"),
                _card("Stress tests", f"Estimated impact of hypothetical scenarios, model vs {b}",
                      html.Div(_stress_table(r), className="ts-table-scroll"))]
    # performance
    return [_card("Hypothetical growth of $10,000",
                  f"Today's weights held constant over the simulated history vs {b}. "
                  "Not a track record.", graph(_perf_figure(r), 280), "ts-mb-5"),
            html.Div([
                _card("Statistics", None, _cmp_table(
                    [{"label": s["label"], "model": s["model"], "benchmark": s["benchmark"]}
                     for s in r["perf_stats"]], b)),
                _card("Calendar-year returns", None,
                      html.Div(_years_table(r), className="ts-table-scroll")),
            ], className="ts-risk-grid-2"),
            html.Details([html.Summary("How these numbers are calculated"),
                          html.Ul([html.Li(x) for x in r["methodology"]])],
                         className="ts-risk-method ts-mt-5")]


# ------------------------------------------------------------------ scale card
def scale_card() -> html.Section:
    controls = html.Div(
        [html.Div([html.Label("Number of models", className="ts-bld-label"),
                   dmc.NumberInput(id="mb-n", value=10, min=1, max=21, step=1,
                                   className="ts-num-input")], className="ts-bld-field"),
         html.Div([html.Label("From equity", className="ts-bld-label"),
                   dmc.NumberInput(id="mb-lo", value=10, min=0, max=100, step=5, suffix="%",
                                   className="ts-num-input")], className="ts-bld-field"),
         html.Div([html.Label("To equity", className="ts-bld-label"),
                   dmc.NumberInput(id="mb-hi", value=100, min=0, max=100, step=5, suffix="%",
                                   className="ts-num-input")], className="ts-bld-field"),
         html.Button([icon("layers", 15), " Preview line"], id="mb-preview", n_clicks=0,
                     type="button", className="ts-btn ts-btn-secondary ts-bld-preview-btn")],
        className="ts-bld-scale-controls")
    save = html.Div(
        [html.Div([html.Label("Line name", className="ts-bld-label"),
                   dcc.Input(id="mb-line-name", type="text", debounce=True,
                             placeholder="e.g. Growth & Income Models", className="ts-input")],
                  className="ts-bld-field ts-bld-grow"),
         html.Div([html.Label("Category", className="ts-bld-label"),
                   dmc.Select(id="mb-objective", data=OBJECTIVE_OPTIONS, value="total_return",
                              allowDeselect=False, className="ts-mm-select",
                              comboboxProps={"withinPortal": True, "zIndex": 400})],
                  className="ts-bld-field"),
         html.Button([icon("save", 15), " Save line"], id="mb-save", n_clicks=0, type="button",
                     className="ts-btn ts-btn-primary ts-bld-preview-btn")],
        className="ts-bld-scale-controls ts-mt-4")
    return _section("3 · Scale into a line",
                    "Same equity mix and bond mix at every level; only the two sleeves are "
                    "resized (cash stays as in your model).",
                    html.Div([controls,
                              dcc.Loading(html.Div(id="mb-line", className="ts-mt-4"),
                                          type="dot", color=t.BRAND_PRIMARY, delay_show=300),
                              save, html.Div(id="mb-save-note", className="ts-mt-3")]),
                    id_="mb-scale-card")


def line_preview(models: list[dict[str, Any]]) -> Any:
    if not models:
        return html.P("Preview the line to see each model.", className="ts-mm-empty")
    rows = []
    for m in models:
        top = sorted(m["holdings"].items(), key=lambda kv: -kv[1])[:4]
        rows.append(html.Tr([
            html.Td(html.Span(m["label"], className="ts-mm-risk")),
            html.Td(html.Div([html.Span([html.B(tk), f" {w * 100:.1f}%"],
                                        className="ts-chip ts-mm-chip") for tk, w in top]
                             + ([html.Span(f"+{len(m['holdings']) - 4}",
                                           className="ts-chip ts-mm-chip")]
                                if len(m["holdings"]) > 4 else []), className="ts-mm-chips")),
            html.Td(fmt.pct(m["volatility"], 1), className="ts-num"),
            html.Td(fmt.pct(m["yield"], 2), className="ts-num"),
            html.Td(f"{m['expense_ratio_bps']:.1f} bps", className="ts-num"),
            html.Td(m["benchmark"], className="ts-num ts-c-ink600"),
        ]))
    return html.Div(html.Table(
        [html.Thead(html.Tr([html.Th("Model"), html.Th("Top holdings"),
                             html.Th("Volatility", className="ts-num"),
                             html.Th("Yield", className="ts-num"),
                             html.Th("Fee", className="ts-num"),
                             html.Th("Benchmark", className="ts-num")])),
         html.Tbody(rows)], className="ts-mm-table ts-bld-line-table"),
        className="ts-mm-table-wrap")
