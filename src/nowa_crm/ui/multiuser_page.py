from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFileDialog,QFormLayout,QFrame,QHBoxLayout,QInputDialog,
                               QLabel,QLineEdit,QMessageBox,QPushButton,QScrollArea,QSpinBox,QTableWidget,QTableWidgetItem,
                               QVBoxLayout,QWidget)


class MultiUserPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent);self.service=service
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        content=QWidget();root=QVBoxLayout(content);root.setContentsMargins(28,24,28,24);root.setSpacing(14)
        scroll.setWidget(content);outer.addWidget(scroll)
        title=QLabel("Multi-user en Synology");title.setObjectName("Title");root.addWidget(title)
        sub=QLabel("Verbind iedere werkplek rechtstreeks met PostgreSQL op de Synology NAS en gebruik persoonlijke aanmeldingen.")
        sub.setObjectName("Subtitle");sub.setWordWrap(True);root.addWidget(sub)

        users=QFrame();users.setObjectName("Card");box=QVBoxLayout(users);head=QHBoxLayout()
        label=QLabel("Persoonlijke gebruikers en rollen");label.setObjectName("SectionTitle");head.addWidget(label);head.addStretch()
        add=QPushButton("+ Gebruiker");add.clicked.connect(self.add_user)
        toggle=QPushButton("In-/uitschakelen");toggle.clicked.connect(self.toggle_user)
        head.addWidget(add);head.addWidget(toggle);box.addLayout(head)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(["Gebruikersnaam","Naam","Rol","Actief","Laatst aangemeld","ID"])
        self.table.setColumnHidden(5,True);self.table.horizontalHeader().setStretchLastSection(True);box.addWidget(self.table)
        postgres=QFrame();postgres.setObjectName("Card");pg=QFormLayout(postgres)
        pg_title=QLabel("Synology PostgreSQL");pg_title.setObjectName("SectionTitle");pg.addRow(pg_title)
        pg_info=QLabel("Centrale database voor meerdere gelijktijdige werkplekken. De lokale database blijft als herstelkopie beschikbaar.")
        pg_info.setWordWrap(True);pg.addRow(pg_info)
        self.pg_host=QLineEdit();self.pg_host.setPlaceholderText("IP-adres van de Synology NAS")
        self.pg_port=QSpinBox();self.pg_port.setRange(1,65535);self.pg_port.setValue(55432)
        self.pg_database=QLineEdit("nowa_crm");self.pg_user=QLineEdit("nowa_crm")
        self.pg_password=QLineEdit();self.pg_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.pg_password.setPlaceholderText("Leeg laten om het opgeslagen wachtwoord te behouden")
        self.pg_ssl=QComboBox();self.pg_ssl.addItems(["prefer","require","disable"])
        self.documents=QLineEdit();choose=QPushButton("Map kiezen");choose.clicked.connect(self.choose_documents)
        docs=QHBoxLayout();docs.addWidget(self.documents,1);docs.addWidget(choose)
        pg.addRow("NAS-adres",self.pg_host);pg.addRow("Poort",self.pg_port);pg.addRow("Database",self.pg_database)
        pg.addRow("Gebruikersnaam",self.pg_user);pg.addRow("Wachtwoord",self.pg_password);pg.addRow("Versleuteling",self.pg_ssl)
        pg.addRow("Gedeelde documenten",docs)
        self.pg_status=QLabel("Nog niet gecontroleerd");self.pg_status.setWordWrap(True);pg.addRow("Status",self.pg_status)
        pg_buttons=QHBoxLayout()
        pg_save=QPushButton("Opslaan & testen");pg_save.clicked.connect(self.save_postgres)
        pg_migrate=QPushButton("Gegevens veilig overzetten");pg_migrate.setObjectName("Primary");pg_migrate.clicked.connect(self.migrate_postgres)
        pg_activate=QPushButton("PostgreSQL activeren");pg_activate.clicked.connect(self.activate_postgres)
        pg_buttons.addWidget(pg_save);pg_buttons.addWidget(pg_migrate);pg_buttons.addWidget(pg_activate);pg.addRow(pg_buttons)
        self.sqlite_source=QLineEdit();self.sqlite_source.setReadOnly(True)
        self.sqlite_source.setPlaceholderText("Kies de oude nowa.sqlite3")
        choose_sqlite=QPushButton("Database kiezen");choose_sqlite.clicked.connect(self.choose_sqlite)
        source_row=QHBoxLayout();source_row.addWidget(self.sqlite_source,1);source_row.addWidget(choose_sqlite)
        pg.addRow("Handmatige import",source_row)
        import_sqlite=QPushButton("Gekozen SQLite-database importeren")
        import_sqlite.setObjectName("Primary");import_sqlite.clicked.connect(self.import_sqlite)
        pg.addRow(import_sqlite)
        root.insertWidget(2,postgres)
        root.addWidget(users,1);self.reload()

    def reload(self):
        settings=self.service.settings();self.documents.setText(settings["shared_documents"])
        self.pg_host.setText(settings.get("host",""));self.pg_port.setValue(int(settings.get("port",55432)))
        self.pg_database.setText(settings.get("database","nowa_crm"));self.pg_user.setText(settings.get("postgres_user","nowa_crm"))
        self.pg_ssl.setCurrentText(settings.get("sslmode","prefer"))
        if settings.get("mode")=="postgres":
            try:
                counts=self.service.database_contents(self.service.db)
                self.pg_status.setText(
                    f"PostgreSQL actief · {counts['customers']} klanten ({counts['active_customers']} actief) · "
                    f"{counts['proposals']} offertes · {counts['proposal_lines']} offerteregels")
            except Exception as exc:self.pg_status.setText(f"PostgreSQL ingesteld, inhoudscontrole mislukt: {exc}")
        elif settings.get("postgres_password"):self.pg_status.setText("Instellingen opgeslagen; klaar voor verbindingstest of migratie.")
        rows=self.service.users();self.table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            values=(item["username"],item["display_name"],self.service.ROLES.get(item["role"],item["role"]),
                    "Ja" if item["active"] else "Nee",item["last_login_at"],item["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))

    def choose_documents(self):
        folder=QFileDialog.getExistingDirectory(self,"Gedeelde documentenmap kiezen",self.documents.text())
        if folder:self.documents.setText(folder)

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

    def save_postgres(self):
        try:
            self.service.save_postgres(self.pg_host.text(),self.pg_port.value(),self.pg_database.text(),
                                       self.pg_user.text(),self.pg_password.text(),self.pg_ssl.currentText())
            self.service.save_shared_documents(self.documents.text())
            result=self.service.test_postgres(self.pg_host.text(),self.pg_port.value(),self.pg_database.text(),
                                              self.pg_user.text(),self.pg_password.text(),self.pg_ssl.currentText())
            self.pg_status.setText(result["detail"])
            if result["reachable"]:
                self.pg_password.clear()
                QMessageBox.information(self,"Synology PostgreSQL",result["detail"])
            else:QMessageBox.warning(self,"Synology PostgreSQL",result["detail"])
            return result["reachable"]
        except Exception as exc:QMessageBox.warning(self,"Synology PostgreSQL",str(exc));return False

    def migrate_postgres(self):
        if not self.save_postgres():return
        if QMessageBox.question(self,"Migreren naar Synology",
            "NOWA CRM maakt eerst een lokale herstelkopie en zet daarna alle tabellen over.\n"
            "Aantallen worden gecontroleerd voordat activeren mogelijk is.\n\nDoorgaan?")!=QMessageBox.StandardButton.Yes:return
        try:
            result=self.service.migrate_to_postgres()
            self.pg_status.setText(f"Migratie gecontroleerd · {result['tables']} tabellen · {result['rows']} rijen")
            QMessageBox.information(self,"Migratie voltooid",
                f"Alle gegevens zijn gecontroleerd overgezet.\n\n{result['tables']} tabellen · {result['rows']} rijen\n"
                f"Lokale herstelkopie:\n{result['backup']}\n\nKlik nu op PostgreSQL activeren.")
        except Exception as exc:QMessageBox.critical(self,"Migratie niet geactiveerd",
            f"{exc}\n\nDe lokale database is actief gebleven.")

    def choose_sqlite(self):
        default=str(self.service.root/"nowa.sqlite3")
        filename,_=QFileDialog.getOpenFileName(self,"Oude NOWA CRM-database kiezen",default,
                                                "SQLite-databases (*.sqlite3 *.sqlite *.db)")
        if filename:self.sqlite_source.setText(filename)

    def import_sqlite(self):
        source=self.sqlite_source.text().strip()
        if not source:QMessageBox.information(self,"Handmatige import","Kies eerst de oude SQLite-database.");return
        if not self.save_postgres():return
        if QMessageBox.question(self,"Handmatige database-import",
            "De gekozen oude database wordt als bron gebruikt.\n\n"
            "Bestaande centrale gebruikers en hun wachtwoorden blijven behouden. "
            "De PostgreSQL-gegevens worden gecontroleerd opnieuw gevuld en de bron wordt niet verwijderd.\n\n"
            "Doorgaan?")!=QMessageBox.StandardButton.Yes:return
        try:
            result=self.service.import_sqlite_to_postgres(source)
            self.pg_status.setText(f"Handmatige import gecontroleerd · {result['tables']} tabellen · {result['rows']} rijen")
            QMessageBox.information(self,"Handmatige import voltooid",
                f"De oude database is volledig gecontroleerd overgezet.\n\n"
                f"Bron: {result['source']}\nKlanten: {result['source_customers']}\n"
                f"In PostgreSQL: {result['target_customers']} klanten ({result['target_active_customers']} actief), "
                f"{result['target_proposals']} offertes en {result['target_proposal_lines']} offerteregels\n"
                f"Tabellen: {result['tables']}\nRijen: {result['rows']}\n"
                f"Centrale gebruikers behouden: {result['central_users_preserved']}\n\n"
                f"Lokale herstelkopie:\n{result['backup']}\n\n"
                "Klik nu op PostgreSQL activeren.")
        except Exception as exc:
            QMessageBox.critical(self,"Handmatige import niet uitgevoerd",
                f"{exc}\n\nDe gekozen SQLite-database is niet verwijderd en PostgreSQL is niet geactiveerd.")

    def activate_postgres(self):
        try:
            self.service.activate_postgres()
            QMessageBox.information(self,"PostgreSQL actief",
                "De Synology-database is ingesteld. Sluit NOWA CRM en start het opnieuw.")
        except Exception as exc:QMessageBox.warning(self,"PostgreSQL activeren",str(exc))

    def toggle_user(self):
        row=self.table.currentRow()
        if row<0:QMessageBox.information(self,"Gebruikers","Selecteer eerst een gebruiker.");return
        try:self.service.set_user_active(int(self.table.item(row,5).text()),self.table.item(row,3).text()!="Ja");self.reload()
        except Exception as exc:QMessageBox.warning(self,"Gebruikers",str(exc))

