from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QDoubleSpinBox,QFormLayout,
    QHBoxLayout,QInputDialog,QLabel,QLineEdit,QMessageBox,QPushButton,QTableWidget,
    QTableWidgetItem,QTabWidget,QTextEdit,QVBoxLayout)

from nowa_crm.modules.proposals.pdf import export_proposal_pdf
from nowa_crm.modules.proposals.service import ProposalService

def money(cents:int)->str:
    return f"EUR {cents/100:,.2f}".replace(",","X").replace(".",",").replace("X",".")

class ProposalDialog(QDialog):
    def __init__(self,service:ProposalService,proposal_id:int,parent=None):
        super().__init__(parent);self.service=service;self.proposal_id=proposal_id
        self.setWindowTitle("Professionele offerte-editor");self.resize(1220,760);box=QVBoxLayout(self)
        self.heading=QLabel();self.heading.setObjectName("Title");box.addWidget(self.heading)
        row=QHBoxLayout();row.addWidget(QLabel("Status"));self.status=QComboBox();self.status.addItems(service.STATUSES);self.status.currentTextChanged.connect(self._status);row.addWidget(self.status);row.addStretch();box.addLayout(row)
        self.table=QTableWidget(0,9);self.table.setHorizontalHeaderLabels(["Actief","Groep","Soort","Omschrijving","Aantal","Periode","Prijs","Totaal","ID"]);self.table.setColumnHidden(8,True);self.table.horizontalHeader().setStretchLastSection(True);box.addWidget(self.table,1)
        form=QFormLayout();self.group=QLineEdit();self.group.setPlaceholderText("Bijvoorbeeld Migratie, Licenties of Hardware");self.kind=QComboBox();self.kind.addItems(["dienst","uren","licentie","hardware","korting"]);self.description=QLineEdit();self.quantity=QDoubleSpinBox();self.quantity.setRange(.01,99999);self.quantity.setDecimals(2);self.quantity.setValue(1);self.period=QComboBox();self.period.addItems(["eenmalig","maandelijks"]);self.price=QDoubleSpinBox();self.price.setRange(0,9999999);self.price.setDecimals(2);self.price.setPrefix("EUR ")
        for label,widget in (("Groep",self.group),("Soort",self.kind),("Omschrijving",self.description),("Aantal",self.quantity),("Facturatie",self.period),("Eenheidsprijs excl. btw",self.price)):form.addRow(label,widget)
        box.addLayout(form)
        catalogrow=QHBoxLayout();self.catalog=QComboBox();self.catalog.setMinimumWidth(300);self._reload_catalog();catalogrow.addWidget(QLabel("Catalogus"));catalogrow.addWidget(self.catalog,1);b=QPushButton("Toevoegen uit catalogus");b.clicked.connect(self._add_catalog);catalogrow.addWidget(b);box.addLayout(catalogrow)
        actions=QHBoxLayout()
        for label,callback in (("Regel toevoegen",self._add),("Verwijderen",self._delete),("In-/uitschakelen",self._toggle),("Omhoog",lambda:self._move(-1)),("Omlaag",lambda:self._move(1))):
            b=QPushButton(label);b.clicked.connect(callback);actions.addWidget(b)
        actions.addStretch();box.addLayout(actions)
        actions=QHBoxLayout();self.template=QComboBox();self.template.addItem("Kies sjabloon...",None)
        for x in service.templates():self.template.addItem(x["name"],x["id"])
        actions.addWidget(self.template)
        for label,callback in (("Sjabloon toepassen",self._apply_template),("Hoofdstukken",self._sections),("Licenties/hardware uit dossier",self._assets),("Bereken uit intake",self._calculate),("Revisie bewaren",self._revision),("Voorbeeld / PDF",self._pdf)):
            b=QPushButton(label);b.clicked.connect(callback);actions.addWidget(b)
        box.addLayout(actions);self.total=QLabel();self.total.setStyleSheet("font-size:18px;font-weight:700;color:#0B2342");box.addWidget(self.total)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(self.reject);box.addWidget(buttons);self.refresh()

    def refresh(self):
        p=self.service.get(self.proposal_id)
        if not p:return
        self.heading.setText(f"{p.number} - revisie {p.revision} - {p.title} - {p.customer_name}");self.status.blockSignals(True);self.status.setCurrentText(p.status);self.status.blockSignals(False)
        lines=self.service.lines(self.proposal_id);self.table.setRowCount(len(lines))
        for r,x in enumerate(lines):
            for c,v in enumerate(("Ja" if x.active else "Nee",x.group_name,x.kind,x.description,f"{x.quantity:g}",x.billing_period,money(x.unit_price_cents),money(x.line_total_cents),str(x.id))):self.table.setItem(r,c,QTableWidgetItem(v))
        t=self.service.totals(self.proposal_id);self.total.setText(f"Eenmalig excl. btw: {money(t['subtotal_cents'])}  |  incl. btw: {money(t['total_cents'])}  |  maandelijks excl. btw: {money(self.service.monthly_total(self.proposal_id))}")

    def _selected(self):
        row=self.table.currentRow();item=self.table.item(row,8) if row>=0 else None;return int(item.text()) if item else None
    def _status(self,value):self.service.set_status(self.proposal_id,value);self.refresh()
    def _add(self):
        try:self.service.add_line(self.proposal_id,self.kind.currentText(),self.description.text(),self.quantity.value(),round(self.price.value()*100),self.period.currentText(),self.group.text());self.description.clear();self.refresh()
        except Exception as e:QMessageBox.warning(self,"Offerteregel",str(e))
    def _delete(self):
        if self._selected():self.service.delete_line(self._selected());self.refresh()
    def _toggle(self):
        line_id=self._selected()
        if line_id:
            line=next(x for x in self.service.lines(self.proposal_id) if x.id==line_id);self.service.set_line_active(line_id,not bool(line.active));self.refresh()
    def _move(self,direction):
        if self._selected():self.service.move_line(self._selected(),direction);self.refresh()
    def _reload_catalog(self):
        self.catalog.clear();self.catalog.addItem("Kies product of dienst...",None)
        for x in self.service.catalog():self.catalog.addItem(f"{x['code']} - {x['name']} ({money(x['unit_price_cents'])})",x["id"])
    def _add_catalog(self):
        if self.catalog.currentData():self.service.add_catalog_line(self.proposal_id,self.catalog.currentData(),self.quantity.value());self.refresh()
    def _apply_template(self):
        try:
            if self.template.currentData():self.service.apply_template(self.proposal_id,self.template.currentData());self.refresh()
        except Exception as e:QMessageBox.warning(self,"Sjabloon",str(e))
    def _sections(self):
        dialog=QDialog(self);dialog.setWindowTitle("Offertehoofdstukken");dialog.resize(820,620);layout=QVBoxLayout(dialog);tabs=QTabWidget();editors={};current=self.service.sections(self.proposal_id)
        for key,title in self.service.SECTION_TITLES.items():editor=QTextEdit();editor.setPlainText(current.get(key,""));editors[key]=editor;tabs.addTab(editor,title)
        layout.addWidget(tabs);buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.service.save_sections(self.proposal_id,{k:e.toPlainText() for k,e in editors.items()});self.refresh()
    def _assets(self):
        try:r=self.service.add_customer_assets(self.proposal_id);self.refresh();QMessageBox.information(self,"Klantdossier",f"Toegevoegd: {r['licenses']} licenties en {r['hardware']} hardware-regels.")
        except Exception as e:QMessageBox.warning(self,"Klantdossier",str(e))
    def _calculate(self):
        if QMessageBox.question(self,"Intakecalculatie","Automatisch berekende uren opnieuw opbouwen?")!=QMessageBox.Yes:return
        try:hours=self.service.calculate_from_intake(self.proposal_id);self.refresh();QMessageBox.information(self,"Intakecalculatie",f"Berekend: {hours:g} uur.")
        except Exception as e:QMessageBox.warning(self,"Intakecalculatie",str(e))
    def _revision(self):
        label,ok=QInputDialog.getText(self,"Nieuwe revisie","Omschrijving van de wijziging")
        if ok:r=self.service.create_revision(self.proposal_id,label);self.refresh();QMessageBox.information(self,"Revisie",f"Revisie {r} is bewaard.")
    def _pdf(self):
        try:
            warnings=self.service.validate(self.proposal_id)
            if warnings and QMessageBox.question(self,"Offertecontrole","Let op:\n\n"+"\n".join("- "+x for x in warnings)+"\n\nToch doorgaan?")!=QMessageBox.Yes:return
            path=export_proposal_pdf(self.service,self.proposal_id)
            if QMessageBox.question(self,"Voorbeeld gereed",f"PDF opgeslagen:\n{path}\n\nNu openen?")==QMessageBox.Yes:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:QMessageBox.warning(self,"PDF export",str(e))

