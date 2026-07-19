from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QFileDialog, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService
from nowa_crm.modules.customer360.service import Customer360Service
from nowa_crm.modules.migration.service import LegacyImportService
from nowa_crm.modules.assets.service import CustomerAssetsService
from nowa_crm.modules.servicedesk.service import ServiceDeskService
from nowa_crm.modules.reporting.service import ReportingService
from nowa_crm.modules.planning.service import PlanningService
from nowa_crm.modules.security.service import SecurityService
from nowa_crm.modules.communications.service import CommunicationService
from nowa_crm.modules.documents.service import DocumentCenterService
from nowa_crm.ui.dialogs import ContactDialog, CustomerDialog, VaultDialog
from nowa_crm.ui.proposal_dialog import ProposalDialog
from nowa_crm.ui.operations_page import OperationsPage
from nowa_crm.ui.workspace_page import WorkspacePage
from nowa_crm.ui.mail_page import MailPage
from nowa_crm.ui.telephony_page import TelephonyPage
from nowa_crm.ui.customer360_page import Customer360Page
from nowa_crm.ui.migration_page import MigrationPage
from nowa_crm.ui.assets_page import CustomerAssetsPage
from nowa_crm.ui.servicedesk_page import ServiceDeskPage
from nowa_crm.ui.reporting_page import ReportingPage
from nowa_crm.ui.planning_page import PlanningPage
from nowa_crm.ui.security_page import SecurityPage
from nowa_crm.ui.communications_page import CommunicationsPage
from nowa_crm.ui.documents_page import DocumentsPage
from nowa_crm.core.updater import RELEASES_URL, UpdateService
from nowa_crm import __version__


class MainWindow(QMainWindow):
    def __init__(self, customers: CustomerService, proposals: ProposalService, vault: VaultService, operations: OperationsService, workspace: WorkspaceService, mail: MailService, telephony: TelephonyService):
        super().__init__(); self.customers=customers; self.proposals=proposals; self.vault=vault; self.operations=operations; self.workspace=workspace; self.mail=mail; self.telephony=telephony
        self.setWindowTitle("NOWA CRM"); self.resize(1380,860)
        root=QWidget(); shell=QHBoxLayout(root); shell.setContentsMargins(0,0,0,0); sidebar=QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(230); nav=QVBoxLayout(sidebar)
        brand=QLabel("NOWA CRM"); brand.setObjectName("Brand"); nav.addWidget(brand); self.stack=QStackedWidget()
        self.operations_page=OperationsPage(customers,operations,self)
        self.workspace_page=WorkspacePage(customers,workspace,self.open_proposal,self)
        self.mail_page=MailPage(customers,mail,workspace,self)
        self.telephony_page=TelephonyPage(customers,telephony,self.open_customer,self.open_vault,self)
        self.assets_service=CustomerAssetsService(customers.db)
        self.documents_service=DocumentCenterService(customers.db,self.assets_service,mail)
        self.documents_page=DocumentsPage(customers,self.documents_service,self.open_proposal,self)
        self.servicedesk_service=ServiceDeskService(customers.db,telephony.actor)
        self.communications_page=CommunicationsPage(customers,CommunicationService(mail,telephony),self.open_mail_message,self.open_call,self.create_ticket_from_communication,self)
        self.reporting_service=ReportingService(customers.db,telephony.actor,mail)
        self.customer360=Customer360Page(customers,Customer360Service(customers,proposals,vault,operations,workspace,mail,telephony,self.assets_service,self.servicedesk_service,self.reporting_service),self.open_vault,self.open_proposal,self)
        self.servicedesk_page=ServiceDeskPage(customers,self.servicedesk_service,self)
        self.assets_page=CustomerAssetsPage(customers,self.assets_service,self)
        self.reporting_page=ReportingPage(customers,self.reporting_service,self.open_mail_message,self)
        self.planning_service=PlanningService(customers.db)
        self.planning_page=PlanningPage(customers,self.planning_service,self)
        self.security_service=SecurityService(customers.db)
        self.security_page=SecurityPage(customers,self.security_service,self)
        self.migration_page=MigrationPage(LegacyImportService(customers.db,customers,proposals,vault,operations,workspace,self.assets_service),self.refresh_all,self)
        pages=[("Overzicht",self._dashboard()),("Werkruimte",self.workspace_page),("Klanten",self._customer_page()),("360° Dossier",self.customer360),("Beheer & Project",self.operations_page),("Offertes",self._proposal_page()),("IT Kluis",self._vault_page()),("Mail",self.mail_page),("Telefonie",self.telephony_page),("Servicedesk",self.servicedesk_page),("Rapportages",self.reporting_page),("Projectplanning",self.planning_page),("Beveiliging",self.security_page),("Klantassets",self.assets_page),("Oude import",self.migration_page),("Updates",self._update_page()),("Communicatie",self.communications_page),("Documentcentrum",self.documents_page)]
        self.nav_group=QButtonGroup(self); self.nav_group.setExclusive(True)
        for _,page in pages:self.stack.addWidget(page)
        self._build_navigation(nav,pages)
        nav.addStretch(); shell.addWidget(sidebar); shell.addWidget(self.stack,1); self.setCentralWidget(root); self.refresh_all()

    def _build_navigation(self,nav,pages):
        groups=(("Start",(0,1)),("Relaties",(2,3,13)),("Verkoop",(5,17)),
                ("Service",(16,6,8,9,12)),("Projecten",(4,11,10)),("Systeem",(7,14,15)))
        self.nav_sections={};self.page_sections={};self.nav_buttons={}
        for section,indices in groups:
            header=QPushButton(f"›  {section}");header.setObjectName("NavSection");nav.addWidget(header)
            content=QWidget();content.setObjectName("NavSectionContent");box=QVBoxLayout(content)
            box.setContentsMargins(0,0,0,4);box.setSpacing(0);nav.addWidget(content)
            self.nav_sections[section]=(header,content)
            header.clicked.connect(lambda _,name=section:self._open_nav_section(name))
            for index in indices:
                title=pages[index][0];button=QPushButton(title);button.setObjectName("Nav")
                button.setCheckable(True);button.setChecked(index==0);self.nav_group.addButton(button,index)
                button.clicked.connect(lambda _,x=index:self._show(x));box.addWidget(button)
                self.page_sections[index]=section;self.nav_buttons[index]=button
        self._open_nav_section("Start")

    def _open_nav_section(self,name):
        for section,(header,content) in self.nav_sections.items():
            active=section==name;content.setVisible(active);header.setText(f"{'⌄' if active else '›'}  {section}")

    def _show(self,index):
        self.stack.setCurrentIndex(index)
        section=self.page_sections.get(index)
        if section:self._open_nav_section(section)
        button=self.nav_buttons.get(index)
        if button:button.setChecked(True)
        self.refresh_all()
    def _page(self,title,subtitle=""):
        page=QWidget(); box=QVBoxLayout(page); head=QLabel(title); head.setObjectName("Title"); box.addWidget(head)
        if subtitle: sub=QLabel(subtitle); sub.setObjectName("Subtitle"); box.addWidget(sub)
        return page,box
    def _placeholder(self,title,text):
        page,box=self._page(title,text); box.addStretch(); return page
    def _update_page(self):
        page,box=self._page("Updates",f"Geïnstalleerde versie: {__version__}")
        card=QFrame(); card.setObjectName("Card"); content=QVBoxLayout(card)
        self.update_status=QLabel("Controleer GitHub Releases op een nieuwe, geteste Windows-versie."); self.update_status.setWordWrap(True); content.addWidget(self.update_status)
        row=QHBoxLayout(); check=QPushButton("Controleren op updates"); check.setObjectName("Primary"); check.clicked.connect(self.check_for_updates); releases=QPushButton("Releases openen"); releases.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(RELEASES_URL))); row.addWidget(check); row.addWidget(releases); row.addStretch(); content.addLayout(row); box.addWidget(card); box.addStretch(); return page
    def _dashboard(self):
        page,box=self._page("Goedemiddag","Uw centrale werkplek voor klanten, offertes en veilige service."); grid=QGridLayout(); self.kpis=[]
        for i,title in enumerate(("Klanten","Open offertes","Kluisitems","Actieve gebruikers","Licenties","Hardware","Open taken","Actiepunten")):
            card=QFrame(); card.setObjectName("Card"); c=QVBoxLayout(card); value=QLabel("0"); value.setObjectName("Kpi"); c.addWidget(value); c.addWidget(QLabel(title)); grid.addWidget(card,i//4,i%4); self.kpis.append(value)
        box.addLayout(grid); hint=QFrame(); hint.setObjectName("Card"); h=QVBoxLayout(hint); h.addWidget(QLabel("Slim voorbereid op groei")); h.addWidget(QLabel("Mail en Coligo-nummerherkenning worden via losse koppelingen toegevoegd zonder de CRM-kern te wijzigen.")); box.addWidget(hint); box.addStretch(); return page
    def _customer_page(self):
        page,box=self._page("Klanten","Eén betrouwbaar klantbeeld voor alle NOWA-modules."); row=QHBoxLayout(); self.customer_search=QLineEdit(); self.customer_search.setPlaceholderText("Zoek op naam, nummer, telefoon, e-mail of plaats…"); self.customer_search.textChanged.connect(self.refresh_customers)
        add=QPushButton("Nieuwe klant"); add.setObjectName("Primary"); add.clicked.connect(self.add_customer); edit=QPushButton("Bewerken"); edit.clicked.connect(self.edit_customer); contacts=QPushButton("Contactpersonen"); contacts.clicked.connect(self.manage_contacts); row.addWidget(self.customer_search,1); row.addWidget(contacts); row.addWidget(edit); row.addWidget(add); box.addLayout(row)
        self.customer_table=QTableWidget(0,6); self.customer_table.setHorizontalHeaderLabels(["Klantnummer","Naam","E-mail","Telefoon","Plaats","ID"]); self.customer_table.setColumnHidden(5,True); self.customer_table.horizontalHeader().setStretchLastSection(True); self.customer_table.doubleClicked.connect(self.edit_customer); box.addWidget(self.customer_table,1); return page
    def _proposal_page(self):
        page,box=self._page("Offertes","Versies en status overzichtelijk per klant beheren."); row=QHBoxLayout(); self.proposal_search=QLineEdit(); self.proposal_search.setPlaceholderText("Zoek offerte of klant…"); self.proposal_search.textChanged.connect(self.refresh_proposals); add=QPushButton("Nieuwe offerte"); add.setObjectName("Primary"); add.clicked.connect(self.add_proposal); row.addWidget(self.proposal_search,1); row.addWidget(add); box.addLayout(row)
        self.proposal_table=QTableWidget(0,7); self.proposal_table.setHorizontalHeaderLabels(["Nummer","Klant","Titel","Status","Revisie","Totaal excl. btw","ID"]); self.proposal_table.setColumnHidden(6,True); self.proposal_table.horizontalHeader().setStretchLastSection(True); self.proposal_table.doubleClicked.connect(self.edit_proposal); box.addWidget(self.proposal_table,1); return page
    def _vault_page(self):
        page,box=self._page("IT Kluis","Vind tijdens een klantgesprek snel het juiste gegeven; zoek ook rechtstreeks op telefoonnummer."); row=QHBoxLayout(); self.vault_search=QLineEdit(); self.vault_search.setPlaceholderText("Zoek klant, telefoon, account, host, gebruikersnaam of domein…"); self.vault_search.textChanged.connect(self.refresh_vault); reveal=QPushButton("Toon wachtwoord"); reveal.clicked.connect(self.reveal_secret); import_btn=QPushButton("KeePass CSV import"); import_btn.clicked.connect(self.import_keepass); add=QPushButton("Nieuw kluisitem"); add.setObjectName("Primary"); add.clicked.connect(self.add_vault); row.addWidget(self.vault_search,1); row.addWidget(import_btn); row.addWidget(reveal); row.addWidget(add); box.addLayout(row)
        self.vault_table=QTableWidget(0,9); self.vault_table.setHorizontalHeaderLabels(["Klant","Klantnr.","Categorie","Groep","Omschrijving","Gebruikersnaam","Host / IP","URL","ID"]); self.vault_table.setColumnHidden(8,True); self.vault_table.horizontalHeader().setStretchLastSection(True); self.vault_table.doubleClicked.connect(self.reveal_secret); box.addWidget(self.vault_table,1); return page
    def _selected_id(self,table,col):
        row=table.currentRow(); item=table.item(row,col) if row>=0 else None; return int(item.text()) if item else None
    def add_customer(self):
        dlg=CustomerDialog(self)
        if dlg.exec():
            try:self.customers.create(*dlg.values()); self.refresh_all(); self.mail_page.reload()
            except Exception as e: QMessageBox.critical(self,"Klant opslaan",str(e))
    def edit_customer(self,*_):
        cid=self._selected_id(self.customer_table,5)
        if not cid:return
        customer=self.customers.get(cid); dlg=CustomerDialog(self,customer)
        if dlg.exec():
            try:self.customers.update(cid,*dlg.values()); self.refresh_all(); self.mail_page.reload()
            except Exception as e: QMessageBox.critical(self,"Klant opslaan",str(e))
    def manage_contacts(self):
        cid=self._selected_id(self.customer_table,5)
        if not cid: QMessageBox.information(self,"Contactpersonen","Selecteer eerst een klant."); return
        existing=self.customers.contacts(cid); summary="\n".join(f"• {x.name} — {x.role or 'contact'} — {x.phone or x.email}" for x in existing) or "Nog geen contactpersonen."
        if QMessageBox.question(self,"Contactpersonen",summary+"\n\nNieuwe contactpersoon toevoegen?")!=QMessageBox.Yes:return
        dlg=ContactDialog(self)
        if dlg.exec():
            try:self.customers.save_contact(cid,*dlg.values()); self.refresh_customers()
            except Exception as e: QMessageBox.warning(self,"Contactpersoon",str(e))
    def add_proposal(self):
        customers=self.customers.search();
        if not customers: QMessageBox.information(self,"Offerte","Voeg eerst een klant toe."); return
        labels=[f"{c.customer_number} — {c.name}" for c in customers]; label,ok=QInputDialog.getItem(self,"Nieuwe offerte","Klant",labels,0,False)
        if not ok:return
        title,ok=QInputDialog.getText(self,"Nieuwe offerte","Titel")
        if ok:
            try:
                proposal_id=self.proposals.create(customers[labels.index(label)].id,title); self.refresh_all(); ProposalDialog(self.proposals,proposal_id,self).exec(); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Offerte",str(e))
    def edit_proposal(self,*_):
        proposal_id=self._selected_id(self.proposal_table,6)
        if proposal_id:ProposalDialog(self.proposals,proposal_id,self).exec(); self.refresh_all()
    def open_proposal(self,proposal_id):
        ProposalDialog(self.proposals,proposal_id,self).exec(); self.refresh_all()
    def open_customer(self,customer_id):
        if self.customers.get(customer_id):self.customer360.select_customer(customer_id); self._show(3)
    def open_vault(self,query):
        self.vault_search.setText(query); self._show(6)
    def open_mail_message(self,message_id):
        if message_id is not None:self.mail_page.open_message(message_id)
        self._show(7)
    def open_call(self,call_id):
        if call_id is not None:self.telephony_page.open_call(call_id)
        self._show(8)
    def create_ticket_from_communication(self,customer_id,subject,description,source_type,source_id):
        try:
            ticket_id=self.servicedesk_service.create_from_source(customer_id,subject or "Servicevraag",description,source_type,source_id)
            self.servicedesk_page.open_ticket(ticket_id);self._show(9)
        except Exception as exc:QMessageBox.warning(self,"Serviceticket",str(exc))
    def handle_incoming_phone(self,phone):
        self.telephony_page.phone.setText(phone); self.telephony_page.incoming_call(); self._show(8); self.raise_(); self.activateWindow()
    def add_vault(self):
        customers=self.customers.search()
        if not customers: QMessageBox.information(self,"IT Kluis","Voeg eerst een klant toe."); return
        dlg=VaultDialog(customers,self)
        if dlg.exec():
            try:self.vault.add(dlg.customer.currentData(),dlg.label.text(),dlg.username.text(),dlg.secret.text(),dlg.category.currentText(),dlg.url.text(),dlg.group_path.text(),dlg.host.text(),dlg.notes.toPlainText()); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"IT Kluis",str(e))
    def import_keepass(self):
        customers=self.customers.search()
        if not customers: QMessageBox.information(self,"KeePass import","Voeg eerst een klant toe."); return
        labels=[f"{c.customer_number} — {c.name}" for c in customers]; label,ok=QInputDialog.getItem(self,"KeePass import","Importeer gegevens voor klant",labels,0,False)
        if not ok:return
        filename,_=QFileDialog.getOpenFileName(self,"KeePass CSV selecteren","","CSV-bestanden (*.csv)")
        if not filename:return
        try:
            count=self.vault.import_keepass_csv(customers[labels.index(label)].id,Path(filename)); self.refresh_all(); QMessageBox.information(self,"KeePass import",f"{count} kluisitems veilig geïmporteerd.")
        except Exception as e: QMessageBox.warning(self,"KeePass import",str(e))
    def reveal_secret(self,*_):
        entry_id=self._selected_id(self.vault_table,8)
        if not entry_id: QMessageBox.information(self,"IT Kluis","Selecteer eerst een kluisitem."); return
        reason,ok=QInputDialog.getText(self,"Verificatie","Reden / wijze van klantverificatie")
        if not ok:return
        try:
            secret=self.vault.reveal(entry_id,reason); QApplication.clipboard().setText(secret); alphabet="  ".join(f"{ch} — {self._spell(ch)}" for ch in secret); QMessageBox.information(self,"Wachtwoord",f"{secret}\n\nSpelalfabet:\n{alphabet}\n\nHet wachtwoord staat 30 seconden op het klembord.")
            QTimer.singleShot(30000,lambda:self._clear_clipboard(secret))
        except Exception as e: QMessageBox.warning(self,"IT Kluis",str(e))
    def _clear_clipboard(self,secret):
        if QApplication.clipboard().text()==secret: QApplication.clipboard().clear()
    @staticmethod
    def _spell(char):
        words=dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",("Anton Bernard Cornelis Dirk Eduard Ferdinand Gerard Hendrik Izaak Johan Karel Lodewijk Maria Nico Otto Pieter Quotiënt Rudolf Simon Theodoor Utrecht Victor Willem Xantippe Ypsilon Zacharias").split()))
        if char.upper() in words:return words[char.upper()]
        if char.isdigit():return ("nul","één","twee","drie","vier","vijf","zes","zeven","acht","negen")[int(char)]
        return {"@":"apenstaartje",".":"punt","-":"streepje","_":"laag streepje"}.get(char,"teken")
    def check_for_updates(self):
        self.update_status.setText("GitHub wordt gecontroleerd…"); QApplication.processEvents()
        try:
            release=UpdateService().latest()
            if not release:
                self.update_status.setText("Er is nog geen GitHub Release gepubliceerd."); return
            if not release.is_newer:
                self.update_status.setText(f"Versie {__version__} is actueel. Nieuwste release: {release.version}."); return
            if not release.asset_url:
                self.update_status.setText(f"Release {release.version} heeft nog geen Windows-pakket."); return
            answer=QMessageBox.question(self,"NOWA CRM bijwerken",f"Versie {release.version} is beschikbaar. Nu downloaden en installeren?\n\nKlantgegevens blijven lokaal behouden.")
            if answer!=QMessageBox.Yes:return
            self.update_status.setText(f"Versie {release.version} wordt gedownload…"); QApplication.processEvents()
            package=UpdateService().download(release); UpdateService().install_after_exit(package)
            QMessageBox.information(self,"Update gereed","NOWA CRM sluit nu af en start automatisch opnieuw met de nieuwe versie."); QApplication.quit()
        except Exception as exc:
            self.update_status.setText(f"Updatecontrole mislukt: {exc}")
    def refresh_all(self):
        self.refresh_customers(); self.refresh_proposals(); self.refresh_vault()
        if hasattr(self,"operations_page"):self.operations_page.reload_customers()
        if hasattr(self,"workspace_page"):self.workspace_page.reload_customers()
        if hasattr(self,"telephony_page"):self.telephony_page.reload_customers()
        if hasattr(self,"customer360"):self.customer360.reload_customers()
        if hasattr(self,"assets_page"):self.assets_page.reload_customers()
        if hasattr(self,"servicedesk_page"):self.servicedesk_page.reload_customers()
        if hasattr(self,"reporting_page"):self.reporting_page.reload_customers()
        if hasattr(self,"planning_page"):self.planning_page.reload_customers()
        if hasattr(self,"security_page"):self.security_page.reload_customers()
        if hasattr(self,"communications_page"):self.communications_page.reload_customers()
        if hasattr(self,"documents_page"):self.documents_page.reload_customers()
        stats=self.operations.dashboard(); values=(self.customers.count(),self.proposals.count_open(),self.vault.count(),stats["users"],stats["licenses"],stats["hardware"],stats["open_tasks"],len(self.workspace.actions()))
        for label,value in zip(self.kpis,values):label.setText(str(value))
    def refresh_customers(self,*_):
        if not hasattr(self,"customer_table"):return
        rows=self.customers.search(self.customer_search.text()); self.customer_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            for c,v in enumerate((x.customer_number,x.name,x.email,x.phone,x.city,str(x.id))):self.customer_table.setItem(r,c,QTableWidgetItem(v))
    def refresh_proposals(self,*_):
        if not hasattr(self,"proposal_table"):return
        rows=self.proposals.list(self.proposal_search.text()); self.proposal_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=(x.number,x.customer_name,x.title,x.status,str(x.revision),f"€ {x.total_cents/100:,.2f}",str(x.id))
            for c,v in enumerate(vals):self.proposal_table.setItem(r,c,QTableWidgetItem(v))
    def refresh_vault(self,*_):
        if not hasattr(self,"vault_table"):return
        rows=self.vault.search_all(self.vault_search.text()); self.vault_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=(x["customer_name"],x["customer_number"],x["category"],x["group_path"],x["label"],x["username"],x["host"],x["url"],str(x["id"]))
            for c,v in enumerate(vals):self.vault_table.setItem(r,c,QTableWidgetItem(v or ""))
