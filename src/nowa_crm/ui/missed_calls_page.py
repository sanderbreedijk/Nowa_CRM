from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from nowa_crm.modules.telephony.service import TelephonyService


class MissedCallsPage(QWidget):
    def __init__(self, service: TelephonyService, open_call, open_customer, parent=None):
        super().__init__(parent);self.service=service;self.open_call_callback=open_call;self.open_customer_callback=open_customer
        root=QVBoxLayout(self);title=QLabel("Gemiste oproepen");title.setObjectName("Title");root.addWidget(title)
        subtitle=QLabel("Eén terugbelwerkvoorraad. Afgehandelde en open oproepen worden na 30 dagen automatisch lokaal verwijderd.")
        subtitle.setObjectName("Subtitle");subtitle.setWordWrap(True);root.addWidget(subtitle)
        summary=QFrame();summary.setObjectName("Toolbar");bar=QHBoxLayout(summary);bar.setContentsMargins(12,9,12,9)
        self.status=QLabel();self.status.setObjectName("SummaryPill");bar.addWidget(self.status);bar.addStretch()
        self.filter=QComboBox();self.filter.addItems(["Open terugbelacties","Alle gemiste oproepen"]);self.filter.currentIndexChanged.connect(self.reload);bar.addWidget(self.filter);root.addWidget(summary)
        self.table=QTableWidget(0,9);self.table.setHorizontalHeaderLabels(["Datum","Klant","Contact","Telefoonnummer","Prioriteit","Toegewezen","Opvolging","Onderwerp","ID"])
        self.table.setColumnHidden(8,True);self.table.horizontalHeader().setStretchLastSection(True);self.table.setAlternatingRowColors(True);self.table.doubleClicked.connect(self.open_call)
        root.addWidget(self.table,1)
        actions=QFrame();actions.setObjectName("ActionBar");row=QHBoxLayout(actions);row.setContentsMargins(12,9,12,9)
        open_call=QPushButton("Open gesprek");open_call.setObjectName("Primary");open_call.clicked.connect(self.open_call)
        dossier=QPushButton("Open klantdossier");dossier.clicked.connect(self.open_customer)
        handled=QPushButton("Terugbelactie afronden");handled.clicked.connect(self.complete)
        link=QPushButton("Klant kiezen / nummer koppelen");link.clicked.connect(self.open_call)
        row.addWidget(open_call);row.addWidget(dossier);row.addWidget(handled);row.addWidget(link);row.addStretch();root.addWidget(actions);self.reload()

    def reload(self,*_):
        removed=self.service.cleanup_missed_calls(30)
        rows=self.service.missed_calls(open_only=self.filter.currentIndex()==0);self.table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            followup="Open" if item["callback_status"]=="open" else "Afgehandeld"
            values=(item["started_at"],item["customer_name"],item["contact_name"],item["phone_number"],item["priority"],item["assigned_to"],followup,item["subject"],item["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.service.missed_stats()
        cleanup=f" · {removed} ouder dan 30 dagen verwijderd" if removed else ""
        self.status.setText(f"{stats['open']} open · {stats['total']} binnen 30 dagen{cleanup}")

    def selected_id(self):
        row=self.table.currentRow();item=self.table.item(row,8) if row>=0 else None
        return int(item.text()) if item else None

    def open_call(self,*_):
        call_id=self.selected_id()
        if call_id:self.open_call_callback(call_id)

    def open_customer(self):
        call=self.service.get(self.selected_id()) if self.selected_id() else None
        if call and call["customer_id"]:self.open_customer_callback(call["customer_id"])
        else:QMessageBox.information(self,"Klantdossier","Deze oproep is nog niet aan een klant gekoppeld.")

    def complete(self):
        call_id=self.selected_id()
        if call_id:self.service.complete_callback(call_id);self.reload()

