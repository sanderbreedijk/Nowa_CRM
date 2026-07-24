from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QFileDialog,QFormLayout,QFrame,QHBoxLayout,QInputDialog,
                               QLabel,QLineEdit,QMessageBox,QPushButton,QSpinBox,QTableWidget,QTableWidgetItem,
                               QVBoxLayout,QWidget)


class MultiUserPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent);self.service=service
        root=QVBoxLayout(self);root.setContentsMargins(28,24,28,24);root.setSpacing(14)
        title=QLabel("Multi-user en centrale server");title.setObjectName("Title");root.addWidget(title)
        sub=QLabel("Laat één vaste computer de centrale database beheren en verbind andere werkplekken veilig met persoonlijke aanmeldingen.")
        sub.setObjectName("Subtitle");sub.setWordWrap(True);root.addWidget(sub)

        server=QFrame();server.setObjectName("Card");form=QFormLayout(server)
        heading=QLabel("Centrale CRM-server");heading.setObjectName("SectionTitle");form.addRow(heading)
        self.host=QLineEdit();self.host.setPlaceholderText("Naam of IP-adres van de vaste servercomputer")
        self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(5088)
        self.database=QLineEdit("nowa_crm")
        self.access_key=QLineEdit();self.access_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_key.setPlaceholderText("Dezelfde sleutel op server en alle werkplekken")
        self.encryption=QCheckBox("Applicatieverkeer volledig versleutelen");self.encryption.setChecked(True);self.encryption.setEnabled(False)
        self.server_enabled=QCheckBox("Deze computer is de centrale server")
        self.documents=QLineEdit();choose=QPushButton("Map kiezen");choose.clicked.connect(self.choose_documents)
        docs=QHBoxLayout();docs.addWidget(self.documents,1);docs.addWidget(choose)
        self.server_status=QLabel();self.server_status.setWordWrap(True)
        form.addRow("Servernaam / IP",self.host);form.addRow("Poort",self.port);form.addRow("Database",self.database)
        form.addRow("Toegangssleutel",self.access_key);form.addRow(self.encryption);form.addRow(self.server_enabled)
        form.addRow("Gedeelde documenten",docs);form.addRow("Status",self.server_status)

        row=QHBoxLayout();save=QPushButton("Instellingen opslaan");save.setObjectName("Primary");save.clicked.connect(self.save)
        start=QPushButton("Server starten");start.clicked.connect(self.start_server)
        test=QPushButton("Verbinding testen");test.clicked.connect(self.test)
        row.addWidget(save);row.addWidget(start);row.addWidget(test);form.addRow(row)
        migration=QHBoxLayout();copy=QPushButton("Veilige migratiekopie");copy.clicked.connect(self.snapshot)
        transfer=QPushButton("Lokale gegevens naar server");transfer.clicked.connect(self.migrate)
        activate=QPushButton("Deze werkplek centraal zetten");activate.setObjectName("Primary");activate.clicked.connect(self.activate)
        local=QPushButton("Lokale modus herstellen");local.clicked.connect(self.restore_local)
        migration.addWidget(copy);migration.addWidget(transfer);migration.addWidget(activate);migration.addWidget(local)
        form.addRow(migration);root.addWidget(server)

        users=QFrame();users.setObjectName("Card");box=QVBoxLayout(users);head=QHBoxLayout()
        label=QLabel("Persoonlijke gebruikers en rollen");label.setObjectName("SectionTitle");head.addWidget(label);head.addStretch()
        add=QPushButton("+ Gebruiker");add.clicked.connect(self.add_user)
        toggle=QPushButton("In-/uitschakelen");toggle.clicked.connect(self.toggle_user)
        head.addWidget(add);head.addWidget(toggle);box.addLayout(head)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(["Gebruikersnaam","Naam","Rol","Actief","Laatst aangemeld","ID"])
        self.table.setColumnHidden(5,True);self.table.horizontalHeader().setStretchLastSection(True);box.addWidget(self.table)
        root.addWidget(users,1);self.reload()

    def reload(self):
        settings=self.service.settings();self.host.setText(settings["host"]);self.port.setValue(int(settings["port"]))
        self.database.setText(settings["database"]);self.documents.setText(settings["shared_documents"])
        self.access_key.setText(settings.get("access_key",""));self.server_enabled.setChecked(bool(settings.get("server_enabled",False)))
        status=self.service.readiness();state="Gereed" if status["ready"] else "Aandacht nodig"
        details="\n".join("• "+item for item in status["issues"]) or "• Databasecontrole geslaagd"
        mode="Centrale database actief" if status.get("remote") else ("Servercomputer" if settings.get("server_enabled") else "Lokale werkplek")
        self.server_status.setText(f"{mode} · {state} · {status['customers']} klanten · {status['users']} gebruikers\n{details}")
        rows=self.service.users();self.table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            values=(item["username"],item["display_name"],self.service.ROLES.get(item["role"],item["role"]),
                    "Ja" if item["active"] else "Nee",item["last_login_at"],item["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))

    def choose_documents(self):
        folder=QFileDialog.getExistingDirectory(self,"Gedeelde documentenmap kiezen",self.documents.text())
        if folder:self.documents.setText(folder)

    def save(self):
        try:
            mode=self.service.settings().get("mode","local")
            self.service.save(self.host.text(),self.port.value(),self.database.text(),True,self.documents.text(),
                              self.access_key.text(),self.server_enabled.isChecked(),mode);self.reload()
            return True
        except Exception as exc:QMessageBox.warning(self,"Serverinstellingen",str(exc));return False

    def test(self):
        result=self.service.test_server(self.host.text(),self.port.value(),access_key=self.access_key.text())
        self.server_status.setText(result["detail"]);QMessageBox.information(self,"Verbindingstest",result["detail"])

    def start_server(self):
        if not self.save():return
        try:
            self.service.start_server("0.0.0.0",self.port.value(),self.access_key.text())
            QMessageBox.information(self,"Centrale server",
                f"De centrale database is actief op poort {self.port.value()}.\n\nLaat NOWA CRM op deze computer geopend.")
        except Exception as exc:QMessageBox.warning(self,"Centrale server",str(exc))

    def migrate(self):
        if QMessageBox.question(self,"Gegevens overzetten",
            "De huidige lokale database wordt veilig naar de centrale server gekopieerd.\n\n"
            "Zorg dat andere gebruikers NOWA CRM hebben gesloten. Doorgaan?")!=QMessageBox.StandardButton.Yes:return
        try:
            result=self.service.migrate_to_server()
            QMessageBox.information(self,"Migratie voltooid",
                f"Alle lokale gegevens staan nu op de centrale server.\n\nLokale herstelkopie:\n{result['snapshot']}")
        except Exception as exc:QMessageBox.warning(self,"Gegevens overzetten",str(exc))

    def activate(self):
        result=self.service.test_server(self.host.text(),self.port.value(),access_key=self.access_key.text())
        if not result["reachable"]:QMessageBox.warning(self,"Centrale werkplek",result["detail"]);return
        if not self.save():return
        self.service.activate_client(True)
        QMessageBox.information(self,"Centrale werkplek","Centrale modus is ingesteld. Sluit NOWA CRM en start het opnieuw.")

    def restore_local(self):
        self.service.activate_client(False)
        QMessageBox.information(self,"Lokale werkplek","Lokale modus is hersteld. Start NOWA CRM opnieuw.")

    def snapshot(self):
        try:
            result=self.service.migration_snapshot();QDesktopServices.openUrl(QUrl.fromLocalFile(str(result["backup"].parent)))
            QMessageBox.information(self,"Migratiekopie gereed",f"Gecontroleerde lokale migratiekopie:\n\n{result['backup']}\n\nDeze bevat klantgegevens en mag nooit naar GitHub.")
        except Exception as exc:QMessageBox.warning(self,"Migratiekopie",str(exc))

    def add_user(self):
        username,ok=QInputDialog.getText(self,"Nieuwe gebruiker","Gebruikersnaam")
        if not ok:return
        name,ok=QInputDialog.getText(self,"Nieuwe gebruiker","Volledige naam")
        if not ok:return
        role_label,ok=QInputDialog.getItem(self,"Nieuwe gebruiker","Rol",list(self.service.ROLES.values()),0,False)
        if not ok:return
        password,ok=QInputDialog.getText(self,"Nieuwe gebruiker","Tijdelijk wachtwoord (minimaal 10 tekens)",QLineEdit.EchoMode.Password)
        if not ok:return
        role=next(key for key,value in self.service.ROLES.items() if value==role_label)
        try:self.service.create_user(username,name,password,role);self.reload()
        except Exception as exc:QMessageBox.warning(self,"Nieuwe gebruiker",str(exc))

    def toggle_user(self):
        row=self.table.currentRow()
        if row<0:QMessageBox.information(self,"Gebruikers","Selecteer eerst een gebruiker.");return
        try:self.service.set_user_active(int(self.table.item(row,5).text()),self.table.item(row,3).text()!="Ja");self.reload()
        except Exception as exc:QMessageBox.warning(self,"Gebruikers",str(exc))

