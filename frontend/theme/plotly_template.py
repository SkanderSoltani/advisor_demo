"""The "schwab" Plotly template used by every figure."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from theme import tokens as t

GRID = t.SURFACE_100


def register() -> None:
    template = go.layout.Template(
        layout=go.Layout(
            font=dict(family=t.FONT_FAMILY, size=12, color=t.INK_600),
            colorway=t.COLORWAY,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor=t.SURFACE_0,
            margin=dict(l=48, r=16, t=8, b=32),
            xaxis=dict(showgrid=False, zeroline=False, showline=True, linecolor=GRID,
                       ticks="", tickfont=dict(size=12, color=t.INK_600)),
            yaxis=dict(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False,
                       showline=False, ticks="", tickfont=dict(size=12, color=t.INK_600)),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=12, color=t.INK_600), bgcolor="rgba(0,0,0,0)"),
            hoverlabel=dict(bgcolor=t.SURFACE_0, bordercolor=t.BRAND_NAVY,
                            font=dict(family=t.FONT_FAMILY, size=12, color=t.INK_900)),
            hovermode="x unified",
            bargap=0.35,
        )
    )
    template.data.scatter = [go.Scatter(line=dict(width=2))]
    pio.templates["schwab"] = template
    pio.templates.default = "schwab"


GRAPH_CONFIG = {"displayModeBar": False, "responsive": True}
