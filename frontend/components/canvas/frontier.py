"""Efficient-frontier figure (tax cost vs. resulting TE) — all points come from POST /frontier."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from theme import tokens as t


def frontier_figure(fr: dict[str, Any], selected_budget: float | None = None) -> go.Figure:
    pts = fr["points"]
    x = [p["est_tax"] for p in pts]
    y = [p["te"] for p in pts]
    sel = fr.get("chosen_index")
    if selected_budget is not None and pts:
        sel = min(range(len(pts)), key=lambda i: abs(pts[i]["budget"] - selected_budget))
    fig = go.Figure()
    fig.add_scatter(x=x, y=y, mode="lines", line={"color": t.SURFACE_100, "width": 2}, hoverinfo="skip")
    fig.add_scatter(
        x=x, y=y, mode="markers", customdata=[[p["budget"], p["turnover"], p["net_gain"]] for p in pts],
        marker={"size": 11,
                "color": [t.BRAND_PRIMARY if i == sel else "rgba(0,61,92,.5)" for i in range(len(pts))],
                    "line": {"width": [6 if i == sel else 0 for i in range(len(pts))],
                              "color": "rgba(0,160,223,.2)"}},
        hovertemplate=("Tax %{x:$,.0f}<br>TE %{y:.2%}<br>Turnover %{customdata[1]:.0%}"
                       "<br>Net gain %{customdata[2]:$,.0f}<extra></extra>"),
    )
    fig.add_hline(y=fr["te_before"], line={"color": t.INK_300, "dash": "dot", "width": 1},
                  annotation_text=f"Today {fr['te_before']:.2%}", annotation_position="top right",
                  annotation_font={"size": 11, "color": t.INK_600})
    fig.update_layout(showlegend=False, margin={"l": 48, "r": 12, "t": 8, "b": 32}, hovermode="closest",
                      xaxis={"tickformat": "$~s", "title": None, "zeroline": False},
                      yaxis={"tickformat": ".1%", "title": None, "rangemode": "tozero"}, clickmode="event")
    return fig
