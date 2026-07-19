from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.proposals.pdf import export_proposal_pdf


def money(cents: int) -> str:
    return f"€ {cents/100:,.2f}".replace(",","X").replace(".",",").replace("X",".")


class ProposalDialog(QDialog):
    def __init__(self, service: ProposalService, proposal_id: int, parent=None):
        super().__init__(parent); self.service=service; self.proposal_id=proposal_id; self.setWindowTitle("Offerte bewerken"); self.resize(900,620)
        box=QVBoxLayout(self); self.heading=QLabel(); self.heading.setObjectName("Title"); box.addWidget(self.heading)
        statusrow=QHBoxLayout(); statusrow.addWidget(QLabel("Status")); self.status=QComboBox(); self.status.addItems(service.STATUSES); self.status.currentTextChanged.connect(self._status_changed); statusrow.addWidget(self.status); statusrow.addStretch(); box.addLayout(statusrow)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["Soort","Omschrijving","Aantal","Prijs","Regeltotaal","ID"]); self.table.setColumnHidden(5,True); self.table.horizontalHeader().setStretchLastSection(True); box.addWidget(self.table,1)
        form=QFormLayout(); self.kind=QComboBox(); self.kind.addItems(["dienst","uren","licentie","hardware","korting"]); self.description=QLineEdit(); self.quantity=QDoubleSpinBox(); self.quantity.setRange(.01,99999); self.quantity.setDecimals(2); self.quantity.setValue(1); self.price=QDoubleSpinBox(); self.price.setRange(0,9999999); self.price.setDecimals(2); self.price.setPrefix("€ ")
        form.addRow("Soort",self.kind); form.addRow("Omschrijving",self.description); form.addRow("Aantal",self.quantity); form.addRow("Eenheidsprijs excl. btw",self.price); box.addLayout(form)
        catalogrow=QHBoxLayout(); self.catalog=QComboBox(); self.catalog.setMinimumWidth(320); self._reload_catalog(); add_catalog=QPushButton("Uit catalogus toevoegen"); add_catalog.clicked.connect(self._add_catalog); manage_catalog=QPushButton("Nieuw catalogusartikel"); manage_catalog.clicked.connect(self._new_catalog_item); catalogrow.addWidget(QLabel("Product- en dienstencatalogus")); catalogrow.addWidget(self.catalog,1); catalogrow.addWidget(add_catalog); catalogrow.addWidget(manage_catalog); box.addLayout(catalogrow)
        actions=QHBoxLayout(); add=QPushButton("Regel toevoegen"); add.setObjectName("Primary"); add.clicked.connect(self._add); delete=QPushButton("Geselecteerde regel verwijderen"); delete.clicked.connect(self._delete)
        self.template=QComboBox(); self.template.addItem("Kies offertesjabloon…",None); [self.template.addItem(x["name"],x["id"]) for x in service.templates()]
        apply=QPushButton("Sjabloon toepassen"); apply.clicked.connect(self._apply_template); text=QPushButton("Intro en voorwaarden"); text.clicked.connect(self._edit_texts); save_template=QPushButton("Opslaan als sjabloon"); save_template.clicked.connect(self._save_template); duplicate=QPushButton("Offerte dupliceren"); duplicate.clicked.connect(self._duplicate); pdf=QPushButton("Professionele PDF"); pdf.clicked.connect(self._pdf)
        actions.addWidget(add); actions.addWidget(delete); actions.addStretch(); actions.addWidget(self.template); actions.addWidget(apply); actions.addWidget(text); actions.addWidget(save_template); actions.addWidget(duplicate); actions.addWidget(pdf); box.addLayout(actions)
        self.total=QLabel(); self.total.setStyleSheet("font-size:18px;font-weight:700;color:#0B2342"); box.addWidget(self.total)
        buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(self.reject); box.addWidget(buttons); self.refresh()
    def refresh(self):
        p=self.service.get(self.proposal_id)
        if not p:return
        self.heading.setText(f"{p.number} — {p.title} — {p.customer_name}"); self.status.blockSignals(True); self.status.setCurrentText(p.status); self.status.blockSignals(False)
        lines=self.service.lines(self.proposal_id); self.table.setRowCount(len(lines))
        for r,x in enumerate(lines):
            vals=(x.kind,x.description,f"{x.quantity:g}",money(x.unit_price_cents),money(x.line_total_cents),str(x.id))
            for c,v in enumerate(vals):self.table.setItem(r,c,QTableWidgetItem(v))
        totals=self.service.totals(self.proposal_id); self.total.setText(f"Excl. btw: {money(totals['subtotal_cents'])}   |   Btw 21%: {money(totals['vat_cents'])}   |   Incl. btw: {money(totals['total_cents'])}")
    def _add(self):
        try:self.service.add_line(self.proposal_id,self.kind.currentText(),self.description.text(),self.quantity.value(),round(self.price.value()*100)); self.description.clear(); self.refresh()
        except Exception as e:QMessageBox.warning(self,"Offerteregel",str(e))
    def _reload_catalog(self):
        current=self.catalog.currentData() if hasattr(self,"catalog") else None
        if not hasattr(self,"catalog"):return
        self.catalog.clear();self.catalog.addItem("Kies product of dienst…",None)
        for item in self.service.catalog():self.catalog.addItem(f"{item['code']} — {item['name']} ({money(item['unit_price_cents'])} / {item['unit']})",item['id'])
        index=self.catalog.findData(current)
        if index>=0:self.catalog.setCurrentIndex(index)
    def _add_catalog(self):
        item_id=self.catalog.currentData()
        if not item_id:return
        try:self.service.add_catalog_line(self.proposal_id,item_id,self.quantity.value());self.refresh()
        except Exception as e:QMessageBox.warning(self,"Catalogus",str(e))
    def _new_catalog_item(self):
        code,ok=QInputDialog.getText(self,"Catalogusartikel","Artikelcode")
        if not ok:return
        name,ok=QInputDialog.getText(self,"Catalogusartikel","Naam")
        if not ok:return
        category,ok=QInputDialog.getItem(self,"Catalogusartikel","Categorie",["Dienst","Uren","Licentie","Hardware"],0,False)
        if not ok:return
        unit,ok=QInputDialog.getText(self,"Catalogusartikel","Eenheid",text="stuk")
        if not ok:return
        price,ok=QInputDialog.getDouble(self,"Catalogusartikel","Prijs excl. btw",0,0,9999999,2)
        if not ok:return
        try:self.service.save_catalog_item(code,name,category,unit,round(price*100));self._reload_catalog()
        except Exception as e:QMessageBox.warning(self,"Catalogus",str(e))
    def _delete(self):
        row=self.table.currentRow(); item=self.table.item(row,5) if row>=0 else None
        if item:self.service.delete_line(int(item.text())); self.refresh()
    def _status_changed(self,status):self.service.set_status(self.proposal_id,status); self.refresh()
    def _apply_template(self):
        template_id=self.template.currentData()
        if not template_id:return
        try:self.service.apply_template(self.proposal_id,template_id); self.refresh()
        except Exception as e:QMessageBox.warning(self,"Offertesjabloon",str(e))
    def _edit_texts(self):
        proposal=self.service.get(self.proposal_id)
        intro,ok=QInputDialog.getMultiLineText(self,"Offertetekst","Introductie",proposal.introduction)
        if not ok:return
        terms,ok=QInputDialog.getMultiLineText(self,"Offertetekst","Aanvullende voorwaarden / afspraken",proposal.terms)
        if ok:self.service.save_texts(self.proposal_id,intro,terms);self.refresh()
    def _save_template(self):
        name,ok=QInputDialog.getText(self,"Offertesjabloon","Naam van het nieuwe sjabloon")
        if not ok:return
        try:
            template_id=self.service.save_as_template(self.proposal_id,name);self.template.addItem(name,template_id);self.template.setCurrentIndex(self.template.count()-1)
        except Exception as e:QMessageBox.warning(self,"Offertesjabloon",str(e))
    def _duplicate(self):
        try:
            self.proposal_id=self.service.duplicate(self.proposal_id);self.refresh();QMessageBox.information(self,"Offerte gedupliceerd","Een nieuw concept is gemaakt en staat nu open.")
        except Exception as e:QMessageBox.warning(self,"Offerte dupliceren",str(e))
    def _pdf(self):
        try:
            path=export_proposal_pdf(self.service,self.proposal_id)
            if QMessageBox.question(self,"Offerte gereed",f"PDF opgeslagen:\n{path}\n\nNu openen?")==QMessageBox.Yes:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:QMessageBox.warning(self,"PDF export",str(e))
