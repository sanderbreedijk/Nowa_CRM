from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTextEdit, QVBoxLayout)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.telephony.service import TelephonyService


class IncomingCallPopup(QDialog):
    """Centrale gesprekswerkplek; blijft open terwijl onderliggende CRM-acties worden uitgevoerd."""

    completed=Signal(int,dict)

    def __init__(self, call_id: int, customers: CustomerService, telephony: TelephonyService,
                 open_call, open_customer, open_vault, create_ticket, parent=None):
        super().__init__(parent)
        self.call_id=call_id;self.customers=customers;self.telephony=telephony
        self.open_call_callback=open_call;self.open_customer_callback=open_customer
        self.open_vault_callback=open_vault;self.create_ticket_callback=create_ticket
        self.setObjectName("IncomingCallPopup");self.setWindowTitle("NOWA · Gesprekswerkplek")
        self.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);self.resize(980,690);self.setMinimumSize(820,600)
        self.handled=False;self.missed_timer=QTimer(self);self.missed_timer.setSingleShot(True)
        self.missed_timer.timeout.connect(self.auto_missed);self.missed_timer.start(45000)

        root=QVBoxLayout(self);root.setContentsMargins(24,22,24,22);root.setSpacing(14)
        top=QHBoxLayout();icon=QLabel("TEL");icon.setObjectName("CallPopupIcon");top.addWidget(icon)
        titles=QVBoxLayout();status=QLabel("●  INKOMEND GESPREK · CENTRALE WERKPLEK");status.setObjectName("CallPopupStatus")
        self.phone=QLabel();self.phone.setObjectName("CallPopupPhone");titles.addWidget(status);titles.addWidget(self.phone);top.addLayout(titles,1)
        self.accept_button=QPushButton("Gesprek aannemen");self.accept_button.setObjectName("CallAccept");self.accept_button.clicked.connect(self.accept_call);top.addWidget(self.accept_button)
        root.addLayout(top)

        identity=QFrame();identity.setObjectName("CallIdentity");identity_box=QVBoxLayout(identity);identity_box.setContentsMargins(16,13,16,13)
        self.customer=QLabel();self.customer.setObjectName("CallPopupCustomer");self.customer.setWordWrap(True);identity_box.addWidget(self.customer)
        self.context=QLabel();self.context.setObjectName("CallPopupContext");self.context.setWordWrap(True);identity_box.addWidget(self.context)
        self.matches=QComboBox();self.matches.setObjectName("CallMatch");self.matches.currentIndexChanged.connect(self.select_match);identity_box.addWidget(self.matches)
        root.addWidget(identity)

        body=QHBoxLayout();body.setSpacing(14)
        input_panel=QFrame();input_panel.setObjectName("CallInputPanel");form=QFormLayout(input_panel);form.setContentsMargins(18,16,18,16);form.setSpacing(11)
        heading=QLabel("Gespreksregistratie");heading.setObjectName("SectionTitle");form.addRow(heading)
        self.subject=QLineEdit();self.subject.setPlaceholderText("Waar gaat het gesprek over?")
        self.notes=QTextEdit();self.notes.setPlaceholderText("Noteer afspraken, vragen en uitgevoerde handelingen…");self.notes.setMinimumHeight(190)
        self.outcome=QComboBox();self.outcome.addItems(["Beantwoord","Informatie verstrekt","Afspraak gemaakt","Doorgezet","Geen gehoor","Overig"])
        self.priority=QComboBox();self.priority.addItems(["Laag","Normaal","Hoog","Kritiek"]);self.priority.setCurrentText("Normaal")
        options=QHBoxLayout();options.addWidget(self.outcome,1);options.addWidget(self.priority,1)
        self.callback=QCheckBox("Terugbelactie maken");self.callback_due=QLineEdit();self.callback_due.setPlaceholderText("Terugbeldatum: jjjj-mm-dd")
        callback_row=QHBoxLayout();callback_row.addWidget(self.callback);callback_row.addWidget(self.callback_due,1)
        form.addRow("Onderwerp",self.subject);form.addRow("Notities",self.notes);form.addRow("Resultaat / prioriteit",options);form.addRow("Opvolging",callback_row)
        body.addWidget(input_panel,3)

        actions=QFrame();actions.setObjectName("CallActionPanel");action_box=QVBoxLayout(actions);action_box.setContentsMargins(16,16,16,16);action_box.setSpacing(10)
        action_title=QLabel("Directe acties");action_title.setObjectName("SectionTitle");action_box.addWidget(action_title)
        action_text=QLabel("Alles blijft binnen deze gesprekswerkplek beschikbaar.");action_text.setObjectName("PanelText");action_text.setWordWrap(True);action_box.addWidget(action_text)
        grid=QGridLayout();grid.setSpacing(9)
        self.dossier=_action("360°\nKlantdossier",self.open_customer);self.vault=_action("IT-KLUIS\nGegevens",self.open_vault)
        ticket=_action("TICKET\nServicedesk",self.create_ticket);callback=_action("TERUGBELLEN\nActie maken",self.make_callback)
        self.link=_action("KOPPELEN\nOnbekend nummer",self.link_number);phone=_action("TELEFONIE\nVolledig overzicht",self.open_call)
        for index,button in enumerate((self.dossier,self.vault,ticket,callback,self.link,phone)):grid.addWidget(button,index//2,index%2)
        action_box.addLayout(grid);action_box.addStretch();body.addWidget(actions,2);root.addLayout(body,1)

        footer=QFrame();footer.setObjectName("CallFooter");footer_row=QHBoxLayout(footer);footer_row.setContentsMargins(12,10,12,10)
        ignore=QPushButton("Niet opgenomen");ignore.setObjectName("CallQuiet");ignore.clicked.connect(self.ignore_call)
        self.save=QPushButton("Alles opslaan en gesprek beëindigen");self.save.setObjectName("EndCallPrimary");self.save.clicked.connect(self.finish_workflow)
        footer_row.addWidget(ignore);footer_row.addStretch();footer_row.addWidget(self.save);root.addWidget(footer)
        self.reload()

    def reload(self):
        call=self.telephony.get(self.call_id)
        if not call:self.close();return
        self.phone.setText(call["phone_number"]);recognition=self.telephony.recognize(call["phone_number"]);matches=recognition.get("matches",[])
        self.matches.blockSignals(True);self.matches.clear()
        for item in matches:
            label=f"{item['customer_number']} — {item['customer_name']}"
            if item.get("contact_name"):label+=f" · {item['contact_name']}"
            self.matches.addItem(label,(item["customer_id"],item.get("contact_id")))
        self.matches.setVisible(len(matches)>1 and not bool(call["customer_id"]))
        if len(matches)>1 and not call["customer_id"]:self.matches.setCurrentIndex(-1)
        self.matches.blockSignals(False)
        if call["customer_id"]:
            contact=f" · {call['contact_name']}" if call["contact_name"] else ""
            self.customer.setText(f"{call['customer_name']}{contact}")
            self.context.setText(self.telephony.customer_briefing(call["customer_id"])["summary"])
        elif len(matches)>1:
            self.customer.setText(f"{len(matches)} mogelijke klanten gevonden")
            self.context.setText("Kies de juiste klant om alle directe acties beschikbaar te maken.")
        else:
            self.customer.setText("Onbekende beller")
            self.context.setText("Koppel het nummer eenmalig; volgende oproepen worden direct herkend.")
        self.dossier.setEnabled(bool(call["customer_id"]));self.link.setVisible(not bool(call["customer_id"]))

    def accept_call(self):
        self._handled();self.accept_button.setText("✓ Gesprek actief");self.accept_button.setEnabled(False);self.notes.setFocus()

    def select_match(self,index):
        data=self.matches.itemData(index)
        if data:self.telephony.select_match(self.call_id,data[0],data[1]);self._handled();self.reload()

    def link_number(self):
        rows=self.customers.search()
        if not rows:QMessageBox.information(self,"Nummer koppelen","Voeg eerst een klant toe.");return
        labels=[f"{row.customer_number} — {row.name}" for row in rows]
        label,ok=QInputDialog.getItem(self,"Onbekend nummer koppelen","Klant",labels,0,False)
        if not ok:return
        name,ok=QInputDialog.getText(self,"Onbekend nummer koppelen","Naam of herkenbare omschrijving")
        if not ok or not name.strip():return
        description,ok=QInputDialog.getText(self,"Onbekend nummer koppelen","Functie / toelichting (optioneel)")
        if not ok:return
        self.telephony.link_customer(self.call_id,rows[labels.index(label)].id,contact_name=name,description=description);self._handled();self.reload()

    def open_customer(self):
        call=self.telephony.get(self.call_id)
        if not call or not call["customer_id"]:return
        self._handled();self.open_customer_callback(call["customer_id"]);self._return_to_workspace()

    def open_vault(self):
        self._handled();self.open_vault_callback(self.phone.text());self._return_to_workspace()

    def open_call(self):
        self._handled();self.open_call_callback(self.call_id);self._return_to_workspace()

    def create_ticket(self):
        call=self.telephony.get(self.call_id)
        if not call or not call["customer_id"]:QMessageBox.information(self,"Serviceticket","Kies of koppel eerst de klant.");return
        subject=self.subject.text().strip() or f"Telefoongesprek {call['contact_name'] or call['phone_number']}"
        description=self.notes.toPlainText().strip() or f"Bron: telefoongesprek met {call['contact_name'] or call['phone_number']}"
        self._handled();self.hide()
        try:self.create_ticket_callback(call["customer_id"],subject,description,"Telefoon",self.call_id)
        finally:self._return_to_workspace()

    def make_callback(self):
        self._handled();self.callback.setChecked(True);self.callback_due.setFocus()

    def finish_workflow(self):
        call=self.telephony.get(self.call_id)
        if not call:return
        try:
            self.telephony.finish_call(self.call_id,self.subject.text(),self.notes.toPlainText(),self.outcome.currentText(),
                                       self.callback.isChecked(),self.callback_due.text(),self.priority.currentText(),self.telephony.actor)
        except Exception as exc:
            QMessageBox.warning(self,"Gesprek beëindigen",str(exc));return
        self.handled=True;self.missed_timer.stop();saved=self.telephony.get(self.call_id);self.completed.emit(self.call_id,saved or {});self.close()

    def ignore_call(self):
        self.handled=True;self.missed_timer.stop();self.telephony.finish_call(self.call_id,"Oproep niet opgenomen","","Geen gehoor");self.close()

    def _handled(self):
        self.handled=True;self.missed_timer.stop();self.telephony.acknowledge_call(self.call_id)

    def _return_to_workspace(self):
        self.show();self.raise_();self.activateWindow();self.notes.setFocus()

    def auto_missed(self):
        if not self.handled:self.telephony.mark_existing_missed(self.call_id);self.handled=True
        self.close()

    def closeEvent(self,event):
        if not self.handled:self.telephony.mark_existing_missed(self.call_id);self.handled=True
        self.missed_timer.stop();super().closeEvent(event)

    def showEvent(self,event):
        super().showEvent(event)
        screen=QGuiApplication.screenAt(self.parentWidget().frameGeometry().center()) if self.parentWidget() else QGuiApplication.primaryScreen()
        area=screen.availableGeometry();width=min(self.width(),area.width()-70);height=min(self.height(),area.height()-70)
        self.resize(width,height);self.move(area.center().x()-width//2,area.center().y()-height//2)


def _action(text,handler):
    button=QPushButton(text);button.setObjectName("CallAction");button.setMinimumHeight(72);button.clicked.connect(handler)
    return button
