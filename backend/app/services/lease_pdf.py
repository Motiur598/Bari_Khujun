"""Lease agreement PDF, generated once when the QR handshake confirms a booking."""

from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.booking import DEPOSIT_METHOD_LABELS
from app.schemas.marketplace import DHAKA_TZ
from app.services.listings import full_address

INK = colors.HexColor("#264076")
SOFT = colors.HexColor("#5a6680")
RULE = colors.HexColor("#d6dacd")
GATE = colors.HexColor("#287a39")
PLASTER = colors.HexColor("#eff1e8")

CATEGORY_TITLES = {
    "FAMILY_FLAT": "Residential Lease Agreement (Family Flat)",
    "BACHELOR_FLAT": "Residential Lease Agreement (Bachelor Flat)",
    "BACHELOR_SEAT": "Shared Accommodation Agreement (Single Seat)",
}
GUEST_POLICY = {"NOT_ALLOWED": "No guests", "DAYTIME_ONLY": "Daytime guests only", "ALLOWED": "Guests allowed"}
DOC_LABELS = {"NID": "National ID", "STUDENT_ID": "Student ID", "JOB_ID": "Job ID"}


def taka(amount: int) -> str:
    # Helvetica has no taka sign, so amounts are written as BDT.
    return f"BDT {amount:,}"


def format_day(value: date | str) -> str:
    value = date.fromisoformat(value) if isinstance(value, str) else value
    return value.strftime("%d %b %Y").lstrip("0")


def format_moment(value: datetime) -> str:
    return value.astimezone(DHAKA_TZ).strftime("%d %b %Y, %I:%M %p").lstrip("0") + " (Dhaka)"


def _mask(number: str) -> str:
    """Show only the last four characters of an ID number on the printed lease."""
    return "*" * max(0, len(number) - 4) + number[-4:]


def _qr_stamp(url: str, size: float = 34 * mm) -> Drawing:
    widget = QrCodeWidget(url, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    return drawing


def build_lease_pdf(lease: dict) -> bytes:
    """`lease` carries the snapshot taken at confirmation: listing, owner, tenant, terms and verify_url."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=SOFT)
    heading = ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=5)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=21)
    right = ParagraphStyle("right", parent=small, alignment=TA_RIGHT)

    listing, owner, tenant = lease["listing"], lease["owner"], lease["tenant"]
    rules, pricing = listing["house_rules"], listing["pricing"]

    def grid(rows, widths, header=False):
        table = Table(rows, colWidths=widths)
        style = [
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("FONT", (0, 0), (0, -1), "Helvetica", 9),
            ("TEXTCOLOR", (0, 0), (0, -1), SOFT),
        ]
        if header:
            style += [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), INK),
                ("BACKGROUND", (0, 0), (-1, 0), PLASTER),
            ]
        table.setStyle(TableStyle(style))
        return table

    def party_lines(person):
        documents = ", ".join(
            f"{DOC_LABELS.get(d['doc_type'], d['doc_type'])} {_mask(d['doc_number'])}" for d in person["documents"]
        ) or "None on file"
        return [
            person["full_name"],
            person["phone"],
            person["email"],
            f"Identity: {person['kyc_status'].replace('_', ' ').title()}",
            documents,
        ]

    story = [
        Table(
            [[Paragraph("<b>BARI KHUJUN</b>", body), Paragraph(f"Lease no. <b>{lease['number']}</b><br/>{format_moment(lease['confirmed_at'])}", right)]],
            colWidths=[90 * mm, 80 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, INK)],
        ),
        Spacer(1, 6 * mm),
        Paragraph(lease.get("agreement_title") or CATEGORY_TITLES[listing["category"]], title),
        Spacer(1, 2 * mm),
        Paragraph(
            "This agreement records the tenancy confirmed through a Bari Khujun QR handshake between the owner "
            "and the tenant named below.",
            body,
        ),
        Paragraph("1. Property", heading),
        grid(
            [
                ["Listing", listing["title"]],
                ["Address", full_address(listing["location"])],
                ["Floor", f"{listing['building']['floor_level']} of {listing['building']['total_floors']} (0 = ground)"],
                ["Let as", lease.get("let_as") or ("One seat in a shared flat" if listing["category"] == "BACHELOR_SEAT" else "Whole flat")],
            ],
            [35 * mm, 135 * mm],
        ),
        Paragraph("2. Parties", heading),
        grid(
            [["", "Owner / lister", "Tenant"]]
            + [[label, o, t] for label, o, t in zip(
                ["Name", "Phone", "Email", "Verification", "ID documents"], party_lines(owner), party_lines(tenant)
            )],
            [35 * mm, 67.5 * mm, 67.5 * mm],
            header=True,
        ),
        Paragraph("3. Rent and deposit", heading),
        grid(
            [
                ["Monthly rent", taka(lease["agreed_rent"])],
                ["Service charge", taka(lease["service_charge"])],
                ["Utilities (estimate)", f"{taka(lease['utility_estimate'])}, billed on a {rules['meter_type'].lower()} meter"],
                ["Advance deposit", f"{taka(lease['deposit']['amount'])} via {DEPOSIT_METHOD_LABELS[lease['deposit']['method']]} (ref. {lease['deposit']['reference']})"],
                ["Deposit terms", f"{pricing['deposit_months']} month(s) of rent as listed"],
                ["Move-in date", format_day(lease["move_in_date"])],
            ],
            [35 * mm, 135 * mm],
        ),
        Paragraph("4. House rules", heading),
        grid(
            [
                ["Gate", f"Closes at {rules['gate_closing_time']}" if rules["gate_closing_time"] else "Open all night"],
                ["Guests", GUEST_POLICY[rules["guest_policy"]]],
                ["Smoking", "Allowed" if rules["smoking_allowed"] else "Not allowed"],
            ],
            [35 * mm, 135 * mm],
        ),
        Paragraph("5. Standard terms", heading),
        Paragraph(
            "a) The tenant pays the monthly rent in advance each month. "
            "b) The advance deposit is returned at the end of the tenancy, less any unpaid rent, bills or damage. "
            "c) Either party may end the tenancy with one month's written notice. "
            "d) Both parties agree to follow the house rules above.",
            body,
        ),
        Paragraph("6. Escrow record", heading),
        grid(
            [["Time", "Status", "Note"]]
            + [[format_moment(e["at"]), e["status"].replace("_", " ").title(), Paragraph(escape(e["note"]), small)] for e in lease["escrow_ledger"]],
            [48 * mm, 27 * mm, 95 * mm],
            header=True,
        ),
        Spacer(1, 6 * mm),
        KeepTogether(
            Table(
                [[
                    Paragraph(
                        f"<b>Confirmed by QR handshake</b><br/>The owner issued a single-use code and the tenant scanned it "
                        f"in the Bari Khujun app on {format_moment(lease['confirmed_at'])}.<br/><br/>"
                        f"Scan the stamp to check this lease against Bari Khujun records.<br/>"
                        f"<font size='7' color='#5a6680'>{escape(lease['verify_url'])}</font><br/><br/>"
                        f"<font size='7' color='#5a6680'>Template agreement generated by Bari Khujun. Both parties should read "
                        f"it before relying on it.</font>",
                        body,
                    ),
                    _qr_stamp(lease["verify_url"]),
                ]],
                colWidths=[130 * mm, 40 * mm],
                style=[
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (1, 0), (1, 0), 1.5, GATE),
                    ("LEFTPADDING", (1, 0), (1, 0), 3 * mm),
                    ("TOPPADDING", (1, 0), (1, 0), 3 * mm),
                ],
            )
        ),
    ]

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Lease {lease['number']}", author="Bari Khujun",
    ).build(story)
    return buffer.getvalue()
