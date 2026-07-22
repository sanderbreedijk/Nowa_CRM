from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle)

from nowa_crm.core.paths import data_dir
from nowa_crm.modules.proposals.service import ProposalService

BLUE=colors.HexColor("#176B9A");DARK=colors.HexColor("#0F3554")
LINE=colors.HexColor("#D7E2EA");SOFT=colors.HexColor("#F4F8FA");TEXT=colors.HexColor("#22313A")

def _money(cents:int)->str:
    return f"€ {cents/100:,.2f}".replace(",","X").replace(".",",").replace("X",".")

def _styles():
    s=getSampleStyleSheet();s.add(ParagraphStyle("CoverKicker",parent=s["BodyText"],fontName="Helvetica-Bold",fontSize=10,textColor=BLUE,spaceAfter=7));s.add(ParagraphStyle("CoverTitle",parent=s["Title"],fontName="Helvetica-Bold",fontSize=23,leading=28,textColor=DARK,spaceAfter=7));s.add(ParagraphStyle("CoverSub",parent=s["BodyText"],fontSize=10,leading=13,textColor=colors.HexColor("#647A8B"),spaceAfter=10));s.add(ParagraphStyle("H1N",parent=s["Heading1"],fontName="Helvetica-Bold",fontSize=18,leading=22,textColor=BLUE,spaceAfter=8));s.add(ParagraphStyle("H2N",parent=s["Heading2"],fontName="Helvetica-Bold",fontSize=12,leading=15,textColor=DARK,spaceBefore=7,spaceAfter=5));s.add(ParagraphStyle("BodyN",parent=s["BodyText"],fontSize=8.8,leading=12,textColor=TEXT,spaceAfter=5));s.add(ParagraphStyle("SmallN",parent=s["BodyText"],fontSize=7.4,leading=9.5,textColor=TEXT));s.add(ParagraphStyle("CellN",parent=s["BodyText"],fontSize=7.2,leading=9,textColor=TEXT));s.add(ParagraphStyle("CellHeadN",parent=s["BodyText"],fontName="Helvetica-Bold",fontSize=7.2,leading=9,textColor=colors.white));return s

def _p(text,style,bold=False):
    value=escape(str(text or "")).replace("\n","<br/>")
    return Paragraph(f"<b>{value}</b>" if bold else value,style)

def _title(story,text,s):
    story.extend([_p(text,s["H1N"]),Table([[""]],colWidths=[174*mm],rowHeights=[.6*mm],style=[("BACKGROUND",(0,0),(-1,-1),LINE)]),Spacer(1,4*mm)])

def _table(rows,widths,s,header=True,align_right=()):
    cooked=[]
    for r,row in enumerate(rows):
        style=s["CellHeadN"] if header and r==0 else s["CellN"]
        cooked.append([_p(v,style) for v in row])
    t=Table(cooked,colWidths=widths,repeatRows=1 if header else 0,hAlign="LEFT")
    commands=[("GRID",(0,0),(-1,-1),.3,LINE),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]
    if header:commands.extend([("BACKGROUND",(0,0),(-1,0),BLUE),("TEXTCOLOR",(0,0),(-1,0),colors.white)])
    for r in range(1 if header else 0,len(rows)):
        if r%2==0:commands.append(("BACKGROUND",(0,r),(-1,r),SOFT))
    for col in align_right:commands.append(("ALIGN",(col,1 if header else 0),(col,-1),"RIGHT"))
    t.setStyle(TableStyle(commands));return t

def _bullets(story,items,s):
    for item in items:story.append(_p("• "+item,s["BodyN"]))

def _page(story,title,s):
    story.append(PageBreak());_title(story,title,s)

def _background(canvas,doc,profile,proposal,cover=False):
    canvas.saveState();w,h=A4;assets=Path(__file__).resolve().parents[2]/"assets"
    canvas.setFillColor(colors.white);canvas.rect(0,0,w,h,fill=1,stroke=0)
    if doc.page==1 and (assets/"briefhoofd.png").exists():
        canvas.drawImage(ImageReader(str(assets/"briefhoofd.png")),0,0,width=w,height=h,preserveAspectRatio=False,mask="auto")
    elif doc.page>1:
        canvas.setStrokeColor(LINE);canvas.setLineWidth(.35);canvas.line(17*mm,h-22*mm,w-17*mm,h-22*mm)
        canvas.setFillColor(BLUE);canvas.setFont("Helvetica-Bold",8);canvas.drawRightString(w-17*mm,h-17*mm,profile.get("company_name") or "NOWA Solutions")
        canvas.setFillColor(colors.HexColor("#6B7F8E"));canvas.setFont("Helvetica",7.5);canvas.drawString(17*mm,11*mm,profile.get("footer_text") or "NOWA Solutions");canvas.drawRightString(w-17*mm,11*mm,f"{proposal.number} | Pagina {doc.page}")
    canvas.restoreState()

def export_proposal_pdf(service:ProposalService,proposal_id:int,output_dir:Path|None=None)->Path:
    proposal=service.get(proposal_id)
    if not proposal:raise ValueError("Offerte niet gevonden")
    with service.db.transaction() as conn:
        customer=dict(conn.execute("SELECT * FROM customers WHERE id=?",(proposal.customer_id,)).fetchone())
        contact=conn.execute("SELECT * FROM contacts WHERE customer_id=? ORDER BY id LIMIT 1",(proposal.customer_id,)).fetchone()
        intake=conn.execute("SELECT * FROM project_intakes WHERE customer_id=?",(proposal.customer_id,)).fetchone()
        licenses=[dict(x) for x in conn.execute("SELECT * FROM customer_licenses WHERE customer_id=? ORDER BY product",(proposal.customer_id,))]
        hardware=[dict(x) for x in conn.execute("SELECT * FROM customer_hardware WHERE customer_id=? ORDER BY kind,brand,model",(proposal.customer_id,))]
        commercial=conn.execute("SELECT * FROM customer_commercial_settings WHERE customer_id=?",(proposal.customer_id,)).fetchone()
        profile_row=conn.execute("SELECT * FROM organization_profile WHERE id=1").fetchone()
    profile=dict(profile_row) if profile_row else {"company_name":"NOWA Solutions","footer_text":"NOWA Solutions"}
    counts={"users":int(intake["users_count"] or 0) if intake else 0,"devices":int(intake["devices_count"] or 0) if intake else 0,"shared":int(intake["shared_mailboxes"] or 0) if intake else 0,"teams":int(intake["teams_count"] or 0) if intake else 0,"sites":int(intake["sharepoint_sites"] or 0) if intake else 0}
    lines=[x for x in service.lines(proposal_id) if x.active];once=[x for x in lines if x.billing_period=="eenmalig"];monthly=[x for x in lines if x.billing_period=="maandelijks"]
    labour=[x for x in once if x.kind=="uren"];labour_hours=sum(x.quantity for x in labour);labour_cents=sum(x.line_total_cents for x in labour);hardware_cents=sum(x.line_total_cents for x in once if x.kind=="hardware");totals=service.totals(proposal_id);monthly_cents=service.monthly_total(proposal_id)
    groups=defaultdict(list)
    for x in lines:groups[x.group_name or x.kind.title()].append(x)
    sections=service.sections(proposal_id);duration="circa 1 week" if labour_hours<=40 else ("circa 2 weken" if labour_hours<=80 else "circa 2-3 weken")
    folder=output_dir or data_dir()/"exports";folder.mkdir(parents=True,exist_ok=True);target=folder/f"{proposal.number}-R{proposal.revision}-professionele-offerte.pdf"
    s=_styles();story=[]

    # 1 Voorblad
    story.extend([Spacer(1,46*mm),_p("Implementatie Microsoft 365 / ICT",s["CoverKicker"]),_p(customer["name"],s["CoverTitle"]),_p("Samen werken aan een veilige, beheersbare en toekomstbestendige digitale werkomgeving.",s["CoverSub"])])
    meta=[["Klant",customer["name"]],["Contactpersoon",contact["name"] if contact else ""],["Offertenummer",proposal.number],["Revisie",str(proposal.revision)],["Datum",date.today().strftime("%d-%m-%Y")],["Gewenste uitvoeringsperiode",intake["desired_date"] if intake and intake["desired_date"] else "In overleg met opdrachtgever"],["Gewenste opleverdatum","Door opdrachtgever in te vullen"]]
    story.extend([_table(meta,[48*mm,118*mm],s,False),Spacer(1,7*mm),_p("Deze offerte bevat naast de prijsopgave ook werkzaamheden, uitgangspunten, verantwoordelijkheden, planning, AVG-verklaring, disclaimer en akkoordpagina.",s["SmallN"])])

    # 2 Inhoudsopgave
    _page(story,"Inhoudsopgave",s)
    toc=["1. Begeleidend schrijven","2. Managementsamenvatting","3. Investeringsoverzicht","4. Onze aanpak","5. Projectaannames en besluiten","6. Licenties","7. Hardware","8. Werkzaamheden en urencalculatie","9. Projectplanning","10. Rollen en verantwoordelijkheden","11. Scope en afbakening","12. Software van derden","13. Nazorg en beheer","14. AVG-verklaring","15. Disclaimer","16. Algemene projectvoorwaarden","17. Akkoord"]
    for x in toc:story.append(_p(x,s["BodyN"]))

    # 3 Begeleidend schrijven
    _page(story,"1. Begeleidend schrijven",s);story.append(_p(f"Geachte {contact['name']}," if contact else "Geachte heer/mevrouw,",s["BodyN"]));story.append(_p(f"Hartelijk dank voor het prettige gesprek over de ICT-omgeving van {customer['name']}. Op basis van dit overleg hebben wij een voorstel samengesteld voor de implementatie en inrichting van een moderne Microsoft 365-omgeving.",s["BodyN"]));story.append(_p("Ons uitgangspunt is een stabiele werkomgeving waarin gebruikers eenvoudig kunnen samenwerken, terwijl beheer, beveiliging, documentatie en verantwoordelijkheden duidelijk zijn vastgelegd.",s["BodyN"]));story.append(_p(sections.get("management_summary") or "In dit voorstel leest u welke werkzaamheden worden uitgevoerd, welk resultaat wordt opgeleverd en welke investering daarmee samenhangt.",s["BodyN"]));story.extend([Spacer(1,8*mm),_p("Met vriendelijke groet,",s["BodyN"]),_p(profile.get("company_name") or "NOWA Solutions",s["BodyN"],True)])

    # 4 Managementsamenvatting
    _page(story,"2. Managementsamenvatting",s);cards=[[str(counts["users"]),str(counts["devices"]),f"{labour_hours:g} uur",_money(totals["subtotal_cents"])],["Gebruikers","Apparaten","Totale arbeid","Investering excl. BTW"]];story.append(_table(cards,[42*mm]*4,s,False));story.append(Spacer(1,6*mm));story.append(_p("Projectdoel",s["H2N"]));story.append(_p(sections.get("solution") or f"Voor {customer['name']} wordt een moderne Microsoft 365-omgeving ingericht met veilige toegang, centrale documentopslag, geconfigureerde werkplekken en duidelijke beheerafspraken.",s["BodyN"]));story.append(_p("Resultaat na oplevering",s["H2N"]));_bullets(story,[f"{counts['users']} gebruikers kunnen werken binnen de nieuwe omgeving.",f"{counts['devices']} apparaten worden volgens scope voorbereid of ingericht.",f"{counts['sites']} SharePoint-site(s) worden ingericht.","De omgeving wordt gecontroleerd, gedocumenteerd en formeel opgeleverd."],s);story.append(_table([["Onderdeel","Waarde"],["Verwachte doorlooptijd",duration],["Arbeid",f"{labour_hours:g} uur / {_money(labour_cents)}"],["Hardware",_money(hardware_cents)],["Eenmalig excl. BTW",_money(totals["subtotal_cents"])],["Eenmalig incl. BTW",_money(totals["total_cents"])],["Licenties/diensten p/m",_money(monthly_cents)]],[80*mm,78*mm],s,True,(1,)))

    # 5 Investering
    _page(story,"3. Investeringsoverzicht",s);story.append(_p("Onderstaand overzicht laat zien hoe de totale investering is opgebouwd. De uren en bedragen komen uit dezelfde centrale berekening als de werkzaamheden en projectplanning.",s["BodyN"]));investment=[["Onderdeel","Uren/aantal","Bedrag excl. BTW","Aandeel"]]
    for name,items in groups.items():
        one=[x for x in items if x.billing_period=="eenmalig"];amount=sum(x.line_total_cents for x in one)
        if amount:investment.append([name,f"{sum(x.quantity for x in one if x.kind=='uren'):g}",_money(amount),f"{amount/max(1,totals['subtotal_cents'])*100:.0f}%"])
    investment.extend([["Arbeid totaal",f"{labour_hours:g} uur",_money(labour_cents),f"{labour_cents/max(1,totals['subtotal_cents'])*100:.0f}%"],["Totaal excl. BTW","",_money(totals["subtotal_cents"]),"100%"]]);story.append(_table(investment,[72*mm,25*mm,36*mm,24*mm],s,True,(1,2,3)));story.append(Spacer(1,5*mm));story.append(_p("Deze begroting omvat voorbereiding, afstemming, uitvoering, kwaliteitscontrole, documentatie en oplevering.",s["SmallN"]))

    # 6 Aanpak
    _page(story,"4. Onze aanpak",s);story.append(_p(sections.get("activities") or "Een succesvolle ICT-implementatie begint met een duidelijke scope, goede voorbereiding en heldere afspraken.",s["BodyN"]));approach=[["Stap","Wat dit voor opdrachtgever oplevert"],["Voorbereiding","Randvoorwaarden, toegang, licenties en planning zijn vooraf duidelijk."],["Implementatie","Microsoft 365, beveiliging en werkplekken worden gecontroleerd ingericht."],["Migratie","Gegevens en mailboxen worden volgens de afgesproken aanpak overgezet."],["Testen","De belangrijkste functies, rechten en gegevensstromen worden gecontroleerd."],["Overdracht","Documentatie, beheerafspraken en open punten worden overgedragen."],["Nazorg","Vragen en opleverpunten worden beheerst afgehandeld."]];story.append(_table(approach,[42*mm,125*mm],s));story.append(_p("Kwaliteitscontrole",s["H2N"]));_bullets(story,["Controle op gebruikers, rechten en beveiligingsinstellingen.","Testen van mailflow, samenwerking en werkplekken.","Vastlegging van wijzigingen en beheerinformatie.","Formele oplevering met opdrachtgever."],s)

    # 7 Aannames
    _page(story,"5. Projectaannames en besluiten",s);_bullets(story,[f"Deze offerte is gebaseerd op circa {counts['users']} gebruikers en {counts['devices']} apparaten.","Licenties, beheeraccounts, domeintoegang en gebruikersinformatie worden tijdig beschikbaar gesteld.","NOWA Solutions verzorgt implementatie, migratie, documentatie en oplevering volgens de beschreven scope.","Functionele ondersteuning op gebruikersapplicaties is alleen inbegrepen wanneer dit expliciet is opgenomen.","De definitieve planning wordt na opdrachtverstrekking gezamenlijk vastgesteld.","Wijzigingen in aantallen of scope kunnen invloed hebben op kosten en doorlooptijd."],s);story.append(_p("Besluitvorming",s["H2N"]));story.append(_p("Opdrachtgever wijst één vast aanspreekpunt aan dat beschikbaar is voor planning, keuzes, testmomenten en acceptatie.",s["BodyN"]))

    # 8 Licenties
    _page(story,"6. Licenties",s);licrows=[["Product","Aantal","Leverancier","Prijs p/m","Meegerekend"]]
    for x in licenses:licrows.append([x["product"],str(x["quantity"]),x["supplier"],_money(x["unit_price_cents"]),"Ja" if x["included_in_proposal"] else "Nee"])
    for x in monthly:
        if not any(y["product"].casefold()==x.description.casefold() for y in licenses):licrows.append([x.description,f"{x.quantity:g}","NOWA",_money(x.unit_price_cents),"Ja"])
    if len(licrows)==1:licrows.append(["Geen licenties opgenomen","0","","EUR 0,00","Nee"])
    story.append(_table(licrows,[58*mm,18*mm,38*mm,28*mm,28*mm],s,True,(1,3)));story.append(_p("Licenties die door opdrachtgever of een externe leverancier worden geleverd, worden vermeld maar niet in de NOWA-maandkosten meegerekend.",s["SmallN"]))

    # 9 Hardware
    _page(story,"7. Hardware",s);story.append(_p("Onderstaand overzicht bevat de opgenomen hardware, inclusief aantallen en verkoopprijs.",s["BodyN"]));hwrows=[["Categorie","Merk/model","Aantal","Prijs/stuk","Totaal"]]
    for x in hardware:hwrows.append([x["kind"]," ".join(v for v in (x["brand"],x["model"]) if v),str(x["quantity"]),_money(x["sales_price_cents"]),_money(x["sales_price_cents"]*x["quantity"])])
    if len(hwrows)==1:
        for x in once:
            if x.kind=="hardware":hwrows.append([x.group_name or "Hardware",x.description,f"{x.quantity:g}",_money(x.unit_price_cents),_money(x.line_total_cents)])
    if len(hwrows)==1:hwrows.append(["Geen hardware opgenomen","","0","EUR 0,00","EUR 0,00"])
    story.append(_table(hwrows,[32*mm,63*mm,18*mm,28*mm,30*mm],s,True,(2,3,4)));story.append(Spacer(1,6*mm));story.append(_table([["Samenvatting hardware","Waarde"],["Apparaten",str(counts["devices"])],["Hardwarewaarde",_money(hardware_cents)],["Oplevering","Volgens projectplanning"]],[70*mm,96*mm],s));story.append(_p("Alle hardware wordt vóór oplevering gecontroleerd, voorzien van de afgesproken configuratie en getest binnen de nieuwe omgeving.",s["BodyN"]))

    # 10 Werkzaamheden overzicht
    _page(story,"8. Werkzaamheden en urencalculatie",s);story.append(_p("Onderstaand overzicht beschrijft de belangrijkste werkzaamheden per projectonderdeel. De nadruk ligt op het resultaat voor opdrachtgever en de begrote arbeid.",s["BodyN"]));workrows=[["Projectonderdeel","Omschrijving","Uren/aantal"]]
    for name,items in groups.items():workrows.append([name,"; ".join(x.description for x in items[:3]),f"{sum(x.quantity for x in items if x.kind=='uren'):g}"])
    story.append(_table(workrows,[42*mm,94*mm,24*mm],s,True,(2,)))

    # 11 Werkdetail
    _page(story,"8. Werkzaamheden - inhoudelijke uitwerking",s)
    for name,items in list(groups.items())[:5]:
        story.append(_p(name,s["H2N"]));story.append(_p("Doel: gecontroleerd realiseren en opleveren van dit projectonderdeel.",s["BodyN"]));_bullets(story,[x.description for x in items[:4]],s);hours=sum(x.quantity for x in items if x.kind=="uren");story.append(_p(f"Begrote arbeid: {hours:g} uur" if hours else "Resultaat wordt volgens de opgenomen aantallen geleverd.",s["SmallN"],True))

    # 12 Urenregister
    _page(story,"8. Urenregister en projectbegeleiding",s);hourrows=[["Werkzaamheid","Groep","Uren","Tarief","Totaal"]]
    for x in labour:hourrows.append([x.description,x.group_name or "Project",f"{x.quantity:g}",_money(x.unit_price_cents),_money(x.line_total_cents)])
    if len(hourrows)==1:hourrows.append(["Geen uren opgenomen","","0","EUR 0,00","EUR 0,00"])
    hourrows.append(["Totaal arbeid","",f"{labour_hours:g}","",_money(labour_cents)]);story.append(_table(hourrows,[65*mm,37*mm,17*mm,25*mm,28*mm],s,True,(2,3,4)));story.append(_p("Deze uren dekken voorbereiding, coördinatie, communicatie, uitvoering, documentatie, oplevering en kwaliteitscontrole.",s["BodyN"]))

    # 13 Planning
    _page(story,"9. Projectplanning",s);story.append(_p(sections.get("planning") or "De projectplanning wordt opgebouwd vanuit dezelfde urenberekening als deze offerte.",s["BodyN"]));story.append(_p(f"Planningsoverzicht: totale begrote arbeid {labour_hours:g} uur. Bij normale beschikbaarheid is de verwachte doorlooptijd {duration}.",s["BodyN"],True));planning=[["Fase","Resultaat","Uren","Indicatie"],["Inventarisatie en voorbereiding","Scope, toegang en planning bevestigd",f"{max(2,labour_hours*.12):.1f}","Week 1"],["Inrichting en migratie","Omgeving en gegevens ingericht",f"{labour_hours*.55:.1f}","Week 1-2"],["Testen en kwaliteitscontrole","Belangrijkste functies gecontroleerd",f"{labour_hours*.15:.1f}","Week 2"],["Oplevering en nazorg","Documentatie en open punten overgedragen",f"{labour_hours*.18:.1f}","Week 2-3"]];story.append(_table(planning,[38*mm,76*mm,20*mm,28*mm],s,True,(2,)))

    # 14 Tijdlijn
    _page(story,"9. Compacte tijdlijn en mijlpalen",s);timeline=[["Fase","Week 1","Week 2","Week 3"],["Inventarisatie & voorbereiding","X X X X","",""],["Microsoft 365 inrichting","X X X X","X X",""],["Migratie en samenwerking","X X","X X X X",""],["Beveiliging / MFA","X X","X X",""],["Hardware / werkplekken","","X X X X",""],["Testen & kwaliteitscontrole","","X X",""],["Oplevering & documentatie","","","X X"],["Projectcoördinatie & nazorg","X X","X X","X X"]];story.append(_table(timeline,[60*mm,34*mm,34*mm,34*mm],s));story.append(_p("Mijlpalen",s["H2N"]));story.append(_table([["Mijlpaal","Resultaat"],["Kick-off afgerond","Planning, aanspreekpunten en randvoorwaarden bevestigd."],["Basisinrichting afgerond","Kerninstellingen en beveiliging ingericht."],["Migratie voltooid","Gebruikers kunnen in de nieuwe omgeving werken."],["Acceptatie","Opdrachtgever controleert de belangrijkste onderdelen."],["Oplevering","Documentatie en beheerafspraken overgedragen."]],[55*mm,112*mm],s))

    # 15 Rollen
    _page(story,"10. Rollen en verantwoordelijkheden",s);roles=[["Onderwerp","NOWA Solutions","Opdrachtgever"],["Projectleiding en planning","Verzorgen","Afstemmen en beschikbaarheid bewaken"],["Microsoft 365 inrichting","Uitvoeren","Benodigde toegang aanleveren"],["Migratie","Uitvoeren en testen","Gebruikersinformatie aanleveren"],["Beveiliging / MFA","Configureren en testen","Gebruikers informeren"],["Licenties","Controleren","Tijdig beschikbaar stellen"],["Acceptatie","Opleveren en toelichten","Controleren en akkoord geven"],["Nazorg","Ondersteunen","Open punten tijdig melden"]];story.append(_table(roles,[50*mm,58*mm,62*mm],s));story.append(_p("Een vast aanspreekpunt met beslissingsbevoegdheid voorkomt vertraging en onduidelijkheid tijdens de uitvoering.",s["BodyN"]))

    # 16 Scope
    _page(story,"11. Scope en afbakening",s);story.append(_p(sections.get("scope") or "Deze offerte beschrijft de werkzaamheden die NOWA Solutions uitvoert binnen de overeengekomen scope.",s["BodyN"]));scope=[["Onderdeel","Toelichting"],["Software van derden","Alleen inbegrepen wanneer expliciet als werkzaamheid opgenomen."],["Bestaande storingen","Herstel van reeds aanwezige fouten valt buiten deze offerte."],["Microsoft 365 back-up","Alleen inbegrepen wanneer afzonderlijk opgenomen."],["Doorlopend beheer / SLA","Valt buiten deze offerte tenzij expliciet overeengekomen."],["Meerwerk","Wordt vooraf besproken en pas na akkoord uitgevoerd."]];story.append(_table(scope,[48*mm,122*mm],s));story.append(_p("Aannames",s["H2N"]));_bullets(story,["Aangeleverde informatie is volledig en correct.","Licenties, accounts en domeintoegang zijn tijdig beschikbaar.","Key-users zijn beschikbaar voor test- en acceptatiemomenten."],s)

    # 17-21 vaste inhoud
    _page(story,"12. Software van derden",s);story.append(_p("Binnen de organisatie kan gebruik worden gemaakt van software van derden, zoals financiële, kerkelijke, branchespecifieke of maatwerkapplicaties. Functionele ondersteuning hierop valt buiten de scope, tenzij expliciet opgenomen.",s["BodyN"]));story.append(_p("Wanneer koppelingen, exports, imports of rechten nodig zijn, stelt opdrachtgever tijdig leverancierstoegang, documentatie en contactpersonen beschikbaar.",s["BodyN"]));story.append(_table([["Onderwerp","Afspraak"],["Functionele werking","Verantwoordelijkheid van leverancier of opdrachtgever."],["Technische koppeling","Alleen inbegrepen indien beschreven."],["Leverancierscontact","Opdrachtgever faciliteert toegang en afstemming."],["Meerwerk","Wordt vooraf gemeld en geaccordeerd."]],[48*mm,122*mm],s))
    _page(story,"13. Nazorg en beheer",s);story.append(_p("Nazorg wordt standaard uitgevoerd op basis van nacalculatie tegen het geldende uurtarief, tenzij een inbegrepen nazorgpakket of beheercontract is opgenomen.",s["BodyN"]));story.append(_p("Nazorg is bedoeld voor vragen rond de oplevering en punten die direct samenhangen met de implementatie. Structureel beheer, monitoring en gebruikerssupport vallen erbuiten.",s["BodyN"]));story.append(_table([["Onderdeel","Nazorg","Structureel beheer"],["Oplevervragen","Ja",""],["Herstel eigen implementatiefout","Ja",""],["Nieuwe wijzigingsverzoeken","","Apart"],["Monitoring en periodiek beheer","","Beheercontract"],["Gebruikerssupport","","Servicedesk/SLA"]],[55*mm,45*mm,65*mm],s))
    _page(story,"14. AVG-verklaring",s);story.append(_p(sections.get("privacy") or "Tijdens de uitvoering kan NOWA Solutions toegang krijgen tot persoonsgegevens. Deze worden uitsluitend verwerkt voor uitvoering van de overeengekomen werkzaamheden.",s["BodyN"]));avg=[["Onderwerp","Uitgangspunt"],["Doelbinding","Alleen gebruik voor uitvoering van de opdracht."],["Beveiliging","Passende technische en organisatorische maatregelen."],["Vertrouwelijkheid","Informatie van opdrachtgever wordt vertrouwelijk behandeld."],["Bewaartermijn","Niet langer dan noodzakelijk of wettelijk verplicht."],["Verantwoordelijkheid","Opdrachtgever blijft verantwoordelijk voor juistheid en rechtmatigheid."],["Datalekken","Opdrachtgever wordt zo spoedig mogelijk geïnformeerd."]];story.append(_table(avg,[46*mm,124*mm],s));story.append(_p("Indien noodzakelijk kan separaat een verwerkersovereenkomst worden gesloten.",s["BodyN"]))
    _page(story,"15. Disclaimer",s);story.append(_p(sections.get("disclaimer") or "Deze offerte is gebaseerd op de informatie die tijdens inventarisatie en klantgesprek beschikbaar was.",s["BodyN"]));disc=[["Onderwerp","Toelichting"],["Scopewijzigingen","Kunnen leiden tot aangepaste planning en prijsopgave."],["Leveranciers","Prijzen, beschikbaarheid en functionaliteiten kunnen wijzigen."],["Derden","NOWA is niet aansprakelijk voor beperkingen veroorzaakt door derden."],["Bestaande omgeving","Verborgen gebreken kunnen extra werkzaamheden veroorzaken."],["Meerwerk","Wordt vooraf besproken en pas na akkoord uitgevoerd."],["Geldigheid","Deze offerte is een momentopname binnen de vermelde termijn."]];story.append(_table(disc,[45*mm,125*mm],s));story.append(_p("Aan deze offerte kunnen geen rechten worden ontleend voor werkzaamheden die niet expliciet zijn opgenomen.",s["BodyN"]))
    _page(story,"16. Algemene projectvoorwaarden",s);terms=[["Onderwerp","Afspraak"],["Communicatie","Eén vast aanspreekpunt bij beide partijen."],["Bereikbaarheid","Tijdige bereikbaarheid is noodzakelijk voor voortgang."],["Wijzigingen","Scope, planning en aantallen worden schriftelijk bevestigd."],["Acceptatie","Opdrachtgever controleert de belangrijkste onderdelen."],["Oplevering","Met documentatie en eventuele openpuntenlijst."],["Garantie op werkzaamheden","Eigen aantoonbare fouten worden binnen redelijke termijn hersteld."],["Nazorg","Is geen vervanging voor beheercontract of SLA."],["Meerwerk","Wordt niet zonder akkoord uitgevoerd."]];story.append(_table(terms,[45*mm,125*mm],s));story.append(_p(f"Betalingstermijn: {commercial['payment_term_days'] if commercial else 14} dagen. Geldigheid offerte: {commercial['validity_days'] if commercial else 30} dagen.",s["BodyN"],True))

    # 22 Akkoord
    _page(story,"17. Akkoord",s);story.append(_p("Door ondertekening verklaart opdrachtgever akkoord te gaan met de beschreven werkzaamheden, uitgangspunten, scope, voorwaarden en prijsopgave.",s["BodyN"]));left=[["Akkoord opdrachtgever",""],["Organisatie",customer["name"]],["Naam",contact["name"] if contact else ""],["Functie",contact["role"] if contact else ""],["Plaats",customer["city"]],["Datum",""],["Gewenste uitvoeringsperiode",""],["Gewenste opleverdatum",""],["Bijzonderheden","\n\n"],["Handtekening","\n\n\n"]];right=[[profile.get("company_name") or "NOWA Solutions",""],["Naam","Sander Breedijk"],["Functie","Directie / projectverantwoordelijke"],["Plaats",profile.get("postal_city") or ""],["Datum",""],["Handtekening","\n\n\n"]];story.append(Table([[_table(left,[38*mm,49*mm],s,False),Spacer(6*mm,1),_table(right,[38*mm,49*mm],s,False)]],colWidths=[87*mm,6*mm,87*mm],style=[("VALIGN",(0,0),(-1,-1),"TOP")]))

    doc=BaseDocTemplate(str(target),pagesize=A4,title=f"Offerte {customer['name']}",author=profile.get("company_name") or "NOWA Solutions",leftMargin=17*mm,rightMargin=17*mm,topMargin=31*mm,bottomMargin=24*mm)
    frame=Frame(doc.leftMargin,doc.bottomMargin,A4[0]-doc.leftMargin-doc.rightMargin,A4[1]-doc.topMargin-doc.bottomMargin,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="NOWA",frames=[frame],onPage=lambda c,d:_background(c,d,profile,proposal))]);doc.build(story);return target
