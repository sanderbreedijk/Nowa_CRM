from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.planning.service import PlanningService


class PlanningPage(QWidget):
    def __init__(self,customers: CustomerService,planning: PlanningService,parent=None):
        super().__init__(parent); self.customers,self.planning=customers,planning; self.task_id=None
        root=QVBoxLayout(self); title=QLabel("Projectplanning"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Plan fases, afhankelijkheden, eigenaren en deadlines; exporteer naar PDF of CSV."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        top=QHBoxLayout(); self.customer=QComboBox(); self.customer.currentIndexChanged.connect(self.refresh)
        seed=QPushButton("Standaardplanning vullen"); seed.clicked.connect(self.seed)
        pdf=QPushButton("Planning-PDF"); pdf.clicked.connect(self.export_pdf); csv=QPushButton("CSV-export"); csv.clicked.connect(self.export_csv)
        top.addWidget(self.customer,1); top.addWidget(seed); top.addWidget(pdf); top.addWidget(csv); root.addLayout(top)
        self.summary=QLabel(); self.summary.setObjectName("Subtitle"); root.addWidget(self.summary)
        split=QSplitter(); self.table=QTableWidget(0,9)
        self.table.setHorizontalHeaderLabels(["Fase","Taak","Eigenaar","Start","Einde","Afhankelijkheid","Status","Notities","ID"])
        self.table.setColumnHidden(8,True); self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.load_selected); split.addWidget(self.table)
        editor=QWidget(); form=QFormLayout(editor); self.phase=QComboBox(); self.phase.setEditable(True); self.phase.addItems(planning.PHASES)
        self.task=QLineEdit(); self.owner=QLineEdit("NOWA"); self.start=QLineEdit(); self.start.setPlaceholderText("JJJJ-MM-DD")
        self.end=QLineEdit(); self.end.setPlaceholderText("JJJJ-MM-DD"); self.dependency=QLineEdit()
        self.status=QComboBox(); self.status.addItems(planning.STATUSES); self.notes=QTextEdit(); self.notes.setMaximumHeight(120)
        for label,control in (("Fase",self.phase),("Taak",self.task),("Eigenaar",self.owner),("Start",self.start),
                              ("Einde",self.end),("Afhankelijkheid",self.dependency),("Status",self.status),("Notities",self.notes)):
            form.addRow(label,control)
        buttons=QHBoxLayout(); new=QPushButton("Nieuw"); new.clicked.connect(self.clear)
        save=QPushButton("Opslaan"); save.setObjectName("Primary"); save.clicked.connect(self.save)
        delete=QPushButton("Verwijderen"); delete.clicked.connect(self.delete)
        buttons.addWidget(new); buttons.addWidget(save); buttons.addWidget(delete); form.addRow("",buttons)
        split.addWidget(editor); split.setSizes([900,430]); root.addWidget(split,1); self.reload_customers()

    def reload_customers(self):
        selected=self.customer.currentData(); self.customer.blockSignals(True); self.customer.clear()
        for item in self.customers.search():self.customer.addItem(f"{item.customer_number} — {item.name}",item.id)
        index=self.customer.findData(selected)
        if index>=0:self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.refresh()

    def refresh(self,*_):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        rows=self.planning.list(customer_id); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=tuple(row[key] for key in ("phase","task_name","owner","start_date","end_date","dependency","status","notes","id"))
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.planning.stats(customer_id)
        self.summary.setText(f"{stats['progress']}% gereed · {stats['open']} open · {stats['overdue']} te laat · {stats['waiting']} wachtend")

    def load_selected(self):
        row=self.table.currentRow()
        if row<0:return
        self.task_id=int(self.table.item(row,8).text())
        values=[self.table.item(row,c).text() for c in range(8)]
        self.phase.setCurrentText(values[0]); self.task.setText(values[1]); self.owner.setText(values[2])
        self.start.setText(values[3]); self.end.setText(values[4]); self.dependency.setText(values[5])
        self.status.setCurrentText(values[6]); self.notes.setPlainText(values[7])

    def clear(self):
        self.task_id=None; self.phase.setCurrentIndex(0); self.task.clear(); self.owner.setText("NOWA")
        self.start.clear(); self.end.clear(); self.dependency.clear(); self.status.setCurrentIndex(0); self.notes.clear(); self.table.clearSelection()

    def save(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        try:
            self.task_id=self.planning.save(customer_id,self.phase.currentText(),self.task.text(),self.owner.text(),
                self.start.text(),self.end.text(),self.dependency.text(),self.status.currentText(),self.notes.toPlainText(),self.task_id)
            self.refresh()
        except Exception as exc:QMessageBox.warning(self,"Projecttaak",str(exc))

    def delete(self):
        if not self.task_id:return
        if QMessageBox.question(self,"Projecttaak","Geselecteerde projecttaak verwijderen?")!=QMessageBox.Yes:return
        self.planning.delete(self.task_id); self.clear(); self.refresh()

    def seed(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        count=self.planning.seed(customer_id); self.refresh()
        QMessageBox.information(self,"Standaardplanning",f"{count} projecttaken toegevoegd." if count else "Er bestaat al een planning voor deze klant.")

    def export_pdf(self):self._export(self.planning.export_pdf,"Planning-PDF")
    def export_csv(self):self._export(self.planning.export_csv,"CSV-export")
    def _export(self,method,title):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        try:QDesktopServices.openUrl(QUrl.fromLocalFile(str(method(customer_id))))
        except Exception as exc:QMessageBox.warning(self,title,str(exc))
