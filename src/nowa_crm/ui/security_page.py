from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox,QHBoxLayout,QLabel,QMessageBox,QPushButton,QTabWidget,
                               QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.security.service import SecurityService


class SecurityPage(QWidget):
    def __init__(self,customers: CustomerService,security: SecurityService,parent=None):
        super().__init__(parent);self.customers,self.security=customers,security
        root=QVBoxLayout(self);title=QLabel("Beveiliging en beheercontrole");title.setObjectName("Title");root.addWidget(title)
        sub=QLabel("Controleer lokaal MFA, identiteiten, licenties, beheercredentials en auditregistratie.");sub.setObjectName("Subtitle");root.addWidget(sub)
        row=QHBoxLayout();self.customer=QComboBox();self.customer.currentIndexChanged.connect(self.refresh)
        refresh=QPushButton("Opnieuw controleren");refresh.clicked.connect(self.refresh)
        report=QPushButton("Rapport opslaan");report.setObjectName("Primary");report.clicked.connect(self.export_report)
        csv=QPushButton("CSV-export");csv.clicked.connect(self.export_csv)
        row.addWidget(self.customer,1);row.addWidget(refresh);row.addWidget(report);row.addWidget(csv);root.addLayout(row)
        self.summary=QLabel();self.summary.setObjectName("Subtitle");root.addWidget(self.summary)
        tabs=QTabWidget();self.findings=QTableWidget(0,4);self.findings.setHorizontalHeaderLabels(["Ernst","Onderdeel","Bevinding","Advies"]);self.findings.horizontalHeader().setStretchLastSection(True)
        self.users=QTableWidget(0,6);self.users.setHorizontalHeaderLabels(["Naam","UPN","Afdeling","Licentie","MFA","Actief"]);self.users.horizontalHeader().setStretchLastSection(True)
        self.audit=QTableWidget(0,5);self.audit.setHorizontalHeaderLabels(["Datum","Gebruiker","Actie","Onderdeel","Reden"]);self.audit.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.findings,"Aandachtspunten");tabs.addTab(self.users,"Gebruikers en MFA");tabs.addTab(self.audit,"Kluis-audit");root.addWidget(tabs,1);self.reload_customers()

    def reload_customers(self):
        selected=self.customer.currentData();self.customer.blockSignals(True);self.customer.clear()
        for item in self.customers.search():self.customer.addItem(f"{item.customer_number} — {item.name}",item.id)
        index=self.customer.findData(selected)
        if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False);self.refresh()

    def refresh(self,*_):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        data=self.security.summary(customer_id)
        self.summary.setText(f"Beveiligingsscore {data['score']}/100 · MFA {data['mfa']} van {data['users']} · {data['critical']} kritisch · {data['high']} hoog")
        self._fill(self.findings,data["findings"],("severity","category","finding","advice"))
        users=self.security.users(customer_id)
        rendered=[{**u,"mfa":"Ja" if u["mfa_enabled"] else "Nee","enabled":"Ja" if u["active"] else "Nee"} for u in users]
        self._fill(self.users,rendered,("display_name","user_principal_name","department","license_name","mfa","enabled"))
        audit=self.security.audit(customer_id)
        self._fill(self.audit,audit,("occurred_at","actor","action","entity_type","reason"))

    @staticmethod
    def _fill(table,rows,keys):
        table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,key in enumerate(keys):table.setItem(r,c,QTableWidgetItem(str(row.get(key,"") or "")))

    def export_report(self):self._export(self.security.export_report,"Beveiligingsrapport")
    def export_csv(self):self._export(self.security.export_csv,"Beveiligings-CSV")
    def _export(self,method,title):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        try:QDesktopServices.openUrl(QUrl.fromLocalFile(str(method(customer_id))))
        except Exception as exc:QMessageBox.warning(self,title,str(exc))
