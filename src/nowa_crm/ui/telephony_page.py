from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.telephony.service import TelephonyService


class TelephonyPage(QWidget):
    def __init__(self, customers: CustomerService, service: TelephonyService, open_customer, open_vault, parent=None):
        super().__init__(parent); self.customers=customers; self.service=service; self.open_customer=open_customer; self.open_vault=open_vault; self.call_id=None
        root=QVBoxLayout(self); title=QLabel("Telefonie en Coligo"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Herken inkomende nummers, open direct het klantdossier of de IT-kluis en registreer het gesprek."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        lookup=QHBoxLayout(); self.phone=QLineEdit(); self.phone.setPlaceholderText("Telefoonnummer uit Coligo of handmatigâ€¦"); self.phone.returnPressed.connect(self.incoming_call)
        incoming=QPushButton("Inkomend gesprek"); incoming.setObjectName("Primary"); incoming.clicked.connect(self.incoming_call)
        outgoing=QPushButton("Uitgaand gesprek"); outgoing.clicked.connect(lambda:self.start_call("uitgaand"))
        lookup.addWidget(self.phone,1); lookup.addWidget(incoming); lookup.addWidget(outgoing); root.addLayout(lookup)
        self.match=QLabel("Nog geen actief gesprek."); self.match.setWordWrap(True); self.match.setStyleSheet("font-size:16px;font-weight:700;color:#0B2342"); root.addWidget(self.match)
        quick=QHBoxLayout(); dossier=QPushButton("Open klantdossier"); dossier.clicked.connect(self._open_customer); vault=QPushButton("Open IT-kluis"); vault.clicked.connect(self._open_vault); link=QPushButton("Koppel aan klant"); link.clicked.connect(self.link_customer)
        quick.addWidget(dossier); quick.addWidget(vault); quick.addWidget(link); quick.addStretch(); root.addLayout(quick)
        split=QSplitter(); formbox=QWidget(); form=QFormLayout(formbox); self.subject=QLineEdit(); self.notes=QTextEdit(); self.outcome=QComboBox(); self.outcome.addItems(["Beantwoord","Informatie verstrekt","Afspraak gemaakt","Doorgezet","Geen gehoor","Overig"])
        self.callback=QCheckBox("Terugbelactie maken"); self.callback_due=QLineEdit(); self.callback_due.setPlaceholderText("jjjj-mm-dd")
        form.addRow("Onderwerp",self.subject); form.addRow("Gespreksnotitie",self.notes); form.addRow("Resultaat",self.outcome); form.addRow("",self.callback); form.addRow("Terugbeldatum",self.callback_due)
        finish=QPushButton("Gesprek afronden"); finish.setObjectName("Primary"); finish.clicked.connect(self.finish); form.addRow("",finish)
        historybox=QWidget(); hl=QVBoxLayout(historybox); searchrow=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Zoek gesprekkenâ€¦"); self.search.textChanged.connect(self.refresh_history); self.filter_customer=QComboBox(); self.filter_customer.currentIndexChanged.connect(self.refresh_history); searchrow.addWidget(self.search,1); searchrow.addWidget(self.filter_customer); hl.addLayout(searchrow)
        self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(["Datum","Klant","Contact","Richting","Nummer","Onderwerp","Resultaat","ID"]); self.table.setColumnHidden(7,True); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.load_selected); hl.addWidget(self.table)
        split.addWidget(formbox); split.addWidget(historybox); split.setSizes([430,850]); root.addWidget(split,1); self.reload_customers()

    def reload_customers(self):
        current=self.filter_customer.currentData(); self.filter_customer.blockSignals(True); self.filter_customer.clear(); self.filter_customer.addItem("Alle klanten",None)
        for customer in self.customers.search():self.filter_customer.addItem(f"{customer.customer_number} â€” {customer.name}",customer.id)
        if current:
            index=self.filter_customer.findData(current)
            if index>=0:self.filter_customer.setCurrentIndex(index)
        self.filter_customer.blockSignals(False); self.refresh_history()

    def incoming_call(self):self.start_call("inkomend")

    def start_call(self,direction):
        if not self.phone.text().strip():return
        try:
            self.call_id=self.service.register_call(self.phone.text(),direction); call=self.service.get(self.call_id)
            contact=f" Â· {call['contact_name']}" if call["contact_name"] else ""
            self.match.setText(f"{call['customer_name']}{contact}\n{call['phone_number']}")
            self.subject.clear(); self.notes.clear(); self.callback.setChecked(False); self.refresh_history()
        except Exception as exc:QMessageBox.warning(self,"Telefonie",str(exc))

    def finish(self):
        if not self.call_id:QMessageBox.information(self,"Telefonie","Start of selecteer eerst een gesprek."); return
        try:
            self.service.finish_call(self.call_id,self.subject.text(),self.notes.toPlainText(),self.outcome.currentText(),self.callback.isChecked(),self.callback_due.text())
            self.match.setText("Gesprek afgerond en lokaal geregistreerd."); self.call_id=None; self.refresh_history()
        except Exception as exc:QMessageBox.warning(self,"Gesprek afronden",str(exc))

    def link_customer(self):
        if not self.call_id:return
        customers=self.customers.search(); labels=[f"{x.customer_number} â€” {x.name}" for x in customers]
        if not customers:QMessageBox.information(self,"Gesprek koppelen","Er zijn nog geen klanten om te koppelen."); return
        label,ok=QInputDialog.getItem(self,"Gesprek koppelen","Klant",labels,0,False)
        if ok:
            customer=customers[labels.index(label)]; self.service.link_customer(self.call_id,customer.id); self.match.setText(f"{customer.name}\n{self.phone.text()}"); self.refresh_history()

    def refresh_history(self,*_):
        rows=self.service.history(self.filter_customer.currentData(),self.search.text()); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["started_at"],row["customer_name"],row["contact_name"],row["direction"],row["phone_number"],row["subject"],row["outcome"],row["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))

    def load_selected(self,*_):
        row=self.table.currentRow(); item=self.table.item(row,7) if row>=0 else None
        if not item:return
        self.call_id=int(item.text()); call=self.service.get(self.call_id); self.phone.setText(call["phone_number"]); self.subject.setText(call["subject"]); self.notes.setPlainText(call["notes"]); self.outcome.setCurrentText(call["outcome"] or "Beantwoord")
        self.match.setText(f"{call['customer_name']} Â· {call['contact_name']}\n{call['phone_number']}")

    def _open_customer(self):
        call=self.service.get(self.call_id) if self.call_id else None
        if call and call["customer_id"]:self.open_customer(call["customer_id"])

    def _open_vault(self):
        if self.phone.text().strip():self.open_vault(self.phone.text())

