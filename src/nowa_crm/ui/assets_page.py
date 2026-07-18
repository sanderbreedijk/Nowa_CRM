from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.assets.service import CustomerAssetsService


class CustomerAssetsPage(QWidget):
    def __init__(self,customers: CustomerService,service: CustomerAssetsService,parent=None):
        super().__init__(parent); self.customers=customers; self.service=service
        root=QVBoxLayout(self); title=QLabel("Locaties, software en documenten"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Beheer lokale klantassets en open documenten rechtstreeks vanuit het klantdossier."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        self.customer=QComboBox(); self.customer.currentIndexChanged.connect(self.reload); root.addWidget(self.customer)
        tabs=QTabWidget(); root.addWidget(tabs,1)
        self.locations=self._tab(tabs,"Locaties",["Naam","Adres","Plaats","Notities","ID"],self.add_location)
        self.software=self._tab(tabs,"Software",["Applicatie","Leverancier","Versie","Support","Notities","ID"],self.add_software)
        self.documents=self._tab(tabs,"Documenten",["Titel","Type","Bestandsnaam","Grootte","Datum","ID"],self.add_document,True)
        self.reload_customers()

    def _tab(self,tabs,title,headers,add_action,double_open=False):
        page=QWidget(); box=QVBoxLayout(page); row=QHBoxLayout(); add=QPushButton(f"Nieuwe {title[:-1].lower()}"); add.setObjectName("Primary"); add.clicked.connect(add_action); row.addStretch(); row.addWidget(add); box.addLayout(row)
        table=QTableWidget(0,len(headers)); table.setHorizontalHeaderLabels(headers); table.setColumnHidden(len(headers)-1,True); table.horizontalHeader().setStretchLastSection(True)
        if double_open:table.doubleClicked.connect(self.open_document)
        box.addWidget(table); tabs.addTab(page,title); return table

    def reload_customers(self):
        current=self.customer.currentData(); self.customer.blockSignals(True); self.customer.clear()
        for item in self.customers.search():self.customer.addItem(f"{item.customer_number} — {item.name}",item.id)
        if current:
            i=self.customer.findData(current)
            if i>=0:self.customer.setCurrentIndex(i)
        self.customer.blockSignals(False); self.reload()

    def reload(self,*_):
        customer_id=self.customer.currentData()
        if not customer_id:return
        self._fill(self.locations,self.service.list("locations",customer_id),("name","address","city","notes","id"))
        self._fill(self.software,self.service.list("software",customer_id),("name","vendor","version","support_scope","notes","id"))
        docs=self.service.list("documents",customer_id)
        self._fill(self.documents,[{**x,"size":f"{x['size_bytes']/1024:.1f} KB"} for x in docs],("title","document_type","original_name","size","created_at","id"))

    @staticmethod
    def _fill(table,rows,keys):
        table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,key in enumerate(keys):table.setItem(r,c,QTableWidgetItem(str(row[key] or "")))

    def add_location(self):
        if not self.customer.currentData():return
        name,ok=QInputDialog.getText(self,"Nieuwe locatie","Naam")
        if not ok or not name.strip():return
        address,_=QInputDialog.getText(self,"Nieuwe locatie","Adres"); city,_=QInputDialog.getText(self,"Nieuwe locatie","Plaats")
        self.service.add_location(self.customer.currentData(),name,address,city); self.reload()

    def add_software(self):
        if not self.customer.currentData():return
        name,ok=QInputDialog.getText(self,"Nieuwe software","Applicatie")
        if not ok or not name.strip():return
        vendor,_=QInputDialog.getText(self,"Nieuwe software","Leverancier"); version,_=QInputDialog.getText(self,"Nieuwe software","Versie")
        support,_=QInputDialog.getText(self,"Nieuwe software","Supportafspraak")
        self.service.add_software(self.customer.currentData(),name,vendor,version,support); self.reload()

    def add_document(self):
        if not self.customer.currentData():return
        filename,_=QFileDialog.getOpenFileName(self,"Document selecteren","","Documenten (*.pdf *.docx *.xlsx *.txt *.csv);;Alle bestanden (*)")
        if not filename:return
        title,ok=QInputDialog.getText(self,"Document toevoegen","Titel",text=Path(filename).stem)
        if not ok:return
        kind,ok=QInputDialog.getItem(self,"Document toevoegen","Type",["Algemeen","Contract","Offerte","Techniek","Rapport","Handleiding"],0,False)
        if ok:self.service.add_document(self.customer.currentData(),title,Path(filename),kind); self.reload()

    def open_document(self,*_):
        row=self.documents.currentRow(); item=self.documents.item(row,5) if row>=0 else None
        if not item:return
        try:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.document_path(int(item.text())))))
        except Exception as exc:QMessageBox.warning(self,"Document openen",str(exc))
