from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFileDialog,QFormLayout,QFrame,QHBoxLayout,QInputDialog,
                               QLabel,QLineEdit,QMessageBox,QPushButton,QSpinBox,QTableWidget,QTableWidgetItem,
                               QVBoxLayout,QWidget)


class MultiUserPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent);self.service=service
        root=QVBoxLayout(self);root.setContentsMargins(28,24,28,24);root.setSpacing(14)
        title=QLabel("Multi-user en centrale server");title.setObjectName("Title");root.addWidget(title)
        sub=QLabel("Bereid NOWA CRM veilig voor op meerdere computers. De huidige SQLite-database blijft lokaal totdat de centrale servermigratie wordt uitgevoerd.")
        sub.setObjectName("Subtitle");sub.setWordWrap(True);root.addWidget(sub)
        server=QFrame();server.setObjectName("Card");form=QFormLayout(server)
        heading=QLabel("Centrale CRM-server");heading.setObjectName("SectionTitle");form.addRow(heading)
        self.host=QLineEdit();self.host.setPlaceholderText("Bijvoorbeeld crm-server of 192.168.1.20")
        self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(5432);self.database=QLineEdit("nowa_crm")
        self.tls=QCheckBox("Versleutelde TLS-verbinding verplicht");self.tls.setChecked(True)
        self.documents=QLineEdit();choose=QPushButton("Map kiezen");choose.clicked.connect(self.choose_documents)
        docs=QHBoxLayout();docs.addWidget(self.documents,1);docs.addWidget(choose)
        self.server_status=QLabel();self.server_status.setWordWrap(True)
        form.addRow("Server",self.host);form.addRow("Poort",self.port);form.addRow("Database",self.database);form.addRow(self.tls)
        form.addRow("Gedeelde documenten",docs);form.addRow("Status",self.server_status)
        row=QHBoxLayout();save=QPushButton("Profiel opslaan");save.setObjectName("Primary");save.clicked.connect(self.save)
        test=QPushButton("Verbinding testen");test.clicked.connect(self.test);snapshot=QPushButton("Migratiekopie maken");snapshot.clicked.connect(self.snapshot)
        row.addWidget(save);row.addWidget(test);row.addWidget(snapshot);form.addRow(row);root.addWidget(server)
        users=QFrame();users.setObjectName("Card");box=QVBoxLayout(users);head=QHBoxLayout()
        label=QLabel("Persoonlijke gebruikers en rollen");label.setObjectName("SectionTitle");head.addWidget(label);head.addStretch()
        add=QPushButton("+ Gebruiker");add.clicked.connect(self.add_user);toggle=QPushButton("In-/uitschakelen");toggle.clicked.connect(self.toggle_user)
        head.addWidget(add);head.addWidget(toggle);box.addLayout(head)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(["Gebruikersnaam","Naam","Rol","Actief","Laatst aangemeld","ID"]);self.table.setColumnHidden(5,True)
        self.table.horizontalHeader().setStretchLastSection(True);box.addWidget(self.table);root.addWidget(users,1);self.reload()

    def reload(self):
        settings=self.service.settings();self.host.setText(settings["host"]);self.port.setValue(int(settings["port"]))
        self.database.setText(settings["database"]);self.tls.setChecked(bool(settings["tls"]));self.documents.setText(settings["shared_documents"])
        status=self.service.readiness();state="Gereed voor servermigratie" if status["ready"] else "Nog niet gereed"
        details="\n".join("• "+item for item in status["issues"]) or "• Lokale broncontrole geslaagd"
        self.server_status.setText(f"{state} · {status['customers']} klanten · {status['users']} gebruikers\n{details}")
        rows=self.service.users();self.table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            values=(item["username"],item["display_name"],self.service.ROLES.get(item["role"],item["role"]),
                    "Ja" if item["active"] else "Nee",item["last_login_at"],item["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))

    def choose_documents(self):
        folder=QFileDialog.getExistingDirectory(self,"Gedeelde documentenmap kiezen",self.documents.text())
        if folder:self.documents.setText(folder)

    def save(self):
        try:self.service.save(self.host.text(),self.port.value(),self.database.text(),self.tls.isChecked(),self.documents.text());self.reload()
        except Exception as exc:QMessageBox.warning(self,"Serverprofiel",str(exc))

    def test(self):
        result=self.service.test_server(self.host.text(),self.port.value())
        self.server_status.setText(result["detail"]);QMessageBox.information(self,"Verbindingstest",result["detail"])

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
