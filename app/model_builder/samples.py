"""Sample model files (Excel and PDF) for trying the import."""

from __future__ import annotations

import io

SAMPLE_NAME = "sample_model_growth_income_70_30"
SAMPLE = [  # ticker, name, weight %
    ("SCHX", "Schwab U.S. Large-Cap ETF", 30.0),
    ("SCHG", "Schwab U.S. Large-Cap Growth ETF", 8.0),
    ("FNDX", "Schwab Fundamental U.S. Large Company ETF", 8.0),
    ("SCHA", "Schwab U.S. Small-Cap ETF", 5.0),
    ("SCHF", "Schwab International Equity ETF", 10.0),
    ("SCHE", "Schwab Emerging Markets Equity ETF", 4.0),
    ("SCHH", "Schwab U.S. REIT ETF", 5.0),
    ("SCHZ", "Schwab U.S. Aggregate Bond ETF", 15.0),
    ("SCHI", "Schwab 5-10 Year Corporate Bond ETF", 6.0),
    ("SCYB", "Schwab High Yield Bond ETF", 3.0),
    ("SCHP", "Schwab U.S. TIPS ETF", 3.0),
    ("CASH", "Cash / cash equivalents", 3.0),
]


def sample_xlsx() -> bytes:
    import pandas as pd

    df = pd.DataFrame(SAMPLE, columns=["Ticker", "Name", "Weight (%)"])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Model")
    return buf.getvalue()


def sample_pdf() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Sample model")
    st = getSampleStyleSheet()
    rows = [["Ticker", "Name", "Weight"]] + [[t, n, f"{w:.1f}%"] for t, n, w in SAMPLE]
    tbl = Table(rows, colWidths=[70, 300, 70])
    tbl.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                             ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                             ("ALIGN", (2, 0), (2, -1), "RIGHT")]))
    doc.build([Paragraph("Growth &amp; Income 70/30 — sample model (demo)", st["Title"]),
               Spacer(1, 12), tbl])
    return buf.getvalue()
