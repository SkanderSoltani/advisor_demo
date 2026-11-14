"""Point-in-time "Risk & exposures" panel, shared by the client book and the client page.

Only plots the API's saved report (GET /book/risk, GET /clients/{id}/risk); nothing is computed
here except formatting.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
from dash import dcc, html

from components.common import graph, kpi_card, skeleton
from components.shell import icon
from services import format as fmt
from theme import tokens as t

LOSS, GAIN = t.NEGATIVE, t.POSITIVE


# ------------------------------------------------------------------ layout shell
def risk_section(prefix: str, title: str, subtitle: str) -> html.Section:
    """Collapsible card: closed by default; the numbers load the first time it is opened."""
    return html.Section(
        [
            dcc.Store(id=f"{prefix}-risk-loaded", data=None),  # scope currently shown
            html.Div(
                [
                    html.Div(
                        [
                            html.Div([html.H2(title, className="ts-h2"),
                                      html.Span(id=f"{prefix}-risk-badge")],
                                     className="ts-row ts-gap-2"),
                            html.P(subtitle, id=f"{prefix}-risk-sub", className="ts-sub ts-mt-1"),
                            html.P(id=f"{prefix}-risk-asof", className="ts-risk-asof ts-mt-1"),
                        ]
                    ),
                    html.Div(
                        [
                            html.Button([icon("refresh-cw", 15), " Recalculate"],
                                        id=f"{prefix}-risk-refresh", n_clicks=0, type="button",
                                        title="Generate the numbers again from current holdings",
                                        className="ts-btn ts-btn-secondary ts-btn-sm",
                                        style={"display": "none"}),
                            html.Button(id=f"{prefix}-risk-toggle", n_clicks=0, type="button",
                                        className="ts-btn ts-btn-secondary ts-btn-sm",
                                        children=toggle_label(False),
                                        **{"aria-expanded": "false",
                                           "aria-controls": f"{prefix}-risk-panel"}),
                        ],
                        className="ts-row ts-gap-2",
                    ),
                ],
                className="ts-row ts-between ts-items-start",
            ),
            html.Div(
                dcc.Loading(
                    html.Div(id=f"{prefix}-risk-body",
                             children=[skeleton(96, cls="ts-mb-4"), skeleton(260)]),
                    type="dot", color=t.BRAND_PRIMARY, delay_show=300,
                    overlay_style={"visibility": "visible", "opacity": .5},
                ),
                id=f"{prefix}-risk-panel", className="ts-mt-5", style={"display": "none"},
            ),
        ],
        className="ts-card ts-p-5 ts-mb-8",
        id=f"{prefix}-risk",
    )


def toggle_label(is_open: bool) -> list[Any]:
    return ([icon("chevron-up", 16), " Hide analytics"] if is_open
            else [icon("chevron-down", 16), " Show analytics"])


# ------------------------------------------------------------------ pieces
def _card(title: str, sub: str | None, body: Any, cls: str = "") -> html.Div:
    return html.Div(
        [html.H3(title, className="ts-risk-card-title"),
         html.P(sub, className="ts-sub ts-mb-3") if sub else None,
         body],
        className=f"ts-risk-card {cls}".strip(),
    )


def _bar_list(items: list[dict[str, Any]], *, limit: int | None = None,
              tone: str = "primary") -> html.Div:
    """Name · bar · % rows (bar length relative to the largest item)."""
    items = items[:limit] if limit else items
    top = max((abs(x["weight"]) for x in items), default=0) or 1
    return html.Div(
        [html.Div(
            [html.Span(x["name"], className="ts-bar-name", title=x["name"]),
             html.Span(html.Span(className=f"ts-bar-fill ts-bar-{tone}"
                                 + (" is-cash" if x["name"] == "Cash" else ""),
                                 style={"width": f"{abs(x['weight']) / top * 100:.1f}%"}),
                       className="ts-bar-track"),
             html.Span(fmt.pct(x["weight"], 1), className="ts-bar-val ts-num")],
            className="ts-bar-row",
            title=f"{x['name']}: {fmt.pct(x['weight'], 2)} · {fmt.money_full(x['market_value'])}"
            if "market_value" in x else None,
        ) for x in items],
        className="ts-bar-list",
    )


def _allocation(items: list[dict[str, Any]]) -> html.Div:
    """Asset classes grouped: Equity and Fixed Income get a total row, then their classes."""
    top = max((x["weight"] for x in items), default=0) or 1
    groups: dict[str, list[dict[str, Any]]] = {}
    for x in items:
        groups.setdefault(x.get("group") or x["name"], []).append(x)

    def row(name: str, w: float, mv: float, cls: str, fill: str) -> html.Div:
        return html.Div(
            [html.Span(name, className="ts-bar-name", title=name),
             html.Span(html.Span(className=f"ts-bar-fill {fill}",
                                 style={"width": f"{max(w, 0) / top * 100:.1f}%"}),
                       className="ts-bar-track"),
             html.Span(fmt.pct(w, 1), className="ts-bar-val ts-num")],
            className=f"ts-bar-row {cls}".strip(),
            title=f"{name}: {fmt.pct(w, 2)} · {fmt.money_full(mv)}",
        )

    rows: list[Any] = []
    for g, xs in groups.items():
        if len(xs) > 1:
            rows.append(row(g, sum(x["weight"] for x in xs), sum(x["market_value"] for x in xs),
                            "is-group", "ts-bar-navy"))
            rows += [row(x["name"], x["weight"], x["market_value"], "is-child", "ts-bar-primary")
                     for x in xs]
        else:
            x = xs[0]
            rows.append(row(x["name"], x["weight"], x["market_value"], "is-group",
                            "ts-bar-navy is-cash" if x["name"] == "Cash" else "ts-bar-navy"))
    return html.Div(rows, className="ts-bar-list")


def _kpis(r: dict[str, Any]) -> html.Div:
    tail = {(x["days"], x["confidence"]): x for x in r["tail"]}
    v95, v99 = tail[(1, 0.95)], tail[(1, 0.99)]
    return html.Div(
        [
            kpi_card("Volatility (1σ, annual)", fmt.pct(r["volatility"], 1),
                     sub=f"Realized 2Y: {fmt.pct(r['realized_volatility'], 1)}",
                     tooltip="Ex-ante standard deviation of returns from the factor model"),
            kpi_card("Beta", f"{r['beta']:.2f}", sub="vs synthetic market index",
                     tooltip="Sensitivity to the cap-weighted market, last 2 years"),
            kpi_card("1-day VaR 95%", fmt.pct(v95["var"]), "negative",
                     sub=fmt.money(v95["var_usd"]),
                     tooltip="Loss not exceeded on 95% of days (historical simulation)"),
            kpi_card("1-day CVaR 95%", fmt.pct(v95["cvar"]), "negative",
                     sub=fmt.money(v95["cvar_usd"]),
                     tooltip="Average loss on the worst 5% of days"),
            kpi_card("1-day VaR 99%", fmt.pct(v99["var"]), "negative",
                     sub=fmt.money(v99["var_usd"]),
                     tooltip="Loss not exceeded on 99% of days"),
            kpi_card("Systematic risk", fmt.pct(r["systematic_pct"], 0),
                     sub=f"Specific {fmt.pct(r['specific_pct'], 0)}",
                     tooltip="Share of variance explained by market, sector and style factors"),
        ],
        className="ts-kpi-grid-6 ts-mb-5",
    )


def _decomp_figure(rows: list[dict[str, Any]], vol: float) -> go.Figure:
    rows = list(reversed(rows))
    y = [x["factor"] for x in rows]
    v = [x["vol_contribution"] for x in rows]
    fig = go.Figure(go.Bar(
        x=v, y=y, orientation="h",
        marker=dict(color=[t.BRAND_PRIMARY if a >= 0 else t.INK_300 for a in v],
                    cornerradius=4),
        text=[f"{x['pct_of_variance']:.0%}" if abs(x["pct_of_variance"]) >= 0.005 else "<1%"
              for x in rows], textposition="outside",
        cliponaxis=False, textfont=dict(color=t.INK_600, size=11),
        customdata=[[x["pct_of_variance"], "—" if x["exposure"] is None else f"{x['exposure']:.2f}"]
                    for x in rows],
        hovertemplate="<b>%{y}</b><br>Contribution %{x:.2%} of " + f"{vol:.2%}"
                      + " volatility<br>Share of variance %{customdata[0]:.1%}"
                        "<br>Exposure %{customdata[1]}<extra></extra>",
    ))
    fig.update_layout(margin=dict(l=4, r=40, t=4, b=24), hovermode="closest", bargap=0.3,
                      xaxis=dict(tickformat=".0%", showgrid=True, gridcolor=t.SURFACE_100,
                                 zeroline=True, zerolinecolor=t.INK_300),
                      yaxis=dict(showgrid=False, automargin=True, ticksuffix="      "))
    return fig


def _hist_figure(r: dict[str, Any]) -> go.Figure:
    h = r["return_histogram"]
    x = [(b["x0"] + b["x1"]) / 2 for b in h]
    width = (h[0]["x1"] - h[0]["x0"]) if h else 0.001
    tail = {(x_["days"], x_["confidence"]): x_ for x_ in r["tail"]}
    v95, v99 = -tail[(1, 0.95)]["var"], -tail[(1, 0.99)]["var"]
    fig = go.Figure(go.Bar(
        x=x, y=[b["count"] for b in h], width=width * 0.9,
        marker=dict(color=[LOSS if c <= v95 else t.BRAND_PRIMARY for c in x], cornerradius=2),
        customdata=[[b["x0"], b["x1"]] for b in h],
        hovertemplate="%{customdata[0]:.2%} to %{customdata[1]:.2%}<br>%{y} days<extra></extra>",
    ))
    for val, lbl, dash, pos in ((v95, "VaR 95%", "dash", "top right"),
                                (v99, "VaR 99%", "dot", "top left")):
        fig.add_vline(x=val, line=dict(color=t.INK_900, width=1.5, dash=dash),
                      annotation=dict(text=f"{lbl} {-val:.2%}", font=dict(size=11, color=t.INK_900),
                                      bgcolor="rgba(255,255,255,.85)"),
                      annotation_position=pos)
    fig.update_layout(margin=dict(l=36, r=8, t=24, b=28), hovermode="closest", bargap=0.05,
                      xaxis=dict(tickformat=".1%", title=None),
                      yaxis=dict(title=None, showgrid=True))
    return fig


def _tail_table(r: dict[str, Any]) -> html.Table:
    rows = []
    for x in r["tail"]:
        rows.append(html.Tr([
            html.Td(f"{x['horizon']} · {x['confidence']:.0%}"),
            html.Td(fmt.pct(x["var"]), className="ts-num"),
            html.Td(fmt.money(x["var_usd"]), className="ts-num ts-c-ink600"),
            html.Td(fmt.pct(x["cvar"]), className="ts-num"),
            html.Td(fmt.money(x["cvar_usd"]), className="ts-num ts-c-ink600"),
        ]))
    return html.Table(
        [html.Thead(html.Tr([html.Th("Horizon · confidence"), html.Th("VaR", className="ts-num"),
                             html.Th("", className="ts-num"), html.Th("CVaR", className="ts-num"),
                             html.Th("", className="ts-num")])),
         html.Tbody(rows)],
        className="ts-risk-table ts-mt-3",
    )


def _stress(r: dict[str, Any]) -> html.Div:
    items = r["stress_tests"]
    top = max((abs(x["pnl_pct"]) for x in items), default=0) or 1
    rows = []
    for x in items:
        neg = x["pnl_pct"] < 0
        w = abs(x["pnl_pct"]) / top * 50
        bar = html.Span(className="ts-stress-fill " + ("is-loss" if neg else "is-gain"),
                        style={"width": f"{w:.1f}%",
                               ("right" if neg else "left"): "50%"})
        rows.append(html.Div(
            [html.Div([html.Div(x["name"], className="ts-stress-title"),
                       html.Div(x["description"], className="ts-stress-desc")],
                      className="ts-stress-name"),
             html.Div([html.Span(className="ts-stress-axis"), bar], className="ts-stress-track"),
             html.Div([html.Div(fmt.signed_pct(x["pnl_pct"], 1),
                                className="ts-num ts-fw-600 " + ("ts-c-negative" if neg
                                                                 else "ts-c-positive")),
                       html.Div(fmt.signed_money(x["pnl_usd"]), className="ts-num ts-stress-desc")],
                      className="ts-stress-val")],
            className="ts-stress-row",
        ))
    return html.Div(rows, className="ts-stress-list")


def _contributors(r: dict[str, Any]) -> html.Table:
    return html.Table(
        [html.Thead(html.Tr([html.Th("Holding"), html.Th("Weight", className="ts-num"),
                             html.Th("Share of risk", className="ts-num")])),
         html.Tbody([html.Tr([
             html.Td([html.Span(x["ticker"], className="ts-fw-600 ts-c-navy"),
                      html.Span(f" {x['name']}", className="ts-c-ink600")]),
             html.Td(fmt.pct(x["weight"], 1), className="ts-num"),
             html.Td(fmt.pct(x["pct_of_risk"], 1), className="ts-num ts-fw-500"),
         ]) for x in r["top_contributors"]])],
        className="ts-risk-table",
    )


def _accounts(r: dict[str, Any]) -> html.Table:
    return html.Table(
        [html.Thead(html.Tr([html.Th("Account"), html.Th("Market value", className="ts-num"),
                             html.Th("Volatility", className="ts-num"),
                             html.Th("Beta", className="ts-num"),
                             html.Th("1-day VaR 95%", className="ts-num"),
                             html.Th("", className="ts-num")])),
         html.Tbody([html.Tr([
             html.Td(a["label"], className="ts-fw-500"),
             html.Td(fmt.money_full(a["market_value"]), className="ts-num"),
             html.Td(fmt.pct(a["volatility"], 1), className="ts-num"),
             html.Td(f"{a['beta']:.2f}", className="ts-num"),
             html.Td(fmt.pct(a["var_95_1d"]), className="ts-num"),
             html.Td(fmt.money(a["var_95_1d_usd"]), className="ts-num ts-c-ink600"),
         ]) for a in r["accounts"]])],
        className="ts-risk-table",
    )


# ------------------------------------------------------------------ body
def risk_body(r: dict[str, Any], *, client: bool = False) -> list[Any]:
    if r["market_value"] <= 0:
        return [html.P("No holdings yet — analytics appear once the accounts hold securities.",
                       className="ts-sub")]
    n_dec = len(r["decomposition"])
    exposures = html.Div(
        [
            _card("Asset allocation", "Look-through, share of market value",
                  _allocation(r["asset_allocation"])),
            _card("GICS sector exposure", "Look-through, share of market value",
                  _bar_list(r["sectors"])),
            _card("Geographic exposure", "By region, then top countries",
                  html.Div([_bar_list(r["regions"]),
                            html.P("Top countries", className="ts-risk-sublabel"),
                            _bar_list(r["countries"], limit=6, tone="navy")])),
        ],
        className="ts-risk-grid-3 ts-mb-5",
    )
    risk = html.Div(
        [
            _card("Volatility decomposition",
                  f"Contribution to {fmt.pct(r['volatility'], 1)} annual volatility by factor "
                  "(labels: share of variance)",
                  graph(_decomp_figure(r["decomposition"], r["volatility"]), 34 * n_dec + 30)),
            _card("Tail risk", "Daily returns of today's holdings over the last 2 years",
                  html.Div([graph(_hist_figure(r), 200),
                            html.Div(_tail_table(r), className="ts-table-scroll")])),
        ],
        className="ts-risk-grid-2 ts-mb-5",
    )
    lower = html.Div(
        [
            _card("Stress tests", "Estimated impact of hypothetical scenarios", _stress(r)),
            _card("Top risk contributors",
                  f"{r['n_positions']} positions · top 10 = {fmt.pct(r['top10_weight'], 0)} "
                  f"of value · effective number of holdings {r['effective_n']:.0f}",
                  html.Div(_contributors(r), className="ts-table-scroll")),
        ],
        className="ts-risk-grid-2",
    )
    out: list[Any] = [_kpis(r), exposures, risk, lower]
    if client and r.get("accounts"):
        out.append(html.Div(_card("Risk by account", "Each account analysed on its own",
                                  html.Div(_accounts(r), className="ts-table-scroll")),
                            className="ts-mt-5"))
    out.append(html.Details(
        [html.Summary("How these numbers are calculated"),
         html.Ul([html.Li(x) for x in r["methodology"]])],
        className="ts-risk-method ts-mt-5",
    ))
    return out


def asof_text(r: dict[str, Any]) -> str:
    from datetime import date

    d = date.fromisoformat(r["as_of"][:10])
    gen = r["generated_at"].replace("T", " ")[:16]
    return f"Point in time · as of {d:%B} {d.day}, {d:%Y} · generated {gen} · {r['source_label']}"
