from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from nowa_crm.core.paths import data_dir
from nowa_crm.modules.proposals.service import ProposalService


def _money(cents: int) -> str:
    return f"€ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def export_proposal_pdf(service: ProposalService, proposal_id: int) -> Path:
    proposal = service.get(proposal_id)
    if not proposal:
        raise ValueError("Offerte niet gevonden")
    with service.db.transaction() as conn:
        row = conn.execute("SELECT name,street,postal_code,city FROM customers WHERE id=?", (proposal.customer_id,)).fetchone()
    customer = dict(row) if row else {"name": proposal.customer_name, "street": "", "postal_code": "", "city": ""}
    lines = service.lines(proposal_id)
    totals = service.totals(proposal_id)
    folder = data_dir() / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{proposal.number}.pdf"

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="NowaTitle", parent=styles["Title"], textColor=colors.HexColor("#0B2342"), fontSize=23, leading=27))
    styles.add(ParagraphStyle(name="Right", parent=styles["BodyText"], alignment=TA_RIGHT))
    doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"{proposal.number} - {proposal.title}", author="NOWA Solutions")
    story = [
        Paragraph("NOWA Solutions", styles["Heading2"]),
        Paragraph("Offerte", styles["NowaTitle"]),
        Paragraph(f"<b>{proposal.number}</b> &nbsp; | &nbsp; Revisie {proposal.revision}", styles["BodyText"]),
        Spacer(1, 8 * mm),
        Paragraph(proposal.title, styles["Heading1"]),
        Paragraph(f"<b>Voor:</b> {customer['name']}", styles["BodyText"]),
    ]
    address = " ".join(value for value in (customer["street"], customer["postal_code"], customer["city"]) if value)
    if address:
        story.append(Paragraph(address, styles["BodyText"]))
    story.extend([Spacer(1, 8 * mm), Paragraph("Investeringsoverzicht", styles["Heading2"])])
    rows = [["Omschrijving", "Aantal", "Prijs", "Totaal"]]
    for line in lines:
        rows.append([Paragraph(line.description, styles["BodyText"]), f"{line.quantity:g}", _money(line.unit_price_cents), _money(line.line_total_cents)])
    table = Table(rows, colWidths=[92 * mm, 20 * mm, 27 * mm, 29 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2342")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#CAD5E2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([
        table, Spacer(1, 6 * mm),
        Paragraph(f"Subtotaal: <b>{_money(totals['subtotal_cents'])}</b>", styles["Right"]),
        Paragraph(f"Btw 21%: {_money(totals['vat_cents'])}", styles["Right"]),
        Paragraph(f"Totaal inclusief btw: <b>{_money(totals['total_cents'])}</b>", styles["Right"]),
        Spacer(1, 14 * mm),
        Paragraph("Uitgangspunten", styles["Heading2"]),
        Paragraph("Deze offerte is gebaseerd op de hierboven beschreven aantallen en werkzaamheden. Meerwerk wordt uitsluitend na afstemming uitgevoerd.", styles["BodyText"]),
        Spacer(1, 12 * mm),
        Paragraph("Akkoord opdrachtgever", styles["Heading2"]),
        Paragraph("Naam: ____________________________________&nbsp;&nbsp;&nbsp; Datum: ____________________", styles["BodyText"]),
        Spacer(1, 10 * mm),
        Paragraph("Handtekening: ______________________________________________________", styles["BodyText"]),
    ])
    doc.build(story)
    return target
