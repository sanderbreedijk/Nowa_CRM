from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from nowa_crm.modules.communications.service import CommunicationService
from nowa_crm.modules.customers.service import CustomerService


class CommunicationsPage(QWidget):
    def __init__(self, customers: CustomerService, service: CommunicationService, open_mail, open_call, create_ticket=None, parent=None):
        super().__init__(parent)
        self.customers, self.service = customers, service
        self.open_mail, self.open_call = open_mail, open_call
        self.create_ticket = create_ticket
        root = QVBoxLayout(self)
        title = QLabel("Communicatiecentrum"); title.setObjectName("Title"); root.addWidget(title)
        subtitle = QLabel("Alle e-mails en telefoongesprekken per klant in één doorzoekbare tijdlijn.")
        subtitle.setObjectName("Subtitle"); root.addWidget(subtitle)
        filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Zoek op klant, onderwerp, adres, nummer of inhoud…")
        self.customer = QComboBox(); self.channel = QComboBox(); self.channel.addItems(["Alles", "E-mail", "Telefoon"])
        self.search.textChanged.connect(self.refresh); self.customer.currentIndexChanged.connect(self.refresh)
        self.channel.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 1); filters.addWidget(self.customer); filters.addWidget(self.channel)
        root.addLayout(filters)
        grid = QGridLayout(); self.kpis = []
        for column, label in enumerate(("Totaal", "Inkomend", "Uitgaand", "Nog te verwerken")):
            card = QFrame(); card.setObjectName("Card"); box = QVBoxLayout(card)
            value = QLabel("0"); value.setObjectName("Kpi"); box.addWidget(value); box.addWidget(QLabel(label))
            grid.addWidget(card, 0, column); self.kpis.append(value)
        root.addLayout(grid)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["Datum", "Kanaal", "Klant", "Richting", "Onderwerp",
                                               "Contact / nummer", "Status", "ID", "Type", "Klant-ID"])
        self.table.setColumnHidden(7, True); self.table.setColumnHidden(8, True); self.table.setColumnHidden(9, True)
        self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.open_selected)
        root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        open_item = QPushButton("Open geselecteerd"); open_item.setObjectName("Primary"); open_item.clicked.connect(self.open_selected)
        mail = QPushButton("Naar Mail"); mail.clicked.connect(lambda: self.open_mail(None))
        call = QPushButton("Naar Telefonie"); call.clicked.connect(lambda: self.open_call(None))
        ticket = QPushButton("Maak serviceticket"); ticket.clicked.connect(self.ticket_selected)
        actions.addWidget(open_item); actions.addWidget(ticket); actions.addWidget(mail); actions.addWidget(call); actions.addStretch()
        root.addLayout(actions); self.reload_customers()

    def reload_customers(self):
        current = self.customer.currentData()
        self.customer.blockSignals(True); self.customer.clear(); self.customer.addItem("Alle klanten", None)
        for item in self.customers.search(): self.customer.addItem(f"{item.customer_number} — {item.name}", item.id)
        if current is not None:
            index = self.customer.findData(current)
            if index >= 0: self.customer.setCurrentIndex(index)
        self.customer.blockSignals(False); self.refresh()

    def refresh(self, *_):
        customer_id = self.customer.currentData()
        rows = self.service.timeline(customer_id, self.search.text(), self.channel.currentText())
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (row["date"], row["channel"], row["customer"], row["direction"], row["subject"],
                      row["contact"], row["status"], row["id"], row["channel"], row["customer_id"])
            for column, value in enumerate(values): self.table.setItem(row_index, column, QTableWidgetItem(str(value or "")))
        stats = self.service.stats(customer_id)
        for label, value in zip(self.kpis, (stats["total"], stats["incoming"], stats["outgoing"], stats["open"])):
            label.setText(str(value))

    def open_selected(self, *_):
        row = self.table.currentRow()
        item_id = self.table.item(row, 7) if row >= 0 else None
        channel = self.table.item(row, 8) if row >= 0 else None
        if not item_id or not channel: return
        if channel.text() == "E-mail": self.open_mail(int(item_id.text()))
        else: self.open_call(int(item_id.text()))

    def ticket_selected(self):
        row=self.table.currentRow()
        if row<0 or not self.create_ticket:return
        customer_id=self.table.item(row,9)
        if not customer_id or not customer_id.text():return
        self.create_ticket(int(customer_id.text()),self.table.item(row,4).text(),
                           f"Bron: {self.table.item(row,1).text()} · {self.table.item(row,5).text()}",
                           self.table.item(row,8).text(),int(self.table.item(row,7).text()))
