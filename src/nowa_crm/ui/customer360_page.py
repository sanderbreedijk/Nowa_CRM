from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.customer360.service import Customer360Service
from nowa_crm.ui.icons import nav_icon


class Customer360Page(QWidget):
    """Compact klantwerkblad met directe acties en één chronologische tijdlijn."""

    def __init__(self, customers: CustomerService, service: Customer360Service, open_vault,
                 open_proposal, start_mail, start_followup, start_proposal, parent=None):
        super().__init__(parent)
        self.customers, self.service = customers, service
        self.open_vault, self.open_proposal = open_vault, open_proposal
        self.start_mail, self.start_followup, self.start_proposal = start_mail, start_followup, start_proposal

        root=QVBoxLayout(self); root.setContentsMargins(34,28,34,28); root.setSpacing(14)
        heading=QHBoxLayout(); titles=QVBoxLayout(); title=QLabel("360° klantdossier"); title.setObjectName("Title"); titles.addWidget(title)
        sub=QLabel("Alle commerciële, operationele en service-informatie van één klant in één praktisch klantbeeld."); sub.setObjectName("Subtitle"); titles.addWidget(sub); heading.addLayout(titles); heading.addStretch()
        self.customer=QComboBox(); self.customer.setMinimumWidth(360); self.customer.currentIndexChanged.connect(self.reload); heading.addWidget(self.customer); root.addLayout(heading)

        hero=QFrame(); hero.setObjectName("CustomerHero"); hero_box=QHBoxLayout(hero); hero_box.setContentsMargins(20,16,20,16)
        badge=QLabel("360"); badge.setObjectName("CustomerBadge"); hero_box.addWidget(badge)
        identity_box=QVBoxLayout(); self.identity=QLabel(); self.identity.setObjectName("CustomerName"); self.identity.setWordWrap(True); identity_box.addWidget(self.identity)
        self.contactline=QLabel(); self.contactline.setObjectName("CustomerMeta"); self.contactline.setWordWrap(True); identity_box.addWidget(self.contactline); hero_box.addLayout(identity_box,1)
        for symbol,text,handler in (("OF","Nieuwe offerte",self._proposal),("ML","Nieuwe mail",self._mail),("OP","Opvolging",self._followup),("KV","IT-kluis",self._vault)):
            button=QPushButton(text); button.setIcon(nav_icon(symbol)); button.setIconSize(QSize(24,24)); button.clicked.connect(handler); hero_box.addWidget(button)
        root.addWidget(hero)

        grid=QGridLayout(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12); self.kpis=[]
        cards=(("CO","Contacten","blue"),("OF","Offertes","purple"),("KV","Kluisitems","teal"),("GB","Gebruikers","orange"),("LI","Licenties","purple"),
               ("HW","Hardware","blue"),("AC","Open acties","orange"),("TK","Open tickets","orange"),("EM","E-mails","teal"),("DO","Documenten","blue"))
        for i,(symbol,name,accent) in enumerate(cards):
            card=QFrame();card.setObjectName("MiniStatCard");box=QHBoxLayout(card);box.setContentsMargins(14,11,14,11)
            icon=QLabel(symbol);icon.setObjectName("MiniKpiIcon");icon.setProperty("accent",accent);box.addWidget(icon)
            text=QVBoxLayout();value=QLabel("0");value.setObjectName("MiniKpi");text.addWidget(value);label=QLabel(name);label.setObjectName("KpiLabel");text.addWidget(label);box.addLayout(text,1)
            grid.addWidget(card,i//5,i%5);self.kpis.append(value)
        root.addLayout(grid)

        self.warning=QLabel();self.warning.setObjectName("AttentionBanner");self.warning.setWordWrap(True);self.warning.hide();root.addWidget(self.warning)
        timeline_head=QHBoxLayout(); timeline_title=QLabel("Klanttijdlijn");timeline_title.setObjectName("SectionTitle");timeline_head.addWidget(timeline_title);timeline_head.addStretch();self.timeline_count=QLabel();self.timeline_count.setObjectName("SummaryPill");timeline_head.addWidget(self.timeline_count);root.addLayout(timeline_head)
        self.timeline=QTableWidget(0,4);self.timeline.setHorizontalHeaderLabels(["Datum","Soort","Onderwerp","Status / detail"]);self.timeline.horizontalHeader().setStretchLastSection(True);self.timeline.setAlternatingRowColors(True);root.addWidget(self.timeline,1)
        self.reload_customers()

    def reload_customers(self, customer_id=None):
        current=customer_id or self.customer.currentData();self.customer.blockSignals(True);self.customer.clear()
        for item in self.customers.search():self.customer.addItem(f"{item.customer_number} — {item.name}",item.id)
        if current:
            index=self.customer.findData(current)
            if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False);self.reload()

    def select_customer(self,customer_id):
        index=self.customer.findData(customer_id)
        if index<0:self.reload_customers(customer_id)
        else:self.customer.setCurrentIndex(index)

    def reload(self,*_):
        customer_id=self.customer.currentData()
        if not customer_id:self.identity.setText("Voeg eerst een klant toe.");self.contactline.clear();self.timeline.setRowCount(0);return
        data=self.service.snapshot(customer_id);c=data["customer"]
        self.identity.setText(f"{c.name}   ·   {c.customer_number}   ·   {c.status}")
        address=" ".join(x for x in (c.street,c.postal_code,c.city,c.country) if x)
        self.contactline.setText("   ·   ".join(x for x in (c.phone,c.mobile_phone,c.email,address,c.tags) if x) or "Nog geen contactgegevens vastgelegd")
        values=(len(data["contacts"]),len(data["proposals"]),len(data["vault"]),len(data["users"]),sum(int(x["quantity"]) for x in data["licenses"]),
                sum(int(x["quantity"]) for x in data["hardware"]),len([x for x in data["actions"] if x["status"] not in ("Gereed","Geannuleerd")]),
                len([x for x in data["tickets"] if x["status"] not in ("Opgelost","Gesloten")]),len(data["mail"]),len(data["documents"]))
        for label,value in zip(self.kpis,values):label.setText(str(value))
        warnings=data["warnings"];self.warning.setText("Aandacht nodig  ·  "+"  ·  ".join(warnings));self.warning.setVisible(bool(warnings))
        rows=self.service.timeline(customer_id);self.timeline.setRowCount(len(rows));self.timeline_count.setText(f"{len(rows)} gebeurtenissen")
        for r,row in enumerate(rows):
            for col,value in enumerate((row["date"],row["kind"],row["title"],row["detail"])):self.timeline.setItem(r,col,QTableWidgetItem(str(value or "")))

    def _vault(self):
        if self.customer.currentData():self.open_vault(self.customers.get(self.customer.currentData()).name)
    def _mail(self):
        if self.customer.currentData():self.start_mail(self.customer.currentData())
    def _followup(self):
        if self.customer.currentData():self.start_followup(self.customer.currentData())
    def _proposal(self):
        if self.customer.currentData():self.start_proposal(self.customer.currentData())
