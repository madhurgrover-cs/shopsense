"""Write a Report to a CSV or PDF file. Used by report_service.export_report().

CSV keeps raw values (1299.00, not "₹1,299.00") so Excel can add them up; PDF is for
reading and printing, so it shows formatted rupees and dates.
"""

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.services.dto import Report
from app.services.validation import IST


def file_name(report: Report, file_format: str) -> str:
    """e.g. "sales_by_category_2026-09-17_to_2026-10-16.pdf"."""
    return f"{report.kind}_{report.start:%Y-%m-%d}_to_{report.end:%Y-%m-%d}.{file_format}"


def free_path(folder: Path, name: str) -> Path:
    """folder/name, or folder/"name (2)" etc. if that file already exists."""
    path = folder / name
    number = 2
    while path.exists():
        path = folder / f"{Path(name).stem} ({number}){Path(name).suffix}"
        number += 1
    return path


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(IST).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def write_csv(report: Report, path: Path) -> None:
    # utf-8-sig adds a byte-order mark, which tells Excel the file is UTF-8 (otherwise
    # names with non-English letters show up garbled).
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(report.columns)
        for row in report.rows:
            writer.writerow([_csv_value(v) for v in row])
        if report.totals:
            writer.writerow([_csv_value(v) for v in report.totals])


# ---------------------------------------------------------------------------
# PDF (reportlab)
# ---------------------------------------------------------------------------

_FONT, _BOLD = "Helvetica", "Helvetica-Bold"


def _register_fonts() -> None:
    """PDF's built-in fonts have no ₹ sign. DejaVu Sans has it, and it is already on
    every machine that runs ShopSense because matplotlib ships it."""
    global _FONT, _BOLD
    if _FONT == "DejaVuSans":
        return
    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(fonts / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(fonts / "DejaVuSans-Bold.ttf")))
        _FONT, _BOLD = "DejaVuSans", "DejaVuSans-Bold"
    except Exception:  # font missing: fall back to Helvetica and "Rs."
        pass


def _pdf_text(value, money: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(IST).strftime("%d %b %Y %H:%M")
    if money and isinstance(value, Decimal):
        symbol = "₹" if _FONT == "DejaVuSans" else "Rs. "
        return f"{symbol}{value:,.2f}"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def write_pdf(report: Report, path: Path) -> None:
    # Imported here: reportlab is only needed when someone actually exports a PDF.
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    wide = len(report.columns) > 6
    page = landscape(A4) if wide else A4
    size = 8 if wide else 9
    cell = ParagraphStyle("cell", fontName=_FONT, fontSize=size, leading=size + 2)
    cell_right = ParagraphStyle("cell_right", parent=cell, alignment=TA_RIGHT)
    bold = ParagraphStyle("bold", parent=cell, fontName=_BOLD)
    bold_right = ParagraphStyle("bold_right", parent=bold, alignment=TA_RIGHT)
    head = ParagraphStyle("head", parent=bold, textColor=colors.white)
    head_right = ParagraphStyle("head_right", parent=head, alignment=TA_RIGHT)
    styles = {"head": (head, head_right), "total": (bold, bold_right),
              "body": (cell, cell_right)}

    # Numbers line up on the right; text on the left.
    sample = report.rows[0] if report.rows else ()
    numeric = {i for i, v in enumerate(sample) if isinstance(v, (int, Decimal))}

    def row_cells(values, kind: str):
        left, right = styles[kind]
        return [Paragraph(_escape(_pdf_text(value, money=i in report.money_columns)),
                          right if i in numeric else left)
                for i, value in enumerate(values)]

    data = [row_cells(report.columns, "head")]
    data += [row_cells(r, "body") for r in report.rows]
    if report.totals:
        data.append(row_cells(report.totals, "total"))

    # Column widths: each column gets the width of its longest text (measured in the
    # real font). If that's too wide for the page, only the wide text columns (names,
    # emails) are narrowed and wrap; short columns like "Items" or amounts never do.
    margin = 15 * mm
    widths = _column_widths(report, size, page[0] - 2 * margin)

    table = Table(data, colWidths=widths, repeatRows=1)  # header repeats on every page
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B1F2A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#6C8CFF")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if report.totals:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black))
    table.setStyle(TableStyle(style))

    title = ParagraphStyle("title", fontName=_BOLD, fontSize=16, leading=20)
    subtitle = ParagraphStyle("subtitle", fontName=_FONT, fontSize=10, leading=14,
                              textColor=colors.HexColor("#555B66"))
    generated = datetime.now(IST).strftime("%d %b %Y %H:%M")
    story = [
        Paragraph(f"ShopSense - {_escape(report.title)}", title),
        Paragraph(f"Orders placed {report.period} (India time). Generated {generated}. "
                  f"Cancelled orders are not counted as sales. {_escape(report.note)}",
                  subtitle),
        Spacer(1, 6 * mm),
        table if report.rows else Paragraph("No orders in this period.", cell),
    ]

    def footer(canvas, doc) -> None:
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawRightString(page[0] - margin, 8 * mm, f"Page {doc.page}")

    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin,
                            title=f"ShopSense {report.title}", author="ShopSense")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def _column_widths(report: Report, size: int, usable: float) -> list[float]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    padding = 14  # the table's default 6 pt left + 6 pt right, plus 2 pt of slack
    lines = [(report.columns, _BOLD), *((r, _FONT) for r in report.rows)]
    if report.totals:
        lines.append((report.totals, _BOLD))
    natural = [
        max(stringWidth(_pdf_text(values[i], i in report.money_columns), font, size)
            for values, font in lines) + padding
        for i in range(len(report.columns))
    ]
    if sum(natural) <= usable:  # fits: share the spare room out evenly
        spare = (usable - sum(natural)) / len(natural)
        return [w + spare for w in natural]
    wide = [i for i, w in enumerate(natural) if w > usable / len(natural)]
    room = usable - sum(w for i, w in enumerate(natural) if i not in wide)
    scale = room / sum(natural[i] for i in wide)
    return [w * scale if i in wide else w for i, w in enumerate(natural)]


def _escape(text: str) -> str:
    """Paragraph text is mini-HTML: a product named "Tom & Jerry" must not break it."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


WRITERS = {"csv": write_csv, "pdf": write_pdf}
