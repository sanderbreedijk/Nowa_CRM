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
from datetime import date


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
        snapshot={"customer":customer,"contacts":contacts,"proposals":proposals,"vault":vault,"users":users,
                "licenses":licenses,"hardware":hardware,"tasks":tasks,"notes":notes,"actions":actions,
                "mail":mail,"calls":calls,"locations":locations,"software":software,"documents":documents,"tickets":tickets,"reports":reports,
                "warnings":self.operations.license_warnings(customer_id)}
        snapshot["pulse"]=self._pulse(snapshot)
        return snapshot

    @staticmethod
    def _pulse(data: dict) -> dict:
        today=date.today().isoformat()
        open_tickets=[x for x in data["tickets"] if x["status"] not in ("Opgelost","Gesloten")]
        overdue_tickets=[x for x in open_tickets if x.get("sla_state")=="Overschreden"]
        critical_tickets=[x for x in open_tickets if x["priority"]=="Kritiek"]
        open_actions=[x for x in data["actions"] if x["status"] not in ("Gereed","Geannuleerd")]
        overdue_actions=[x for x in open_actions if x.get("due_date") and x["due_date"]<today]
        unsafe_users=[x for x in data["users"] if x.get("active") and not x.get("mfa_enabled")]
        warnings=data["warnings"]
        score=max(0,100-len(overdue_tickets)*18-len(critical_tickets)*15-len(overdue_actions)*8-len(unsafe_users)*4-len(warnings)*5)
        if score>=85:label,color="Sterk","#158467"
        elif score>=65:label,color="Aandacht","#C27018"
        else:label,color="Kritiek","#C33D4B"
        signals=[]
        if overdue_tickets:signals.append(f"{len(overdue_tickets)} ticket(s) buiten SLA")
        if critical_tickets:signals.append(f"{len(critical_tickets)} kritisch(e) ticket(s)")
        if overdue_actions:signals.append(f"{len(overdue_actions)} actie(s) te laat")
        if unsafe_users:signals.append(f"{len(unsafe_users)} actieve gebruiker(s) zonder MFA")
        signals.extend(warnings[:2])
        if not signals:signals.append("Geen urgente service- of beveiligingssignalen")
        contacts=[x.get("occurred_at") for x in data["mail"]]+[x.get("started_at") for x in data["calls"]]
        last_contact=max((x for x in contacts if x),default="")
        briefing=[
            f"{len(open_tickets)} open ticket(s), waarvan {len(overdue_tickets)} buiten SLA.",
            f"{len(open_actions)} open actie(s) en {len(data['proposals'])} offerte(s) in het dossier.",
            f"{sum(int(x['quantity']) for x in data['licenses'])} licentie(s), {sum(int(x['quantity']) for x in data['hardware'])} hardware-item(s).",
            f"Laatste geregistreerde contact: {last_contact or 'nog niet vastgelegd'}.",
        ]
        return {"score":score,"label":label,"color":color,"signals":signals,"briefing":briefing}

    def timeline(self, customer_id: int) -> list[dict]:
        data=self.snapshot(customer_id); rows=[]
        for x in data["notes"]:rows.append({"date":x["created_at"],"kind":"Notitie","title":x["subject"],"detail":x["body"],"group":"Werk"})
        for x in data["calls"]:rows.append({"date":x["started_at"],"kind":"Gesprek","title":x["subject"] or x["phone_number"],"detail":x["outcome"],"group":"Communicatie"})
        for x in data["mail"]:rows.append({"date":x["occurred_at"],"kind":"E-mail","title":x["subject"],"detail":x["status"],"group":"Communicatie"})
        for x in data["actions"]:rows.append({"date":x["due_date"],"kind":"Actie","title":x["title"],"detail":x["status"],"group":"Werk"})
        for x in data["proposals"]:rows.append({"date":"","kind":"Offerte","title":f"{x.number} · {x.title}","detail":x.status,"group":"Commercieel"})
        for x in data["documents"]:rows.append({"date":x["created_at"],"kind":"Document","title":x["title"],"detail":x["document_type"],"group":"Dossier"})
        for x in data["tickets"]:rows.append({"date":x["updated_at"],"kind":"Ticket","title":f"{x['number']} · {x['subject']}","detail":x["status"],"group":"Service"})
        for x in data["reports"]:rows.append({"date":x["created_at"],"kind":"Rapportage","title":x["subject"],"detail":f"{x['progress_percent']}% voortgang","group":"Werk"})
        for x in self.customers.history(customer_id):rows.append({"date":x["created_at"],"kind":"Klantwijziging","title":x["action"],"detail":x["changed_fields"],"group":"Dossier"})
        return sorted(rows,key=lambda x:(x["date"] or "",x["title"]),reverse=True)
