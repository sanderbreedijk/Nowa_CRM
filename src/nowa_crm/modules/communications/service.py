from __future__ import annotations

from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService


class CommunicationService:
    """Voegt lokale mail- en gesprekshistorie samen zonder gegevens te kopiëren."""

    def __init__(self, mail: MailService, telephony: TelephonyService):
        self.mail = mail
        self.telephony = telephony

    def timeline(self, customer_id: int | None = None, query: str = "", channel: str = "Alles") -> list[dict]:
        rows: list[dict] = []
        if channel in ("Alles", "E-mail"):
            for item in self.mail.list_messages(customer_id, query):
                address = item["sender"] if item["direction"] == "inkomend" else item["recipients"]
                rows.append({"date": item["occurred_at"], "channel": "E-mail", "customer": item["customer_name"],
                             "direction": item["direction"], "subject": item["subject"], "contact": address,
                             "status": item["status"], "id": item["id"]})
        if channel in ("Alles", "Telefoon"):
            for item in self.telephony.history(customer_id, query):
                rows.append({"date": item["started_at"], "channel": "Telefoon", "customer": item["customer_name"],
                             "direction": item["direction"], "subject": item["subject"] or "Telefoongesprek",
                             "contact": item["contact_name"] or item["phone_number"],
                             "status": item["outcome"] or item["status"], "id": item["id"]})
        return sorted(rows, key=lambda row: (row["date"] or "", row["id"]), reverse=True)

    def stats(self, customer_id: int | None = None) -> dict[str, int]:
        mail = self.mail.list_messages(customer_id)
        calls = self.telephony.history(customer_id)
        return {
            "total": len(mail) + len(calls),
            "incoming": sum(x["direction"] == "inkomend" for x in mail + calls),
            "outgoing": sum(x["direction"] == "uitgaand" for x in mail + calls),
            "open": sum(x["status"] in ("concept", "klaar") for x in mail)
                    + sum(x["status"] != "afgerond" for x in calls),
        }
