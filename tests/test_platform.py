from pathlib import Path

from nowa_crm.core.database import Database
from nowa_crm.core.auth import AuthService
from nowa_crm.core.events import EventBus
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.core.updater import ReleaseInfo, _version_tuple


def test_customer_and_vault_roundtrip(tmp_path: Path):
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
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 3
    assert _version_tuple("v0.10.0") > _version_tuple("0.3.0")
    assert ReleaseInfo("v99.0.0", "Test", "", "https://github.com/test.zip", "").is_newer
