from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QHeaderView, QHBoxLayout,
                               QFileDialog, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.customers.importer import CustomerImportService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.proposals.legacy_importer import LegacyProposalImportService
from nowa_crm.modules.proposals.pdf import export_proposal_pdf
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
from nowa_crm.ui.approval_manager_dialog import ApprovalManagerDialog
from nowa_crm.ui.vault_verification_dialog import VaultVerificationDialog
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
from nowa_crm.ui.incoming_call_popup import IncomingCallPopup
from nowa_crm.ui.missed_calls_page import MissedCallsPage
from nowa_crm.ui.shomi_workbench_page import ShomiWorkbenchPage
from nowa_crm.core.updater import RELEASES_URL, UpdateService
from nowa_crm.core.backup import BackupService
from nowa_crm.core.paths import data_dir
from nowa_crm import __version__
from nowa_crm.ui.icons import app_icon, nav_icon


class ClickableCard(QFrame):
    clicked = Signal()

    def __init__(self, page_index: int, parent=None):
        super().__init__(parent);self.page_index=page_index
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.clicked.emit()
        super().mouseReleaseEvent(event)


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
        self.servicedesk_service=ServiceDeskService(customers.db,telephony.actor)
        self.telephony_page=TelephonyPage(customers,telephony,self.open_customer,self.open_vault,self.create_ticket_from_communication,self)
        self.assets_service=CustomerAssetsService(customers.db)
        self.legacy_proposal_import=LegacyProposalImportService(customers.db,proposals,operations,self.assets_service)
        self.documents_service=DocumentCenterService(customers.db,self.assets_service,mail)
        self.documents_page=DocumentsPage(customers,self.documents_service,self.open_proposal,self)
        self.integration_service=IntegrationService(customers.db,mail,telephony,telephony.actor)
        self.daystart_service=DaystartService(customers.db)
        self.incoming_call_popup=None
        self.integrations_page=IntegrationsPage(self.integration_service,self.show_incoming_call,self)
        self.communications_page=CommunicationsPage(customers,CommunicationService(mail,telephony,self.servicedesk_service),self.open_mail_message,self.open_call,self.open_service_ticket,self.create_ticket_from_communication,self)
        self.reporting_service=ReportingService(customers.db,telephony.actor,mail)
        self.customer360=Customer360Page(customers,Customer360Service(customers,proposals,vault,operations,workspace,mail,telephony,self.assets_service,self.servicedesk_service,self.reporting_service),self.open_vault,self.open_proposal,self.start_customer_mail,self.start_customer_followup,self.add_proposal_for_customer,self.start_customer_call,self.start_customer_ticket,self)
        self.servicedesk_page=ServiceDeskPage(customers,self.servicedesk_service,self.start_customer_mail,self.open_call,self.open_vault,self)
        self.assets_page=CustomerAssetsPage(customers,self.assets_service,self)
        self.reporting_page=ReportingPage(customers,self.reporting_service,self.open_mail_message,self)
        self.planning_service=PlanningService(customers.db)
        self.planning_page=PlanningPage(customers,self.planning_service,self)
        self.security_service=SecurityService(customers.db)
        self.security_page=SecurityPage(customers,self.security_service,self)
        self.migration_page=MigrationPage(LegacyImportService(customers.db,customers,proposals,vault,operations,workspace,self.assets_service),self.refresh_all,self)
        self.missed_calls_page=MissedCallsPage(telephony,self.open_call,self.open_customer,self)
        self.shomi_page=ShomiWorkbenchPage(self.integration_service,customers,self.open_call,self)
        pages=[("Dagstart",self._dashboard()),("Werkruimte",self.workspace_page),("Klanten",self._customer_page()),("360° klantbeeld",self.customer360),("Beheer & projecten",self.operations_page),("Offertes",self._proposal_page()),("IT-kluis",self._vault_page()),("E-mail",self.mail_page),("Telefonie",self.telephony_page),("Servicedesk",self.servicedesk_page),("Rapportages",self.reporting_page),("Projectplanning",self.planning_page),("Beveiliging",self.security_page),("Klantassets",self.assets_page),("Import & migratie",self.migration_page),("Updates & herstel",self._update_page()),("Communicatie",self.communications_page),("Documenten",self.documents_page),("Koppelingen",self.integrations_page),("Gemiste oproepen",self.missed_calls_page),("Shomi-werkbak",self.shomi_page)]
        self.nav_group=QButtonGroup(self); self.nav_group.setExclusive(True)
        for _,page in pages:self.stack.addWidget(page)
        self._build_navigation(nav,pages)
        self.telephony_page.call_started.connect(self.start_call_tracking);self.telephony_page.call_finished.connect(self.handle_call_finished)
        nav.addStretch();self.active_call_id=None;self.call_timer=QTimer(self);self.call_timer.timeout.connect(self.update_call_tracking);self.call_timer.setInterval(1000)
        self.call_panel=QFrame();self.call_panel.setObjectName("ActiveCallPanel");call_box=QVBoxLayout(self.call_panel);call_box.setContentsMargins(11,10,11,10);call_box.setSpacing(5)
        self.call_caption=QLabel("ACTIEF GESPREK");self.call_caption.setObjectName("ActiveCallCaption");self.call_name=QLabel();self.call_name.setObjectName("ActiveCallName");self.call_name.setWordWrap(True)
        call_row=QHBoxLayout();self.call_duration=QLabel("00:00:00");self.call_duration.setObjectName("ActiveCallDuration");open_workspace=QPushButton("Open");open_workspace.setObjectName("OpenCallWorkspace");open_workspace.clicked.connect(self.open_active_call_workspace);end_call=QPushButton("Einde");end_call.setObjectName("EndCall");end_call.clicked.connect(self.end_active_call)
        call_row.addWidget(self.call_duration);call_row.addStretch();call_row.addWidget(open_workspace);call_row.addWidget(end_call);call_box.addWidget(self.call_caption);call_box.addWidget(self.call_name);call_box.addLayout(call_row);self.call_panel.hide();nav.addWidget(self.call_panel)
        self.sip_nav_status=QLabel("SIP  •  niet actief");self.sip_nav_status.setObjectName("SipSidebarStatus");self.sip_nav_status.setProperty("sipState","idle");nav.addWidget(self.sip_nav_status)
        self.integrations_page.sip_status_changed.connect(self.update_sip_sidebar_status)
        self.integrations_page.open_shomi_workbench.connect(lambda:self._show(20))
        version=QLabel(f"Versie {__version__}  •  lokaal"); version.setObjectName("SidebarFooter"); nav.addWidget(version); shell.addWidget(self.sidebar); shell.addWidget(self.stack,1); self.setCentralWidget(root);self._polish_ui()
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
        groups=(("Start",(0,1)),("Klanten",(2,3,16,7)),("Verkoop",(5,10)),
                ("Service",(20,9,8,19,6)),("Projecten",(4,11,13,17,12)),("Systeem",(18,14,15)))
        symbols=("OV","WK","KL","360","BP","OF","KV","ML","TEL","SD","RP","PL","BV","AS","IM","UP","CM","DC","IN","GO","SH")
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

    def update_sip_sidebar_status(self,state,detail=""):
        labels={"luistert":"luistert","verbinden":"verbinden…","verbonden":"verbonden","fout":"fout"}
        self.sip_nav_status.setText(f"SIP  •  {labels.get(state,state)}")
        self.sip_nav_status.setToolTip(detail);self.sip_nav_status.setProperty("sipState",state)
        self.sip_nav_status.style().unpolish(self.sip_nav_status);self.sip_nav_status.style().polish(self.sip_nav_status)

    def _show(self,index):
        self.stack.setCurrentIndex(index)
        section=self.page_sections.get(index)
        if section:self._open_nav_section(section)
        button=self.nav_buttons.get(index)
        if button:button.setChecked(True)
        self.refresh_all()
    def _page(self,title,subtitle=""):
        page=QWidget(); box=QVBoxLayout(page); box.setContentsMargins(34,28,34,28); box.setSpacing(16)
        head_row=QHBoxLayout(); head=QLabel(title); head.setObjectName("Title"); head_row.addWidget(head); head_row.addStretch(); hint=QLabel("Ctrl+K  Zoeken"); hint.setObjectName("SearchHint"); head_row.addWidget(hint); box.addLayout(head_row)
        if subtitle: sub=QLabel(subtitle); sub.setObjectName("Subtitle"); sub.setWordWrap(True); box.addWidget(sub)
        return page,box
    def _placeholder(self,title,text):
        page,box=self._page(title,text); box.addStretch(); return page
    def _update_page(self):
        page,box=self._page("Updates",f"Geïnstalleerde versie: {__version__}")
        card=QFrame(); card.setObjectName("Card"); content=QVBoxLayout(card)
        self.update_status=QLabel("De broncode en releases staan privé op GitHub. Meld je daar aan om een Windows-updatepakket te downloaden."); self.update_status.setWordWrap(True); content.addWidget(self.update_status)
        row=QHBoxLayout(); check=QPushButton("Controleren op updates"); check.clicked.connect(self.check_for_updates)
        releases=QPushButton("GitHub-releases openen"); releases.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        local=QPushButton("Updatepakket kiezen"); local.setObjectName("Primary"); local.clicked.connect(self.install_local_update)
        row.addWidget(local); row.addWidget(releases); row.addWidget(check); row.addStretch(); content.addLayout(row); box.addWidget(card)
        backup_card=QFrame();backup_card.setObjectName("Card");backup_box=QVBoxLayout(backup_card)
        backup_title=QLabel("Lokale gegevensbescherming");backup_title.setObjectName("SectionTitle");backup_box.addWidget(backup_title)
        self.backup_status=QLabel();self.backup_status.setWordWrap(True);backup_box.addWidget(self.backup_status)
        backup_row=QHBoxLayout();make_backup=QPushButton("Complete herstelset maken");make_backup.setObjectName("Primary");make_backup.clicked.connect(self.create_recovery_backup)
        restore_backup=QPushButton("Herstelset terugzetten");restore_backup.clicked.connect(self.restore_recovery_backup)
        open_backups=QPushButton("Back-upmap openen");open_backups.clicked.connect(self.open_backup_folder)
        backup_row.addWidget(make_backup);backup_row.addWidget(restore_backup);backup_row.addWidget(open_backups);backup_row.addStretch();backup_box.addLayout(backup_row)
        box.addWidget(backup_card);self.refresh_backup_status();box.addStretch();return page
    def _dashboard(self):
        page,box=self._page("Dagstart","Alles wat vandaag aandacht nodig heeft, lokaal in één werkbak."); grid=QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(14); self.kpis=[]
        card_data=(("KL","Klanten","blue",2),("OF","Open offertes","purple",5),("KV","Kluisitems","teal",6),
                   ("GB","Actieve gebruikers","orange",4),("TK","Open taken","orange",4),("AP","Actiepunten","teal",1))
        self.kpi_cards=[]
        for i,(symbol,title,accent,page_index) in enumerate(card_data):
            card=ClickableCard(page_index);card.clicked.connect(lambda x=page_index:self._show(x))
            card.setObjectName("StatCard");card.setProperty("accent",accent);card.setMinimumHeight(118)
            c=QVBoxLayout(card); c.setContentsMargins(20,17,20,17); c.setSpacing(4); top=QHBoxLayout()
            icon=QLabel(symbol); icon.setObjectName("KpiIcon"); icon.setProperty("accent",accent); value=QLabel("0"); value.setObjectName("Kpi")
            top.addWidget(icon);top.addStretch();top.addWidget(value);c.addLayout(top)
            bottom=QHBoxLayout();label=QLabel(title);label.setObjectName("KpiLabel");hint=QLabel("Open  →");hint.setObjectName("CardLink")
            bottom.addWidget(label);bottom.addStretch();bottom.addWidget(hint);c.addLayout(bottom)
            grid.addWidget(card,i//3,i%3);self.kpis.append(value);self.kpi_cards.append(card)
        box.addLayout(grid)
        toolbar=QFrame(); toolbar.setObjectName("Toolbar"); filters=QHBoxLayout(toolbar); filters.setContentsMargins(12,9,12,9); filters.setSpacing(9); filter_label=QLabel("Werkbak"); filter_label.setObjectName("ToolbarTitle"); filters.addWidget(filter_label)
        self.day_owner=QLineEdit();self.day_owner.setPlaceholderText("Zoek medewerker…");self.day_owner.textChanged.connect(self.refresh_daystart)
        self.day_priority=QComboBox()
        for label,value in (("Alle prioriteiten","Alle"),("Kritiek","Kritiek"),("Hoog","Hoog"),("Normaal","Normaal"),("Laag","Laag")):self.day_priority.addItem(label,value)
        self.day_priority.currentIndexChanged.connect(self.refresh_daystart)
        self.day_period=QComboBox()
        for label,value in (("Alles actueel","Actueel"),("Alleen vandaag","Vandaag"),("Alleen te laat","Te laat")):self.day_period.addItem(label,value)
        self.day_period.currentIndexChanged.connect(self.refresh_daystart);self.day_summary=QLabel()
        self.day_summary.setObjectName("SummaryPill"); filters.addWidget(self.day_owner,1);filters.addWidget(self.day_priority);filters.addWidget(self.day_period);filters.addWidget(self.day_summary);box.addWidget(toolbar)
        self.day_table=QTableWidget(0,9);self.day_table.setHorizontalHeaderLabels(["Prioriteit","Actie","Wanneer","Klant","Wat is er nodig?","Eigenaar","Status","Klant-ID","Item-ID"])
        self.day_table.setColumnHidden(7,True);self.day_table.setColumnHidden(8,True);self.day_table.verticalHeader().hide()
        self.day_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.day_table.setWordWrap(False)
        header=self.day_table.horizontalHeader()
        for column in (0,1,2,5):header.setSectionResizeMode(column,QHeaderView.ResizeMode.ResizeToContents)
        for column in (3,4,6):header.setSectionResizeMode(column,QHeaderView.ResizeMode.Stretch)
        self.day_table.doubleClicked.connect(self.open_daystart_customer)
        empty=QFrame(); empty.setObjectName("EmptyState"); empty_box=QVBoxLayout(empty); empty_box.setAlignment(Qt.AlignCenter); empty_box.setSpacing(8)
        empty_icon=QLabel("✓"); empty_icon.setObjectName("EmptyIcon"); empty_icon.setAlignment(Qt.AlignCenter); empty_title=QLabel("Alles bijgewerkt"); empty_title.setObjectName("EmptyTitle"); empty_title.setAlignment(Qt.AlignCenter)
        empty_text=QLabel("Er staan geen open acties in je werkbak.\nNieuwe taken en meldingen verschijnen hier automatisch."); empty_text.setObjectName("EmptyText"); empty_text.setAlignment(Qt.AlignCenter)
        empty_box.addStretch(); empty_box.addWidget(empty_icon,0,Qt.AlignCenter); empty_box.addWidget(empty_title); empty_box.addWidget(empty_text); empty_box.addStretch()
        self.day_content=QStackedWidget(); self.day_content.addWidget(self.day_table); self.day_content.addWidget(empty); box.addWidget(self.day_content,1)
        action_bar=QFrame(); action_bar.setObjectName("ActionBar"); actions=QHBoxLayout(action_bar); actions.setContentsMargins(12,9,12,9); self.day_action_buttons=[]
        for symbol,text,handler in (("KL","Open klantdossier",self.open_daystart_customer),("TW","Toewijzen",self.assign_daystart),("UT","Uitstellen",self.snooze_daystart),("OK","Melding afronden",self.dismiss_daystart)):
            button=QPushButton(text); button.setIcon(nav_icon(symbol)); button.setIconSize(QSize(24,24)); button.clicked.connect(handler);actions.addWidget(button);self.day_action_buttons.append(button)
        self.day_action_buttons[0].setObjectName("Primary"); actions.addStretch();box.addWidget(action_bar);return page

    def selected_daystart(self):
        row=self.day_table.currentRow()
        if row<0:return None
        kind=self.day_table.item(row,1);entity=self.day_table.item(row,8);customer=self.day_table.item(row,7)
        return (kind.text(),int(entity.text()),int(customer.text())) if kind and entity and customer and customer.text() else (kind.text(),int(entity.text()),None) if kind and entity else None

    def refresh_daystart(self,*_):
        if not hasattr(self,"day_table"):return
        rows=self.daystart_service.items(self.day_owner.text(),self.day_priority.currentData(),self.day_period.currentData());self.day_table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            values=(item["priority"],item["kind"],item["due_at"],item["customer_name"],item["title"],item["assigned_to"],item["detail"],item["customer_id"] or "",item["entity_id"])
            for c,value in enumerate(values):
                cell=QTableWidgetItem(str(value or ""));cell.setTextAlignment((Qt.AlignVCenter|Qt.AlignLeft) if c not in (0,2) else Qt.AlignCenter)
                if c==0:
                    colors={"Kritiek":("#FDE8E7","#A3221B"),"Hoog":("#FFF0DE","#9A4B11"),"Normaal":("#EAF4FF","#1265C4"),"Laag":("#EEF3F7","#596B7E")}
                    background,foreground=colors.get(str(value),("#EEF3F7","#596B7E"));cell.setBackground(QColor(background));cell.setForeground(QColor(foreground))
                elif c==2 and value:
                    from datetime import date
                    day=str(value)[:10];today=date.today().isoformat()
                    background,foreground=("#FDE8E7","#A3221B") if day<today else ("#FFF0DE","#9A4B11") if day==today else ("#EAF4FF","#1265C4")
                    cell.setBackground(QColor(background));cell.setForeground(QColor(foreground))
                elif c==5:
                    employee=str(value or "Niet toegewezen")
                    palette=(("#E8F1FC","#1B5F9E"),("#E8F7F1","#176B50"),("#F1EAFE","#6841B5"),
                             ("#FFF0DE","#9A4B11"),("#FCEAEC","#9B2942"),("#E7F5F7","#176878"))
                    background,foreground=palette[sum(ord(char) for char in employee.lower())%len(palette)]
                    cell.setText(employee);cell.setBackground(QColor(background));cell.setForeground(QColor(foreground))
                self.day_table.setItem(r,c,cell)
            self.day_table.setRowHeight(r,40)
        summary=self.daystart_service.summary();self.day_summary.setText(f"{summary['total']} open · {summary['overdue']} te laat · {summary['urgent']} urgent")
        has_rows=bool(rows); self.day_content.setCurrentIndex(0 if has_rows else 1)
        for button in self.day_action_buttons: button.setEnabled(has_rows)

    def open_daystart_customer(self,*_):
        selected=self.selected_daystart()
        if selected and selected[2]:self.open_customer(selected[2])

    def assign_daystart(self):
        selected=self.selected_daystart()
        if not selected:return
        owner,ok=QInputDialog.getText(self,"Dagstart toewijzen","Medewerker")
        if ok:self.daystart_service.assign(selected[0],selected[1],owner);self.refresh_daystart()

    def snooze_daystart(self):
        selected=self.selected_daystart()
        if not selected:return
        until,ok=QInputDialog.getText(self,"Melding uitstellen","Tonen vanaf (jjjj-mm-dd)")
        if ok:
            try:self.daystart_service.snooze(selected[0],selected[1],until);self.refresh_daystart()
            except Exception as exc:QMessageBox.warning(self,"Melding uitstellen",str(exc))

    def dismiss_daystart(self):
        selected=self.selected_daystart()
        if selected:self.daystart_service.dismiss(selected[0],selected[1]);self.refresh_daystart()
    def _customer_page(self):
        page,box=self._page("Klanten","Eén betrouwbaar klantbeeld voor alle NOWA-modules.")
        toolbar=QFrame();toolbar.setObjectName("Toolbar");row=QHBoxLayout(toolbar);row.setContentsMargins(12,9,12,9);row.setSpacing(9); label=QLabel("Klantbestand");label.setObjectName("ToolbarTitle");row.addWidget(label)
        self.customer_search=QLineEdit(); self.customer_search.setPlaceholderText("Zoek naam, klantnummer, telefoon, e-mail of contactpersoon…"); self.customer_search.textChanged.connect(self.refresh_customers)
        add=QPushButton("Nieuwe klant"); add.setObjectName("Primary"); add.setIcon(nav_icon("+")); add.setIconSize(QSize(24,24)); add.clicked.connect(self.add_customer)
        dossier=QPushButton("Open dossier");dossier.setIcon(nav_icon("360"));dossier.setIconSize(QSize(24,24));dossier.clicked.connect(self.open_selected_customer)
        edit=QPushButton("Bewerken"); edit.clicked.connect(self.edit_customer); contacts=QPushButton("Contactpersonen"); contacts.clicked.connect(self.manage_contacts)
        import_btn=QPushButton("Excel synchroniseren");import_btn.clicked.connect(self.import_customers)
        history_btn=QPushButton("Importhistorie");history_btn.clicked.connect(self.customer_import_history)
        export_btn=QPushButton("Exporteren");export_btn.clicked.connect(self.export_customers)
        reactivate_btn=QPushButton("Heractiveren");reactivate_btn.clicked.connect(self.reactivate_customer)
        row.addWidget(self.customer_search,1); row.addWidget(dossier); row.addWidget(edit); row.addWidget(contacts); row.addWidget(add); box.addWidget(toolbar)
        importbar=QFrame();importbar.setObjectName("ActionBar");tools=QHBoxLayout(importbar);tools.setContentsMargins(12,8,12,8);tools.addWidget(QLabel("Gegevensbeheer"));tools.addStretch();tools.addWidget(import_btn);tools.addWidget(history_btn);tools.addWidget(export_btn);tools.addWidget(reactivate_btn);box.addWidget(importbar)
        self.customer_card=QFrame();self.customer_card.setObjectName("CustomerHero");card=QHBoxLayout(self.customer_card);card.setContentsMargins(18,14,18,14)
        badge=QLabel("KL");badge.setObjectName("CustomerBadge");card.addWidget(badge);identity=QVBoxLayout();self.customer_card_name=QLabel("Selecteer een klant");self.customer_card_name.setObjectName("CustomerName");identity.addWidget(self.customer_card_name);self.customer_card_meta=QLabel("De belangrijkste gegevens en acties verschijnen hier.");self.customer_card_meta.setObjectName("CustomerMeta");self.customer_card_meta.setWordWrap(True);identity.addWidget(self.customer_card_meta);self.customer_card_warning=QLabel();self.customer_card_warning.setObjectName("AttentionBanner");self.customer_card_warning.setWordWrap(True);self.customer_card_warning.hide();identity.addWidget(self.customer_card_warning);card.addLayout(identity,1)
        for symbol,text,handler in (("360","Dossier",self.open_selected_customer),("OF","Offerte",self.customer_quick_proposal),("ML","Mail",self.customer_quick_mail),("KV","IT-kluis",self.customer_quick_vault)):
            button=QPushButton(text);button.setIcon(nav_icon(symbol));button.setIconSize(QSize(24,24));button.clicked.connect(handler);card.addWidget(button)
        box.addWidget(self.customer_card)
        self.customer_table=QTableWidget(0,9); self.customer_table.setHorizontalHeaderLabels(["Klantnummer","Naam","Status","Labels","E-mail","Telefoon","Mobiel","Plaats","ID"]); self.customer_table.setColumnHidden(8,True); self.customer_table.horizontalHeader().setStretchLastSection(True); self.customer_table.setAlternatingRowColors(True); self.customer_table.doubleClicked.connect(self.open_selected_customer);self.customer_table.itemSelectionChanged.connect(self.refresh_customer_card); box.addWidget(self.customer_table,1); return page
    def _proposal_page(self):
        page,box=self._page("Offertes","Versies en status overzichtelijk per klant beheren."); searchbar=QFrame();searchbar.setObjectName("Toolbar");row=QHBoxLayout(searchbar);row.setContentsMargins(12,9,12,9);row.addWidget(QLabel("Offerteoverzicht")); self.proposal_search=QLineEdit(); self.proposal_search.setPlaceholderText("Zoek offerte of klant…"); self.proposal_search.textChanged.connect(self.refresh_proposals);self.proposal_customer=QComboBox();self.proposal_customer.addItem("Alle klanten",None);[self.proposal_customer.addItem(c.name,c.id) for c in self.customers.search()];self.proposal_customer.currentIndexChanged.connect(self.refresh_proposals);self.proposal_status=QComboBox();self.proposal_status.addItems(["Alle statussen","concept","verzonden","geaccepteerd","afgewezen","verlopen"]);self.proposal_status.currentTextChanged.connect(self.refresh_proposals);self.proposal_period=QComboBox();self.proposal_period.addItems(["Alle perioden","Deze maand","Dit jaar"]);self.proposal_period.currentTextChanged.connect(self.refresh_proposals);row.addWidget(self.proposal_search,1);row.addWidget(self.proposal_customer);row.addWidget(self.proposal_status);row.addWidget(self.proposal_period);box.addWidget(searchbar)
        body=QHBoxLayout();self.proposal_table=QTableWidget(0,7); self.proposal_table.setHorizontalHeaderLabels(["Nummer","Klant","Titel","Status","Revisie","Totaal excl. btw","ID"]); self.proposal_table.setColumnHidden(6,True); self.proposal_table.horizontalHeader().setStretchLastSection(True);self.proposal_table.setAlternatingRowColors(True); self.proposal_table.doubleClicked.connect(self.edit_proposal)
        actions=QFrame();actions.setObjectName("LeftActionPanel");side=QVBoxLayout(actions);side.setContentsMargins(16,16,16,16);side.setSpacing(10);head=QLabel("Offerte-acties");head.setObjectName("PanelTitle");side.addWidget(head);sub=QLabel("Selecteer een offerte voor de acties hieronder.");sub.setObjectName("PanelText");sub.setWordWrap(True);side.addWidget(sub)
        for symbol,text,handler,primary in (("+","Nieuwe offerte",self.add_proposal,True),("OP","Openen",self.edit_proposal,False),("AK","Akkoordbeheer",self.open_approval_manager,False),("PDF","Controleer & PDF",self.export_selected_proposal,False),("KO","Dupliceren",self.duplicate_proposal,False),("RV","Nieuwe revisie",self.revise_proposal,False),("CK","Controleer offerte",self.validate_proposal,False),("IM","Oude offerte importeren",self.import_legacy_proposal,False)):
            button=QPushButton(text);button.setObjectName("SidePrimary" if primary else "SideAction");button.setIcon(nav_icon(symbol));button.setIconSize(QSize(28,28));button.clicked.connect(handler);side.addWidget(button)
        side.addStretch();actions.setFixedWidth(245);body.addWidget(actions);body.addWidget(self.proposal_table,1);box.addLayout(body,1);return page
    def _vault_page(self):
        page,box=self._page("IT Kluis","Vind tijdens een klantgesprek snel het juiste gegeven; zoek ook rechtstreeks op telefoonnummer.");searchbar=QFrame();searchbar.setObjectName("Toolbar");row=QHBoxLayout(searchbar);row.setContentsMargins(12,9,12,9);row.addWidget(QLabel("Veilige zoekopdracht")); self.vault_search=QLineEdit(); self.vault_search.setPlaceholderText("Zoek klant, telefoon, account, host, gebruikersnaam of domein…"); self.vault_search.textChanged.connect(self.refresh_vault);row.addWidget(self.vault_search,1);box.addWidget(searchbar)
        body=QHBoxLayout();self.vault_table=QTableWidget(0,10); self.vault_table.setHorizontalHeaderLabels(["Klant","Klantnr.","Categorie","Groep","Omschrijving","Gebruikersnaam","Host / IP","URL","Klant-ID","ID"]); self.vault_table.setColumnHidden(8,True);self.vault_table.setColumnHidden(9,True); self.vault_table.horizontalHeader().setStretchLastSection(True);self.vault_table.setAlternatingRowColors(True); self.vault_table.doubleClicked.connect(self.reveal_secret)
        actions=QFrame();actions.setObjectName("LeftActionPanel");side=QVBoxLayout(actions);side.setContentsMargins(16,16,16,16);side.setSpacing(10);head=QLabel("Kluis-acties");head.setObjectName("PanelTitle");side.addWidget(head);sub=QLabel("Wachtwoorden worden alleen vrijgegeven na de telefonische verificatiestappen.");sub.setObjectName("PanelText");sub.setWordWrap(True);side.addWidget(sub)
        for symbol,text,handler,primary in (("+","Nieuw kluisitem",self.add_vault,True),("PW","Veilige verstrekking",self.reveal_secret,False),("US","Gebruikersnaam kopiëren",self.copy_vault_username,False),("360","Open klantdossier",self.open_vault_customer,False),("KP","KeePass importeren",self.import_keepass,False)):
            button=QPushButton(text);button.setObjectName("SidePrimary" if primary else "SideAction");button.setIcon(nav_icon(symbol));button.setIconSize(QSize(28,28));button.clicked.connect(handler);side.addWidget(button)
        side.addStretch();notice=QLabel("Lokaal versleuteld\nGeen credentials in GitHub");notice.setObjectName("SecurityNote");notice.setWordWrap(True);side.addWidget(notice);actions.setFixedWidth(245);body.addWidget(actions);body.addWidget(self.vault_table,1);box.addLayout(body,1);return page
    def _selected_id(self,table,col):
        row=table.currentRow(); item=table.item(row,col) if row>=0 else None; return int(item.text()) if item else None
    def open_selected_customer(self,*_):
        customer_id=self._selected_id(self.customer_table,8)
        if customer_id:self.open_customer(customer_id)
    def refresh_customer_card(self):
        customer_id=self._selected_id(self.customer_table,8)
        customer=self.customers.get(customer_id) if customer_id else None
        if not customer:self.customer_card_name.setText("Selecteer een klant");self.customer_card_meta.setText("De belangrijkste gegevens en acties verschijnen hier.");self.customer_card_warning.hide();return
        contacts=self.customers.contacts(customer.id);self.customer_card_name.setText(f"{customer.name}  ·  {customer.customer_number}  ·  {customer.status}")
        address=" ".join(x for x in (customer.street,customer.postal_code,customer.city) if x);details=[customer.phone or customer.mobile_phone,customer.email,address,f"{len(contacts)} contactperso{'on' if len(contacts)==1 else 'nen'}",customer.tags]
        self.customer_card_meta.setText("   ·   ".join(x for x in details if x) or "Nog geen contactgegevens vastgelegd")
        missing=[]
        if not (customer.phone or customer.mobile_phone):missing.append("telefoonnummer ontbreekt")
        if not customer.email:missing.append("e-mailadres ontbreekt")
        if not contacts:missing.append("geen contactpersoon")
        self.customer_card_warning.setText("Aanvullen  ·  "+"  ·  ".join(missing));self.customer_card_warning.setVisible(bool(missing))
    def customer_quick_proposal(self):
        customer_id=self._selected_id(self.customer_table,8)
        if customer_id:self.add_proposal_for_customer(customer_id)
    def customer_quick_mail(self):
        customer_id=self._selected_id(self.customer_table,8)
        if customer_id:self.start_customer_mail(customer_id)
    def customer_quick_vault(self):
        customer_id=self._selected_id(self.customer_table,8);customer=self.customers.get(customer_id) if customer_id else None
        if customer:self.open_vault(customer.name)
    def add_customer(self):
        dlg=CustomerDialog(self)
        if dlg.exec():
            try:self.customers.create(*dlg.values()); self.refresh_all(); self.mail_page.reload()
            except Exception as e: QMessageBox.critical(self,"Klant opslaan",str(e))
    def edit_customer(self,*_):
        cid=self._selected_id(self.customer_table,8)
        if not cid:return
        customer=self.customers.get(cid); dlg=CustomerDialog(self,customer)
        if dlg.exec():
            try:self.customers.update(cid,*dlg.values()); self.refresh_all(); self.mail_page.reload()
            except Exception as e: QMessageBox.critical(self,"Klant opslaan",str(e))
    def manage_contacts(self):
        cid=self._selected_id(self.customer_table,8)
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
                proposal_id=self.proposals.create(customers[labels.index(label)].id,title); self.refresh_all(); ProposalDialog(self.proposals,proposal_id,self,mail=self.mail).exec(); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Offerte",str(e))
    def add_proposal_for_customer(self,customer_id):
        customer=self.customers.get(customer_id)
        if not customer:return
        title,ok=QInputDialog.getText(self,"Nieuwe offerte",f"Titel voor {customer.name}")
        if ok and title.strip():
            try:proposal_id=self.proposals.create(customer_id,title);self.refresh_all();ProposalDialog(self.proposals,proposal_id,self,mail=self.mail).exec();self.refresh_all()
            except Exception as exc:QMessageBox.warning(self,"Nieuwe offerte",str(exc))
    def import_legacy_proposal(self):
        filename,_=QFileDialog.getOpenFileName(self,"Geëxtraheerde oude offerte selecteren","","NOWA-offertepakket (*.zip)")
        if not filename:return
        try:
            preview=self.legacy_proposal_import.preview(Path(filename))
            customers=self.customers.search()
            if not customers:
                QMessageBox.information(self,"Oude offerte importeren","Voeg eerst de klant toe waaraan de offerte gekoppeld moet worden.");return
            labels=[f"{customer.customer_number} — {customer.name}" for customer in customers]
            label,ok=QInputDialog.getItem(self,"Klant voor oude offerte",f"Kies de klant voor {preview.source_number} — {preview.title}",labels,0,False)
            if not ok:return
            customer=customers[labels.index(label)]
            line_summary="\n".join(
                f"• {line['description']}: {line['quantity']:g} × € {line['unit_price_cents']/100:,.2f}"
                for line in preview.lines[:12]
            )
            message=(
                f"GEKOZEN KLANT\n{customer.customer_number} — {customer.name}\n\n"
                f"OUDE OFFERTE\nNummer: {preview.source_number}\nDatum: {preview.source_date or 'onbekend'}\n"
                f"Titel: {preview.title}\nUren: {preview.labor_hours:g}\n"
                f"Totaal excl. btw: € {preview.subtotal_cents/100:,.2f}\n\n"
                f"KOPPELING AAN KLANT\nGebruikers: {preview.intake.get('users_count',0)}\n"
                f"Apparaten: {preview.intake.get('devices_count',0)}\n"
                f"Gedeelde mailboxen: {preview.intake.get('shared_mailboxes',0)}\n"
                f"Licentieregels: {len(preview.licenses)}\nHardwareregels: {len(preview.hardware)}\n"
                f"Originele PDF: {'ja' if preview.pdf_file else 'nee'}\n\n"
                f"OFFERTEREGELS\n{line_summary}\n\n"
                "Bestaande klantgegevens worden behouden. Nieuwe gegevens worden toegevoegd; verschillen worden gemeld.\n"
                "Vooraf wordt automatisch een lokale back-up gemaakt.\n\nImport uitvoeren?"
            )
            if QMessageBox.question(self,"Oude offerte controleren",message)!=QMessageBox.Yes:return
            result=self.legacy_proposal_import.apply(preview,customer.id)
            self.refresh_all();self.assets_page.reload();self.customer360.reload()
            warning_text=("\n\nAandachtspunten:\n"+"\n".join(f"• {x}" for x in result["warnings"])) if result["warnings"] else ""
            QMessageBox.information(
                self,"Oude offerte geïmporteerd",
                f"Offerte gekoppeld aan {customer.name}.\n\nOfferteregels: {result['lines']}\n"
                f"Nieuwe licenties: {result['licenses']}\nNieuwe hardware: {result['hardware']}\n"
                f"PDF in documentcentrum: {'ja' if result['document_id'] else 'nee'}\n\n"
                f"Back-up:\n{result['backup']}{warning_text}",
            )
            ProposalDialog(self.proposals,result["proposal_id"],self,mail=self.mail).exec();self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self,"Oude offerte importeren",str(exc))
    def import_customers(self):
        filename,_=QFileDialog.getOpenFileName(self,"Excel-adressenlijst selecteren","","Excel-bestanden (*.xlsx)")
        if not filename:return
        try:
            preview=self.customer_import.preview(Path(filename))
            detail="\n".join(f"• {item['action']}: {item['customer_number']} — {item['name']} ({item['fields']})" for item in preview.changes[:25])
            if len(preview.changes)>25:detail+=f"\n• … en nog {len(preview.changes)-25} wijzigingen"
            warnings=("\n\nWAARSCHUWINGEN\n"+"\n".join(f"• {text}" for text in preview.warnings)) if preview.warnings else ""
            message=(f"Bronregels: {len(preview.rows)}\n\n"
                     f"Nieuw: {preview.created}\nBijwerken: {preview.updated}\nOngewijzigd: {preview.unchanged}\n"
                     f"Niet meer aanwezig (uit actieve klantenlijst): {preview.archived}\n\n"
                     f"WIJZIGINGEN\n{detail or 'Geen wijzigingen.'}{warnings}\n\n"
                     "Fax en krediettermijn worden genegeerd.\n"
                     "Vóór uitvoering wordt automatisch een lokale back-up gemaakt.\n\nSynchronisatie uitvoeren?")
            if QMessageBox.question(self,"Klantimport controleren",message)!=QMessageBox.Yes:return
            result=self.customer_import.apply(preview);self.refresh_all();self.mail_page.reload()
            QMessageBox.information(self,"Klantimport voltooid",
                f"{result['created']} toegevoegd\n{result['updated']} bijgewerkt\n{result['archived']} uitgefaseerd\n"
                f"{result['unchanged']} ongewijzigd\n\nBack-up:\n{result['backup']}")
        except Exception as exc:QMessageBox.warning(self,"Klantimport",str(exc))
    def customer_import_history(self):
        runs=self.customer_import.history()
        if not runs:
            QMessageBox.information(self,"Importhistorie","Er zijn nog geen klantimports uitgevoerd.");return
        labels=[f"#{run['id']} — {run['created_at']} — {run['source_name']} — {run['status']}" for run in runs]
        label,ok=QInputDialog.getItem(self,"Importhistorie","Import bekijken",labels,0,False)
        if not ok:return
        run=runs[labels.index(label)];changes=self.customer_import.changes(run["id"])
        lines=[f"{item['action'].capitalize()}: {item['customer_number']} — {item['customer_name']}"
               +(f" ({item['changed_fields']})" if item["changed_fields"] else "") for item in changes if item["action"]!="ongewijzigd"]
        summary=(f"Bestand: {run['source_name']}\nDatum: {run['created_at']}\nDoor: {run['performed_by'] or 'onbekend'}\n"
                 f"Status: {run['status']}\n\nNieuw: {run['created_count']}\nBijgewerkt: {run['updated_count']}\n"
                 f"Gedeactiveerd: {run['archived_count']}\nOngewijzigd: {run['unchanged_count']}\n\n"
                 +"Wijzigingen:\n"+("\n".join(lines[:40]) or "Geen wijzigingen."))
        if len(lines)>40:summary+=f"\n… en nog {len(lines)-40}"
        if run["status"]=="uitgevoerd":
            answer=QMessageBox.question(self,"Importverslag",summary+"\n\nDeze laatste import ongedaan maken?")
            if answer==QMessageBox.Yes:
                try:
                    result=self.customer_import.undo(run["id"]);self.refresh_all();self.mail_page.reload()
                    QMessageBox.information(self,"Import hersteld",f"{result['restored']} klantwijzigingen zijn lokaal teruggedraaid.")
                except Exception as exc:QMessageBox.warning(self,"Import herstellen",str(exc))
        else:QMessageBox.information(self,"Importverslag",summary)
    def export_customers(self):
        filename,_=QFileDialog.getSaveFileName(self,"Actieve klanten exporteren",f"NOWA-klanten-{__version__}.xlsx","Excel-bestanden (*.xlsx)")
        if not filename:return
        if not filename.lower().endswith(".xlsx"):filename+=".xlsx"
        try:
            path=self.customer_import.export_active(Path(filename))
            QMessageBox.information(self,"Klanten geëxporteerd",f"De actuele actieve klantenlijst is opgeslagen:\n{path}")
        except Exception as exc:QMessageBox.warning(self,"Klanten exporteren",str(exc))
    def reactivate_customer(self):
        number,ok=QInputDialog.getText(self,"Klant opnieuw activeren","Klantnummer")
        if ok and number.strip():
            try:
                self.customer_import.reactivate(number);self.refresh_all()
                QMessageBox.information(self,"Klant geactiveerd",f"Klant {number.strip()} staat weer in de actieve klantenlijst.")
            except Exception as exc:QMessageBox.warning(self,"Klant activeren",str(exc))
    def edit_proposal(self,*_):
        proposal_id=self._selected_id(self.proposal_table,6)
        if proposal_id:ProposalDialog(self.proposals,proposal_id,self,mail=self.mail).exec(); self.refresh_all()
    def open_approval_manager(self):
        ApprovalManagerDialog(self.proposals,self.open_proposal,self).exec();self.refresh_all()
    def duplicate_proposal(self):
        proposal_id=self._selected_id(self.proposal_table,6)
        if not proposal_id:return
        try:new_id=self.proposals.duplicate(proposal_id);self.refresh_all();ProposalDialog(self.proposals,new_id,self,mail=self.mail).exec();self.refresh_all()
        except Exception as exc:QMessageBox.warning(self,"Offerte dupliceren",str(exc))
    def revise_proposal(self):
        proposal_id=self._selected_id(self.proposal_table,6)
        if not proposal_id:return
        label,ok=QInputDialog.getText(self,"Nieuwe revisie","Omschrijving van deze revisie")
        if ok:self.proposals.create_revision(proposal_id,label);self.refresh_proposals();QMessageBox.information(self,"Revisie opgeslagen","De huidige offerte is als nieuwe revisie vastgelegd.")
    def validate_proposal(self):
        proposal_id=self._selected_id(self.proposal_table,6)
        if not proposal_id:return
        warnings=self.proposals.validate(proposal_id);QMessageBox.information(self,"Offertecontrole","\n".join(f"• {x}" for x in warnings) if warnings else "De offerte is volledig en bevat geen bekende aandachtspunten.")
    def export_selected_proposal(self):
        proposal_id=self._selected_id(self.proposal_table,6)
        if not proposal_id:return
        warnings=self.proposals.validate(proposal_id)
        if warnings and QMessageBox.question(self,"Offertecontrole","\n".join(f"• {x}" for x in warnings)+"\n\nToch een PDF maken?")!=QMessageBox.Yes:return
        try:
            path=export_proposal_pdf(self.proposals,proposal_id)
            if QMessageBox.question(self,"PDF gereed",f"PDF lokaal opgeslagen:\n{path}\n\nNu openen?")==QMessageBox.Yes:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:QMessageBox.warning(self,"PDF export",str(exc))
    def open_proposal(self,proposal_id):
        ProposalDialog(self.proposals,proposal_id,self,mail=self.mail).exec(); self.refresh_all()
    def open_customer(self,customer_id):
        if self.customers.get(customer_id):self.customer360.select_customer(customer_id); self._show(3)
    def start_customer_mail(self,customer_id):
        self.mail_page.reload(); index=self.mail_page.customer.findData(customer_id)
        if index>=0:self.mail_page.customer.setCurrentIndex(index)
        self.mail_page.clear();self._show(7);self.mail_page.subject.setFocus()
    def start_customer_followup(self,customer_id):
        self.workspace_page.reload_customers();index=self.workspace_page.customer.findData(customer_id)
        if index>=0:self.workspace_page.customer.setCurrentIndex(index)
        self._show(1);self.workspace_page.add_action();self.refresh_all()
    def start_customer_call(self,customer_id):
        customer=self.customers.get(customer_id)
        if not customer:return
        self.telephony_page.phone.setText(customer.mobile_phone or customer.phone)
        self._show(8);self.telephony_page.phone.setFocus();self.telephony_page.phone.selectAll()
    def start_customer_ticket(self,customer_id):
        self._show(9);self.servicedesk_page.create_ticket_for_customer(customer_id)
    def open_vault(self,query):
        self.vault_search.setText(query); self._show(6)
    def open_mail_message(self,message_id):
        if message_id is not None:self.mail_page.open_message(message_id)
        self._show(7)
    def open_call(self,call_id):
        if call_id is not None:self.telephony_page.open_call(call_id)
        self._show(8)
    def show_incoming_call(self,call_id):
        call=self.telephony.get(call_id)
        if not call or call["status"]!="nieuw":return
        self.start_call_tracking(call_id)
        if self.incoming_call_popup:
            try:
                if self.incoming_call_popup.call_id==call_id:
                    self.incoming_call_popup.raise_();return
            except RuntimeError:
                self.incoming_call_popup=None
        if self.incoming_call_popup:
            try:self.incoming_call_popup.close()
            except RuntimeError:pass
        if self.isMinimized():self.showNormal()
        popup=IncomingCallPopup(call_id,self.customers,self.telephony,self.open_call,
            self.open_customer,self.open_vault,self.create_ticket_from_communication,self.open_call_workspace_item,self)
        self.incoming_call_popup=popup
        popup.completed.connect(self.handle_call_finished)
        popup.destroyed.connect(lambda:self._clear_incoming_popup(popup))
        popup.show();popup.raise_()
    def _clear_incoming_popup(self,popup):
        if self.incoming_call_popup is popup:self.incoming_call_popup=None
        call=self.telephony.get(popup.call_id)
        if call and call["status"] in ("afgerond","gemist"):self.stop_call_tracking(popup.call_id)

    def start_call_tracking(self,call_id):
        call=self.telephony.get(call_id)
        if not call or call["status"] in ("afgerond","gemist"):return
        self.active_call_id=call_id;self.call_name.setText(f"{call['customer_name']}\n{call['phone_number']}")
        self.call_panel.show();self.call_timer.start();self.update_call_tracking()

    def update_call_tracking(self):
        if not self.active_call_id:return
        call=self.telephony.get(self.active_call_id)
        if not call or call["status"] in ("afgerond","gemist"):
            self.stop_call_tracking(self.active_call_id);return
        seconds=self.telephony.elapsed_seconds(self.active_call_id);hours,remainder=divmod(seconds,3600);minutes,seconds=divmod(remainder,60)
        self.call_duration.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def open_active_call_workspace(self):
        if not self.active_call_id:return
        if self.incoming_call_popup:
            try:
                if self.incoming_call_popup.call_id==self.active_call_id:
                    self.incoming_call_popup.show();self.incoming_call_popup.raise_();self.incoming_call_popup.activateWindow();return
            except RuntimeError:self.incoming_call_popup=None
        self.show_incoming_call(self.active_call_id)

    def open_call_workspace_item(self,kind,entity_id,title):
        if kind=="Ticket":self.open_service_ticket(entity_id)
        else:
            self._show(1);self.workspace_page.search.setText(title)

    def stop_call_tracking(self,call_id=None):
        if call_id is not None and self.active_call_id!=call_id:return
        self.call_timer.stop();self.active_call_id=None;self.call_panel.hide();self.call_duration.setText("00:00:00")

    def end_active_call(self):
        if not self.active_call_id:return
        if self.incoming_call_popup:
            try:
                if self.incoming_call_popup.call_id==self.active_call_id:
                    self.incoming_call_popup.finish_workflow();return
            except RuntimeError:
                self.incoming_call_popup=None
        if self.telephony_page.call_id!=self.active_call_id:self.telephony_page.open_call(self.active_call_id)
        self.telephony_page.finish()

    def handle_call_finished(self,call_id,call):
        duration=self.telephony.elapsed_seconds(call_id);self.stop_call_tracking(call_id)
        if not call or not call.get("customer_id"):return
        if QMessageBox.question(self,"Gesprek afgerond","Gesprek en tijdregistratie zijn opgeslagen.\n\nEen samenvatting per e-mail voorbereiden?")!=QMessageBox.Yes:return
        customer=self.customers.get(call["customer_id"]);contacts=self.customers.contacts(call["customer_id"])
        contact=next((item for item in contacts if item.id==call.get("contact_id")),None)
        recipient=(contact.email if contact and contact.email else customer.email) if customer else ""
        if not recipient:
            QMessageBox.information(self,"Gesprekssamenvatting","Bij deze klant is geen e-mailadres vastgelegd.");return
        hours,remainder=divmod(duration,3600);minutes,seconds=divmod(remainder,60);duration_text=f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        subject=call.get("subject") or "Telefonisch contact"
        greeting=f"Beste {contact.name}," if contact else "Geachte heer/mevrouw,"
        body=(f"{greeting}\n\nHierbij ontvangt u een korte samenvatting van ons telefoongesprek.\n\n"
              f"Onderwerp: {subject}\nResultaat: {call.get('outcome') or 'Besproken'}\n"
              f"Gespreksduur: {duration_text}\n\n{call.get('notes') or 'Geen aanvullende notities.'}\n\n"
              "Met vriendelijke groet,\nNOWA")
        self.mail_page.reload();self.mail_page.clear();index=self.mail_page.customer.findData(call["customer_id"])
        if index>=0:self.mail_page.customer.setCurrentIndex(index)
        if contact:
            contact_index=self.mail_page.contact.findData(contact.id)
            if contact_index>=0:self.mail_page.contact.setCurrentIndex(contact_index)
        self.mail_page.to.setText(recipient);self.mail_page.subject.setText(f"Samenvatting telefoongesprek – {subject}");self.mail_page.body.setPlainText(body);self._show(7)
    def create_ticket_from_communication(self,customer_id,subject,description,source_type,source_id):
        try:
            self._show(9)
            self.servicedesk_page.create_ticket_from_source(customer_id,subject or "Servicevraag",description,source_type,source_id)
        except Exception as exc:QMessageBox.warning(self,"Serviceticket",str(exc))
    def open_service_ticket(self,ticket_id):
        self.servicedesk_page.open_ticket(ticket_id);self._show(9)
    def open_global_search(self):
        self._show(1);self.workspace_page.search.setFocus();self.workspace_page.search.selectAll()
    def open_global_result(self,kind,entity_id,customer_id,title):
        if kind=="Offerte" and entity_id:self.open_proposal(entity_id)
        elif kind=="Ticket" and entity_id:self.servicedesk_page.open_ticket(entity_id);self._show(9)
        elif kind=="E-mail" and entity_id:self.open_mail_message(entity_id)
        elif kind=="Gesprek" and entity_id:self.open_call(entity_id)
        elif kind=="Kluis":self.open_vault(title.split(" · ",1)[0])
        elif kind=="Document":
            self.documents_page.search.setText(title);self._show(17)
        elif kind=="Projecttaak":
            self.planning_page.reload_customers()
            index=self.planning_page.customer.findData(customer_id)
            if index>=0:self.planning_page.customer.setCurrentIndex(index)
            self._show(11)
        elif kind=="Actie":
            index=self.workspace_page.customer.findData(customer_id)
            if index>=0:self.workspace_page.customer.setCurrentIndex(index)
            self._show(1)
        elif customer_id:self.open_customer(customer_id)
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
        entry_id=self._selected_id(self.vault_table,9)
        if not entry_id: QMessageBox.information(self,"IT Kluis","Selecteer eerst een kluisitem."); return
        call_id=self.telephony_page.call_id
        if not call_id:
            QMessageBox.warning(self,"Veilige wachtwoordverstrekking","Start of selecteer eerst het telefoongesprek in Telefonie. Zonder gekoppeld gesprek blijft het wachtwoord verborgen.");return
        call=self.telephony.get(call_id);entry=self.vault.entry_info(entry_id)
        if not call or not entry:return
        if call["customer_id"]!=entry["customer_id"]:
            QMessageBox.warning(self,"Veilige wachtwoordverstrekking",f"De beller is gekoppeld aan {call['customer_name']}, maar het kluisitem hoort bij {entry['customer_name']}. Er wordt niets getoond.");return
        verification=VaultVerificationDialog(entry,call,self.customers.contacts(entry["customer_id"]),list(self.vault.VERIFICATION_METHODS),self)
        if not verification.exec():return
        try:
            verification_id=self.vault.record_verification(entry_id,call_id,verification.requester_name,verification.method.currentText(),verification.request_reason,True,True)
            secret=self.vault.reveal(entry_id,verification.request_reason,verification_id);alphabet="  ".join(f"{ch} — {self._spell(ch)}" for ch in secret);copied=verification.delivery_mode=="copy"
            if copied:QApplication.clipboard().setText(secret);QTimer.singleShot(30000,lambda:self._clear_clipboard(secret))
            tail="\n\nHet wachtwoord staat 30 seconden op het klembord." if copied else "\n\nHet wachtwoord is niet naar het klembord gekopieerd."
            QMessageBox.information(self,"Veilig vrijgegeven",f"{secret}\n\nSpelalfabet:\n{alphabet}{tail}")
        except Exception as e: QMessageBox.warning(self,"IT Kluis",str(e))
    def copy_vault_username(self):
        row=self.vault_table.currentRow();item=self.vault_table.item(row,5) if row>=0 else None
        if not item:return
        QApplication.clipboard().setText(item.text());QMessageBox.information(self,"IT Kluis","De gebruikersnaam is naar het klembord gekopieerd.")
    def open_vault_customer(self):
        customer_id=self._selected_id(self.vault_table,8)
        if customer_id:self.open_customer(customer_id)
    def _polish_ui(self):
        for table in self.findChildren(QTableWidget):
            table.setAlternatingRowColors(True);table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection);table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.verticalHeader().setVisible(False);table.verticalHeader().setDefaultSectionSize(36)
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
    def install_local_update(self):
        archive,_=QFileDialog.getOpenFileName(self,"Kies NOWA CRM-updatepakket","","ZIP-pakketten (*.zip)")
        if not archive:return
        try:
            self.update_status.setText("Het lokale updatepakket wordt veilig gecontroleerd…");QApplication.processEvents()
            package=UpdateService().prepare_local_package(Path(archive))
            answer=QMessageBox.question(
                self,"NOWA CRM bijwerken",
                "Het Windows-pakket is geldig. Nu installeren?\n\n"
                "Alleen programmabestanden worden vervangen. Klantgegevens, kluis en instellingen blijven lokaal behouden."
            )
            if answer!=QMessageBox.Yes:return
            UpdateService().install_after_exit(package)
            QMessageBox.information(self,"Update gereed","NOWA CRM sluit nu af en start automatisch opnieuw met de nieuwe versie.")
            QApplication.quit()
        except Exception as exc:
            self.update_status.setText(f"Updatepakket geweigerd: {exc}")
    def refresh_backup_status(self):
        if not hasattr(self,"backup_status"):return
        latest=BackupService(self.customers.db).latest()
        if not latest:self.backup_status.setText("Er is nog geen complete herstelset gemaakt.");return
        size=latest.size_bytes/(1024*1024)
        status="gecontroleerd en geldig" if latest.valid else "beschadigd of onvolledig"
        self.backup_status.setText(f"Laatste herstelset: {latest.created_at} · {latest.files} bestanden · {size:.1f} MB · {status}.")
    def create_recovery_backup(self):
        try:
            self.backup_status.setText("Database, kluis en klantbestanden worden lokaal veiliggesteld…");QApplication.processEvents()
            result=BackupService(self.customers.db).create()
            self.refresh_backup_status()
            QMessageBox.information(
                self,"Herstelset gereed",
                f"De complete lokale herstelset is gemaakt en gecontroleerd.\n\n{result.folder}\n\n"
                "Let op: deze map bevat ook de kluissleutel. Bewaar een externe kopie uitsluitend op een beveiligde locatie."
            )
        except Exception as exc:
            self.backup_status.setText(f"Herstelset maken mislukt: {exc}")
    def open_backup_folder(self):
        folder=data_dir()/"backups"/"herstelsets";folder.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    def restore_recovery_backup(self):
        folder=QFileDialog.getExistingDirectory(self,"Kies een NOWA CRM-herstelset",str(data_dir()/"backups"/"herstelsets"))
        if not folder:return
        service=BackupService(self.customers.db)
        try:
            info=service.prepare_restore(Path(folder))
            size=info.size_bytes/(1024*1024)
            answer=QMessageBox.warning(
                self,"Herstelset terugzetten",
                f"Herstelset van {info.created_at}\n{info.files} bestanden · {size:.1f} MB\n\n"
                "De huidige database, kluis, documenten en mailbijlagen worden teruggezet naar deze situatie.\n"
                "NOWA CRM maakt eerst automatisch een extra veiligheidskopie en start daarna opnieuw.\n\nDoorgaan?",
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No
            )
            if answer!=QMessageBox.Yes:return
            service.restore_after_exit(Path(folder))
            QMessageBox.information(self,"Herstel voorbereid","NOWA CRM sluit nu af, zet de gecontroleerde herstelset terug en start daarna opnieuw.")
            QApplication.quit()
        except Exception as exc:
            QMessageBox.critical(self,"Herstellen niet mogelijk",str(exc))
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
        if hasattr(self,"integrations_page"):self.integrations_page.reload()
        if hasattr(self,"shomi_page") and self.stack.currentWidget() is self.shomi_page:self.shomi_page.reload()
        if hasattr(self,"missed_calls_page"):
            self.missed_calls_page.reload()
            missed=self.telephony.missed_stats()["open"]
            self.nav_buttons[19].setText(f"Gemiste oproepen  ·  {missed}" if missed else "Gemiste oproepen")
        self.refresh_backup_status()
        if hasattr(self,"day_table"):self.refresh_daystart()
        stats=self.operations.dashboard(); values=(self.customers.count(),self.proposals.count_open(),self.vault.count(),
                                                   stats["users"],stats["open_tasks"],len(self.workspace.actions()))
        for label,value in zip(self.kpis,values):label.setText(str(value))
    def refresh_customers(self,*_):
        if not hasattr(self,"customer_table"):return
        selected_id=self._selected_id(self.customer_table,8);rows=self.customers.search(self.customer_search.text())
        self.customer_table.blockSignals(True);self.customer_table.clearSelection();self.customer_table.setCurrentCell(-1,-1)
        self.customer_table.setRowCount(len(rows));selected_row=-1
        for r,x in enumerate(rows):
            for c,v in enumerate((x.customer_number,x.name,x.status,x.tags,x.email,x.phone,x.mobile_phone,x.city,str(x.id))):
                item=QTableWidgetItem(v)
                if c==2:item.setForeground(QColor({"actief":"#16815F","prospect":"#1265C4","tijdelijk gestopt":"#9A4B11","uitgeschreven":"#6B7280"}.get(x.status,"#344259")))
                self.customer_table.setItem(r,c,item)
            if x.id==selected_id:selected_row=r
        target_row=selected_row if selected_row>=0 else (0 if rows else -1)
        if target_row>=0:self.customer_table.setCurrentCell(target_row,0);self.customer_table.selectRow(target_row)
        self.customer_table.blockSignals(False);self.refresh_customer_card()
    def refresh_proposals(self,*_):
        if not hasattr(self,"proposal_table"):return
        from datetime import datetime
        rows=self.proposals.list(self.proposal_search.text());status=self.proposal_status.currentText() if hasattr(self,"proposal_status") else "Alle statussen";customer_id=self.proposal_customer.currentData() if hasattr(self,"proposal_customer") else None;period=self.proposal_period.currentText() if hasattr(self,"proposal_period") else "Alle perioden";today=datetime.now().strftime("%Y-%m")
        if customer_id:rows=[x for x in rows if x.customer_id==customer_id]
        if status!="Alle statussen":rows=[x for x in rows if x.status==status]
        if period=="Deze maand":rows=[x for x in rows if x.created_at.startswith(today)]
        elif period=="Dit jaar":rows=[x for x in rows if x.created_at.startswith(today[:4])]
        self.proposal_table.setRowCount(len(rows));colors={"concept":"#6B7280","verzonden":"#1265C4","geaccepteerd":"#16815F","afgewezen":"#B42318","verlopen":"#9A4B11"}
        for r,x in enumerate(rows):
            vals=(x.number,x.customer_name,x.title,x.status,str(x.revision),f"€ {x.total_cents/100:,.2f}",str(x.id))
            for c,v in enumerate(vals):
                item=QTableWidgetItem(v)
                if c==3:item.setForeground(QColor(colors.get(x.status,"#344259")))
                self.proposal_table.setItem(r,c,item)
    def refresh_vault(self,*_):
        if not hasattr(self,"vault_table"):return
        rows=self.vault.search_all(self.vault_search.text()); self.vault_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=(x["customer_name"],x["customer_number"],x["category"],x["group_path"],x["label"],x["username"],x["host"],x["url"],str(x["customer_id"]),str(x["id"]))
            for c,v in enumerate(vals):self.vault_table.setItem(r,c,QTableWidgetItem(v or ""))
