from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from nowa_crm.modules.migration.service import LegacyImportService


class MigrationPage(QWidget):
    def __init__(self, service: LegacyImportService, refresh, parent=None):
        super().__init__(parent); self.service=service; self.refresh=refresh; self.source=None; self.key=None
        root=QVBoxLayout(self); title=QLabel("Oude Workspace importeren"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Bekijk eerst wat er wordt gevonden. Voor de echte import maakt NOWA automatisch een lokale back-up."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        choose=QPushButton("Selecteer nowa_workspace.sqlite3"); choose.setObjectName("Primary"); choose.clicked.connect(self.choose_source); root.addWidget(choose)
        key=QPushButton("Selecteer oude secret.key (optioneel)"); key.clicked.connect(self.choose_key); root.addWidget(key)
        self.summary=QTextEdit(); self.summary.setReadOnly(True); root.addWidget(self.summary,1)
        self.run=QPushButton("Import starten"); self.run.setEnabled(False); self.run.clicked.connect(self.import_data); root.addWidget(self.run)

    def choose_source(self):
        name,_=QFileDialog.getOpenFileName(self,"Oude NOWA-database selecteren","","SQLite-database (*.sqlite3 *.db);;Alle bestanden (*)")
        if name:self.source=Path(name); self.preview()

    def choose_key(self):
        name,_=QFileDialog.getOpenFileName(self,"Oude secret.key selecteren","","Sleutelbestand (*.key);;Alle bestanden (*)")
        if name:self.key=Path(name); self.preview()

    def preview(self):
        if not self.source:return
        try:
            data=self.service.preview(self.source,self.key); lines=[f"Bron: {data['source']}","",f"Totaal gevonden: {data['total']}",""]
            lines.extend(f"{name}: {amount}" for name,amount in data["counts"].items())
            if data["warnings"]:lines+=["","Let op:",*data["warnings"]]
            self.summary.setPlainText("\n".join(lines)); self.run.setEnabled(True)
        except Exception as exc:self.summary.setPlainText(str(exc)); self.run.setEnabled(False)

    def import_data(self):
        if QMessageBox.question(self,"Import bevestigen","Importeren nadat automatisch een lokale back-up is gemaakt?")!=QMessageBox.Yes:return
        try:
            report=self.service.import_database(self.source,self.key); created=sum(report["created"].values()); skipped=sum(report["skipped"].values())
            text=f"Import gereed.\n\nNieuw: {created}\nOvergeslagen: {skipped}\nBack-up: {report['backup']}"
            if report["warnings"]:text+="\n\nWaarschuwingen:\n"+"\n".join(report["warnings"])
            self.summary.setPlainText(text); self.refresh(); QMessageBox.information(self,"Import gereed",text)
        except Exception as exc:QMessageBox.critical(self,"Import mislukt",str(exc))
