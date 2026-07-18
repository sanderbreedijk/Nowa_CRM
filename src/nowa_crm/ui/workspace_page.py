from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.workspace.service import WorkspaceService


class WorkspacePage(QWidget):
    def __init__(self, customers: CustomerService, service: WorkspaceService, on_proposal, parent=None):
        super().__init__(parent); self.customers=customers; self.service=service; self.on_proposal=on_proposal
        root=QVBoxLayout(self); title=QLabel("Werkruimte"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Zoeken, notities, acties en commerciële werkstromen over alle modules."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        top=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Zoek klant, contact, offerte, kluisitem, gebruiker of projecttaak…"); self.search.textChanged.connect(self.refresh_search)
        top.addWidget(self.search,1); root.addLayout(top)
        self.results=QTableWidget(0,4); self.results.setHorizontalHeaderLabels(["Soort","Resultaat","Details","Klant-ID"]); self.results.setColumnHidden(3,True); self.results.horizontalHeader().setStretchLastSection(True); root.addWidget(self.results,1)
        bar=QHBoxLayout(); bar.addWidget(QLabel("Klantcontext")); self.customer=QComboBox(); self.customer.currentIndexChanged.connect(self.refresh_context); bar.addWidget(self.customer,1)
        for text,handler in (("Offerte uit intake",self.create_proposal),("Prijsinstellingen",self.commercial_settings),("Voortgangsmail",self.progress_mail),("CSV-export",self.export_csv),("Back-up maken",self.backup)):
            button=QPushButton(text); button.clicked.connect(handler); bar.addWidget(button)
        root.addLayout(bar)
        split=QSplitter(); notes=QWidget(); nl=QVBoxLayout(notes); nl.addWidget(QLabel("Klantnotities")); self.notes=QTableWidget(0,3); self.notes.setHorizontalHeaderLabels(["Onderwerp","Notitie","Datum"]); self.notes.horizontalHeader().setStretchLastSection(True); nl.addWidget(self.notes,1)
        add_note=QPushButton("Notitie toevoegen"); add_note.clicked.connect(self.add_note); nl.addWidget(add_note)
        actions=QWidget(); al=QVBoxLayout(actions); al.addWidget(QLabel("Actiepunten")); self.actions=QTableWidget(0,6); self.actions.setHorizontalHeaderLabels(["Actie","Eigenaar","Deadline","Prioriteit","Status","ID"]); self.actions.setColumnHidden(5,True); self.actions.horizontalHeader().setStretchLastSection(True); al.addWidget(self.actions,1)
        action_bar=QHBoxLayout(); add_action=QPushButton("Actie toevoegen"); add_action.clicked.connect(self.add_action); complete=QPushButton("Markeer gereed"); complete.clicked.connect(self.complete_action); action_bar.addWidget(add_action); action_bar.addWidget(complete); action_bar.addStretch(); al.addLayout(action_bar)
        split.addWidget(notes); split.addWidget(actions); root.addWidget(split,1); self.reload_customers()

    def reload_customers(self):
        current=self.customer.currentData(); self.customer.blockSignals(True); self.customer.clear()
        for customer in self.customers.search():self.customer.addItem(f"{customer.customer_number} — {customer.name}",customer.id)
        if current:
            index=self.customer.findData(current)
            if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.refresh_context()

    def refresh_search(self,*_):
        rows=self.service.global_search(self.search.text()); self.results.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate((row["kind"],row["title"],row["detail"],row["customer_id"])):
                self.results.setItem(r,c,QTableWidgetItem(str(value or "")))

    def refresh_context(self,*_):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        notes=self.service.notes(customer_id); self.notes.setRowCount(len(notes))
        for r,row in enumerate(notes):
            for c,value in enumerate((row["subject"],row["body"],row["created_at"])):self.notes.setItem(r,c,QTableWidgetItem(str(value)))
        actions=self.service.actions(customer_id); self.actions.setRowCount(len(actions))
        for r,row in enumerate(actions):
            for c,value in enumerate((row["title"],row["owner"],row["due_date"],row["priority"],row["status"],row["id"])):self.actions.setItem(r,c,QTableWidgetItem(str(value or "")))

    def add_note(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        subject,ok=QInputDialog.getText(self,"Klantnotitie","Onderwerp")
        if not ok:return
        body,ok=QInputDialog.getMultiLineText(self,"Klantnotitie","Notitie")
        if not ok:return
        try:self.service.add_note(customer_id,subject,body); self.refresh_context()
        except Exception as exc:QMessageBox.warning(self,"Klantnotitie",str(exc))

    def add_action(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        title,ok=QInputDialog.getText(self,"Actiepunt","Actie")
        if not ok:return
        owner,ok=QInputDialog.getText(self,"Actiepunt","Eigenaar",text="NOWA")
        if not ok:return
        due,ok=QInputDialog.getText(self,"Actiepunt","Deadline (jjjj-mm-dd)")
        if not ok:return
        priority,ok=QInputDialog.getItem(self,"Actiepunt","Prioriteit",["Hoog","Normaal","Laag"],1,False)
        if not ok:return
        try:self.service.add_action(customer_id,title,owner,due,priority); self.refresh_context()
        except Exception as exc:QMessageBox.warning(self,"Actiepunt",str(exc))

    def complete_action(self):
        row=self.actions.currentRow(); item=self.actions.item(row,5) if row>=0 else None
        if item:self.service.complete_action(int(item.text())); self.refresh_context()

    def create_proposal(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        title,ok=QInputDialog.getText(self,"Offerte uit intake","Offertetitel",text="IT-modernisering")
        if not ok:return
        try:
            proposal_id=self.service.build_intake_proposal(customer_id,title); self.on_proposal(proposal_id)
        except Exception as exc:QMessageBox.warning(self,"Offerte uit intake",str(exc))

    def commercial_settings(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        current=self.service.commercial_settings(customer_id)
        rate,ok=QInputDialog.getDouble(self,"Prijsinstellingen","Uurtarief excl. btw",current["hourly_rate_cents"]/100,1,10000,2)
        if not ok:return
        discount,ok=QInputDialog.getDouble(self,"Prijsinstellingen","Klantkorting (%)",current["discount_percent"],0,100,2)
        if not ok:return
        payment,ok=QInputDialog.getInt(self,"Prijsinstellingen","Betalingstermijn (dagen)",current["payment_term_days"],1,365)
        if not ok:return
        validity,ok=QInputDialog.getInt(self,"Prijsinstellingen","Geldigheid offerte (dagen)",current["validity_days"],1,365)
        if ok:self.service.save_commercial_settings(customer_id,round(rate*100),discount,payment,validity)

    def progress_mail(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        text=self.service.progress_mail(customer_id); QApplication.clipboard().setText(text)
        dialog=QMessageBox(self); dialog.setWindowTitle("Voortgangsmail"); dialog.setText("De voortgangsmail staat op het klembord."); dialog.setDetailedText(text); dialog.exec()

    def export_csv(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        paths=self.service.export_customer_csv(customer_id); QMessageBox.information(self,"CSV-export",f"{len(paths)} bestanden opgeslagen in:\n{paths[0].parent}")

    def backup(self):
        path=self.service.backup(); QMessageBox.information(self,"Back-up gereed",f"Lokale databaseback-up gemaakt:\n{path}")
