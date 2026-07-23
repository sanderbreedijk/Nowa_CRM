from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QFileDialog,QFormLayout,QFrame,QGridLayout,QHBoxLayout,QLabel,QLineEdit,
                               QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from nowa_crm.modules.integrations.service import IntegrationService
from nowa_crm.integrations.coligo_bridge import ColigoBridge


class IntegrationsPage(QWidget):
    def __init__(self, service: IntegrationService, open_call, parent=None):
        super().__init__(parent); self.service, self.open_call = service, open_call
        self.bridge=ColigoBridge(self);self.bridge.event_received.connect(self.receive_coligo_event)
        self.bridge.state_changed.connect(self.bridge_state)
        root=QVBoxLayout(self);title=QLabel("Integratiecentrum");title.setObjectName("Title");root.addWidget(title)
        subtitle=QLabel("Beheer lokale Outlook-overdracht en Coligo-nummerherkenning zonder tokens of klantdata in GitHub.")
        subtitle.setObjectName("Subtitle");root.addWidget(subtitle)
        cards=QGridLayout();self.outlook_card=self._outlook_card();self.coligo_card=self._coligo_card()
        cards.addWidget(self.outlook_card,0,0);cards.addWidget(self.coligo_card,0,1);root.addLayout(cards)
        heading=QLabel("Koppelingslog");heading.setStyleSheet("font-size:16px;font-weight:700;color:#0B2342");root.addWidget(heading)
        self.events=QTableWidget(0,6);self.events.setHorizontalHeaderLabels(["Datum","Koppeling","Actie","Detail","Resultaat","ID"])
        self.events.setColumnHidden(5,True);self.events.horizontalHeader().setStretchLastSection(True);root.addWidget(self.events,1);self.reload()

    def _outlook_card(self):
        card=QFrame();card.setObjectName("Card");form=QFormLayout(card);heading=QLabel("Outlook");heading.setObjectName("Kpi");form.addRow(heading)
        self.outlook_enabled=QCheckBox("Lokale Outlook-overdracht actief");self.sender=QLineEdit();self.sender.setPlaceholderText("Bijvoorbeeld service@jouwdomein.nl");self.outlook_folder=QLineEdit();self.outlook_folder.setPlaceholderText("Lokale map met geëxporteerde .eml-bestanden")
        choose=QPushButton("Map kiezen");choose.clicked.connect(self.choose_outlook_folder);folderrow=QHBoxLayout();folderrow.addWidget(self.outlook_folder,1);folderrow.addWidget(choose)
        form.addRow(self.outlook_enabled);form.addRow("CRM-mailbox",self.sender);form.addRow("Importmap",folderrow)
        row=QHBoxLayout();save=QPushButton("Opslaan");save.setObjectName("Primary");save.clicked.connect(self.save_outlook)
        sync=QPushButton("Mailmap nu inlezen");sync.clicked.connect(self.sync_outlook);test=QPushButton("Open laatste concept");test.clicked.connect(self.open_latest);row.addWidget(save);row.addWidget(sync);row.addWidget(test);form.addRow(row);return card

    def _coligo_card(self):
        card=QFrame();card.setObjectName("Card");form=QFormLayout(card);heading=QLabel("Coligo");heading.setObjectName("Kpi");form.addRow(heading)
        self.coligo_enabled=QCheckBox("Lokale Coligo-invoer actief");self.line_name=QLineEdit();self.line_name.setPlaceholderText("Bijvoorbeeld Hoofdlijn")
        self.webhook_port=QLineEdit("8765");self.webhook_port.setPlaceholderText("8765")
        self.webhook_key=QLineEdit();self.webhook_key.setEchoMode(QLineEdit.EchoMode.Password);self.webhook_key.setPlaceholderText("Optionele lokale beveiligingssleutel")
        self.phone=QLineEdit();self.phone.setPlaceholderText("Testnummer of inkomend nummer");self.external_id=QLineEdit();self.external_id.setPlaceholderText("Extern gespreks-ID")
        self.bridge_status=QLabel("Ontvanger gestopt");self.bridge_status.setWordWrap(True)
        form.addRow(self.coligo_enabled);form.addRow("Lijnnaam",self.line_name);form.addRow("Lokale poort",self.webhook_port);form.addRow("Webhook-sleutel",self.webhook_key)
        form.addRow("Status",self.bridge_status);form.addRow("Testnummer",self.phone);form.addRow("Gespreks-ID",self.external_id)
        row=QHBoxLayout();save=QPushButton("Opslaan");save.setObjectName("Primary");save.clicked.connect(self.save_coligo)
        listen=QPushButton("Ontvanger starten");listen.clicked.connect(self.start_bridge)
        ingest=QPushButton("Test gesprek");ingest.clicked.connect(self.ingest_call);row.addWidget(save);row.addWidget(listen);row.addWidget(ingest);form.addRow(row);return card

    def reload(self):
        outlook=self.service.settings("outlook");coligo=self.service.settings("coligo")
        self.outlook_enabled.setChecked(outlook["enabled"]);self.sender.setText(outlook["settings"].get("mailbox_address",outlook["settings"].get("sender_address","")));self.outlook_folder.setText(outlook["settings"].get("folder_path",""))
        self.coligo_enabled.setChecked(coligo["enabled"]);self.line_name.setText(coligo["settings"].get("line_name",""))
        self.webhook_port.setText(coligo["settings"].get("webhook_port","8765"));self.webhook_key.setText(coligo["settings"].get("webhook_key",""))
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

    def save_coligo(self):
        try: port=int(self.webhook_port.text())
        except ValueError:QMessageBox.warning(self,"Coligo","De lokale poort moet een getal zijn.");return False
        if not 1024<=port<=65535:QMessageBox.warning(self,"Coligo","Kies een poort tussen 1024 en 65535.");return False
        self.service.save("coligo",self.coligo_enabled.isChecked(),{"mode":"local_webhook","line_name":self.line_name.text(),
            "webhook_port":str(port),"webhook_key":self.webhook_key.text()});self.reload()
        return True

    def start_bridge(self):
        if not self.save_coligo():return
        if not self.coligo_enabled.isChecked():QMessageBox.information(self,"Coligo","Schakel de lokale Coligo-invoer eerst in.");return
        if self.bridge.start(int(self.webhook_port.text()),self.webhook_key.text()):
            QMessageBox.information(self,"Coligo-ontvanger","De lokale ontvanger staat klaar. Gebruik POST /coligo en eventueel de header X-NOWA-Key.")

    def bridge_state(self,running,detail):
        self.bridge_status.setText(("Actief · " if running else "Niet actief · ")+detail)

    def receive_coligo_event(self,payload):
        try:
            call=self.service.ingest_coligo_event(payload);self.reload();self.open_call(call["id"])
        except Exception as exc:
            self.service.log("coligo","webhook_fout",str(exc),False);self.reload()

    def open_latest(self):
        try:
            draft=self.service.latest_draft()
            if not draft:QMessageBox.information(self,"Outlook","Er staat geen uitgaand concept klaar.");return
            path=self.service.prepare_outlook(draft["id"]);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)));self.reload()
        except Exception as exc:QMessageBox.warning(self,"Outlook",str(exc))

    def ingest_call(self):
        try:
            call=self.service.ingest_coligo(self.phone.text(),self.external_id.text(),self.line_name.text())
            self.reload();self.open_call(call["id"])
        except Exception as exc:QMessageBox.warning(self,"Coligo",str(exc))
