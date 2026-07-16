from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from nowa_crm.modules.proposals.service import ProposalService


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
        actions=QHBoxLayout(); add=QPushButton("Regel toevoegen"); add.setObjectName("Primary"); add.clicked.connect(self._add); delete=QPushButton("Geselecteerde regel verwijderen"); delete.clicked.connect(self._delete); actions.addWidget(add); actions.addWidget(delete); actions.addStretch(); box.addLayout(actions)
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
    def _delete(self):
        row=self.table.currentRow(); item=self.table.item(row,5) if row>=0 else None
        if item:self.service.delete_line(int(item.text())); self.refresh()
    def _status_changed(self,status):self.service.set_status(self.proposal_id,status); self.refresh()
