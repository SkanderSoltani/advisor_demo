"""One-page-plus PDF summary of an optimization result (reportlab)."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.common import DISCLAIMER
from app.schemas.transitions import OptimizationResult

MAX_TRADE_ROWS = 250


def _money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _tbl(rows: list[list[str]], widths: list[float] | None = None) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eaf0")),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c4c7d0")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#8a8f9c")),
            ]
        )
    )
    return t


def render_summary_pdf(r: OptimizationResult, client_name: str, account_label: str) -> bytes:
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="Transition summary (illustrative)",
    )
    budget = (
        "none (full transition)"
        if r.budget_mode == "none" or r.budget_value is None
        else f"{r.budget_mode.replace('_', ' ')} up to {_money(r.budget_value)}"
    )
    story = [
        Paragraph("Transition summary — illustrative, for advisor review", styles["Title"]),
        Paragraph(
            f"<font color='#b00020'><b>{DISCLAIMER} SYNTHETIC DATA — simulated analytics "
            f"({r.data_source}).</b></font>",
            styles["Normal"],
        ),
        Spacer(1, 0.12 * inch),
        Paragraph(
            f"Client: {client_name} · Account: {account_label} ({r.account_id}) · "
            f"Target: {r.target_model_id} · As of {r.as_of} · Budget: {budget}",
            styles["Normal"],
        ),
        Spacer(1, 0.15 * inch),
        _tbl(
            [
                ["", "Before", "After"],
                ["Ex-ante tracking error", f"{r.pre.te:.2%}", f"{r.post.te:.2%}"],
                ["Holdings", str(r.pre.n_holdings), str(r.post.n_holdings)],
                ["Dividend yield", f"{r.pre.dividend_yield:.2%}", f"{r.post.dividend_yield:.2%}"],
                ["Beta", f"{r.pre.beta:.2f}", f"{r.post.beta:.2f}"],
            ],
            [2.4 * inch, 1.3 * inch, 1.3 * inch],
        ),
        Spacer(1, 0.15 * inch),
        _tbl(
            [
                ["Realized", "Gains", "Losses"],
                ["Short-term", _money(r.realized.st_gain), _money(r.realized.st_loss)],
                ["Long-term", _money(r.realized.lt_gain), _money(r.realized.lt_loss)],
                ["Net realized gain", _money(r.realized.net_gain), ""],
                ["Estimated tax", _money(r.realized.est_tax), ""],
                ["Turnover", f"{r.summary.turnover:.1%}", ""],
            ],
            [2.4 * inch, 1.3 * inch, 1.3 * inch],
        ),
        Spacer(1, 0.15 * inch),
        Paragraph("<b>Why tracking error is not zero</b>", styles["Normal"]),
    ]
    story += [Paragraph(f"- {line}", styles["Normal"]) for line in r.diagnostics.explanation]
    if r.glide_path:
        story += [
            Spacer(1, 0.15 * inch),
            Paragraph("<b>Multi-year glide path</b>", styles["Normal"]),
            _tbl(
                [["Year", "Budget", "Est. tax", "TE after", "Trades"]]
                + [
                    [
                        str(y.year),
                        _money(y.budget),
                        _money(y.est_tax),
                        f"{y.te_after:.2%}",
                        str(y.n_trades),
                    ]
                    for y in r.glide_path
                ]
            ),
        ]
    trades = [["Side", "Ticker", "Lot ID", "Shares", "Value", "Gain", "Term"]]
    trades += [
        ["BUY", b.ticker, "", f"{b.shares:,.0f}", _money(b.value), "", ""] for b in r.trades.buys
    ]
    trades += [
        [
            "SELL",
            s.ticker,
            s.lot_ref or s.lot_id,
            f"{s.shares:,.3f}",
            _money(s.proceeds),
            _money(s.realized_gain),
            s.term,
        ]
        for s in r.trades.sells[:MAX_TRADE_ROWS]
    ]
    story += [Spacer(1, 0.2 * inch), Paragraph("<b>Trade list</b>", styles["Normal"]), _tbl(trades)]
    if len(r.trades.sells) > MAX_TRADE_ROWS:
        story.append(
            Paragraph(
                f"… {len(r.trades.sells) - MAX_TRADE_ROWS} more sells in the CSV.", styles["Italic"]
            )
        )

    def footer(canvas, _doc):  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(0.6 * inch, 0.35 * inch, f"{DISCLAIMER} Synthetic data.")
        canvas.drawRightString(7.9 * inch, 0.35 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
