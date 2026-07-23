from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QFileDialog,QFormLayout,QFrame,QGridLayout,QHBoxLayout,QLabel,QLineEdit,
                               QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from nowa_crm.modules.integrations.service import IntegrationService
from nowa_crm.integrations.sip_monitor import SipMonitor


class IntegrationsPage(QWidget):
    def __init__(self, service: IntegrationService, incoming_call, parent=None):
        super().__init__(parent); self.service, self.incoming_call = service, incoming_call
        self.service.cleanup_sip_connection_noise()
        self.sip=SipMonitor(self);self.sip.event_received.connect(self.receive_sip_event);self.sip.state_changed.connect(self.sip_state)
        root=QVBoxLayout(self);title=QLabel("Integratiecentrum");title.setObjectName("Title");root.addWidget(title)
        subtitle=QLabel("Beheer lokale Outlook-overdracht en SIP-nummerherkenning zonder klantdata in GitHub.")
        subtitle.setObjectName("Subtitle");root.addWidget(subtitle)
        cards=QGridLayout();self.outlook_card=self._outlook_card();self.sip_card=self._sip_card()
        cards.addWidget(self.outlook_card,0,0);cards.addWidget(self.sip_card,0,1);root.addLayout(cards)
        heading=QLabel("Koppelingslog");heading.setStyleSheet("font-size:16px;font-weight:700;color:#0B2342");root.addWidget(heading)
        self.events=QTableWidget(0,6);self.events.setHorizontalHeaderLabels(["Datum","Koppeling","Actie","Detail","Resultaat","ID"])
        self.events.setColumnHidden(5,True);self.events.horizontalHeader().setStretchLastSection(True);root.addWidget(self.events,1);self.reload()
        QTimer.singleShot(600,self.auto_start_sip)

    def _outlook_card(self):
        card=QFrame();card.setObjectName("Card");form=QFormLayout(card);heading=QLabel("Outlook");heading.setObjectName("Kpi");form.addRow(heading)
        self.outlook_enabled=QCheckBox("Lokale Outlook-overdracht actief");self.sender=QLineEdit();self.sender.setPlaceholderText("Bijvoorbeeld service@jouwdomein.nl");self.outlook_folder=QLineEdit();self.outlook_folder.setPlaceholderText("Lokale map met geëxporteerde .eml-bestanden")
        choose=QPushButton("Map kiezen");choose.clicked.connect(self.choose_outlook_folder);folderrow=QHBoxLayout();folderrow.addWidget(self.outlook_folder,1);folderrow.addWidget(choose)
        form.addRow(self.outlook_enabled);form.addRow("CRM-mailbox",self.sender);form.addRow("Importmap",folderrow)
        row=QHBoxLayout();save=QPushButton("Opslaan");save.setObjectName("Primary");save.clicked.connect(self.save_outlook)
        sync=QPushButton("Mailmap nu inlezen");sync.clicked.connect(self.sync_outlook);test=QPushButton("Open laatste concept");test.clicked.connect(self.open_latest);row.addWidget(save);row.addWidget(sync);row.addWidget(test);form.addRow(row);return card

    def _sip_card(self):
        card=QFrame();card.setObjectName("Card");form=QFormLayout(card);heading=QLabel("SIP-monitor · alleen inkomende signalering");heading.setObjectName("Kpi");form.addRow(heading)
        self.sip_enabled=QCheckBox("SIP-monitor actief");self.sip_auto=QCheckBox("Automatisch verbinden bij opstarten")
        self.sip_server=QLineEdit();self.sip_server.setPlaceholderText("SIP-server of IP-adres")
        self.sip_server_port=QLineEdit("5080");self.sip_local_port=QLineEdit("5080")
        self.sip_username=QLineEdit();self.sip_username.setPlaceholderText("Extensie / gebruikersnaam")
        self.sip_password=QLineEdit();self.sip_password.setEchoMode(QLineEdit.EchoMode.Password);self.sip_password.setPlaceholderText("Ongewijzigd laten om bestaand wachtwoord te behouden")
        self.sip_domain=QLineEdit();self.sip_domain.setPlaceholderText("Optioneel registratiedomein")
        self.sip_transport=QLineEdit("UDP");self.sip_transport.setReadOnly(True)
        self.sip_status=QLabel("Niet verbonden");self.sip_status.setWordWrap(True)
        ports=QHBoxLayout();ports.addWidget(QLabel("Server"));ports.addWidget(self.sip_server_port);ports.addWidget(QLabel("Lokaal"));ports.addWidget(self.sip_local_port)
        form.addRow(self.sip_enabled);form.addRow(self.sip_auto);form.addRow("SIP-server",self.sip_server);form.addRow("Poorten",ports)
        form.addRow("Gebruikersnaam",self.sip_username);form.addRow("Wachtwoord",self.sip_password);form.addRow("Domein",self.sip_domain)
        form.addRow("Transport",self.sip_transport);form.addRow("Status",self.sip_status)
        row=QHBoxLayout();save=QPushButton("SIP opslaan");save.setObjectName("Primary");save.clicked.connect(self.save_sip)
        connect=QPushButton("Verbinden / testen");connect.clicked.connect(self.start_sip);stop=QPushButton("Stoppen");stop.clicked.connect(self.sip.stop)
        row.addWidget(save);row.addWidget(connect);row.addWidget(stop);form.addRow(row);return card

    def reload(self):
        outlook=self.service.settings("outlook");sip=self.service.settings("sip")
        self.outlook_enabled.setChecked(outlook["enabled"]);self.sender.setText(outlook["settings"].get("mailbox_address",outlook["settings"].get("sender_address","")));self.outlook_folder.setText(outlook["settings"].get("folder_path",""))
        s=sip["settings"];self.sip_enabled.setChecked(sip["enabled"]);self.sip_auto.setChecked(s.get("auto_start","")=="1")
        self.sip_server.setText(s.get("server",""));self.sip_server_port.setText(s.get("server_port","5080"));self.sip_local_port.setText(s.get("local_port","5080"))
        self.sip_username.setText(s.get("username",""));self.sip_domain.setText(s.get("domain",""));self.sip_transport.setText(s.get("transport","UDP"))
        rows=self.service.events();self.events.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["occurred_at"],row["provider"].title(),row["action"],row["detail"],"Geslaagd" if row["successful"] else "Mislukt",row["id"])
            for c,value in enumerate(values):self.events.setItem(r,c,QTableWidgetItem(str(value or "")))

    def save_outlook(self):
        address=self.sender.text().strip()
        if address and ("@" not in address or "." not in address.split("@",1)[1]):QMessageBox.warning(self,"CRM-mailbox","Vul een geldig e-mailadres in.");return
        self.service.save("outlook",self.outlook_enabled.isChecked(),{"mode":"eml_folder","mailbox_address":address,"folder_path":self.outlook_folder.text()});self.reload()

    def choose_outlook_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Lokale Outlook-importmap kiezen",self.outlook_folder.text())
        if folder:self.outlook_folder.setText(folder)

    def sync_outlook(self):
        try:
            self.save_outlook();result=self.service.sync_outlook_folder();self.reload()
            QMessageBox.information(self,"Outlook-map ingelezen",f"{result['imported']} nieuwe berichten\n{result['linked']} automatisch gekoppeld\n{result['unlinked']} nog te koppelen\n{result['duplicates']} al aanwezig\n{result['errors']} fouten")
        except Exception as exc:QMessageBox.warning(self,"Outlook import",str(exc))

    def save_sip(self):
        try:ports=(int(self.sip_server_port.text()),int(self.sip_local_port.text()))
        except ValueError:QMessageBox.warning(self,"SIP-monitor","Beide poorten moeten getallen zijn.");return False
        if any(not 1024<=port<=65535 for port in ports):QMessageBox.warning(self,"SIP-monitor","Kies poorten tussen 1024 en 65535.");return False
        settings={"server":self.sip_server.text(),"server_port":str(ports[0]),"local_port":str(ports[1]),
            "username":self.sip_username.text(),"domain":self.sip_domain.text(),"transport":"UDP",
            "auto_start":"1" if self.sip_auto.isChecked() else "0"}
        self.service.save_sip(self.sip_enabled.isChecked(),settings,self.sip_password.text());self.sip_password.clear();self.reload();return True

    def start_sip(self):
        if not self.save_sip():return
        config=self.service.sip_runtime_settings()
        if not config["enabled"]:QMessageBox.information(self,"SIP-monitor","Schakel de SIP-monitor eerst in.");return
        self.sip.start(config)

    def sip_state(self,state,detail):
        labels={"luistert":"Luistert","verbinden":"Verbinden…","verbonden":"Verbonden","fout":"Fout"}
        self.sip_status.setText(f"{labels.get(state,state)} · {detail}")
        if state in ("verbonden","fout"):
            self.service.log("sip","verbinding",f"{state} · {detail}",state!="fout")
            self.reload()

    def receive_sip_event(self,payload):
        try:
            call=self.service.ingest_sip_event(payload);self.reload();self.incoming_call(call["id"])
        except Exception as exc:
            self.service.log("sip","event_fout",str(exc),False);self.reload()

    def showEvent(self,event):
        super().showEvent(event)
        self.auto_start_sip()

    def auto_start_sip(self):
        if self.sip.running:return
        config=self.service.sip_runtime_settings()
        if config.get("enabled") and config.get("auto_start")=="1":self.sip.start(config)

    def open_latest(self):
        try:
            draft=self.service.latest_draft()
            if not draft:QMessageBox.information(self,"Outlook","Er staat geen uitgaand concept klaar.");return
            path=self.service.prepare_outlook(draft["id"]);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)));self.reload()
        except Exception as exc:QMessageBox.warning(self,"Outlook",str(exc))
