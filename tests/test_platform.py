from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet

from nowa_crm.core.database import Database
from nowa_crm.core.auth import AuthService
from nowa_crm.core.events import EventBus
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService, normalize_phone
from nowa_crm.modules.customer360.service import Customer360Service
from nowa_crm.modules.migration.service import LegacyImportService
from nowa_crm.integrations.coligo import ColigoAdapter
from nowa_crm.app import _startup_phone
from nowa_crm.core.updater import ReleaseInfo, _version_tuple


def test_customer_and_vault_roundtrip(tmp_path: Path):
    source_root = Path(__file__).parents[1] / "src"
    for source in source_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not any(marker in text for marker in ("Ã", "Â", "â€")), f"Beschadigde UTF-8-tekst in {source}"
    dossier_ui = (source_root / "nowa_crm" / "ui" / "customer360_page.py").read_text(encoding="utf-8")
    assert "360° klantdossier" in dossier_ui and "commerciële" in dossier_ui and "één klant" in dossier_ui
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
    proposal_id = proposals.create(customer_id, "Modernisering werkplekken")
    assert proposals.list("Modernisering")[0].id == proposal_id
    proposals.add_line(proposal_id, "uren", "Implementatie", 10, 12500)
    proposals.add_line(proposal_id, "licentie", "Microsoft 365", 5, 2060)
    assert proposals.get(proposal_id).total_cents == 135300
    assert proposals.totals(proposal_id) == {"subtotal_cents": 135300, "vat_cents": 28413, "total_cents": 163713}
    template = proposals.templates()[0]
    proposals.apply_template(proposal_id, template["id"])
    assert len(proposals.lines(proposal_id)) > 2
    vault = VaultService(db, tmp_path / "vault.key", "beheerder", session)
    entry_id = vault.add(customer_id, "Microsoft 365 beheer", "admin@example.nl", "heel-geheim")
    assert vault.search(customer_id, "Microsoft")[0]["id"] == entry_id
    assert vault.reveal(entry_id, "Klant telefonisch geverifieerd") == "heel-geheim"
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
    workspace = WorkspaceService(db, proposals, "beheerder", tmp_path)
    workspace.add_note(customer_id, "Afspraak", "Migratie gefaseerd uitvoeren")
    action_id = workspace.add_action(customer_id, "DNS controleren", "Sander", "2026-08-01", "Hoog")
    assert workspace.actions(customer_id)[0]["id"] == action_id
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
    telephony = TelephonyService(db, workspace, "beheerder")
    assert normalize_phone("+31 6 12345678") == "0612345678"
    match = telephony.recognize("06-12345678")
    assert match["customer"]["id"] == customer_id
    assert match["contact"]["id"] == contact_id
    call_id = telephony.register_call("+31 6 12345678", external_id="coligo-test-1")
    telephony.finish_call(call_id, "Servicevraag", "Klant telefonisch geholpen", "Informatie verstrekt", True, "2026-08-02")
    assert telephony.get(call_id)["status"] == "afgerond"
    assert telephony.history(customer_id)[0]["id"] == call_id
    assert workspace.actions(customer_id)[0]["title"].startswith("Terugbellen:")
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
    assert len(snapshot["proposals"]) == 2
    assert len(snapshot["vault"]) == 2
    assert len(snapshot["users"]) == len(snapshot["licenses"]) == len(snapshot["hardware"]) == 1
    assert any(item["kind"] == "Gesprek" for item in dossier.timeline(customer_id))
    assert any(item["kind"] == "E-mail" for item in dossier.timeline(customer_id))
    legacy = tmp_path / "oude-workspace.sqlite3"; legacy_key = tmp_path / "secret.key"; key = Fernet.generate_key(); legacy_key.write_bytes(key)
    with sqlite3.connect(legacy) as conn:
        conn.execute("""CREATE TABLE customers(id INTEGER PRIMARY KEY,customer_number TEXT,name TEXT,organisation_type TEXT,contact_name TEXT,email TEXT,phone TEXT,postcode TEXT,street TEXT,city TEXT,address TEXT,notes TEXT,created_at TEXT,updated_at TEXT)""")
        conn.execute("""CREATE TABLE contacts(id INTEGER PRIMARY KEY,customer_id INTEGER,name TEXT,role TEXT,email TEXT,phone TEXT,notes TEXT,created_at TEXT)""")
        conn.execute("""CREATE TABLE secrets(id INTEGER PRIMARY KEY,customer_id INTEGER,label TEXT,username TEXT,encrypted_value BLOB,notes TEXT,updated_at TEXT,category TEXT,vault_path TEXT,host TEXT,url TEXT,linked_user_id INTEGER)""")
        conn.execute("INSERT INTO customers VALUES(2,'OUD-002','Oude Klant BV','','','oud@example.nl','0201234567','1000 AA','Dam 1','Amsterdam','','Importtest','','')")
        conn.execute("INSERT INTO contacts VALUES(1,2,'Oude Contact','Directeur','contact@oud.nl','0611111111','','')")
        conn.execute("INSERT INTO secrets VALUES(1,2,'Oude router','admin',?,'','','Netwerk','Netwerk','192.168.1.1','',NULL)",(Fernet(key).encrypt(b"oud-geheim"),))
    migration = LegacyImportService(db,customers,proposals,vault,operations,workspace)
    assert migration.preview(legacy)["warnings"]
    assert migration.preview(legacy,legacy_key)["counts"]["customers"] == 1
    imported = migration.import_database(legacy,legacy_key)
    assert imported["created"]["customers"] == imported["created"]["contacts"] == imported["created"]["secrets"] == 1
    old_customer = customers.search("OUD-002")[0]
    assert vault.reveal(vault.search(old_customer.id,"Oude router")[0]["id"],"Migratietest") == "oud-geheim"
    repeated = migration.import_database(legacy,legacy_key)
    assert repeated["created"]["customers"] == repeated["created"]["contacts"] == repeated["created"]["secrets"] == 0
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 5
    assert _version_tuple("v0.10.0") > _version_tuple("0.3.0")
    assert ReleaseInfo("v99.0.0", "Test", "", "https://github.com/test.zip", "").is_newer
