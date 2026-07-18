from __future__ import annotations

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService
from nowa_crm.modules.assets.service import CustomerAssetsService
from nowa_crm.modules.servicedesk.service import ServiceDeskService
from nowa_crm.modules.reporting.service import ReportingService


class Customer360Service:
    def __init__(self, customers: CustomerService, proposals: ProposalService, vault: VaultService,
                 operations: OperationsService, workspace: WorkspaceService, mail: MailService,
                 telephony: TelephonyService, assets: CustomerAssetsService | None = None,
                 servicedesk: ServiceDeskService | None = None, reporting: ReportingService | None = None):
        self.customers, self.proposals, self.vault = customers, proposals, vault
        self.operations, self.workspace, self.mail, self.telephony = operations, workspace, mail, telephony
        self.assets=assets
        self.servicedesk=servicedesk
        self.reporting=reporting

    def snapshot(self, customer_id: int) -> dict:
        customer=self.customers.get(customer_id)
        if not customer:raise ValueError("Klant niet gevonden")
        proposals=[x for x in self.proposals.list() if x.customer_id==customer_id]
        contacts=self.customers.contacts(customer_id); vault=self.vault.search(customer_id)
        users=self.operations.list_rows("users",customer_id); licenses=self.operations.list_rows("licenses",customer_id)
        hardware=self.operations.list_rows("hardware",customer_id); tasks=self.operations.list_rows("tasks",customer_id)
        notes=self.workspace.notes(customer_id); actions=self.workspace.actions(customer_id,True)
        mail=self.mail.list_messages(customer_id); calls=self.telephony.history(customer_id)
        locations=self.assets.list("locations",customer_id) if self.assets else []
        software=self.assets.list("software",customer_id) if self.assets else []
        documents=self.assets.list("documents",customer_id) if self.assets else []
        tickets=self.servicedesk.list(customer_id) if self.servicedesk else []
        reports=self.reporting.history(customer_id) if self.reporting else []
        return {"customer":customer,"contacts":contacts,"proposals":proposals,"vault":vault,"users":users,
                "licenses":licenses,"hardware":hardware,"tasks":tasks,"notes":notes,"actions":actions,
                "mail":mail,"calls":calls,"locations":locations,"software":software,"documents":documents,"tickets":tickets,"reports":reports,
                "warnings":self.operations.license_warnings(customer_id)}

    def timeline(self, customer_id: int) -> list[dict]:
        data=self.snapshot(customer_id); rows=[]
        for x in data["notes"]:rows.append({"date":x["created_at"],"kind":"Notitie","title":x["subject"],"detail":x["body"]})
        for x in data["calls"]:rows.append({"date":x["started_at"],"kind":"Gesprek","title":x["subject"] or x["phone_number"],"detail":x["outcome"]})
        for x in data["mail"]:rows.append({"date":x["occurred_at"],"kind":"E-mail","title":x["subject"],"detail":x["status"]})
        for x in data["actions"]:rows.append({"date":x["due_date"],"kind":"Actie","title":x["title"],"detail":x["status"]})
        for x in data["proposals"]:rows.append({"date":"","kind":"Offerte","title":f"{x.number} · {x.title}","detail":x.status})
        for x in data["documents"]:rows.append({"date":x["created_at"],"kind":"Document","title":x["title"],"detail":x["document_type"]})
        for x in data["tickets"]:rows.append({"date":x["updated_at"],"kind":"Ticket","title":f"{x['number']} · {x['subject']}","detail":x["status"]})
        for x in data["reports"]:rows.append({"date":x["created_at"],"kind":"Rapportage","title":x["subject"],"detail":f"{x['progress_percent']}% voortgang"})
        return sorted(rows,key=lambda x:(x["date"] or "",x["title"]),reverse=True)
