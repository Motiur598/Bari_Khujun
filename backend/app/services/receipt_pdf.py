"""Rent and utility receipt PDF, built on demand for paid invoices."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.booking import DEPOSIT_METHOD_LABELS
from app.services.lease_pdf import GATE, INK, PLASTER, RULE, SOFT, format_day, format_moment, taka


def _period_label(period: str) -> str:
    return format_day(f"{period}-01").split(" ", 1)[1]  # "1 Nov 2026" -> "Nov 2026"


def build_receipt_pdf(invoice: dict) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=SOFT)
    right = ParagraphStyle("right", parent=small, alignment=TA_RIGHT)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=15, leading=19)

    payment = invoice["payment"]
    seats = invoice.get("split_seats")
    line_rows = [["Item", "Whole flat" if seats else "", "Amount"]]
    for line in invoice["lines"]:
        flat = taka(line["flat_amount"]) if line.get("flat_amount") is not None else ""
        line_rows.append([line["label"], flat, taka(line["amount"])])
    line_rows.append(["Total paid", "", taka(invoice["total"])])

    lines = Table(line_rows, colWidths=[52 * mm, 30 * mm, 30 * mm])
    lines.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), PLASTER),
        ("TEXTCOLOR", (1, 1), (1, -1), SOFT),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
        ("LINEABOVE", (0, -1), (-1, -1), 1, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    facts = Table(
        [
            ["Received from", invoice["tenant"]["full_name"]],
            ["Received by", invoice["owner"]["full_name"]],
            ["Property", Paragraph(escape(invoice["listing_title"]), body)],
            ["For", _period_label(invoice["period"]) + (f", one of {seats} seats" if seats else "")],
            ["Paid via", f"{DEPOSIT_METHOD_LABELS[payment['method']]} (ref. {payment['reference']})"],
            ["Confirmed", format_moment(invoice["paid_at"])],
        ],
        colWidths=[30 * mm, 82 * mm],
    )
    facts.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), SOFT),
        ("TEXTCOLOR", (1, 0), (1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    story = [
        Table(
            [[Paragraph("<b>BARI KHUJUN</b>", body), Paragraph(f"Receipt <b>{invoice['receipt_number']}</b><br/>Invoice {invoice['number']}", right)]],
            colWidths=[50 * mm, 62 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, INK)],
        ),
        Spacer(1, 5 * mm),
        Paragraph(f"Rent receipt · {_period_label(invoice['period'])}", title),
        Spacer(1, 4 * mm),
        facts,
        Spacer(1, 5 * mm),
        lines,
        Spacer(1, 4 * mm),
        Paragraph(
            "Shared-flat bills are split equally across all seats in the flat, rounded up to the nearest taka."
            if seats else "Bills are one seat's share, as set by the lister, for each seat held."
            if invoice.get("billed_per_seat") else "Bills shown are for the whole flat.",
            small,
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            f"<font color='#{GATE.hexval()[2:]}'><b>Paid in full.</b></font> The owner confirmed this payment in Bari Khujun.",
            small,
        ),
    ]
    buffer = BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A5, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Receipt {invoice['receipt_number']}", author="Bari Khujun",
    ).build(story)
    return buffer.getvalue()
