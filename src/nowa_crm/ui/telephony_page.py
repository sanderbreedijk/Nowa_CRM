from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.telephony.service import TelephonyService


class TelephonyPage(QWidget):
    call_started=Signal(int)
    call_finished=Signal(int,dict)
    def __init__(self, customers: CustomerService, service: TelephonyService, open_customer, open_vault, create_ticket=None, parent=None):
        super().__init__(parent); self.customers=customers; self.service=service; self.open_customer=open_customer; self.open_vault=open_vault; self.call_id=None
        self.create_ticket=create_ticket
        root=QVBoxLayout(self); title=QLabel("Telefonie en Coligo"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Herken inkomende nummers, open direct het klantdossier of de IT-kluis en registreer het gesprek."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        lookup=QHBoxLayout(); self.phone=QLineEdit(); self.phone.setPlaceholderText("Telefoonnummer uit Coligo of handmatig…"); self.phone.returnPressed.connect(self.incoming_call)
        incoming=QPushButton("Inkomend gesprek"); incoming.setObjectName("Primary"); incoming.clicked.connect(self.incoming_call)
        outgoing=QPushButton("Uitgaand gesprek"); outgoing.clicked.connect(lambda:self.start_call("uitgaand"))
        missed=QPushButton("Gemiste oproep");missed.clicked.connect(self.missed_call)
        lookup.addWidget(self.phone,1); lookup.addWidget(incoming); lookup.addWidget(outgoing);lookup.addWidget(missed); root.addLayout(lookup)
        self.match=QLabel("Nog geen actief gesprek."); self.match.setWordWrap(True); self.match.setStyleSheet("font-size:16px;font-weight:700;color:#0B2342"); root.addWidget(self.match)
        self.briefing=QLabel("Klantcontext verschijnt hier zodra het nummer is herkend.");self.briefing.setObjectName("CallBriefing")
        self.briefing.setWordWrap(True);root.addWidget(self.briefing)
        quick=QHBoxLayout(); dossier=QPushButton("Open klantdossier"); dossier.clicked.connect(self._open_customer); vault=QPushButton("Open IT-kluis"); vault.clicked.connect(self._open_vault); link=QPushButton("Onbekend nummer toevoegen"); link.clicked.connect(self.link_customer)
        ticket=QPushButton("Maak serviceticket");ticket.clicked.connect(self.create_call_ticket)
        quick.addWidget(dossier); quick.addWidget(vault); quick.addWidget(link);quick.addWidget(ticket); quick.addStretch(); root.addLayout(quick)
        split=QSplitter(); formbox=QWidget(); form=QFormLayout(formbox); self.subject=QLineEdit(); self.notes=QTextEdit(); self.outcome=QComboBox(); self.outcome.addItems(["Beantwoord","Informatie verstrekt","Afspraak gemaakt","Doorgezet","Geen gehoor","Overig"])
        self.priority=QComboBox();self.priority.addItems(["Laag","Normaal","Hoog","Kritiek"]);self.assigned=QLineEdit();self.assigned.setText(self.service.actor)
        self.callback=QCheckBox("Terugbelactie maken"); self.callback_due=QLineEdit(); self.callback_due.setPlaceholderText("jjjj-mm-dd")
        form.addRow("Onderwerp",self.subject); form.addRow("Gespreksnotitie",self.notes); form.addRow("Resultaat",self.outcome);form.addRow("Prioriteit",self.priority);form.addRow("Toegewezen aan",self.assigned); form.addRow("",self.callback); form.addRow("Terugbeldatum",self.callback_due)
        finish=QPushButton("Gesprek afronden"); finish.setObjectName("Primary"); finish.clicked.connect(self.finish); form.addRow("",finish)
        historybox=QWidget(); hl=QVBoxLayout(historybox); searchrow=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Zoek gesprekken…"); self.search.textChanged.connect(self.refresh_history); self.queue=QComboBox()
        for label,value in (("Alle gesprekken","alle"),("Terugbellen","terugbellen"),("Gemist","gemist"),("Onbekend","onbekend")):self.queue.addItem(label,value)
        self.queue.currentIndexChanged.connect(self.refresh_history);self.filter_customer=QComboBox(); self.filter_customer.currentIndexChanged.connect(self.refresh_history);self.queue_status=QLabel(); searchrow.addWidget(self.search,1);searchrow.addWidget(self.queue); searchrow.addWidget(self.filter_customer);searchrow.addWidget(self.queue_status); hl.addLayout(searchrow)
        self.table=QTableWidget(0,12); self.table.setHorizontalHeaderLabels(["Datum","Klant","Contact","Richting","Nummer","Duur","Status","Prioriteit","Terugbellen","Toegewezen","Onderwerp","ID"]); self.table.setColumnHidden(11,True); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.load_selected); hl.addWidget(self.table)
        callback_done=QPushButton("Terugbelactie afronden");callback_done.clicked.connect(self.complete_callback);hl.addWidget(callback_done)
        split.addWidget(formbox); split.addWidget(historybox); split.setSizes([430,850]); root.addWidget(split,1); self.reload_customers()

    def reload_customers(self):
        current=self.filter_customer.currentData(); self.filter_customer.blockSignals(True); self.filter_customer.clear(); self.filter_customer.addItem("Alle klanten",None)
        for customer in self.customers.search():self.filter_customer.addItem(f"{customer.customer_number} — {customer.name}",customer.id)
        if current:
            index=self.filter_customer.findData(current)
            if index>=0:self.filter_customer.setCurrentIndex(index)
        self.filter_customer.blockSignals(False); self.refresh_history()

    def incoming_call(self):self.start_call("inkomend")

    def missed_call(self):
        if not self.phone.text().strip():return
        try:
            self.call_id=self.service.mark_missed(self.phone.text());call=self.service.get(self.call_id)
            self.match.setText(f"Gemiste oproep: {call['customer_name']}\n{call['phone_number']}")
            self.show_briefing(call)
            self.refresh_history()
        except Exception as exc:QMessageBox.warning(self,"Gemiste oproep",str(exc))

    def start_call(self,direction):
        if not self.phone.text().strip():return
        try:
            recognition=self.service.recognize(self.phone.text())
            self.call_id=self.service.register_call(self.phone.text(),direction)
            if len(recognition.get("matches",[]))>1 and not self.choose_recognized_customer(recognition["matches"]):
                self.match.setText(f"Meerdere klanten gevonden · nog niet gekozen\n{self.phone.text()}")
            call=self.service.get(self.call_id)
            contact=f" · {call['contact_name']}" if call["contact_name"] else ""
            self.match.setText(f"{call['customer_name']}{contact}\n{call['phone_number']}")
            self.show_briefing(call)
            self.subject.clear(); self.notes.clear(); self.callback.setChecked(False); self.refresh_history()
            self.call_started.emit(self.call_id)
        except Exception as exc:QMessageBox.warning(self,"Telefonie",str(exc))

    def finish(self):
        if not self.call_id:QMessageBox.information(self,"Telefonie","Start of selecteer eerst een gesprek."); return
        try:
            call_id=self.call_id
            self.service.finish_call(call_id,self.subject.text(),self.notes.toPlainText(),self.outcome.currentText(),self.callback.isChecked(),self.callback_due.text(),self.priority.currentText(),self.assigned.text())
            saved=self.service.get(call_id);self.match.setText("Gesprek afgerond en lokaal geregistreerd.")
            self.call_id=None;self.phone.clear();self.subject.clear();self.notes.clear();self.callback.setChecked(False);self.callback_due.clear();self.refresh_history()
            self.call_finished.emit(call_id,saved or {})
        except Exception as exc:QMessageBox.warning(self,"Gesprek afronden",str(exc))

    def link_customer(self):
        if not self.call_id:return
        customers=self.customers.search(); labels=[f"{x.customer_number} — {x.name}" for x in customers]
        if not customers:QMessageBox.information(self,"Gesprek koppelen","Er zijn nog geen klanten om te koppelen."); return
        label,ok=QInputDialog.getItem(self,"Gesprek koppelen","Klant",labels,0,False)
        if not ok:return
        name,ok=QInputDialog.getText(self,"Onbekend nummer toevoegen","Naam of herkenbare omschrijving")
        if not ok or not name.strip():return
        description,ok=QInputDialog.getText(self,"Onbekend nummer toevoegen","Functie / toelichting (optioneel)")
        if not ok:return
        customer=customers[labels.index(label)]
        self.service.link_customer(self.call_id,customer.id,contact_name=name,description=description)
        self.match.setText(f"{customer.name} · {name}\n{self.phone.text()}");self.refresh_history()
        QMessageBox.information(self,"Nummer opgeslagen",f"{self.phone.text()} wordt voortaan als {name} bij {customer.name} herkend.")

    def choose_recognized_customer(self,matches):
        labels=[f"{item['customer_number']} — {item['customer_name']}" +
                (f" · {item['contact_name']}" if item.get("contact_name") else "") for item in matches]
        label,ok=QInputDialog.getItem(self,"Meerdere klanten gevonden","Bij welke klant hoort dit gesprek?",labels,0,False)
        if not ok:return False
        match=matches[labels.index(label)]
        self.service.select_match(self.call_id,match["customer_id"],match.get("contact_id"))
        self.open_customer(match["customer_id"])
        return True

    def create_call_ticket(self):
        if not self.call_id or not self.create_ticket:return
        call=self.service.get(self.call_id)
        if not call or not call["customer_id"]:
            QMessageBox.information(self,"Serviceticket","Kies of koppel eerst de juiste klant.");return
        subject=self.subject.text().strip() or call["subject"] or f"Telefoongesprek {call['contact_name'] or call['phone_number']}"
        description=self.notes.toPlainText().strip() or f"Bron: telefoongesprek met {call['contact_name'] or call['phone_number']}"
        self.create_ticket(call["customer_id"],subject,description,"Telefoon",self.call_id)

    def refresh_history(self,*_):
        rows=self.service.history(self.filter_customer.currentData(),self.search.text(),self.queue.currentData() or "alle"); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["started_at"],row["customer_name"],row["contact_name"],row["direction"],row["phone_number"],_duration(row["duration_seconds"]),row["status"],row["priority"],row["callback_due"],row["assigned_to"],row["subject"],row["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.service.queue_stats();self.queue_status.setText(f"{stats['callbacks']} terugbellen · {stats['unknown']} onbekend")

    def load_selected(self,*_):
        row=self.table.currentRow(); item=self.table.item(row,11) if row>=0 else None
        if not item:return
        self.call_id=int(item.text()); call=self.service.get(self.call_id); self.phone.setText(call["phone_number"]); self.subject.setText(call["subject"]); self.notes.setPlainText(call["notes"]); self.outcome.setCurrentText(call["outcome"] or "Beantwoord")
        self.priority.setCurrentText(call["priority"]);self.assigned.setText(call["assigned_to"] or self.service.actor);self.callback_due.setText(call["callback_due"])
        self.callback.setChecked(call["callback_status"]=="open");self.match.setText(f"{call['customer_name']} · {call['contact_name']}\n{call['phone_number']}")
        self.show_briefing(call)

    def complete_callback(self):
        row=self.table.currentRow();item=self.table.item(row,11) if row>=0 else None
        if not item:return
        self.service.complete_callback(int(item.text()));self.refresh_history()

    def open_call(self,call_id):
        if call_id is None:return
        self.call_id=call_id; call=self.service.get(call_id)
        if not call:return
        self.phone.setText(call["phone_number"]); self.subject.setText(call["subject"]); self.notes.setPlainText(call["notes"])
        self.outcome.setCurrentText(call["outcome"] or "Beantwoord")
        self.priority.setCurrentText(call["priority"]);self.assigned.setText(call["assigned_to"] or self.service.actor)
        self.callback_due.setText(call["callback_due"]);self.callback.setChecked(call["callback_status"]=="open")
        self.match.setText(f"{call['customer_name']} · {call['contact_name']}\n{call['phone_number']}")
        self.show_briefing(call)

    def show_briefing(self,call):
        context=self.service.customer_briefing(call.get("customer_id") if call else None)
        title="Klant in beeld" if call and call.get("customer_id") else "Onbekende beller"
        recent=context["recent_calls"]
        last=f"\nLaatste gesprek: {recent[0]['subject'] or recent[0]['outcome'] or recent[0]['status']}" if recent else ""
        self.briefing.setText(f"{title}  •  {context['summary']}{last}")

    def _open_customer(self):
        call=self.service.get(self.call_id) if self.call_id else None
        if call and call["customer_id"]:self.open_customer(call["customer_id"])

    def _open_vault(self):
        if self.phone.text().strip():self.open_vault(self.phone.text())


def _duration(seconds):
    seconds=max(0,int(seconds or 0));minutes,second=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return f"{hours:02d}:{minutes:02d}:{second:02d}"
