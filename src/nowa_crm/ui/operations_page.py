from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.operations.service import OperationsService


class OperationsPage(QWidget):
    def __init__(self, customers: CustomerService, operations: OperationsService, parent=None):
        super().__init__(parent); self.customers=customers; self.operations=operations
        root=QVBoxLayout(self); title=QLabel("Klantbeheer en projecten"); title.setObjectName("Title"); root.addWidget(title)
        subtitle=QLabel("Gebruikers, licenties, hardware, projectintake en planning in één klantcontext."); subtitle.setObjectName("Subtitle"); root.addWidget(subtitle)
        bar=QHBoxLayout(); bar.addWidget(QLabel("Actieve klant")); self.customer=QComboBox(); self.customer.currentIndexChanged.connect(self.refresh); bar.addWidget(self.customer,1)
        check=QPushButton("Controle gebruikers/licenties"); check.clicked.connect(self._check); bar.addWidget(check); root.addLayout(bar)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1); self.tables={}
        self._table_tab("users","Gebruikers",["Naam","UPN","Afdeling","Licentie","MFA","Actief","ID"])
        self._table_tab("licenses","Licenties",["Product","Leverancier","Aantal","Prijs p/st","Verlengdatum","Offerte","ID"])
        self._table_tab("hardware","Hardware",["Type","Merk","Model","Serienummer","Aantal","Status","ID"])
        self._intake_tab()
        self._table_tab("tasks","Planning",["Fase","Taak","Eigenaar","Start","Einde","Status","ID"])
        self.reload_customers()

    def _table_tab(self, kind, label, headers):
        page=QWidget(); box=QVBoxLayout(page); table=QTableWidget(0,len(headers)); table.setHorizontalHeaderLabels(headers); table.setColumnHidden(len(headers)-1,True); table.horizontalHeader().setStretchLastSection(True); box.addWidget(table,1)
        row=QHBoxLayout(); add=QPushButton(f"{label[:-1] if label.endswith('s') else label} toevoegen"); add.setObjectName("Primary"); add.clicked.connect(lambda _,k=kind:self._add(k)); delete=QPushButton("Geselecteerde verwijderen"); delete.clicked.connect(lambda _,k=kind:self._delete(k)); row.addWidget(add); row.addWidget(delete); row.addStretch(); box.addLayout(row)
        self.tables[kind]=table; self.tabs.addTab(page,label)

    def _intake_tab(self):
        page=QWidget(); form=QFormLayout(page); self.intake_counts=[]
        for label in ("Gebruikers","Apparaten","Gedeelde mailboxen","Teams","SharePoint-sites"):
            spin=QSpinBox(); spin.setRange(0,100000); form.addRow(label,spin); self.intake_counts.append(spin)
        self.migration=QComboBox(); self.migration.setEditable(True); self.migration.addItems(["","On-premises Exchange","Microsoft 365 tenant","IMAP","Nieuwe omgeving"])
        self.desired=QComboBox(); self.desired.setEditable(True); self.desired.addItems(["","Zo snel mogelijk","Binnen 1 maand","Binnen 3 maanden","Nog te bepalen"])
        self.scope=QTextEdit(); self.scope.setMaximumHeight(130); form.addRow("Huidige omgeving",self.migration); form.addRow("Gewenste planning",self.desired); form.addRow("Scope en aandachtspunten",self.scope)
        save=QPushButton("Projectintake opslaan"); save.setObjectName("Primary"); save.clicked.connect(self._save_intake); form.addRow("",save); self.tabs.addTab(page,"Projectintake")

    def reload_customers(self):
        current=self.customer.currentData(); self.customer.blockSignals(True); self.customer.clear()
        for item in self.customers.search(): self.customer.addItem(f"{item.customer_number} — {item.name}",item.id)
        if current:
            index=self.customer.findData(current)
            if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.refresh()

    def refresh(self,*_):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        for kind,table in self.tables.items():
            rows=self.operations.list_rows(kind,customer_id); table.setRowCount(len(rows))
            for r,row in enumerate(rows):
                if kind=="users": values=(row["display_name"],row["user_principal_name"],row["department"],row["license_name"],"Ja" if row["mfa_enabled"] else "Nee","Ja" if row["active"] else "Nee",row["id"])
                elif kind=="licenses": values=(row["product"],row["supplier"],row["quantity"],f"€ {row['unit_price_cents']/100:.2f}",row["renewal_date"],"Ja" if row["included_in_proposal"] else "Nee",row["id"])
                elif kind=="hardware": values=(row["kind"],row["brand"],row["model"],row["serial_number"],row["quantity"],row["status"],row["id"])
                else: values=(row["phase"],row["task_name"],row["owner"],row["start_date"],row["end_date"],row["status"],row["id"])
                for c,value in enumerate(values):table.setItem(r,c,QTableWidgetItem(str(value or "")))
        data=self.operations.intake(customer_id)
        for spin,key in zip(self.intake_counts,("users_count","devices_count","shared_mailboxes","teams_count","sharepoint_sites")):spin.setValue(data[key])
        self.migration.setCurrentText(data["migration_source"]); self.desired.setCurrentText(data["desired_date"]); self.scope.setPlainText(data["scope_notes"])

    def _add(self,kind):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        try:
            if kind=="users":
                name,ok=QInputDialog.getText(self,"Gebruiker","Naam"); 
                if not ok:return
                upn,ok=QInputDialog.getText(self,"Gebruiker","E-mailadres / UPN")
                if not ok:return
                license_name,ok=QInputDialog.getText(self,"Gebruiker","Licentie")
                if not ok:return
                self.operations.save_user(customer_id,name,upn,license_name=license_name)
            elif kind=="licenses":
                product,ok=QInputDialog.getText(self,"Licentie","Product")
                if not ok:return
                quantity,ok=QInputDialog.getInt(self,"Licentie","Aantal",1,1,100000)
                if not ok:return
                price,ok=QInputDialog.getDouble(self,"Licentie","Prijs per stuk excl. btw",0,0,1000000,2)
                if not ok:return
                self.operations.save_license(customer_id,product,quantity=quantity,unit_price_cents=round(price*100))
            elif kind=="hardware":
                hardware_kind,ok=QInputDialog.getText(self,"Hardware","Type")
                if not ok:return
                brand,ok=QInputDialog.getText(self,"Hardware","Merk")
                if not ok:return
                model,ok=QInputDialog.getText(self,"Hardware","Model")
                if not ok:return
                quantity,ok=QInputDialog.getInt(self,"Hardware","Aantal",1,1,100000)
                if not ok:return
                self.operations.save_hardware(customer_id,hardware_kind,brand,model,quantity=quantity)
            else:
                task,ok=QInputDialog.getText(self,"Projecttaak","Taak")
                if not ok:return
                phase,ok=QInputDialog.getItem(self,"Projecttaak","Fase",["Voorbereiding","Inventarisatie","Migratie","Implementatie","Oplevering"],0,False)
                if not ok:return
                self.operations.save_task(customer_id,phase,task)
            self.refresh()
        except Exception as exc:QMessageBox.warning(self,"Opslaan",str(exc))

    def _delete(self,kind):
        table=self.tables[kind]; row=table.currentRow(); item=table.item(row,table.columnCount()-1) if row>=0 else None
        if not item:return
        if QMessageBox.question(self,"Verwijderen","Dit geselecteerde onderdeel verwijderen?")!=QMessageBox.Yes:return
        self.operations.delete(kind,int(item.text())); self.refresh()

    def _save_intake(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        self.operations.save_intake(customer_id,*[spin.value() for spin in self.intake_counts],self.migration.currentText(),self.desired.currentText(),self.scope.toPlainText())
        QMessageBox.information(self,"Projectintake","De projectintake is opgeslagen.")

    def _check(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        warnings=self.operations.license_warnings(customer_id)
        QMessageBox.information(self,"Controle gebruikers/licenties","\n".join(f"• {x}" for x in warnings) if warnings else "Geen afwijkingen gevonden.")
