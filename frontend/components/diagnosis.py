"""AI review: findings from the backend account diagnosis (GET /accounts/{id}/diagnosis).

Used by the transition workspace (account review step, fixes apply to the session) and by the
client page (fixes are picked here and carried into a new transition). Layout only.
"""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from components.shell import icon

CHECK_ICON = {"concentration": "target", "sector": "chart-pie", "region": "globe",
              "risk": "activity", "tax": "receipt-text", "cash": "wallet"}
SEVERITY = {"high": ("High", "negative"), "medium": ("Worth a look", "warning"),
            "low": ("Note", "neutral"), "info": ("FYI", "neutral")}


def bench_line(d: dict[str, Any]) -> str:
    b = d["benchmark"]
    if d["benchmark_kind"] == "target":
        return f"Compared with the target model ({b['name'].removeprefix('Target model · ')})."
    return (f"Compared with {b['name']}, the closest stock/bond blend to the portfolio's "
            f"{d['equity_pct'] * 100:.0f}% equity.")


def finding_card(f: dict[str, Any], fix_area: Any = None) -> html.Div:
    label, tone = SEVERITY[f["severity"]]
    return html.Div(
        [html.Div(icon(CHECK_ICON.get(f["check"], "info"), 18), className="ts-ai-icon"),
         html.Div([html.Div([html.Span(f["title"], className="ts-ai-title"),
                             html.Span(label, className=f"ts-pill ts-pill--{tone}")],
                            className="ts-ai-head"),
                   html.P(f["detail"], className="ts-ai-detail"),
                   fix_area], className="ts-ai-main")],
        className=f"ts-ai-finding ts-ai-finding--{f['severity']}",
    )


def workspace_findings(d: dict[str, Any]) -> list[html.Div]:
    """Transition canvas: each fix appears once as an apply / undo button."""
    applied = set(d.get("applied") or [])
    fixes = {**(d.get("all_fixes") or {}), **(d.get("fixes") or {})}
    shown: set[str] = set()
    out = []
    for f in d["findings"]:
        btns = []
        for fx in f["fixes"]:
            if fx in shown or fx not in fixes:
                continue
            shown.add(fx)
            on = fx in applied
            btns.append(html.Button(
                [icon("check", 14) if on else icon("plus", 14),
                 fixes[fx]["label"] + (" — applied" if on else "")],
                id={"type": "ws-act", "id": f"{'unfix' if on else 'fix'}:{fx}"}, n_clicks=0,
                type="button", title=fixes[fx]["description"]
                + (" Click to undo." if on else ""),
                className="ts-ai-fix" + (" is-on" if on else "")))
        out.append(finding_card(f, html.Div(btns, className="ts-ai-fixes") if btns else None))
    # fixes applied earlier (e.g. picked on the client page) that no finding offers
    extra = [fx for fx in applied if fx not in shown and fx in fixes]
    if extra:
        out.append(html.Div(
            [html.Span("Also applied: ", className="ts-fw-600"),
             *[html.Button([icon("check", 14), fixes[fx]["label"]],
                           id={"type": "ws-act", "id": f"unfix:{fx}"}, n_clicks=0,
                           type="button", className="ts-ai-fix is-on",
                           title="Click to undo") for fx in extra]],
            className="ts-ai-fixes ts-mt-2"))
    return out


def client_review(d: dict[str, Any], can_start: bool) -> list[Any]:
    """Client page card body: findings, the fixes to carry into a transition, and start."""
    if not d["findings"]:
        return [html.P(d["summary"], className="ts-sub"), html.P(bench_line(d), className="ts-sub")]
    fixes = d.get("fixes") or {}
    opts = [{"label": html.Span([html.Strong(v["label"]),
                                 html.Span(f" — {v['description']}", className="ts-c-ink600")]),
             "value": k} for k, v in fixes.items()]
    start = html.Button([icon("arrow-right-left", 16), "Start transition with selected fixes"],
                        id="cd-ai-start", n_clicks=0, type="button",
                        className="ts-btn ts-btn-primary ts-btn-sm", disabled=not can_start)
    return [
        html.P([html.Strong(d["summary"]), " ", bench_line(d)], className="ts-sub ts-mb-4"),
        html.Div([finding_card(f) for f in d["findings"]], className="ts-ai-list"),
        html.Div([
            html.P("What can I do?", className="ts-ai-title ts-mb-2"),
            dcc.Checklist(id="cd-ai-fixes", options=opts, value=[], className="ts-ai-checks",
                          inputClassName="ts-ai-check-input"),
            html.Div([start, html.Span(
                "Pick an account above to start a transition." if not can_start else
                "The guide applies these as settings and asks before trading.",
                className="ts-sub")], className="ts-row ts-gap-3 ts-mt-3"),
        ], className="ts-ai-solutions") if opts else None,
    ]
