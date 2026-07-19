from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.documents.service import DocumentCenterService


class DocumentsPage(QWidget):
    def __init__(self, customers: CustomerService, service: DocumentCenterService, open_proposal, parent=None):
        super().__init__(parent); self.customers, self.service = customers, service
        self.open_proposal = open_proposal; self.template_id = None
        root = QVBoxLayout(self); title = QLabel("Document- en sjablooncentrum"); title.setObjectName("Title"); root.addWidget(title)
        subtitle = QLabel("Zoek klantdocumenten, offertes en rapportages en beheer de lokale NOWA-huisstijl.")
        subtitle.setObjectName("Subtitle"); root.addWidget(subtitle)
        tabs = QTabWidget(); tabs.addTab(self._documents_tab(), "Documenten"); tabs.addTab(self._templates_tab(), "Sjablonen")
        tabs.addTab(self._profile_tab(), "Huisstijl"); root.addWidget(tabs, 1); self.reload_customers(); self.reload_templates(); self.load_profile()

    def _documents_tab(self):
        page = QWidget(); box = QVBoxLayout(page); filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Zoek titel, klant, nummer of bestandsnaam…")
        self.customer = QComboBox(); self.kind = QComboBox(); self.kind.addItems(["Alles","Document","Offerte","Rapportage"])
        for widget in (self.search, self.customer, self.kind):
            (widget.textChanged if isinstance(widget,QLineEdit) else widget.currentIndexChanged).connect(self.refresh_documents)
        filters.addWidget(self.search,1); filters.addWidget(self.customer); filters.addWidget(self.kind); box.addLayout(filters)
        split = QSplitter(); self.documents = QTableWidget(0,8)
        self.documents.setHorizontalHeaderLabels(["Datum","Type","Klant","Titel","Status","Referentie","ID","Klant-ID"])
        self.documents.setColumnHidden(6,True); self.documents.setColumnHidden(7,True)
        self.documents.horizontalHeader().setStretchLastSection(True); self.documents.itemSelectionChanged.connect(self.preview_selected)
        self.documents.doubleClicked.connect(self.open_selected); split.addWidget(self.documents)
        self.preview = QTextEdit(); self.preview.setReadOnly(True); self.preview.setPlaceholderText("Selecteer een document voor een voorbeeld."); split.addWidget(self.preview)
        split.setSizes([850,430]); box.addWidget(split,1)
        open_button=QPushButton("Open geselecteerd"); open_button.setObjectName("Primary"); open_button.clicked.connect(self.open_selected)
        row=QHBoxLayout(); row.addWidget(open_button); row.addStretch(); box.addLayout(row); return page

    def _templates_tab(self):
        page=QWidget(); box=QVBoxLayout(page); split=QSplitter(); self.templates=QTableWidget(0,5)
        self.templates.setHorizontalHeaderLabels(["Type","Categorie","Naam","Samenvatting","ID"]); self.templates.setColumnHidden(4,True)
        self.templates.horizontalHeader().setStretchLastSection(True); self.templates.itemSelectionChanged.connect(self.load_template)
        split.addWidget(self.templates); editor=QWidget(); form=QFormLayout(editor)
        self.template_name=QLineEdit(); self.template_category=QLineEdit(); self.template_subject=QLineEdit(); self.template_body=QTextEdit()
        form.addRow("Naam",self.template_name); form.addRow("Categorie",self.template_category)
        form.addRow("Onderwerp",self.template_subject); form.addRow("Tekst",self.template_body)
        save=QPushButton("Mailsjabloon opslaan"); save.setObjectName("Primary"); save.clicked.connect(self.save_template); form.addRow("",save)
        split.addWidget(editor); split.setSizes([600,650]); box.addWidget(split); return page

    def _profile_tab(self):
        page=QWidget(); form=QFormLayout(page)
        self.company=QLineEdit(); self.address=QLineEdit(); self.postal_city=QLineEdit(); self.phone=QLineEdit()
        self.email=QLineEdit(); self.website=QLineEdit(); self.color=QLineEdit(); self.footer=QLineEdit()
        for label,widget in (("Bedrijfsnaam",self.company),("Adres",self.address),("Postcode en plaats",self.postal_city),
                             ("Telefoon",self.phone),("E-mail",self.email),("Website",self.website),
                             ("Primaire kleur",self.color),("Voettekst",self.footer)): form.addRow(label,widget)
        save=QPushButton("Huisstijl opslaan"); save.setObjectName("Primary"); save.clicked.connect(self.save_profile); form.addRow("",save)
        return page

    def reload_customers(self):
        current=self.customer.currentData(); self.customer.blockSignals(True); self.customer.clear(); self.customer.addItem("Alle klanten",None)
        for item in self.customers.search():self.customer.addItem(f"{item.customer_number} — {item.name}",item.id)
        if current is not None:
            index=self.customer.findData(current)
            if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.refresh_documents()

    def refresh_documents(self,*_):
        rows=self.service.search(self.search.text(),self.customer.currentData(),self.kind.currentText())
        self.documents.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["date"],row["kind"],row["customer_name"],row["title"],row["status"],row["reference"],row["id"],row["customer_id"])
            for c,value in enumerate(values):self.documents.setItem(r,c,QTableWidgetItem(str(value or "")))

    def preview_selected(self):
        row=self.documents.currentRow()
        if row<0:return
        kind=self.documents.item(row,1).text(); title=self.documents.item(row,3).text(); status=self.documents.item(row,4).text()
        reference=self.documents.item(row,5).text(); item_id=int(self.documents.item(row,6).text())
        if kind=="Rapportage":self.preview.setPlainText(self.service.report_preview(item_id))
        else:self.preview.setPlainText(f"{kind}\n\n{title}\nKlant: {self.documents.item(row,2).text()}\nStatus: {status}\nReferentie: {reference}")

    def open_selected(self,*_):
        row=self.documents.currentRow()
        if row<0:return
        kind=self.documents.item(row,1).text(); item_id=int(self.documents.item(row,6).text())
        try:
            if kind=="Document":QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.document_path(item_id))))
            elif kind=="Offerte":self.open_proposal(item_id)
            else:self.preview_selected()
        except Exception as exc:QMessageBox.warning(self,"Document openen",str(exc))

    def reload_templates(self):
        rows=self.service.templates(); self.templates.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["kind"],row.get("category",""),row["name"],row["summary"],row["id"])
            for c,value in enumerate(values):self.templates.setItem(r,c,QTableWidgetItem(str(value or "")))

    def load_template(self):
        row=self.templates.currentRow()
        if row<0:return
        if self.templates.item(row,0).text()!="E-mail":
            self.template_id=None; self.template_name.setText(self.templates.item(row,2).text())
            self.template_category.setText("Offerte"); self.template_subject.clear()
            self.template_body.setPlainText(self.templates.item(row,3).text()); return
        self.template_id=int(self.templates.item(row,4).text()); item=self.service.mail_template(self.template_id)
        self.template_name.setText(item["name"]); self.template_category.setText(item["category"])
        self.template_subject.setText(item["subject_template"]); self.template_body.setPlainText(item["body_template"])

    def save_template(self):
        try:
            self.service.mail.save_template(self.template_name.text(),self.template_subject.text(),
                                            self.template_body.toPlainText(),self.template_category.text())
            self.reload_templates(); QMessageBox.information(self,"Sjabloon","Mailsjabloon lokaal opgeslagen.")
        except Exception as exc:QMessageBox.warning(self,"Sjabloon",str(exc))

    def load_profile(self):
        p=self.service.profile()
        for widget,key in ((self.company,"company_name"),(self.address,"address"),(self.postal_city,"postal_city"),
                           (self.phone,"phone"),(self.email,"email"),(self.website,"website"),
                           (self.color,"primary_color"),(self.footer,"footer_text")):widget.setText(p.get(key,""))

    def save_profile(self):
        try:
            self.service.save_profile(self.company.text(),self.address.text(),self.postal_city.text(),self.phone.text(),
                                      self.email.text(),self.website.text(),self.color.text(),self.footer.text())
            QMessageBox.information(self,"Huisstijl","Huisstijl lokaal opgeslagen en actief voor nieuwe offerte-PDF's.")
        except Exception as exc:QMessageBox.warning(self,"Huisstijl",str(exc))
