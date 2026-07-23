from __future__ import annotations

import json
from pathlib import Path

from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.proposals.approval import ProposalApprovalService
from nowa_crm.modules.proposals.pdf import export_proposal_pdf
from nowa_crm.modules.proposals.service import ProposalService


class ProposalDeliveryService:
    """Creates one complete Outlook-ready proposal message, entirely locally."""

    def __init__(self, proposals: ProposalService, mail: MailService):
        self.proposals = proposals
        self.mail = mail
        self.approvals = ProposalApprovalService(proposals)

    def defaults(self, proposal_id: int) -> dict:
        proposal = self.proposals.get(proposal_id)
        if not proposal:
            raise ValueError("Offerte niet gevonden.")
        with self.proposals.db.transaction() as conn:
            customer = conn.execute(
                "SELECT name,email FROM customers WHERE id=?", (proposal.customer_id,)).fetchone()
            contact = conn.execute(
                """SELECT id,name,email FROM contacts WHERE customer_id=? AND email<>''
                   ORDER BY id LIMIT 1""", (proposal.customer_id,)).fetchone()
            integration = conn.execute(
                "SELECT enabled,settings_json FROM integration_settings WHERE provider='outlook'"
            ).fetchone()
        settings = {}
        if integration:
            try:
                settings = json.loads(integration["settings_json"])
            except (TypeError, json.JSONDecodeError):
                settings = {}
        recipient = contact["email"] if contact else customer["email"]
        return {
            "recipient": recipient or "",
            "contact_id": int(contact["id"]) if contact else None,
            "contact_name": contact["name"] if contact else "",
            "sender": settings.get("mailbox_address", settings.get("sender_address", "")),
            "outlook_enabled": bool(integration and integration["enabled"]),
        }

    def prepare(self, proposal_id: int, recipient: str, expires_at: str) -> dict:
        proposal = self.proposals.get(proposal_id)
        defaults = self.defaults(proposal_id)
        address = recipient.strip()
        if "@" not in address or "." not in address.rsplit("@", 1)[-1]:
            raise ValueError("Vul een geldig e-mailadres van de ontvanger in.")
        if not defaults["outlook_enabled"]:
            raise ValueError("Schakel eerst de lokale Outlook-overdracht in bij Integraties.")
        if not defaults["sender"]:
            raise ValueError("Vul bij Integraties eerst het aparte NOWA-mailboxadres in.")

        export_root = self.mail.root / "exports" / "offertes"
        portal = self.approvals.prepare(
            proposal_id, address, expires_at, export_root / "akkoord")
        pdf = export_proposal_pdf(self.proposals, proposal_id, export_root / "pdf")
        with self.proposals.db.transaction() as conn:
            template = conn.execute(
                """SELECT id FROM mail_templates
                   WHERE name='Offerte verzenden' AND active=1 LIMIT 1""").fetchone()
        rendered = self.mail.render_template(
            int(template["id"]), proposal.customer_id, defaults["contact_id"], proposal_id
        ) if template else {
            "subject": f"Offerte {proposal.number} – {proposal.title}",
            "body": f"Beste relatie,\n\nIn de bijlage ontvangt u onze offerte {proposal.number}.\n\n"
                    "Met vriendelijke groet,\nNOWA Solutions",
        }
        body = rendered["body"] + (
            "\n\nDigitaal akkoord\n"
            "Open de bijlage met ‘Digitaal-akkoord’ in uw browser. Na akkoord downloadt "
            "u een klein akkoordbestand; stuur dat bestand als antwoord op deze e-mail terug."
        )
        message_id = self.mail.create_draft(
            proposal.customer_id, address, rendered["subject"], body,
            defaults["contact_id"], sender=defaults["sender"])
        self.mail.add_attachment(message_id, pdf, f"{proposal.number}-offerte.pdf")
        self.mail.add_attachment(
            message_id, portal["path"], f"{proposal.number}-digitaal-akkoord.html")
        eml = self.mail.export_eml(message_id)
        return {"message_id": message_id, "eml_path": eml, "pdf_path": pdf,
                "portal_path": portal["path"], "recipient": address,
                "sender": defaults["sender"]}
