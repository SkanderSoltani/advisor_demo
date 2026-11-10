"""Render a fake brokerage tax-lot statement PDF (reportlab) for one seeded account.

The PDF is clearly marked "SAMPLE — SYNTHETIC DATA" and is used to exercise the PDF parser.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.db import models as m
from app.domain.entities import holding_period

BANNER = "SAMPLE — SYNTHETIC DATA"
COLUMNS = [
    "Symbol",
    "Description",
    "Quantity",
    "Acquired",
    "Cost Basis",
    "Price",
    "Market Value",
    "Unrealized G/L",
    "Term",
    "Lot ID",
]


def _money(x: float) -> str:
    return f"({abs(x):,.2f})" if x < 0 else f"{x:,.2f}"


def render_statement_pdf(session: Session, account_id: str, out_path: Path, as_of: date) -> Path:
    """Write a tax-lot statement for ``account_id`` to ``out_path``."""
    acct = session.get(m.Account, account_id)
    if acct is None:
        raise ValueError(f"unknown account {account_id}")
    secs = {s.ticker: s for s in session.query(m.Security).all()}

    rows: list[list[str]] = [COLUMNS]
    total_mv = total_cost = 0.0
    for lot in sorted(acct.lots, key=lambda x: (x.ticker, x.acquired_date)):
        sec = secs[lot.ticker]
        mv = lot.quantity * sec.last_price
        total_mv += mv
        total_cost += lot.cost_basis_total
        rows.append(
            [
                lot.ticker,
                sec.name[:28],
                f"{lot.quantity:,.3f}",
                lot.acquired_date.strftime("%m/%d/%Y"),
                _money(lot.cost_basis_total),
                f"{sec.last_price:,.2f}",
                _money(mv),
                _money(mv - lot.cost_basis_total),
                holding_period(lot.acquired_date, as_of).value,
                lot.lot_ref or "",
            ]
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=landscape(letter),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"{BANNER} — Tax Lot Statement",
    )
    owner = acct.client.name
    story = [
        Paragraph(f"<font color='#b00020'><b>{BANNER}</b></font>", styles["Title"]),
        Paragraph(
            "Northbridge Clearing (fictional) — Realized / Unrealized Tax Lot Detail", styles["h2"]
        ),
        Paragraph(
            f"Account: {acct.nickname or acct.account_type} · ID {acct.id} · Owner: {owner} · "
            f"Statement date: {as_of.strftime('%m/%d/%Y')}",
            styles["Normal"],
        ),
        Paragraph(
            f"Total market value: ${total_mv:,.2f} · Total cost basis: ${total_cost:,.2f} · "
            f"Cash &amp; equivalents: ${acct.cash:,.2f}",
            styles["Normal"],
        ),
        Spacer(1, 0.15 * inch),
    ]
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eaf0")),
                ("ALIGN", (2, 1), (-2, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c4c7d0")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#8a8f9c")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f9")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            f"{BANNER}. Fictional statement generated for software testing. Not a real account.",
            styles["Italic"],
        )
    )

    def _footer(canvas, _doc):  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.HexColor("#b00020"))
        canvas.drawString(0.5 * inch, 0.3 * inch, BANNER)
        canvas.drawRightString(10.5 * inch, 0.3 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path


def _typo(ticker: str, taken: set[str]) -> str:
    """A plausible mistyped ticker that is not in the universe (for the validation demo)."""
    for c in "QXZJ":
        t = ticker[:-1] + c
        if t not in taken:
            return t
    return ticker + "X"


def render_messy_statement_pdf(
    session: Session, account_id: str, out_path: Path, as_of: date
) -> Path:
    """A harder statement: free text (no table grid), month-name dates, wrapped descriptions,
    parenthesised losses, page subtotals, a cash line and one mistyped ticker. Table extraction
    fails on it, so ingestion falls back to the LLM pass."""
    from reportlab.pdfgen import canvas as rl_canvas

    acct = session.get(m.Account, account_id)
    if acct is None:
        raise ValueError(f"unknown account {account_id}")
    secs = {s.ticker: s for s in session.query(m.Security).all()}
    lots = sorted(acct.lots, key=lambda x: (x.ticker, x.acquired_date))
    typo_index = len(lots) // 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(out_path), pagesize=letter)
    c.setTitle(f"{BANNER} — Position Detail (messy layout)")
    _, height = letter
    cols = [36, 72, 160, 215, 273, 347, 420, 485]  # x positions

    def money(x: float) -> str:
        return f"({abs(x):,.2f})" if x < 0 else f"{x:,.2f}"

    def header(page_no: int) -> float:
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(colors.HexColor("#b00020"))
        c.drawString(36, height - 40, BANNER)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawString(
            36, height - 56, "Harbor & Pine Securities (fictional) - Position Detail by Tax Lot"
        )
        c.drawString(
            36,
            height - 68,
            f"Acct ending {acct.id[-3:]}   Statement date: "
            f"{as_of.strftime('%b %d, %Y')}   Page {page_no}",
        )
        c.setFont("Helvetica-Bold", 8)
        for x, h in zip(
            cols,
            [
                "Sym",
                "Security Description",
                "Open Date",
                "Qty",
                "Adj Cost Basis",
                "Mkt Value",
                "Gain/(Loss)",
                "Lot ID",
            ],
            strict=True,
        ):
            c.drawString(x, height - 90, h)
        c.setFont("Helvetica", 8)
        return float(height - 104)

    page, y = 1, header(1)
    sub_mv = sub_cost = 0.0
    for idx, lot in enumerate(lots):
        sec = secs[lot.ticker]
        mv = lot.quantity * sec.last_price
        ticker = _typo(lot.ticker, set(secs)) if idx == typo_index else lot.ticker
        name = sec.name
        wrap = len(name) > 18
        c.drawString(cols[0], y, ticker)
        c.drawString(cols[1], y, name[:18] if wrap else name)
        c.drawString(cols[2], y, lot.acquired_date.strftime("%b %d, %Y"))
        c.drawRightString(cols[3] + 50, y, f"{lot.quantity:,.3f}")
        c.drawRightString(cols[4] + 62, y, money(lot.cost_basis_total))
        c.drawRightString(cols[5] + 58, y, money(mv))
        c.drawRightString(cols[6] + 50, y, money(mv - lot.cost_basis_total))
        c.drawString(cols[7], y, lot.lot_ref or "")
        y -= 11
        if wrap:
            c.drawString(cols[1] + 6, y, name[18:])
            y -= 11
        sub_mv += mv
        sub_cost += lot.cost_basis_total
        if y < 80 or idx == len(lots) - 1:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(cols[1], y - 4, f"Subtotal page {page}")
            c.drawRightString(cols[4] + 62, y - 4, money(sub_cost))
            c.drawRightString(cols[5] + 58, y - 4, money(sub_mv))
            c.setFont("Helvetica", 8)
            sub_mv = sub_cost = 0.0
            if idx == len(lots) - 1:
                c.setFont("Helvetica-Bold", 9)
                c.drawString(cols[0], y - 24, f"Cash & Money Market   ${acct.cash:,.2f}")
                c.setFont("Helvetica", 7)
                c.drawString(cols[0], 40, f"{BANNER}. Fictional statement for software testing.")
            else:
                c.setFont("Helvetica", 7)
                c.drawString(cols[0], 40, f"{BANNER}. Continued on next page.")
                c.showPage()
                page += 1
                y = header(page)
    c.save()
    return out_path
