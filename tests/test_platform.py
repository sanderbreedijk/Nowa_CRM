from pathlib import Path

from nowa_crm.core.database import Database
from nowa_crm.core.auth import AuthService
from nowa_crm.core.events import EventBus
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService


def test_customer_and_vault_roundtrip(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite3"); db.migrate()
    assert (tmp_path / "backups").exists()
    auth = AuthService(db)
    auth.create_user("beheerder", "Beheerder", "veilig-wachtwoord", "administrator")
    session = auth.authenticate("beheerder", "veilig-wachtwoord")
    assert session and session.can("vault.read")
    assert auth.authenticate("beheerder", "verkeerd") is None
    customers = CustomerService(db, EventBus())
    customer_id = customers.create("K-001", "Voorbeeld BV", "info@example.nl", "0101234567", "Rotterdam")
    assert customers.search("010123")[0].id == customer_id
    proposals = ProposalService(db)
    proposal_id = proposals.create(customer_id, "Modernisering werkplekken")
    assert proposals.list("Modernisering")[0].id == proposal_id
    vault = VaultService(db, tmp_path / "vault.key", "beheerder", session)
    entry_id = vault.add(customer_id, "Microsoft 365 beheer", "admin@example.nl", "heel-geheim")
    assert vault.search(customer_id, "Microsoft")[0]["id"] == entry_id
    assert vault.reveal(entry_id, "Klant telefonisch geverifieerd") == "heel-geheim"
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 2
