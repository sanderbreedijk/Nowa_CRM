from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QFileDialog, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.customers.importer import CustomerImportService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.proposals.legacy_importer import LegacyProposalImportService
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
from nowa_crm.modules.integrations.service import IntegrationService
from nowa_crm.modules.daystart.service import DaystartService
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
from nowa_crm.ui.integrations_page import IntegrationsPage
from nowa_crm.core.updater import RELEASES_URL, UpdateService
from nowa_crm import __version__
from nowa_crm.ui.icons import app_icon, nav_icon


class MainWindow(QMainWindow):
    def __init__(self, customers: CustomerService, proposals: ProposalService, vault: VaultService, operations: OperationsService, workspace: WorkspaceService, mail: MailService, telephony: TelephonyService):
        super().__init__(); self.customers=customers; self.proposals=proposals; self.vault=vault; self.operations=operations; self.workspace=workspace; self.mail=mail; self.telephony=telephony
        self.customer_import=CustomerImportService(customers.db,telephony.actor)
        self.setWindowTitle("NOWA CRM"); self.setWindowIcon(app_icon()); self.resize(1440,900); self.setMinimumSize(1024,700)
        root=QWidget(); shell=QHBoxLayout(root); shell.setContentsMargins(0,0,0,0); shell.setSpacing(0)
        self.sidebar=QFrame(); self.sidebar.setObjectName("Sidebar"); self.sidebar.setFixedWidth(244); nav=QVBoxLayout(self.sidebar); nav.setContentsMargins(12,14,12,14); nav.setSpacing(4)
        brand_row=QHBoxLayout(); brand_icon=QLabel("N"); brand_icon.setObjectName("BrandIcon"); brand=QLabel("NOWA\nCRM"); brand.setObjectName("Brand"); brand_row.addWidget(brand_icon); brand_row.addWidget(brand); brand_row.addStretch(); nav.addLayout(brand_row)
        caption=QLabel("KLANTWERKPLEK"); caption.setObjectName("BrandCaption"); nav.addWidget(caption); self.stack=QStackedWidget(); self.stack.setObjectName("ContentStack")
        self.operations_page=OperationsPage(customers,operations,self)
        self.workspace_page=WorkspacePage(customers,workspace,self.open_proposal,self.open_global_result,self)
        self.mail_page=MailPage(customers,mail,workspace,self)
        self.telephony_page=TelephonyPage(customers,telephony,self.open_customer,self.open_vault,self)
        self.assets_service=CustomerAssetsService(customers.db)
        self.legacy_proposal_import=LegacyProposalImportService(customers.db,proposals,operations,self.assets_service)
        self.documents_service=DocumentCenterService(customers.db,self.assets_service,mail)
        self.documents_page=DocumentsPage(customers,self.documents_service,self.open_proposal,self)
        self.servicedesk_service=ServiceDeskService(customers.db,telephony.actor)
        self.integration_service=IntegrationService(customers.db,mail,telephony,telephony.actor)
        self.daystart_service=DaystartService(customers.db)
        self.integrations_page=IntegrationsPage(self.integration_service,self.open_call,self)
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
        pages=[("Overzicht",self._dashboard()),("Werkruimte",self.workspace_page),("Klanten",self._customer_page()),("360° Dossier",self.customer360),("Beheer & Project",self.operations_page),("Offertes",self._proposal_page()),("IT Kluis",self._vault_page()),("Mail",self.mail_page),("Telefonie",self.telephony_page),("Servicedesk",self.servicedesk_page),("Rapportages",self.reporting_page),("Projectplanning",self.planning_page),("Beveiliging",self.security_page),("Klantassets",self.assets_page),("Oude import",self.migration_page),("Updates",self._update_page()),("Communicatie",self.communications_page),("Documentcentrum",self.documents_page),("Integraties",self.integrations_page)]
        self.nav_group=QButtonGroup(self); self.nav_group.setExclusive(True)
        for _,page in pages:self.stack.addWidget(page)
        self._build_navigation(nav,pages)
        nav.addStretch(); version=QLabel(f"Versie {__version__}  •  lokaal"); version.setObjectName("SidebarFooter"); nav.addWidget(version); shell.addWidget(self.sidebar); shell.addWidget(self.stack,1); self.setCentralWidget(root);self._polish_ui()
        self.search_shortcut=QShortcut(QKeySequence("Ctrl+K"),self);self.search_shortcut.activated.connect(self.open_global_search)
        self.refresh_all()
        QTimer.singleShot(800,self.show_followup_reminder)

    def resizeEvent(self,event):
        """Keep navigation balanced on both laptop and full-HD displays."""
        self.sidebar.setFixedWidth(214 if event.size().width()<1250 else 244)
        super().resizeEvent(event)

    def show_followup_reminder(self):
        stats=self.workspace.action_summary()
        if not stats["overdue"] and not stats["today"]:return
        parts=[]
        if stats["overdue"]:parts.append(f"{stats['overdue']} te laat")
        if stats["today"]:parts.append(f"{stats['today']} voor vandaag")
        answer=QMessageBox.question(self,"Opvolging nodig",f"Er staan {' en '.join(parts)}.\n\nWerkvoorraad openen?")
        if answer==QMessageBox.Yes:self._show(1)

    def _build_navigation(self,nav,pages):
        groups=(("Start",(0,1)),("Relaties",(2,3,13)),("Verkoop",(5,17)),
                ("Service",(16,6,8,9,12)),("Projecten",(4,11,10)),("Systeem",(18,7,14,15)))
        symbols=("OV","WK","KL","360","BP","OF","KV","ML","TEL","SD","RP","PL","BV","AS","IM","UP","CM","DC","IN")
        self.nav_sections={};self.page_sections={};self.nav_buttons={}
        for section,indices in groups:
            header=QPushButton(section.upper());header.setObjectName("NavSection");nav.addWidget(header)
            content=QWidget();content.setObjectName("NavSectionContent");box=QVBoxLayout(content)
            box.setContentsMargins(0,0,0,4);box.setSpacing(0);nav.addWidget(content)
            self.nav_sections[section]=(header,content)
            header.clicked.connect(lambda _,name=section:self._open_nav_section(name))
            for index in indices:
                title=pages[index][0];button=QPushButton(title);button.setObjectName("Nav");button.setIcon(nav_icon(symbols[index]));button.setIconSize(QSize(28,28))
                button.setCheckable(True);button.setChecked(index==0);self.nav_group.addButton(button,index)
                button.clicked.connect(lambda _,x=index:self._show(x));box.addWidget(button)
                self.page_sections[index]=section;self.nav_buttons[index]=button
        self._open_nav_section("Start")

    def _open_nav_section(self,name):
        for section,(header,content) in self.nav_sections.items():
            active=section==name;content.setVisible(active);header.setText(f"{'—' if active else '+'}  {section.upper()}")

    def _show(self,index):
        self.stack.setCurrentIndex(index)
        section=self.page_sections.get(index)
        if section:self._open_nav_section(section)
        button=self.nav_buttons.get(index)
        if button:button.setChecked(True)
        self.refresh_all()
    def _page(self,title,subtitle=""):
        page=QWidget(); box=QVBoxLayout(page); box.setContentsMargins(30,24,30,26); box.setSpacing(12)
        head_row=QHBoxLayout(); head=QLabel(title); head.setObjectName("Title"); head_row.addWidget(head); head_row.addStretch(); hint=QLabel("Ctrl+K  Zoeken"); hint.setObjectName("SearchHint"); head_row.addWidget(hint); box.addLayout(head_row)
        if subtitle: sub=QLabel(subtitle); sub.setObjectName("Subtitle"); sub.setWordWrap(True); box.addWidget(sub)
        return page,box
    def _placeholder(self,title,text):
        page,box=self._page(title,text); box.addStretch(); return page
    def _update_page(self):
        page,box=self._page("Updates",f"Geïnstalleerde versie: {__version__}")
        card=QFrame(); card.setObjectName("Card"); content=QVBoxLayout(card)
        self.update_status=QLabel("Controleer GitHub Releases op een nieuwe, geteste Windows-versie."); self.update_status.setWordWrap(True); content.addWidget(self.update_status)
        row=QHBoxLayout(); check=QPushButton("Controleren op updates"); check.setObjectName("Primary"); check.clicked.connect(self.check_for_updates); releases=QPushButton("Releases openen"); releases.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(RELEASES_URL))); row.addWidget(check); row.addWidget(releases); row.addStretch(); content.addLayout(row); box.addWidget(card); box.addStretch(); return page
    def _dashboard(self):
        page,box=self._page("Dagstart","Alles wat vandaag aandacht nodig heeft, lokaal in één werkbak."); grid=QGridLayout(); self.kpis=[]
        for i,title in enumerate(("Klanten","Open offertes","Kluisitems","Actieve gebruikers","Licenties","Hardware","Open taken","Actiepunten")):
            card=QFrame(); card.setObjectName("Card"); c=QVBoxLayout(card); value=QLabel("0"); value.setObjectName("Kpi"); c.addWidget(value); c.addWidget(QLabel(title)); grid.addWidget(card,i//4,i%4); self.kpis.append(value)
        box.addLayout(grid)
        filters=QHBoxLayout();self.day_owner=QLineEdit();self.day_owner.setPlaceholderText("Filter op medewerker…");self.day_owner.textChanged.connect(self.refresh_daystart)
        self.day_priority=QComboBox();self.day_priority.addItems(["Alle","Kritiek","Hoog","Normaal","Laag"]);self.day_priority.currentIndexChanged.connect(self.refresh_daystart)
        self.day_period=QComboBox();self.day_period.addItems(["Actueel","Vandaag","Te laat"]);self.day_period.currentIndexChanged.connect(self.refresh_daystart);self.day_summary=QLabel()
        filters.addWidget(self.day_owner,1);filters.addWidget(self.day_priority);filters.addWidget(self.day_period);filters.addWidget(self.day_summary);box.addLayout(filters)
        self.day_table=QTableWidget(0,9);self.day_table.setHorizontalHeaderLabels(["Prioriteit","Soort","Deadline","Klant","Onderwerp","Toegewezen","Status / detail","Klant-ID","Item-ID"])
        self.day_table.setColumnHidden(7,True);self.day_table.setColumnHidden(8,True);self.day_table.horizontalHeader().setStretchLastSection(True);self.day_table.doubleClicked.connect(self.open_daystart_customer);box.addWidget(self.day_table,1)
        actions=QHBoxLayout()
        for text,handler in (("Open klantdossier",self.open_daystart_customer),("Toewijzen",self.assign_daystart),("Uitstellen",self.snooze_daystart),("Melding afronden",self.dismiss_daystart)):
            button=QPushButton(text);button.clicked.connect(handler);actions.addWidget(button)
        actions.addStretch();box.addLayout(actions);return page

    def selected_daystart(self):
        row=self.day_table.currentRow()
        if row<0:return None
        kind=self.day_table.item(row,1);entity=self.day_table.item(row,8);customer=self.day_table.item(row,7)
        return (kind.text(),int(entity.text()),int(customer.text())) if kind and entity and customer and customer.text() else (kind.text(),int(entity.text()),None) if kind and entity else None

    def refresh_daystart(self,*_):
        if not hasattr(self,"day_table"):return
        rows=self.daystart_service.items(self.day_owner.text(),self.day_priority.currentText(),self.day_period.currentText());self.day_table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            values=(item["priority"],item["kind"],item["due_at"],item["customer_name"],item["title"],item["assigned_to"],item["detail"],item["customer_id"] or "",item["entity_id"])
            for c,value in e