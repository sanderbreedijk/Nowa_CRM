from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.reporting.service import ReportingService


class ReportingPage(QWidget):
    def __init__(self, customers: CustomerService, reporting: ReportingService, open_mail, parent=None):
        super().__init__(parent)
        self.customers, self.reporting, self.open_mail = customers, reporting, open_mail
        root = QVBoxLayout(self)
        title = QLabel("Projectrapportages"); title.setObjectName("Title"); root.addWidget(title)
        sub = QLabel("Maak vanuit de lokale CRM-gegevens direct een managementsamenvatting en voortgangsmail.")
        sub.setObjectName("Subtitle"); root.addWidget(sub)
        row = QHBoxLayout(); self.customer = QComboBox(); self.customer.currentIndexChanged.connect(self.refresh)
        preview = QPushButton("Voorbeeld vernieuwen"); preview.clicked.connect(self.refresh)
        save = QPushButton("Rapport lokaal opslaan"); save.clicked.connect(self.export)
        mail = QPushButton("Als mailconcept klaarzetten"); mail.setObjectName("Primary"); mail.clicked.connect(self.to_mail)
        row.addWidget(self.customer, 1); row.addWidget(preview); row.addWidget(save); row.addWidget(mail); root.addLayout(row)
        self.summary = QLabel("Selecteer een klant."); self.summary.setObjectName("Subtitle"); root.addWidget(self.summary)
        self.body = QTextEdit(); self.body.setReadOnly(True); root.addWidget(self.body, 2)
        root.addWidget(QLabel("Eerder gemaakte rapportages"))
        self.history = QTableWidget(0, 5)
        self.history.setHorizontalHeaderLabels(["Datum", "Type", "Onderwerp", "Voortgang", "ID"])
        self.history.setColumnHidden(4, True); self.history.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.history, 1)
        self.reload_customers()

    def reload_customers(self):
        selected = self.customer.currentData()
        self.customer.blockSignals(True); self.customer.clear()
        for customer in self.customers.search():
            self.customer.addItem(f"{customer.customer_number} — {customer.name}", customer.id)
        index = self.customer.findData(selected)
        if index >= 0: self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.refresh()

    def refresh(self, *_):
        customer_id = self.customer.currentData()
        if customer_id is None:
            self.body.clear(); self.history.setRowCount(0); return
        try:
            report = self.reporting.compose(customer_id)
            data = self.reporting.snapshot(customer_id)
            self.summary.setText(
                f"{report['progress']}% voortgang · {len(data['actions'])} open acties · "
                f"{len(data['tickets'])} open tickets · {len(data['risks'])} aandachtspunten")
            self.body.setPlainText(f"Onderwerp: {report['subject']}\n\n{report['body']}")
            rows = self.reporting.history(customer_id); self.history.setRowCount(len(rows))
            for r, item in enumerate(rows):
                values = (item["created_at"], item["report_type"], item["subject"],
                          f"{item['progress_percent']}%", str(item["id"]))
                for c, value in enumerate(values): self.history.setItem(r, c, QTableWidgetItem(value))
        except Exception as exc:
            QMessageBox.warning(self, "Projectrapportage", str(exc))

    def export(self):
        customer_id = self.customer.currentData()
        if customer_id is None: return
        try:
            path = self.reporting.export_text(customer_id)
            self.refresh(); QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:
            QMessageBox.warning(self, "Rapport opslaan", str(exc))

    def to_mail(self):
        customer_id = self.customer.currentData()
        if customer_id is None: return
        try:
            message_id = self.reporting.create_mail_draft(customer_id)
            self.refresh(); self.open_mail(message_id)
            QMessageBox.information(self, "Voortgangsmail", "Het rapport staat lokaal klaar als mailconcept.")
        except Exception as exc:
            QMessageBox.warning(self, "Voortgangsmail", str(exc))
