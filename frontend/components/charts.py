"""Plotly figure builders. They only *plot* API payloads — no analytics are computed here
(filtering to the selected period is the only data operation)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import plotly.graph_objects as go

from services import format as fmt
from theme import tokens as t

EVENT_COLORS = {
    "transition": t.BRAND_NAVY,
    "rebalance": t.BRAND_PRIMARY,
    "tax_loss_harvest": t.POSITIVE,
    "cash_flow": "#7FCFEF",
    "model_change": "#8C8279",
}
EVENT_LABELS = {
    "transition": "Transition",
    "rebalance": "Rebalance",
    "tax_loss_harvest": "Tax-loss harvest",
    "cash_flow": "Cash flow",
    "model_change": "Model change",
}
PERIOD_DAYS = {"1y": 365, "3y": 3 * 365, "all": None}

# Tax chart views (toggle on the book "Cumulative tax impact" card and the client "Taxes saved" card)
TAX_VIEWS = [{"label": "Taxes saved", "value": "saved"},
             {"label": "Gains & losses", "value": "gl"},
             {"label": "ST / LT", "value": "term"}]
GAIN_COLOR, LOSS_COLOR = t.BRAND_NAVY, t.BRAND_PRIMARY
# (label, color, sign, payload keys summed) — losses are plotted below zero
TAX_SERIES: dict[str, list[tuple[str, str, int, tuple[str, ...]]]] = {
    "gl": [("Realized gains", GAIN_COLOR, 1, ("realized_st_gain", "realized_lt_gain")),
           ("Harvested losses", LOSS_COLOR, -1, ("losses_harvested",))],
    "term": [("ST gains", "#8C8279", 1, ("realized_st_gain",)),
             ("LT gains", GAIN_COLOR, 1, ("realized_lt_gain",)),
             ("ST losses", "#7FCFEF", -1, ("realized_st_loss",)),
             ("LT losses", LOSS_COLOR, -1, ("realized_lt_loss",))],
}


def tax_series_value(p: dict[str, Any], keys: Sequence[str], cum: bool = False) -> float:
    """Sum of the payload fields for one series (cumulative fields when ``cum``)."""
    return float(sum(p[f"cum_{k}" if cum else k] for k in keys))


def _tax_bars(fig: go.Figure, x: list[str], pts: list[dict[str, Any]], view: str,
              hover_x: bool = False) -> None:
    for label, color, sign, keys in TAX_SERIES[view]:
        vals = [tax_series_value(p, keys) for p in pts]
        fig.add_bar(x=x, y=[sign * v for v in vals], customdata=vals, name=label,
                    marker_color=color,
                    hovertemplate=("%{x} · " if hover_x else "") + f"{label} $%{{customdata:,.0f}}"
                                  "<extra></extra>")
    fig.update_layout(barmode="relative")


def rgba(hex_: str, a: float) -> str:
    h = hex_.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def _as_date(key: str) -> date:
    """'2026-10-30' | '2026-10' (month end-ish) | '2026' (year end) → date."""
    if len(key) >= 10:
        return date.fromisoformat(key[:10])
    if len(key) == 7:
        return date.fromisoformat(f"{key}-28")
    return date(int(key[:4]), 12, 31)


def in_period(keys: Sequence[str], period: str) -> list[bool]:
    """Which points fall in the selected window (1Y / 3Y / since inception), ending at the
    latest point returned by the API."""
    days = PERIOD_DAYS.get(period)
    if days is None or not keys:
        return [True] * len(keys)
    end = max(_as_date(k) for k in keys)
    start = end - timedelta(days=days)
    return [_as_date(k) >= start for k in keys]


def _period_label(key: str) -> str:
    """'2026-10' → 'Oct 26'; '2026' stays '2026' (display only)."""
    return fmt.short_month(f"{key}-01") if len(key) == 7 else key


def _spark_layout(fig: go.Figure, *, yfmt: str = ".2%", show_y: bool = False) -> go.Figure:
    fig.update_layout(
        margin=dict(l=0, r=0, t=4, b=0), showlegend=False, hovermode="x unified",
        xaxis=dict(visible=False, showgrid=False), yaxis=dict(visible=show_y, tickformat=yfmt,
                                                              showgrid=show_y),
    )
    return fig


def book_te_figure(series: list[dict[str, Any]], period: str) -> go.Figure:
    """AUM-weighted average rolling TE with the 10th–90th percentile band (book page)."""
    keep = in_period([p["date"] for p in series], period)
    pts = [p for p, k in zip(series, keep, strict=True) if k]
    x = [p["date"] for p in pts]
    fig = go.Figure()
    fig.add_scatter(x=x, y=[p["p90"] for p in pts], line=dict(width=0), hoverinfo="skip",
                    showlegend=False)
    fig.add_scatter(x=x, y=[p["p10"] for p in pts], fill="tonexty", line=dict(width=0),
                    fillcolor=rgba(t.BRAND_PRIMARY, 0.08), name="10th–90th percentile",
                    hoverinfo="skip")
    fig.add_scatter(x=x, y=[p["avg_te"] for p in pts], name="Average TE",
                    line=dict(color=t.BRAND_PRIMARY, width=2),
                    customdata=[[p["p10"], p["p90"], p["n_accounts"]] for p in pts],
                    hovertemplate="Avg TE %{y:.2%}<br>10th–90th: %{customdata[0]:.2%}–"
                                  "%{customdata[1]:.2%}<br>%{customdata[2]} accounts<extra></extra>")
    return _spark_layout(fig)


def book_tax_figure(periods: list[dict[str, Any]], granularity: str, period: str,
                    view: str = "saved") -> go.Figure:
    keep = in_period([p["period"] for p in periods], period)
    pts = [p for p, k in zip(periods, keep, strict=True) if k]
    x = [p["period"] for p in pts]
    fig = go.Figure()
    if view in TAX_SERIES:
        if granularity == "year":
            _tax_bars(fig, x, pts, view, hover_x=True)
            fig.update_layout(bargap=0.45)
            return _spark_layout(fig)
        for label, color, sign, keys in TAX_SERIES[view]:
            vals = [tax_series_value(p, keys, cum=True) for p in pts]
            fig.add_scatter(x=x, y=[sign * v for v in vals], customdata=vals, name=label,
                            mode="lines", line=dict(color=color, width=2 if view == "gl" else 1.5),
                            fill="tozeroy" if view == "gl" else None,
                            fillcolor=rgba(color, 0.08),
                            hovertemplate=f"{label} $%{{customdata:,.0f}}<extra></extra>")
        return _spark_layout(fig)
    if granularity == "year":
        fig.add_bar(x=x, y=[p["taxes_saved"] for p in pts], name="Taxes saved",
                    marker_color=t.POSITIVE, hovertemplate="%{x}: $%{y:,.0f} saved<extra></extra>")
        fig.update_layout(bargap=0.45)
        return _spark_layout(fig)
    fig.add_scatter(x=x, y=[p["cum_taxes_saved"] for p in pts], name="Taxes saved", mode="lines",
                    line=dict(color=t.POSITIVE, width=2), fill="tozeroy",
                    fillcolor=rgba(t.POSITIVE, 0.08), hovertemplate="Taxes saved $%{y:,.0f}<extra></extra>")
    for key, label, color in (("cum_losses_harvested", "Losses harvested", t.BRAND_PRIMARY),
                              ("cum_realized_st_gain", "Realized ST gains", "#8C8279"),
                              ("cum_realized_lt_gain", "Realized LT gains", t.BRAND_NAVY)):
        fig.add_scatter(x=x, y=[p[key] for p in pts], name=label, mode="lines",
                        line=dict(color=rgba(color, 0.35), width=1),
                        hovertemplate=f"{label} $%{{y:,.0f}}<extra></extra>")
    return _spark_layout(fig)


def activity_figure(periods: list[dict[str, Any]], period: str) -> go.Figure:
    keep = in_period([p["period"] for p in periods], period)
    pts = [p for p, k in zip(periods, keep, strict=True) if k]
    x = [_period_label(p["period"]) for p in pts]
    fig = go.Figure()
    for kind, label in EVENT_LABELS.items():
        fig.add_bar(x=x, y=[p["counts"].get(kind, 0) for p in pts], name=label,
                    marker_color=EVENT_COLORS[kind], hovertemplate=f"{label}: %{{y}}<extra></extra>")
    aum = [p["aum"] for p in pts]
    lo, hi = (min(aum), max(aum)) if aum else (0.0, 1.0)
    step = _nice_step(max(hi - lo, 1.0) / 4)
    aum_ticks = [step * k for k in range(math.floor(lo / step), math.ceil(hi / step) + 1)]
    fig.add_scatter(x=x, y=aum, name="AUM", yaxis="y2", mode="lines",
                    line=dict(color=t.BRAND_NAVY, width=2), hovertemplate="AUM $%{y:,.0f}<extra></extra>")
    fig.update_layout(
        barmode="stack", bargap=0.3, margin=dict(l=28, r=48, t=22, b=34), hovermode="x unified",
        yaxis=dict(title=None, tickformat=",d", showgrid=True, gridcolor=t.SURFACE_100),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, tickmode="array",
                    tickvals=aum_ticks, ticktext=[fmt.money(v) for v in aum_ticks]),
        xaxis=dict(showgrid=False, type="category", nticks=8, automargin=True,
                   tickfont=dict(size=12, color=t.INK_900)),
        legend=dict(orientation="h", y=1.32, x=0, font=dict(size=11), itemwidth=30),
    )
    return fig


def client_te_figure(series: list[dict[str, Any]], events: list[dict[str, Any]],
                     tolerance: float | None, window: int) -> go.Figure:
    """Rolling TE to target with the drift-tolerance band and event markers (client page)."""
    x = [p["date"] for p in series]
    fig = go.Figure()
    if tolerance is not None and x:
        fig.add_hrect(y0=0, y1=tolerance, fillcolor=rgba(t.POSITIVE, 0.06), line_width=0,
                      layer="below")
        fig.add_hline(y=tolerance, line=dict(color=t.WARNING, width=1, dash="dash"),
                      annotation_text=f"Tolerance {fmt.pct(tolerance, 1)}",
                      annotation_position="top left", annotation_font=dict(size=11, color=t.INK_600))
    fig.add_scatter(x=x, y=[p["te"] for p in series], name=f"{window}-day TE",
                    line=dict(color=t.BRAND_PRIMARY, width=2), fill="tozeroy",
                    fillcolor=rgba(t.BRAND_PRIMARY, 0.06),
                    hovertemplate=f"{window}-day TE %{{y:.2%}}<extra></extra>")
    if events and series:
        lo = min(p["te"] for p in series)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            by_type.setdefault(e["type"], []).append(e)
        for kind, evs in by_type.items():
            fig.add_scatter(
                x=[e["date"] for e in evs], y=[lo * 0.5] * len(evs), mode="markers",
                name=EVENT_LABELS.get(kind, kind),
                marker=dict(symbol="line-ns-open", size=12, color=EVENT_COLORS.get(kind, t.INK_600),
                            line=dict(width=2)),
                hovertemplate=f"{EVENT_LABELS.get(kind, kind)} · %{{x}}<extra></extra>")
    fig.update_layout(margin=dict(l=44, r=8, t=8, b=28), showlegend=False,
                      yaxis=dict(tickformat=".1%", rangemode="tozero"),
                      xaxis=dict(showgrid=False, tickformat="%b %y"))
    return fig


def _zero_aligned(lo1: float, hi1: float, lo2: float, hi2: float,
                  pad: float = 0.08) -> tuple[list[float], list[float]]:
    """Ranges for two y axes so that 0 sits at the same height on both."""
    lo1, hi1, lo2, hi2 = min(lo1, 0.0), max(hi1, 0.0), min(lo2, 0.0), max(hi2, 0.0)
    span1, span2 = (hi1 - lo1) or 1.0, (hi2 - lo2) or 1.0
    f = max(-lo1 / span1, -lo2 / span2)  # share of the height below zero
    up = max(hi1 / span1, hi2 / span2)  # share above zero
    total = f + up or 1.0
    f, up = f / total, up / total
    s1 = max(hi1 / up if up else 0.0, -lo1 / f if f else 0.0) * (1 + pad)
    s2 = max(hi2 / up if up else 0.0, -lo2 / f if f else 0.0) * (1 + pad)
    return [-f * s1, up * s1], [-f * s2, up * s2]


def _nice_step(raw: float) -> float:
    """Round an axis step up to 1, 2, 2.5 or 5 × a power of ten."""
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def tax_legend_items(view: str) -> list[tuple[str, str]]:
    """(label, color) for the HTML legend under a gains/losses tax chart."""
    return [(label, color) for label, color, _, _ in TAX_SERIES.get(view, [])]


def client_tax_figure(periods: list[dict[str, Any]], view: str = "saved") -> go.Figure:
    x = [_period_label(p["period"]) for p in periods]
    fig = go.Figure()
    if view in TAX_SERIES:
        _tax_bars(fig, x, periods, view)
        net, run = [], 0.0
        for p in periods:
            run += sum(sign * tax_series_value(p, keys) for _, _, sign, keys in TAX_SERIES[view])
            net.append(round(run, 2))
        fig.add_scatter(x=x, y=net, name="Cumulative net", yaxis="y2", mode="lines",
                        line=dict(color=t.INK_900, width=1.5, dash="dot"),
                        hovertemplate="Cumulative net $%{y:,.0f}<extra></extra>")
        # stacked bar extents, then line both axes up at zero
        tops = [sum(tax_series_value(p, k) for _, _, s, k in TAX_SERIES[view] if s > 0)
                for p in periods]
        bots = [-sum(tax_series_value(p, k) for _, _, s, k in TAX_SERIES[view] if s < 0)
                for p in periods]
        r1, r2 = _zero_aligned(min(bots, default=0), max(tops, default=0),
                               min(net, default=0), max(net, default=0))
        fig.update_layout(margin=dict(l=44, r=52, t=8, b=28), showlegend=False, bargap=0.35,
                          xaxis=dict(type="category", nticks=6, showgrid=False),
                          yaxis=dict(tickprefix="$", tickformat=".2s", zeroline=True,
                                     zerolinecolor=t.INK_300, range=r1),
                          yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                      tickprefix="$", tickformat=".3s", range=r2,
                                      tick0=0, dtick=_nice_step((r2[1] - r2[0]) / 5)))
        return fig
    fig.add_bar(x=x, y=[p["taxes_saved"] for p in periods], name="Taxes saved",
                marker_color=rgba(t.POSITIVE, 0.7), hovertemplate="%{x}: $%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=x, y=[p["cum_taxes_saved"] for p in periods], name="Cumulative", yaxis="y2",
                    mode="lines", line=dict(color=t.BRAND_NAVY, width=2),
                    hovertemplate="Cumulative $%{y:,.0f}<extra></extra>")
    fig.update_layout(margin=dict(l=44, r=52, t=8, b=28), showlegend=False, bargap=0.35,
                      xaxis=dict(type="category", nticks=6, showgrid=False),
                      yaxis=dict(tickprefix="$", tickformat=".2s"),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False, tickprefix="$",
                                  tickformat=".3s", rangemode="tozero"))
    return fig
