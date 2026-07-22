from __future__ import annotations
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle,getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak,Paragraph,SimpleDocTemplate,Spacer,Table,TableStyle

from nowa_crm.core.paths import data_dir
from nowa_crm.modules.proposals.service import ProposalService

def _money(cents:int)->str:
    return f"EUR {cents/100:,.2f}".replace(",","X").replace(".",",").replace("X",".")

def export_proposal_pdf(service:ProposalService,proposal_id:int,output_dir:Path|None=None)->Path:
    proposal=service.get(proposal_id)
    if not proposal:raise ValueError("Offerte niet gevonden")
    with service.db.transaction() as conn:
        customer=conn.execute("SELECT name,street,postal_code,city,email FROM customers WHERE id=?",(proposal.customer_id,)).fetchone()
        commercial=conn.execute("SELECT * FROM customer_commercial_settings WHERE customer_id=?",(proposal.customer_id,)).fetchone()
        profile_row=conn.execute("SELECT * FROM organization_profile WHERE id=1").fetchone()
    profile=dict(profile_row) if profile_row else {"company_name":"NOWA Solutions","primary_color":"#0B2342","footer_text":"NOWA Solutions"}
    company=profile.get("company_name") or "NOWA Solutions";primary=colors.HexColor(profile.get("primary_color") or "#0B2342")
    folder=output_dir or data_dir()/"exports";folder.mkdir(parents=True,exist_ok=True);target=folder/f"{proposal.number}-R{proposal.revision}.pdf"
    styles=getSampleStyleSheet();styles.add(ParagraphStyle(name="NowaTitle",parent=styles["Title"],textColor=primary,fontSize=28,leading=33));styles.add(ParagraphStyle(name="Section",parent=styles["Heading1"],textColor=primary,fontSize=20,spaceAfter=10));styles.add(ParagraphStyle(name="Right",parent=styles["BodyText"],alignment=TA_RIGHT));styles["BodyText"].leading=16
    doc=SimpleDocTemplate(str(target),pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=22*mm,bottomMargin=20*mm,title=f"{proposal.number} - {proposal.title}",author=company)
    story=[Spacer(1,24*mm),Paragraph(company,styles["Heading2"]),Spacer(1,12*mm),Paragraph("Offerte",styles["NowaTitle"]),Paragraph(escape(proposal.title),styles["Heading1"]),Spacer(1,22*mm),Paragraph(f"<b>Voor:</b> {escape(customer['name'] if customer else proposal.customer_name)}",styles["BodyText"])]
    if customer:
        address=" ".join(str(customer[x] or "") for x in ("street","postal_code","city")).strip()
        if address:story.append(Paragraph(escape(address),styles["BodyText"]))
    story.extend([Spacer(1,16*mm),Paragraph(f"Offertenummer: <b>{proposal.number}</b>",styles["BodyText"]),Paragraph(f"Revisie: <b>{proposal.revision}</b>",styles["BodyText"]),Paragraph(f"Datum: <b>{date.today():%d-%m-%Y}</b>",styles["BodyText"]),PageBreak()])
    sections=service.sections(proposal_id)
    for key,title in service.SECTION_TITLES.items():
        text=sections.get(key,"").strip()
        if not text:continue
        story.extend([Paragraph(title,styles["Section"]),Paragraph(escape(text).replace("\n","<br/>"),styles["BodyText"]),Spacer(1,8*mm)])
        if key in ("solution","activities","privacy"):story.append(PageBreak())
    story.extend([Paragraph("Investering",styles["Section"]),Paragraph("Onderstaand overzicht maakt eenmalige en terugkerende kosten afzonderlijk inzichtelijk.",styles["BodyText"]),Spacer(1,5*mm)])
    active=[x for x in service.lines(proposal_id) if x.active]
    for period,title in (("eenmalig","Eenmalige investering"),("maandelijks","Maandelijkse dienstverlening en licenties")):
        lines=[x for x in active if x.billing_period==period]
        if not lines:continue
        story.extend([Paragraph(title,styles["Heading2"]),_table(lines,styles,primary),Spacer(1,5*mm)])
        subtotal=sum(x.line_total_cents for x in lines);story.append(Paragraph(f"Subtotaal excl. btw: <b>{_money(subtotal)}</b>",styles["Right"]));story.append(Spacer(1,5*mm))
    totals=service.totals(proposal_id);story.extend([Paragraph(f"Btw over eenmalige investering: {_money(totals['vat_cents'])}",styles["Right"]),Paragraph(f"Eenmalig totaal incl. btw: <b>{_money(totals['total_cents'])}</b>",styles["Right"]),Paragraph(f"Maandelijks excl. btw: <b>{_money(service.monthly_total(proposal_id))}</b>",styles["Right"]),PageBreak(),Paragraph("Voorwaarden en akkoord",styles["Section"]),Paragraph(f"Betalingstermijn: {commercial['payment_term_days'] if commercial else 14} dagen. Geldigheid: {commercial['validity_days'] if commercial else 30} dagen.",styles["BodyText"]),Spacer(1,18*mm),Paragraph("Naam: ____________________________________    Datum: ____________________",styles["BodyText"]),Spacer(1,14*mm),Paragraph("Handtekening: ______________________________________________________",styles["BodyText"])])
    def footer(canvas,document):
        canvas.saveState();canvas.setStrokeColor(primary);canvas.line(20*mm,13*mm,A4[0]-20*mm,13*mm);canvas.setFont("Helvetica",8);canvas.setFillColor(colors.HexColor("#52657A"));canvas.drawString(20*mm,8*mm,profile.get("footer_text") or company);canvas.drawRightString(A4[0]-20*mm,8*mm,f"{proposal.number} | Pagina {document.page}");canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return target

def _table(lines,styles,primary):
    rows=[["Groep","Omschrijving","Aantal","Prijs","Totaal"]]
    for x in lines:rows.append([x.group_name,Paragraph(escape(x.description),styles["BodyText"]),f"{x.quantity:g}",_money(x.unit_price_cents),_money(x.line_total_cents)])
    table=Table(rows,colWidths=[30*mm,70*mm,17*mm,25*mm,28*mm],repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),primary),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ALIGN",(2,1),(-1,-1),"RIGHT"),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#CAD5E2")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F7FB")]),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]));return table

