from datetime import date, timedelta
import json

import pytest

from nowa_crm.core.database import Database
from nowa_crm.core.events import EventBus
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.proposals.approval import ProposalApprovalService
from nowa_crm.modules.proposals.service import ProposalService


def test_portal_decision_and_controlled_license_update(tmp_path):
    db = Database(tmp_path / "crm.sqlite3")
    db.migrate()
    customer_id = CustomerService(db, EventBus()).create(
        "K-100", "Klant BV", "info@klant.nl")
    proposals = ProposalService(db)
    proposal_id = proposals.create(customer_id, "Microsoft 365 uitbreiding")
    proposals.add_line(proposal_id, "uren", "Inrichting", 2, 9400)
    proposals.save_sections(proposal_id, {"management_summary": "Uitbreiding van de omgeving."})
    license_id = OperationsService(db).save_license(
        customer_id, "Microsoft 365 Business Premium",
        quantity=12, unit_price_cents=2250)
    future_license_id = OperationsService(db).save_license(
        customer_id, "Exchange Online Archiving", quantity=2, unit_price_cents=350)
    service = ProposalApprovalService(proposals)
    result = service.prepare(
        proposal_id, "directie@klant.nl",
        (date.today() + timedelta(days=14)).isoformat(), tmp_path / "portal")

    portal = result["path"].read_text(encoding="utf-8")
    assert "Bestaande licenties aanpassen" in portal
    assert "Microsoft 365 Business Premium" in portal
    assert "vault" not in portal.casefold()
    package = json.loads((result["folder"] / "akkoordpakket.json").read_text(encoding="utf-8"))
    premium = next(item for item in package["license_changes"]
                   if item["license_id"] == license_id)
    assert premium["current_quantity"] == 12

    decision = {
        "format": "nowa-proposal-decision-v1",
        "access_token": result["token"],
        "accepted": True,
        "accepted_by": "S. Beslisser",
        "accepted_function": "Directeur",
        "comment": "Graag per volgende maand.",
        "license_changes": [{
            "license_id": license_id,
            "requested_quantity": 8,
            "effective_date": "",
        }, {
            "license_id": future_license_id,
            "requested_quantity": 3,
            "effective_date": (date.today() + timedelta(days=7)).isoformat(),
        }],
    }
    decision_path = tmp_path / "akkoord.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    imported = service.import_decision(decision_path)
    assert imported["license_changes"][0]["difference"] == -4

    applied = service.apply_license_changes(imported["publication_id"])
    assert applied["changed"] == 1
    assert applied["pending"] == 1 and not applied["complete"]
    licenses = {row["product"]: row["quantity"]
                for row in OperationsService(db).list_rows("licenses", customer_id)}
    assert licenses["Microsoft 365 Business Premium"] == 8
    assert licenses["Exchange Online Archiving"] == 2
    overview = service.overview()[0]
    assert overview["display_status"] == "ingepland"
    assert overview["future_count"] == 1 and overview["due_count"] == 0


def test_decision_rejects_unknown_token_and_license_tampering(tmp_path):
    db = Database(tmp_path / "crm.sqlite3")
    db.migrate()
    customer_id = CustomerService(db, EventBus()).create("K-101", "Veilig BV")
    proposals = ProposalService(db)
    proposal_id = proposals.create(customer_id, "Veilige offerte")
    proposals.add_line(proposal_id, "dienst", "Werkzaamheden", 1, 10000)
    proposals.save_sections(proposal_id, {"management_summary": "Veilige uitvoering."})
    license_id = OperationsService(db).save_license(customer_id, "Business Basic", quantity=5)
    service = ProposalApprovalService(proposals)
    result = service.prepare(
        proposal_id, "", (date.today() + timedelta(days=7)).isoformat(), tmp_path)
    base = {"format": "nowa-proposal-decision-v1", "accepted": True,
            "accepted_by": "Klant", "access_token": "verkeerd",
            "license_changes": [{"license_id": license_id,
                                 "requested_quantity": 6, "effective_date": ""}]}
    path = tmp_path / "besluit.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="onbekend"):
        service.import_decision(path)
    base["access_token"] = result["token"]
    base["license_changes"][0]["license_id"] = license_id + 999
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="onbekende"):
        service.import_decision(path)
