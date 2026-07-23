from pathlib import Path
import json
import shutil
import sqlite3
import zipfile
from datetime import date, timedelta
from email.message import EmailMessage

import pytest
from cryptography.fernet import Fernet

from nowa_crm.core.database import Database
from nowa_crm.core.auth import AuthService
from nowa_crm.core.events import EventBus
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.customers.importer import CustomerImportService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.proposals.legacy_importer import LegacyProposalImportService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService, normalize_phone
from nowa_crm.modules.customer360.service import Customer360Service
from nowa_crm.modules.migration.service import LegacyImportService
from nowa_crm.modules.assets.service import CustomerAssetsService
from nowa_crm.modules.servicedesk.service import ServiceDeskService
from nowa_crm.modules.reporting.service import ReportingService
from nowa_crm.modules.planning.service import PlanningService
from nowa_crm.modules.security.service import SecurityService
from nowa_crm.modules.communications.service import CommunicationService
from nowa_crm.modules.documents.service import DocumentCenterService
from nowa_crm.modules.integrations.service import IntegrationService
from nowa_crm.modules.daystart.service import DaystartService
from nowa_crm.modules.proposals.pdf import export_proposal_pdf
from nowa_crm.integrations.coligo import ColigoAdapter
from nowa_crm.app import _startup_phone
from nowa_crm.core.updater import ReleaseInfo, UpdateService, _version_tuple
from nowa_crm.core.backup import BackupService


def test_customer_and_vault_roundtrip(tmp_path: Path):
    source_root = Path(__file__).parents[1] / "src"
    for source in source_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not any(marker in text for marker in ("Ã", "Â", "â€")), f"Beschadigde UTF-8-tekst in {source}"
    dossier_ui = (source_root / "nowa_crm" / "ui" / "customer360_page.py").read_text(encoding="utf-8")
    assert "360° klantdossier" in dossier_ui and "commerciële" in dossier_ui and "één klant" in dossier_ui
    navigation_ui = (source_root / "nowa_crm" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "NavSection" in navigation_ui
    assert all(section in navigation_ui for section in ("Start","Klanten","Verkoop","Service","Projecten","Systeem"))
    assert "Gemiste oproepen" in navigation_ui
    assert "ClickableCard" in navigation_ui and "CardLink" in navigation_ui
    assert "self.customer_table.blockSignals(True)" in navigation_ui
    assert 'call["status"]!="nieuw"' in navigation_ui
    sip_ui = (source_root / "nowa_crm" / "integrations" / "sip_monitor.py").read_text(encoding="utf-8")
    assert "seen_invites" in sip_ui and "if duplicate:continue" in sip_ui
    servicedesk_ui = (source_root / "nowa_crm" / "ui" / "servicedesk_page.py").read_text(encoding="utf-8")
    assert "TicketDraftDialog" in servicedesk_ui and "create_ticket_from_source" in servicedesk_ui
    assert "ActiveCallPanel" in navigation_ui and "end_active_call" in navigation_ui
    assert "Alle prioriteiten" in navigation_ui and "Wat is er nodig?" in navigation_ui
    assert '("LI","Licenties"' not in navigation_ui and '("HW","Hardware"' not in navigation_ui
    assert "Niet toegewezen" in navigation_ui and "day<today" in navigation_ui
    call_workspace_ui = (source_root / "nowa_crm" / "ui" / "incoming_call_popup.py").read_text(encoding="utf-8")
    assert "CENTRALE WERKPLEK" in call_workspace_ui and "_return_to_workspace" in call_workspace_ui
    assert "CallQuickBlock" in call_workspace_ui and "schedule_autosave" in call_workspace_ui
    assert "missed_timer" not in call_workspace_ui and "_next_workdays" in call_workspace_ui
    assert "CallOpenItem" in call_workspace_ui and "Controle voor afsluiten" in call_workspace_ui
    assert "Minimaliseren" in call_workspace_ui and "CallFollowup" in call_workspace_ui
    db = Database(tmp_path / "test.sqlite3"); db.migrate()
    assert (tmp_path / "backups").exists()
    auth = AuthService(db)
    auth.create_user("beheerder", "Beheerder", "veilig-wachtwoord", "administrator")
    session = auth.authenticate("beheerder", "veilig-wachtwoord")
    assert session and session.can("vault.read")
    assert auth.authenticate("beheerder", "verkeerd") is None
    customers = CustomerService(db, EventBus())
    customer_id = customers.create("K-001", "Voorbeeld BV", "info@example.nl", "0101234567", "Coolsingel 1", "3012 AA", "Rotterdam", "Belangrijke klant")
    assert customers.search("010123")[0].id == customer_id
    contact_id = customers.save_contact(customer_id, "Sander", "Directeur", "sander@example.nl", "0612345678")
    assert customers.search("Sander")[0].id == customer_id
    assert customers.contacts(customer_id)[0].id == contact_id
    proposals = ProposalService(db)
    professional = next(item for item in proposals.templates() if item["name"] == "NOWA Professional")
    professional_config = proposals.template_configuration(professional["id"])
    assert len(professional_config["sections"]) == 14
    assert professional_config["calculation"]["minimum_total_hours"] == 56.0
    assert professional_config["calculation"]["hourly_rate_eur"] == 94.0
    with db.transaction() as conn:
        professional_line_count = conn.execute(
            "SELECT COUNT(*) FROM proposal_template_lines WHERE template_id=?",
            (professional["id"],),
        ).fetchone()[0]
    assert professional_line_count == 7
    db.migrate()
    with db.transaction() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM proposal_templates WHERE name='NOWA Professional'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM proposal_template_lines WHERE template_id=?",
            (professional["id"],),
        ).fetchone()[0] == professional_line_count
    proposal_id = proposals.create(customer_id, "Modernisering werkplekken")
    assert proposals.list("Modernisering")[0].id == proposal_id
    proposals.add_line(proposal_id, "uren", "Implementatie", 10, 12500)
    proposals.add_line(proposal_id, "licentie", "Microsoft 365", 5, 2060)
    assert proposals.get(proposal_id).total_cents == 135300
    assert proposals.totals(proposal_id) == {"subtotal_cents": 135300, "vat_cents": 28413, "total_cents": 163713}
    template = proposals.templates()[0]
    proposals.apply_template(proposal_id, template["id"])
    assert len(proposals.lines(proposal_id)) > 2
    catalog_id=proposals.save_catalog_item("BACKUP-MON","Beheerde cloudback-up","Licentie","maand",2495,"Maanddienst")
    proposals.add_catalog_line(proposal_id,catalog_id,2)
    assert any(item["code"]=="BACKUP-MON" for item in proposals.catalog("backup"))
    proposals.save_texts(proposal_id,"Een heldere introductie voor de klant.","Uitvoering in overleg met opdrachtgever.")
    copy_id=proposals.duplicate(proposal_id)
    assert proposals.get(copy_id).introduction.startswith("Een heldere") and len(proposals.lines(copy_id))==len(proposals.lines(proposal_id))
    saved_template=proposals.save_as_template(proposal_id,"Klantgerichte beheeroplossing")
    assert any(item["id"]==saved_template for item in proposals.templates())
    vault = VaultService(db, tmp_path / "vault.key", "beheerder", session)
    entry_id = vault.add(customer_id, "Microsoft 365 beheer", "admin@example.nl", "heel-geheim")
    assert vault.search(customer_id, "Microsoft")[0]["id"] == entry_id
    with db.transaction() as conn:
        verification_call=int(conn.execute("INSERT INTO call_events(external_id,phone_number,normalized_number,customer_id,handled_by) VALUES('vault-test','0612345678','0612345678',?,'beheerder')",(customer_id,)).lastrowid)
    failed_verification=vault.record_verification(entry_id,verification_call,"Sander","Contactpersoon en controlevraag","Toegang herstellen",True,False)
    try:vault.reveal(entry_id,"Onvoldoende verificatie",failed_verification);assert False
    except PermissionError:pass
    successful_verification=vault.record_verification(entry_id,verification_call,"Sander","Terugbellen op geregistreerd nummer","Klant telefonisch geverifieerd",True,True)
    assert vault.reveal(entry_id,"Klant telefonisch geverifieerd",successful_verification) == "heel-geheim"
    try:vault.reveal(entry_id,"Verificatie niet hergebruiken",successful_verification);assert False
    except PermissionError:pass
    keepass = tmp_path / "keepass.csv"
    keepass.write_text("Title,Username,Password,URL,Notes,Group\nRouter,admin,router-geheim,https://192.168.1.1,Lokaal,Netwerk\n", encoding="utf-8")
    assert vault.import_keepass_csv(customer_id, keepass) == 1
    assert vault.search_all("Router")[0]["category"] == "Netwerk"
    operations = OperationsService(db)
    operations.save_user(customer_id, "Sander", "sander@example.nl", "Directie", "Microsoft 365 Business Premium", False)
    operations.save_license(customer_id, "Microsoft 365 Business Premium", quantity=1, unit_price_cents=2060)
    operations.save_hardware(customer_id, "Laptop", "Lenovo", "ThinkPad", "ABC-123", 1, 80000, 109900)
    operations.save_intake(customer_id, 1, 1, 0, 1, 1, "Microsoft 365 tenant", "Binnen 1 maand", "Gefaseerde migratie")
    operations.save_task(customer_id, "Inventarisatie", "Technische intake")
    assert operations.dashboard() == {"users": 1, "licenses": 1, "hardware": 1, "open_tasks": 1}
    assert operations.license_warnings(customer_id) == ["1 actieve gebruikers hebben nog geen MFA-registratie."]
    assert operations.intake(customer_id)["teams_count"] == 1
    planning=PlanningService(db,tmp_path/"planning")
    task=planning.list(customer_id)[0]
    planning.save(customer_id,task["phase"],task["task_name"],"Sander","2026-07-01","2026-07-02","Klantgegevens","Gereed","Afgerond",task["id"])
    second_task=planning.save(customer_id,"Migratie","Mailboxmigratie","NOWA","2026-07-03","2026-07-04","Technische intake","Wacht op klant")
    stats=planning.stats(customer_id)
    assert stats["total"] == 2 and stats["done"] == 1 and stats["waiting"] == 1 and stats["progress"] == 50
    assert planning.export_csv(customer_id).read_text(encoding="utf-8-sig").startswith("Fase;Taak;")
    assert planning.export_pdf(customer_id).read_bytes().startswith(b"%PDF")
    planning.delete(second_task)
    assert planning.stats(customer_id)["progress"] == 100
    security=SecurityService(db,tmp_path/"security")
    security_summary=security.summary(customer_id)
    assert security_summary["score"] < 100
    assert any(item["category"]=="MFA" and item["severity"]=="Hoog" for item in security_summary["findings"])
    assert security.audit(customer_id)
    security_csv=security.export_csv(customer_id)
    assert security_csv.exists() and "MFA" in security_csv.read_text(encoding="utf-8-sig")
    security_report=security.export_report(customer_id)
    assert "Beveiligingsscore" in security_report.read_text(encoding="utf-8")
    workspace = WorkspaceService(db, proposals, "beheerder", tmp_path)
    workspace.add_note(customer_id, "Afspraak", "Migratie gefaseerd uitvoeren")
    tomorrow=(date.today()+timedelta(days=1)).isoformat()
    action_id = workspace.add_action(customer_id, "DNS controleren", "Sander", tomorrow, "Hoog", "Controle na wijziging", "Terugbellen", f"{tomorrow} 09:00")
    assert workspace.actions(customer_id)[0]["id"] == action_id
    assert workspace.actions(period="Komende 7 dagen")[0]["action_type"] == "Terugbellen"
    assert workspace.action_summary()["upcoming"] == 1
    workspace.set_action_status(action_id,"Wacht op klant")
    assert workspace.actions(customer_id)[0]["status"] == "Wacht op klant"
    workspace.reschedule_action(action_id,date.today().isoformat())
    assert workspace.action_summary()["today"] == 1
    assert workspace.global_search("Technische intake")[0]["kind"] == "Projecttaak"
    assert workspace.notes(customer_id)[0]["subject"] == "Afspraak"
    workspace.save_commercial_settings(customer_id, 9900, 5, 14, 30)
    generated_id = workspace.build_intake_proposal(customer_id, "Automatische migratieofferte")
    assert proposals.get(generated_id).total_cents > 0
    assert "Voortgang IT-project" in workspace.progress_mail(customer_id)
    assert len(workspace.export_customer_csv(customer_id)) == 4
    assert workspace.backup().exists()
    workspace.complete_action(action_id)
    assert workspace.actions(customer_id) == []
    mail = MailService(db, "beheerder", tmp_path)
    template = next(item for item in mail.templates() if item["category"] == "Offerte")
    rendered = mail.render_template(template["id"], customer_id, contact_id, generated_id)
    assert proposals.get(generated_id).number in rendered["subject"]
    message_id = mail.create_draft(customer_id, rendered["recipient"], rendered["subject"], rendered["body"], contact_id)
    attachment = tmp_path / "offerte.pdf"; attachment.write_bytes(b"%PDF-voorbeeld")
    mail.add_attachment(message_id, attachment)
    eml = mail.export_eml(message_id)
    assert eml.exists() and b"offerte.pdf" in eml.read_bytes()
    mail.mark_sent(message_id)
    incoming_id = mail.record_incoming("sander@example.nl", "info@nowa.nl", "Akkoord", "Offerte is akkoord")
    assert mail.get(incoming_id)["customer_id"] == customer_id
    assert {item["status"] for item in mail.list_messages(customer_id)} == {"verzonden", "ontvangen"}
    unknown_mail=mail.record_incoming("onbekend@gmail.com","service@nowa.nl","Nieuwe vraag","Kunt u helpen?")
    assert mail.get(unknown_mail)["customer_id"] is None
    mail.link_customer(unknown_mail,customer_id)
    assert mail.detect_customer("onbekend@gmail.com")[0]==customer_id
    mail.triage(unknown_mail,"wacht_op_klant","Hoog","Sander","2026-08-04")
    assert mail.list_messages(queue="open")[0]["priority"]=="Hoog"
    queue=mail.queue_stats();assert queue["open"]>=1 and queue["urgent"]>=1 and queue["unlinked"]==0
    reply_id=mail.reply_draft(unknown_mail)
    assert mail.get(reply_id)["subject"]=="Re: Nieuwe vraag"
    mail.triage(unknown_mail,"afgerond","Hoog","Sander","2026-08-04")
    assert mail.list_messages(queue="afgerond")[0]["id"]==unknown_mail
    telephony = TelephonyService(db, workspace, "beheerder")
    assert normalize_phone("+31 6 12345678") == "0612345678"
    match = telephony.recognize("06-12345678")
    assert match["customer"]["id"] == customer_id
    assert match["contact"]["id"] == contact_id
    call_id = telephony.register_call("+31 6 12345678", external_id="coligo-test-1")
    telephony.finish_call(call_id, "Servicevraag", "Klant telefonisch geholpen", "Informatie verstrekt", True, "2026-08-02")
    assert telephony.get(call_id)["status"] == "afgerond"
    assert telephony.history(customer_id)[0]["id"] == call_id
    communications = CommunicationService(mail, telephony)
    combined = communications.timeline(customer_id)
    assert {item["channel"] for item in combined} == {"E-mail", "Telefoon"}
    assert communications.timeline(customer_id, "Servicevraag", "Telefoon")[0]["id"] == call_id
    communication_stats = communications.stats(customer_id)
    assert communication_stats["total"] == 6
    assert communication_stats["incoming"] == 4 and communication_stats["outgoing"] == 2
    unknown_call=telephony.register_call("085-0000000",external_id="coligo-unknown-1")
    assert telephony.get(unknown_call)["customer_id"] is None
    telephony.link_customer(unknown_call,customer_id)
    assert telephony.recognize("0850000000")["customer"]["id"]==customer_id
    second_customer=customers.create("K-002","Tweede klant",phone="085 000 00 00")
    second_call=telephony.register_call("0850000000",external_id="multi-link")
    telephony.link_customer(second_call,second_customer,contact_name="Centrale",description="Algemeen nummer")
    multiple=telephony.recognize("085-0000000")
    assert multiple["customer"] is None and len(multiple["matches"])==2
    telephony.select_match(second_call,second_customer,multiple["matches"][1].get("contact_id"))
    assert telephony.get(second_call)["customer_id"]==second_customer
    assert telephony.register_call("0850000000",external_id="coligo-unknown-1")==unknown_call
    queue_before=telephony.queue_stats()
    missed_call=telephony.mark_missed("06-12345678","coligo-missed-1")
    assert telephony.get(missed_call)["status"]=="gemist"
    assert telephony.history(queue="terugbellen")[0]["callback_status"]=="open"
    call_queue=telephony.queue_stats();assert call_queue["callbacks"]==queue_before["callbacks"]+1 and call_queue["missed"]==queue_before["missed"]+1
    telephony.complete_callback(missed_call)
    assert telephony.queue_stats()["callbacks"]==queue_before["callbacks"]
    old_missed=telephony.mark_missed("010-9999999","old-missed-cleanup")
    with db.transaction() as conn:
        conn.execute("UPDATE call_events SET started_at=datetime('now','-31 days') WHERE id=?",(old_missed,))
    assert telephony.cleanup_missed_calls(30)==1 and telephony.get(old_missed) is None
    assert telephony.missed_stats()["total"]>=1
    telephony.mark_missed("06-12345678","daystart-missed-1")
    telephony.mark_missed("06-12345678","daystart-missed-2")
    daystart_calls=[item for item in DaystartService(db).items()
                    if item["kind"]=="Terugbellen" and item["title"].startswith("Gemiste oproepen")]
    assert len(daystart_calls)==1
    assert any(item["title"].startswith("Terugbellen:") for item in workspace.actions(customer_id))
    calls = []
    coligo = ColigoAdapter(); coligo.start(calls.append)
    coligo.ingest("0612345678", "coligo-test-2", "Sander")
    assert calls[0].external_id == "coligo-test-2"
    assert _startup_phone(["--phone", "0101234567"]) == "0101234567"
    assert _startup_phone(["tel:+31612345678"]) == "+31612345678"
    dossier = Customer360Service(customers, proposals, vault, operations, workspace, mail, telephony)
    snapshot = dossier.snapshot(customer_id)
    assert snapshot["customer"].name == "Voorbeeld BV"
    assert len(snapshot["contacts"]) == 1
    assert len(snapshot["proposals"]) == 3
    assert len(snapshot["vault"]) == 2
    assert len(snapshot["users"]) == len(snapshot["licenses"]) == len(snapshot["hardware"]) == 1
    call_snapshot=telephony.call_workspace_snapshot(customer_id,contact_id)
    assert call_snapshot["users"]==1 and call_snapshot["teams"]==1
    assert call_snapshot["licenses"][0]["product"]=="Microsoft 365 Business Premium"
    assert call_snapshot["departments"][0]["department"]=="Directie"
    assert len(call_snapshot["recent_calls"])<=3
    assert call_snapshot["open_items"]
    draft_call=telephony.register_call("06-12345678",external_id="autosave-draft")
    telephony.save_call_draft(draft_call,"Tussentijds","Nog bezig","Beantwoord","Hoog","2026-08-03")
    saved_draft=telephony.get(draft_call)
    assert saved_draft["subject"]=="Tussentijds" and saved_draft["notes"]=="Nog bezig"
    assert saved_draft["status"]=="nieuw" and saved_draft["ended_at"] is None
    assert 0<=snapshot["pulse"]["score"]<=100
    assert snapshot["pulse"]["label"] in ("Sterk","Aandacht","Kritiek")
    assert len(snapshot["pulse"]["briefing"])==4
    assert any(item["kind"] == "Gesprek" for item in dossier.timeline(customer_id))
    assert any(item["kind"] == "E-mail" for item in dossier.timeline(customer_id))
    assert all(item["group"] in ("Communicatie","Service","Commercieel","Werk","Dossier") for item in dossier.timeline(customer_id))
    assets = CustomerAssetsService(db,tmp_path/"documents")
    location_id = assets.add_location(customer_id,"Hoofdkantoor","Coolsingel 1","Rotterdam")
    assert assets.add_location(customer_id,"Hoofdkantoor") == location_id
    software_id = assets.add_software(customer_id,"Exact Online","Exact","Cloud","NOWA ondersteunt")
    document_source = tmp_path/"netwerkplan.txt"; document_source.write_text("Lokaal klantdocument",encoding="utf-8")
    document_id = assets.add_document(customer_id,"Netwerkplan",document_source,"Techniek")
    assert assets.document_path(document_id).read_text(encoding="utf-8") == "Lokaal klantdocument"
    assert assets.add_document(customer_id,"Netwerkplan",document_source,"Techniek") == document_id
    servicedesk = ServiceDeskService(db,"beheerder")
    ticket_id = servicedesk.create(customer_id,"Internetverbinding valt uit","Sinds vanochtend instabiel","Storing","Kritiek","Sander","2026-08-01 12:00",contact_id)
    assert servicedesk.get(ticket_id)["number"].startswith("TK-")
    servicedesk.add_update(ticket_id,"Routerlogboeken onderzocht","In behandeling")
    servicedesk.add_time(ticket_id,45,"Analyse en herstel")
    service_stats=servicedesk.stats(customer_id)
    assert service_stats["open"] == service_stats["critical"] == 1 and service_stats["minutes"] == 45
    assert servicedesk.get(ticket_id)["sla_state"] in ("Binnen SLA","Dreigt","Overschreden")
    servicedesk.close(ticket_id,"Defecte uplinkkabel vervangen")
    assert servicedesk.get(ticket_id)["status"] == "Gesloten"
    closed_stats=servicedesk.stats(customer_id)
    assert closed_stats["open"] == closed_stats["critical"] == 0 and closed_stats["closed"] == 1
    printer_ticket=servicedesk.create(customer_id,"Printer niet bereikbaar","Controle nodig","Support","Hoog","NOWA","2026-08-03",contact_id)
    source_ticket=servicedesk.create_from_source(customer_id,"Servicevraag","Vanuit telefoongesprek","Telefoon",call_id,"Normaal")
    assert servicedesk.get(source_ticket)["source_type"] == "Telefoon"
    assert servicedesk.get(source_ticket)["sla_due_at"]
    assert len(servicedesk.list(customer_id,priority="Normaal")) == 1
    maintenance_id=servicedesk.add_maintenance(customer_id,"Firewallcontrole","Maandelijks","2026-08-15")
    assert servicedesk.maintenance(customer_id)[0]["id"] == maintenance_id
    reporting=ReportingService(db,"beheerder",mail,tmp_path/"rapportages")
    report=reporting.compose(customer_id,"Sander")
    assert "Voortgangsupdate IT-project" in report["subject"]
    assert "Printer niet bereikbaar" in report["body"]
    assert report["progress"] == 100
    report_id=reporting.save(customer_id,"Sander")
    assert reporting.get(report_id)["progress_percent"] == 100
    report_path=reporting.export_text(customer_id,"Sander")
    assert report_path.exists() and "Acties en aandachtspunten" in report_path.read_text(encoding="utf-8")
    report_mail=reporting.create_mail_draft(customer_id,contact_id,"Sander")
    assert mail.get(report_mail)["status"] == "concept"
    integrations=IntegrationService(db,mail,telephony,"beheerder")
    outlook_import=tmp_path/"outlook-import";outlook_import.mkdir()
    imported_message=EmailMessage();imported_message["From"]="Sander <sander@example.nl>";imported_message["To"]="info@nowa.nl"
    imported_message["Subject"]="Nieuwe Outlook servicevraag";imported_message["Message-ID"]="<nowa-test-240@example.nl>"
    imported_message.set_content("Graag ondersteuning bij de printer.");imported_message.add_attachment(b"voorbeeld",maintype="text",subtype="plain",filename="vraag.txt")
    (outlook_import/"servicevraag.eml").write_bytes(imported_message.as_bytes())
    integrations.save("outlook",True,{"mode":"eml_folder","mailbox_address":"service@nowa.nl","folder_path":str(outlook_import),"token":"nooit-opslaan"})
    integrations.save("coligo",True,{"mode":"local_ingest","line_name":"Hoofdlijn","password":"nooit-opslaan"})
    assert integrations.settings("outlook")["settings"]["mailbox_address"] == "service@nowa.nl"
    assert "token" not in integrations.settings("outlook")["settings"]
    first_sync=integrations.sync_outlook_folder();second_sync=integrations.sync_outlook_folder()
    assert first_sync["imported"]==first_sync["linked"]==1 and second_sync["duplicates"]==1
    imported_mail=next(item for item in mail.list_messages(customer_id) if item["subject"]=="Nieuwe Outlook servicevraag")
    assert mail.attachments(imported_mail["id"])[0]["original_name"]=="vraag.txt"
    assert mail.dossier_stats()["unlinked"]==0
    outlook_file=integrations.prepare_outlook(report_mail)
    assert outlook_file.exists() and outlook_file.suffix == ".eml"
    coligo_call=integrations.ingest_coligo("06-12345678","coligo-live-1","Hoofdlijn")
    assert coligo_call["customer_id"] == customer_id
    webhook_call=integrations.ingest_coligo_event({"remoteNumber":"+31 6 12345678","callId":"coligo-webhook-1","event":"ringing"})
    assert webhook_call["customer_id"] == customer_id
    webhook_missed=integrations.ingest_coligo_event({"caller":"0850000000","id":"coligo-webhook-2","status":"missed"})
    assert integrations.telephony.get(webhook_missed["id"])["status"] == "gemist"
    assert "open servicetickets" in telephony.customer_briefing(customer_id)["summary"]
    assert telephony.customer_briefing(None)["summary"] == "Nummer nog niet gekoppeld"
    integrations.save_sip(True,{"server":"sip.example.nl","server_port":"5080","local_port":"5080",
        "username":"100","domain":"example.nl","transport":"UDP","auto_start":"1"},"lokaal-geheim")
    sip_settings=integrations.sip_runtime_settings()
    assert sip_settings["password"]=="lokaal-geheim" and sip_settings["local_port"]=="5080"
    assert "lokaal-geheim" not in str(integrations.settings("sip"))
    sip_call=integrations.ingest_sip_event({"phone_number":"0612345678","external_id":"sip-call-1","display_name":"Sander"})
    assert sip_call["customer_id"]==customer_id
    assert {item["provider"] for item in integrations.events()} == {"outlook","coligo","sip"}
    documents=DocumentCenterService(db,assets,mail)
    documents.save_profile("NOWA Test","Teststraat 1","1000 AA Test","010-1234567","info@nowa.test",
                           "https://nowa.test","#123456","Lokale testvoettekst")
    assert documents.profile()["primary_color"] == "#123456"
    document_rows=documents.search("Netwerkplan",customer_id)
    assert document_rows[0]["kind"] == "Document" and document_rows[0]["id"] == document_id
    assert {row["kind"] for row in documents.search("",customer_id)} >= {"Document","Offerte","Rapportage"}
    documents.mail.save_template("Testupdate","Test {klantnaam}","Beste {contactnaam}","Test")
    assert any(row["name"]=="Testupdate" for row in documents.templates())
    branded_pdf=export_proposal_pdf(proposals,proposal_id,tmp_path/"branded-pdf")
    assert branded_pdf.read_bytes().startswith(b"%PDF")
    assert workspace.global_search("Printer")[0]["kind"] == "Ticket"
    assert workspace.global_search("Netwerkplan")[0]["kind"] == "Document"
    assert any(row["kind"]=="E-mail" and row["entity_id"]==incoming_id for row in workspace.global_search("Akkoord"))
    assert any(row["kind"]=="Gesprek" and row["entity_id"]==call_id for row in workspace.global_search("Servicevraag"))
    assert workspace.global_search("heel-geheim") == []
    dossier_service = Customer360Service(customers,proposals,vault,operations,workspace,mail,telephony,assets,servicedesk,reporting)
    dossier_assets = dossier_service.snapshot(customer_id)
    assert dossier_assets["locations"][0]["id"] == location_id
    assert dossier_assets["software"][0]["id"] == software_id
    assert dossier_assets["documents"][0]["id"] == document_id
    assert any(item["id"] == ticket_id for item in dossier_assets["tickets"])
    assert dossier_assets["reports"][0]["customer_id"] == customer_id
    assert any(item["kind"] == "Ticket" for item in dossier_service.timeline(customer_id))
    assert any(item["kind"] == "Rapportage" for item in dossier_service.timeline(customer_id))
    daystart=DaystartService(db);day_items=daystart.items()
    assert {item["kind"] for item in day_items}>={"Actie","E-mail","Terugbellen","Ticket","Beveiliging"}
    selected_day=next(item for item in day_items if item["kind"]=="Actie")
    daystart.assign(selected_day["kind"],selected_day["entity_id"],"Sander")
    assert any(item["assigned_to"]=="Sander" for item in daystart.items(owner="Sander"))
    future_day=(date.today()+timedelta(days=10)).isoformat();daystart.snooze(selected_day["kind"],selected_day["entity_id"],future_day)
    assert all(not (item["kind"]==selected_day["kind"] and item["entity_id"]==selected_day["entity_id"]) for item in daystart.items())
    mail_day=next(item for item in daystart.items() if item["kind"]=="E-mail");daystart.dismiss(mail_day["kind"],mail_day["entity_id"])
    assert daystart.summary()["total"]>=1
    legacy = tmp_path / "oude-workspace.sqlite3"; legacy_key = tmp_path / "secret.key"; key = Fernet.generate_key(); legacy_key.write_bytes(key)
    with sqlite3.connect(legacy) as conn:
        conn.execute("""CREATE TABLE customers(id INTEGER PRIMARY KEY,customer_number TEXT,name TEXT,organisation_type TEXT,contact_name TEXT,email TEXT,phone TEXT,postcode TEXT,street TEXT,city TEXT,address TEXT,notes TEXT,created_at TEXT,updated_at TEXT)""")
        conn.execute("""CREATE TABLE contacts(id INTEGER PRIMARY KEY,customer_id INTEGER,name TEXT,role TEXT,email TEXT,phone TEXT,notes TEXT,created_at TEXT)""")
        conn.execute("""CREATE TABLE secrets(id INTEGER PRIMARY KEY,customer_id INTEGER,label TEXT,username TEXT,encrypted_value BLOB,notes TEXT,updated_at TEXT,category TEXT,vault_path TEXT,host TEXT,url TEXT,linked_user_id INTEGER)""")
        conn.execute("INSERT INTO customers VALUES(2,'OUD-002','Oude Klant BV','','','oud@example.nl','0201234567','1000 AA','Dam 1','Amsterdam','','Importtest','','')")
        conn.execute("INSERT INTO contacts VALUES(1,2,'Oude Contact','Directeur','contact@oud.nl','0611111111','','')")
        conn.execute("INSERT INTO secrets VALUES(1,2,'Oude router','admin',?,'','','Netwerk','Netwerk','192.168.1.1','',NULL)",(Fernet(key).encrypt(b"oud-geheim"),))
    migration = LegacyImportService(db,customers,proposals,vault,operations,workspace,assets)
    assert migration.preview(legacy)["warnings"]
    assert migration.preview(legacy,legacy_key)["counts"]["customers"] == 1
    imported = migration.import_database(legacy,legacy_key)
    assert imported["created"]["customers"] == imported["created"]["contacts"] == imported["created"]["secrets"] == 1
    old_customer = customers.search("OUD-002")[0]
    old_entry=vault.search(old_customer.id,"Oude router")[0]["id"]
    old_call=telephony.register_call("0611111111",external_id="vault-migratie-test")
    old_verification=vault.record_verification(old_entry,old_call,"Oude Contact","Contactpersoon en controlevraag","Migratietest toegang",True,True)
    assert vault.reveal(old_entry,"Migratietest",old_verification) == "oud-geheim"
    repeated = migration.import_database(legacy,legacy_key)
    assert repeated["created"]["customers"] == repeated["created"]["contacts"] == repeated["created"]["secrets"] == 0
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] >= 8
    assert _version_tuple("v0.10.0") > _version_tuple("0.3.0")
    assert ReleaseInfo("v99.0.0", "Test", "", "https://github.com/test.zip", "").is_newer
    update_zip=tmp_path/"NOWA_CRM-Windows.zip"
    with zipfile.ZipFile(update_zip,"w") as package:
        package.writestr("NOWA_CRM/NOWA_CRM.exe",b"test-app")
        package.writestr("NOWA_CRM/_internal/runtime.dll",b"runtime")
    prepared=UpdateService().prepare_local_package(update_zip)
    assert (prepared/"NOWA_CRM.exe").read_bytes()==b"test-app"
    unsafe_zip=tmp_path/"onveilig.zip"
    with zipfile.ZipFile(unsafe_zip,"w") as package:
        package.writestr("NOWA_CRM/data/klanten.sqlite3",b"verboden")
    with pytest.raises(RuntimeError,match="verboden gegevensbestand"):
        UpdateService().prepare_local_package(unsafe_zip)
    backup_root=tmp_path/"backup-data";backup_root.mkdir()
    shutil.copy2(tmp_path/"test.sqlite3",backup_root/"nowa.sqlite3")
    (backup_root/"vault.key").write_bytes(b"lokale-kluissleutel")
    (backup_root/"documents").mkdir();(backup_root/"documents"/"contract.txt").write_text("test",encoding="utf-8")
    backup_db=Database(backup_root/"nowa.sqlite3")
    recovery=BackupService(backup_db,backup_root).create()
    assert recovery.valid and recovery.files>=3
    assert (recovery.folder/"vault.key").read_bytes()==b"lokale-kluissleutel"
    assert BackupService(backup_db,backup_root).latest().valid
    assert BackupService(backup_db,backup_root).prepare_restore(recovery.folder).valid
    (recovery.folder/"vault.key").write_bytes(b"gemanipuleerd")
    with pytest.raises(RuntimeError,match="beschadigd of onvolledig"):
        BackupService(backup_db,backup_root).prepare_restore(recovery.folder)

    import_db=Database(tmp_path/"customer-import.sqlite3");import_db.migrate()
    import_customers=CustomerService(import_db,EventBus());import_customers.create("OUD-1","Uit te faseren klant")
    import_file=tmp_path/"klanten.xlsx"
    _write_customer_xlsx(import_file,[
        ["Relatiecode","Naam","Contactpersoon","Adres","Postcode","Plaats","LandNaam","Telefoon","MobieleTelefoon","Fax","Email","Krediettermijn"],
        ["1643","Aannemersbedrijf Gebr. Bergstra B.V.","Jan Bergstra","Lopikerweg West 5","3411 AL","Lopik","Nederland","0348-551329","0612345678","fax-negeren","factuur@bergstrabv.nl","14"],
    ])
    importer=CustomerImportService(import_db,"beheerder");preview=importer.preview(import_file)
    assert (preview.created,preview.updated,preview.archived)==(1,0,1)
    result=importer.apply(preview);assert result["backup"].exists()
    imported_customer=import_customers.search("1643")[0]
    assert imported_customer.mobile_phone=="06-12345678" and imported_customer.country==""
    assert import_customers.contacts(imported_customer.id)[0].name=="Jan Bergstra"
    assert import_customers.search("Uit te faseren")==[]
    with import_db.transaction() as conn:
        assert conn.execute("SELECT active FROM customers WHERE customer_number='OUD-1'").fetchone()[0]==0
        assert "fax-negeren" not in str(dict(conn.execute("SELECT * FROM customers WHERE id=?",(imported_customer.id,)).fetchone()))
        assert 24 in [row[0] for row in conn.execute("SELECT version FROM schema_versions")]
    assert importer.history()[0]["unchanged_count"]==0
    assert {item["action"] for item in importer.changes(result["run_id"])}=={"nieuw","gedeactiveerd"}
    export_file=importer.export_active(tmp_path/"actieve-klanten.xlsx")
    assert export_file.exists() and zipfile.is_zipfile(export_file)
    restored=importer.undo(result["run_id"]);assert restored["restored"]==2
    assert import_customers.search("Uit te faseren")[0].customer_number=="OUD-1"
    assert import_customers.search("1643")==[]
    importer.reactivate("1643")
    assert import_customers.search("1643")[0].name=="Aannemersbedrijf Gebr. Bergstra B.V."

    quote_db=Database(tmp_path/"quote-import.sqlite3");quote_db.migrate()
    quote_customers=CustomerService(quote_db,EventBus())
    quote_customer_id=quote_customers.create("DOEL-1","Gekozen importklant")
    quote_proposals=ProposalService(quote_db);quote_operations=OperationsService(quote_db)
    quote_assets=CustomerAssetsService(quote_db,tmp_path/"quote-documents")
    quote_importer=LegacyProposalImportService(quote_db,quote_proposals,quote_operations,quote_assets)
    quote_package=tmp_path/"oude-offerte.zip"
    manifest={
        "format":"nowa-crm-legacy-proposal","format_version":1,
        "source_fingerprint":"oude-offerte-test-1","source_number":"OFF-2026-1001",
        "source_date":"2026-07-10","title":"Volledige oude offerte",
        "introduction":"Historische introductie","terms":"Historische voorwaarden",
        "pdf_file":"origineel.pdf",
        "proposal_lines":[
            {"kind":"uren","description":"Migratie","quantity":10.5,"unit_price_cents":9400},
            {"kind":"hardware","description":"Werkplek","quantity":2,"unit_price_cents":99900},
            {"kind":"licentie","description":"Licentie buiten eenmalige prijs","quantity":30,"unit_price_cents":0},
        ],
        "intake":{"users_count":30,"devices_count":30,"shared_mailboxes":4,"teams_count":4,"sharepoint_sites":4,
                  "migration_source":"Microsoft 365","desired_date":"In overleg","scope_notes":"Volledige scope"},
        "licenses":[{"product":"Microsoft 365 Business Premium","supplier":"TechSoup","quantity":30,
                     "unit_price_cents":2060,"included":False,"notes":"Maandprijs"}],
        "hardware":[{"kind":"Notebook","brand":"Lenovo","model":"ThinkBook 16","quantity":2,
                     "sales_price_cents":99900,"notes":"Offertehardware"}],
        "expected_totals":{"subtotal_cents":298500},
    }
    with zipfile.ZipFile(quote_package,"w") as archive:
        archive.writestr("proposal_import.json",json.dumps(manifest))
        archive.writestr("origineel.pdf",b"%PDF-1.4\n% testdocument\n")
    quote_preview=quote_importer.preview(quote_package)
    assert quote_preview.labor_hours==10.5 and quote_preview.subtotal_cents==298500
    quote_result=quote_importer.apply(quote_preview,quote_customer_id)
    assert len(quote_proposals.lines(quote_result["proposal_id"]))==3
    assert quote_proposals.get(quote_result["proposal_id"]).number=="OFF-2026-1001"
    assert quote_proposals.get(quote_result["proposal_id"]).terms=="Historische voorwaarden"
    assert quote_operations.intake(quote_customer_id)["shared_mailboxes"]==4
    assert quote_operations.list_rows("licenses",quote_customer_id)[0]["quantity"]==30
    assert quote_operations.list_rows("hardware",quote_customer_id)[0]["model"]=="ThinkBook 16"
    assert quote_assets.list("documents",quote_customer_id)[0]["original_name"]=="origineel.pdf"
    try:quote_importer.apply(quote_preview,quote_customer_id);assert False
    except ValueError as exc:assert "al geïmporteerd" in str(exc)


def _write_customer_xlsx(path: Path, rows: list[list[str]]) -> None:
    cells=[]
    for row_index,row in enumerate(rows,1):
        parts=[]
        for column_index,value in enumerate(row):
            number=column_index+1;letters=""
            while number:
                number,remainder=divmod(number-1,26);letters=chr(65+remainder)+letters
            parts.append(f'<c r="{letters}{row_index}" t="inlineStr"><is><t>{value}</t></is></c>')
        cells.append(f'<row r="{row_index}">{"".join(parts)}</row>')
    sheet='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(cells)+'</sheetData></worksheet>'
    with zipfile.ZipFile(path,"w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml",sheet)
