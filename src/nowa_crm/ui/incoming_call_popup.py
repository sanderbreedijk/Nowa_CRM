from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.telephony.service import TelephonyService


class IncomingCallPopup(QDialog):
    """Niet-modale oproepkaart die het actieve CRM-scherm intact laat."""

    def __init__(self, call_id: int, customers: CustomerService, telephony: TelephonyService,
                 open_call, open_customer, open_vault, create_ticket, parent=None):
        super().__init__(parent)
        self.call_id=call_id;self.customers=customers;self.telephony=telephony
        self.open_call_callback=open_call;self.open_customer_callback=open_customer
        self.open_vault_callback=open_vault;self.create_ticket_callback=create_ticket
        self.setObjectName("IncomingCallPopup");self.setWindowTitle("Inkomend gesprek")
        self.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);self.setFixedWidth(460)
        self.handled=False;self.missed_timer=QTimer(self);self.missed_timer.setSingleShot(True);self.missed_timer.timeout.connect(self.auto_missed);self.missed_timer.start(45000)
        root=QVBoxLayout(self);root.setContentsMargins(22,20,22,18);root.setSpacing(12)
        top=QHBoxLayout();icon=QLabel("TEL");icon.setObjectName("CallPopupIcon");top.addWidget(icon)
        titles=QVBoxLayout();status=QLabel("●  INKOMENDE OPROEP");status.setObjectName("CallPopupStatus");self.phone=QLabel()
        self.phone.setObjectName("CallPopupPhone");titles.addWidget(status);titles.addWidget(self.phone);top.addLayout(titles,1)
        close=QPushButton("×");close.setObjectName("CallPopupClose");close.clicked.connect(self.close);top.addWidget(close);root.addLayout(top)
        identity=QFrame();identity.setObjectName("CallIdentity");identity_box=QVBoxLayout(identity);identity_box.setContentsMargins(15,13,15,13);identity_box.setSpacing(5)
        self.customer=QLabel();self.customer.setObjectName("CallPopupCustomer");self.customer.setWordWrap(True);identity_box.addWidget(self.customer)
        self.context=QLabel();self.context.setObjectName("CallPopupContext");self.context.setWordWrap(True);identity_box.addWidget(self.context);root.addWidget(identity)
        self.matches=QComboBox();self.matches.setObjectName("CallMatch");self.matches.currentIndexChanged.connect(self.select_match);root.addWidget(self.matches)
        self.dossier=QPushButton("Open klantdossier");self.dossier.setObjectName("CallPrimary");self.dossier.clicked.connect(self.open_customer);root.addWidget(self.dossier)
        actions=QGridLayout();actions.setHorizontalSpacing(8);actions.setVerticalSpacing(8)
        vault=QPushButton("IT-kluis");vault.clicked.connect(self.open_vault);phone=QPushButton("Gesprek openen");phone.clicked.connect(self.open_call)
        ticket=QPushButton("Serviceticket");ticket.clicked.connect(self.create_ticket);callback=QPushButton("Terugbellen");callback.clicked.connect(self.make_callback)
        self.link=QPushButton("Nummer koppelen");self.link.clicked.connect(self.link_number)
        actions.addWidget(vault,0,0);actions.addWidget(phone,0,1);actions.addWidget(ticket,1,0);actions.addWidget(callback,1,1);actions.addWidget(self.link,2,0,1,2);root.addLayout(actions)
        divider=QFrame();divider.setFrameShape(QFrame.Shape.HLine);divider.setObjectName("CallDivider");root.addWidget(divider)
        dismiss=QHBoxLayout();ignore=QPushButton("Niet opnemen");ignore.setObjectName("CallQuiet");ignore.clicked.connect(self.ignore_call)
        registered=QPushButton("Oproep aangenomen");registered.setObjectName("Primary");registered.clicked.connect(self.register_only)
        dismiss.addWidget(ignore);dismiss.addStretch();dismiss.addWidget(registered);root.addLayout(dismiss)
        self.reload()

    def reload(self):
        call=self.telephony.get(self.call_id)
        if not call:self.close();return
        self.phone.setText(call["phone_number"]);recognition=self.telephony.recognize(call["phone_number"])
        matches=recognition.get("matches",[]);self.matches.blockSignals(True);self.matches.clear()
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
            brief=self.telephony.customer_briefing(call["customer_id"]);self.context.setText(brief["summary"])
        elif len(matches)>1:
            self.customer.setText(f"{len(matches)} mogelijke klanten gevonden")
            self.context.setText("Kies eerst de juiste klant; daarna kun je het dossier of de IT-kluis openen.")
        else:
            self.customer.setText("Onbekende beller")
            self.context.setText("Koppel dit nummer eenmalig; volgende oproepen worden direct herkend.")
        self.dossier.setEnabled(bool(call["customer_id"]))
        self.dossier.setText("Open klantdossier" if call["customer_id"] else "Kies of koppel eerst een klant")
        self.link.setVisible(not bool(call["customer_id"]))

    def select_match(self,index):
        data=self.matches.itemData(index)
        if data:
            self.telephony.select_match(self.call_id,data[0],data[1]);self.reload()

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
        self.telephony.link_customer(self.call_id,rows[labels.index(label)].id,contact_name=name,description=description);self.reload()

    def open_customer(self):
        call=self.telephony.get(self.call_id)
        if not call or not call["customer_id"]:QMessageBox.information(self,"Klantdossier","Kies of koppel eerst de klant.");return
        self._handled();self.open_customer_callback(call["customer_id"]);self.close()

    def open_vault(self):
        self._handled();self.open_vault_callback(self.phone.text());self.close()

    def open_call(self):
        self._handled();self.open_call_callback(self.call_id);self.close()

    def create_ticket(self):
        call=self.telephony.get(self.call_id)
        if not call or not call["customer_id"]:QMessageBox.information(self,"Serviceticket","Kies of koppel eerst de klant.");return
        subject=f"Telefoongesprek {call['contact_name'] or call['phone_number']}"
        self._handled();self.create_ticket_callback(call["customer_id"],subject,"Aangemaakt vanuit inkomende oproep.","Telefoon",self.call_id);self.close()

    def make_callback(self):
        call=self.telephony.get(self.call_id)
        if not call or not call["customer_id"]:QMessageBox.information(self,"Terugbellen","Kies of koppel eerst de klant.");return
        self.telephony.finish_call(self.call_id,"Terugbelverzoek","Terugbellen naar aanleiding van inkomende oproep.","Terugbellen",True,"","Hoog",self.telephony.actor)
        self.handled=True;self.missed_timer.stop()
        self.close()

    def ignore_call(self):
        self.handled=True;self.missed_timer.stop();self.telephony.finish_call(self.call_id,"Oproep genegeerd","","Genegeerd");self.close()

    def register_only(self):
        self._handled();self.close()

    def _handled(self):
        self.handled=True;self.missed_timer.stop();self.telephony.acknowledge_call(self.call_id)

    def auto_missed(self):
        if not self.handled:self.telephony.mark_existing_missed(self.call_id);self.handled=True
        self.close()

    def closeEvent(self,event):
        if not self.handled:self.telephony.mark_existing_missed(self.call_id);self.handled=True
        self.missed_timer.stop();super().closeEvent(event)

    def showEvent(self,event):
        super().showEvent(event)
        screen=QGuiApplication.screenAt(self.parentWidget().frameGeometry().center()) if self.parentWidget() else QGuiApplication.primaryScreen()
        area=screen.availableGeometry();self.adjustSize();self.move(area.right()-self.width()-24,area.top()+24)
