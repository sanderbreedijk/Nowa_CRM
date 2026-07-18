from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.customer360.service import Customer360Service


class Customer360Page(QWidget):
    def __init__(self, customers: CustomerService, service: Customer360Service, open_vault, open_proposal, parent=None):
        super().__init__(parent); self.customers=customers; self.service=service; self.open_vault=open_vault; self.open_proposal=open_proposal
        root=QVBoxLayout(self); title=QLabel("360Â° klantdossier"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Alle commerciÃ«le, operationele en service-informatie van Ã©Ã©n klant in Ã©Ã©n scherm."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        top=QHBoxLayout(); self.customer=QComboBox(); self.customer.currentIndexChanged.connect(self.reload)
        vault=QPushButton("Open IT-kluis"); vault.clicked.connect(self._vault); top.addWidget(self.customer,1); top.addWidget(vault); root.addLayout(top)
        self.identity=QLabel(); self.identity.setWordWrap(True); self.identity.setStyleSheet("font-size:16px;font-weight:700;color:#0B2342"); root.addWidget(self.identity)
        grid=QGridLayout(); self.kpis=[]
        for i,name in enumerate(("Contacten","Offertes","Kluisitems","Gebruikers","Licenties","Hardware","Open acties","Gesprekken","E-mails")):
            card=QFrame(); card.setObjectName("Card"); box=QVBoxLayout(card); value=QLabel("0"); value.setObjectName("Kpi"); box.addWidget(value); box.addWidget(QLabel(name)); grid.addWidget(card,i//5,i%5); self.kpis.append(value)
        root.addLayout(grid); self.warning=QLabel(); self.warning.setWordWrap(True); self.warning.setStyleSheet("color:#9A3412;font-weight:700"); root.addWidget(self.warning)
        self.timeline=QTableWidget(0,4); self.timeline.setHorizontalHeaderLabels(["Datum","Soort","Onderwerp","Status / detail"]); self.timeline.horizontalHeader().setStretchLastSection(True); root.addWidget(self.timeline,1)
        self.reload_customers()

    def reload_customers(self, customer_id=None):
        current=customer_id or self.customer.currentData(); self.customer.blockSignals(True); self.customer.clear()
        for item in self.customers.search():self.customer.addItem(f"{item.customer_number} â€” {item.name}",item.id)
        if current:
            index=self.customer.findData(current)
            if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.reload()

    def select_customer(self,customer_id):
        index=self.customer.findData(customer_id)
        if index<0:self.reload_customers(customer_id)
        else:self.customer.setCurrentIndex(index)

    def reload(self,*_):
        customer_id=self.customer.currentData()
        if not customer_id:self.identity.setText("Voeg eerst een klant toe."); self.timeline.setRowCount(0); return
        data=self.service.snapshot(customer_id); c=data["customer"]
        self.identity.setText(f"{c.name} Â· {c.customer_number}\n{c.phone} Â· {c.email} Â· {c.city}")
        values=(len(data["contacts"]),len(data["proposals"]),len(data["vault"]),len(data["users"]),
                sum(int(x["quantity"]) for x in data["licenses"]),sum(int(x["quantity"]) for x in data["hardware"]),
                len([x for x in data["actions"] if x["status"] not in ("Gereed","Geannuleerd")]),len(data["calls"]),len(data["mail"]))
        for label,value in zip(self.kpis,values):label.setText(str(value))
        self.warning.setText("  Â·  ".join(data["warnings"]))
        rows=self.service.timeline(customer_id); self.timeline.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for col,value in enumerate((row["date"],row["kind"],row["title"],row["detail"])):self.timeline.setItem(r,col,QTableWidgetItem(str(value or "")))

    def _vault(self):
        if self.customer.currentData():self.open_vault(self.customers.get(self.customer.currentData()).name)

