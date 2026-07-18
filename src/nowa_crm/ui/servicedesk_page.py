from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.servicedesk.service import ServiceDeskService


class ServiceDeskPage(QWidget):
    def __init__(self,customers: CustomerService,service: ServiceDeskService,parent=None):
        super().__init__(parent); self.customers=customers; self.service=service; self.ticket_id=None
        root=QVBoxLayout(self); title=QLabel("Servicedesk"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Registreer servicevragen, bewaak SLA-afspraken en leg voortgang en bestede tijd vast."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        filters=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Zoek ticket, klant of onderwerp…"); self.search.textChanged.connect(self.reload)
        self.customer_filter=QComboBox(); self.customer_filter.currentIndexChanged.connect(self.reload); self.status_filter=QComboBox(); self.status_filter.addItem("Alle statussen",""); self.status_filter.addItems(ServiceDeskService.STATUSES); self.status_filter.currentIndexChanged.connect(self.reload)
        filters.addWidget(self.search,1); filters.addWidget(self.customer_filter); filters.addWidget(self.status_filter); root.addLayout(filters)
        self.stats=QLabel(); self.stats.setStyleSheet("font-size:16px;font-weight:700;color:#0B2342"); root.addWidget(self.stats)
        split=QSplitter(); left=QWidget(); ll=QVBoxLayout(left); self.table=QTableWidget(0,9); self.table.setHorizontalHeaderLabels(["Nummer","Klant","Onderwerp","Prioriteit","Status","Eigenaar","SLA","Tijd","ID"]); self.table.setColumnHidden(8,True); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.load_selected); ll.addWidget(self.table)
        create=QPushButton("Nieuw ticket"); create.setObjectName("Primary"); create.clicked.connect(self.create_ticket); ll.addWidget(create)
        right=QWidget(); form=QFormLayout(right); self.heading=QLabel("Selecteer een ticket"); self.heading.setWordWrap(True); form.addRow(self.heading)
        self.updates=QTableWidget(0,3); self.updates.setHorizontalHeaderLabels(["Datum","Status","Voortgang"]); self.updates.horizontalHeader().setStretchLastSection(True); form.addRow(self.updates)
        progress=QPushButton("Voortgang toevoegen"); progress.clicked.connect(self.add_update); time=QPushButton("Tijd registreren"); time.clicked.connect(self.add_time); close=QPushButton("Ticket sluiten"); close.clicked.connect(self.close_ticket)
        row=QHBoxLayout(); row.addWidget(progress); row.addWidget(time); row.addWidget(close); form.addRow(row)
        split.addWidget(left); split.addWidget(right); split.setSizes([900,500]); root.addWidget(split,1); self.reload_customers()

    def reload_customers(self):
        current=self.customer_filter.currentData(); self.customer_filter.blockSignals(True); self.customer_filter.clear(); self.customer_filter.addItem("Alle klanten",None)
        for customer in self.customers.search():self.customer_filter.addItem(f"{customer.customer_number} — {customer.name}",customer.id)
        if current:
            i=self.customer_filter.findData(current)
            if i>=0:self.customer_filter.setCurrentIndex(i)
        self.customer_filter.blockSignals(False); self.reload()

    def reload(self,*_):
        customer_id=self.customer_filter.currentData(); rows=self.service.list(customer_id,self.status_filter.currentData() or "",self.search.text()); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["number"],row["customer_name"],row["subject"],row["priority"],row["status"],row["owner"],row["sla_due_at"],f"{row['minutes']/60:.2f} uur",row["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.service.stats(customer_id); self.stats.setText(f"Open: {stats['open']}  ·  Kritiek: {stats['critical']}  ·  Geregistreerde tijd: {stats['minutes']/60:.2f} uur")

    def create_ticket(self):
        customers=self.customers.search()
        if not customers:QMessageBox.information(self,"Servicedesk","Voeg eerst een klant toe."); return
        labels=[f"{x.customer_number} — {x.name}" for x in customers]; label,ok=QInputDialog.getItem(self,"Nieuw ticket","Klant",labels,0,False)
        if not ok:return
        subject,ok=QInputDialog.getText(self,"Nieuw ticket","Onderwerp")
        if not ok:return
        description,ok=QInputDialog.getMultiLineText(self,"Nieuw ticket","Omschrijving")
        if not ok:return
        priority,ok=QInputDialog.getItem(self,"Nieuw ticket","Prioriteit",list(ServiceDeskService.PRIORITIES),1,False)
        if not ok:return
        owner,ok=QInputDialog.getText(self,"Nieuw ticket","Behandelaar",text="NOWA")
        if not ok:return
        sla,ok=QInputDialog.getText(self,"Nieuw ticket","SLA-datum (jjjj-mm-dd uu:mm)")
        if ok:self.ticket_id=self.service.create(customers[labels.index(label)].id,subject,description,priority=priority,owner=owner,sla_due_at=sla); self.reload(); self.load_ticket()

    def load_selected(self,*_):
        row=self.table.currentRow(); item=self.table.item(row,8) if row>=0 else None
        if item:self.ticket_id=int(item.text()); self.load_ticket()

    def load_ticket(self):
        ticket=self.service.get(self.ticket_id) if self.ticket_id else None
        if not ticket:return
        self.heading.setText(f"{ticket['number']} · {ticket['subject']}\n{ticket['customer_name']} · {ticket['priority']} · {ticket['status']}\n{ticket['description']}")
        rows=self.service.updates(self.ticket_id); self.updates.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate((row["created_at"],row["status"],row["body"])):self.updates.setItem(r,c,QTableWidgetItem(str(value or "")))

    def add_update(self):
        if not self.ticket_id:return
        body,ok=QInputDialog.getMultiLineText(self,"Ticketvoortgang","Voortgang")
        if not ok:return
        status,ok=QInputDialog.getItem(self,"Ticketvoortgang","Nieuwe status",["",*ServiceDeskService.STATUSES],0,False)
        if ok:self.service.add_update(self.ticket_id,body,status); self.reload(); self.load_ticket()

    def add_time(self):
        if not self.ticket_id:return
        minutes,ok=QInputDialog.getInt(self,"Tijd registreren","Minuten",15,1,1440,5)
        if not ok:return
        description,ok=QInputDialog.getText(self,"Tijd registreren","Werkzaamheden")
        if ok:self.service.add_time(self.ticket_id,minutes,description); self.reload(); self.load_ticket()

    def close_ticket(self):
        if not self.ticket_id:return
        resolution,ok=QInputDialog.getMultiLineText(self,"Ticket sluiten","Oplossing")
        if ok:self.service.close(self.ticket_id,resolution); self.reload(); self.load_ticket()
