from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from nowa_crm.modules.proposals.approval import ProposalApprovalService
from nowa_crm.modules.proposals.service import ProposalService


class ApprovalManagerDialog(QDialog):
    def __init__(self, proposals: ProposalService, open_proposal, parent=None):
        super().__init__(parent)
        self.service = ProposalApprovalService(proposals)
        self.open_proposal = open_proposal
        self.setWindowTitle("Akkoordbeheer")
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(1380, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        title = QLabel("Akkoordbeheer en licentieplanning")
        title.setObjectName("Title")
        layout.addWidget(title)
        self.summary = QLabel()
        self.summary.setObjectName("Subtitle")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "Offerte", "Klant", "Titel", "Revisie", "Status", "Vervaldatum",
            "Akkoordgever", "Wijzigingen", "Nu", "Gepland", "Publicatie-ID",
        ])
        self.table.setColumnHidden(10, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 210)
        self.table.setColumnWidth(2, 280)
        self.table.setColumnWidth(4, 125)
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        refresh = QPushButton("Vernieuwen")
        refresh.clicked.connect(self.refresh)
        process = QPushButton("Vervallen wijzigingen nu verwerken")
        process.setObjectName("Primary")
        process.clicked.connect(self._process)
        open_button = QPushButton("Offerte openen")
        open_button.clicked.connect(self._open)
        revoke = QPushButton("Open publicatie intrekken")
        revoke.clicked.connect(self._revoke)
        close = QPushButton("Sluiten")
        close.clicked.connect(self.accept)
        for button in (refresh, process, open_button, revoke):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        self.service.expire_publications()
        rows = self.service.overview()
        self.rows = rows
        self.table.setRowCount(len(rows))
        colors = {"voorbereid": "#1265C4", "gepubliceerd": "#1265C4",
                  "verlopen": "#9A4B11", "ingetrokken": "#6B7280",
                  "te verwerken": "#B42318", "ingepland": "#7C3AED",
                  "verwerkt": "#16815F", "geaccepteerd": "#16815F"}
        for row_index, row in enumerate(rows):
            values = (row["number"], row["customer_name"], row["title"],
                      row["revision"], row["display_status"], row["expires_at"],
                      row["accepted_by"] or row["recipient_email"],
                      row["changed_count"], row["due_count"],
                      row["next_effective"] or row["future_count"], row["id"])
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if column == 4:
                    item.setForeground(QColor(colors.get(row["display_status"], "#0B2342")))
                self.table.setItem(row_index, column, item)
        due = sum(row["due_count"] for row in rows)
        planned = sum(row["future_count"] for row in rows)
        open_count = sum(row["display_status"] in ("voorbereid", "gepubliceerd") for row in rows)
        expired = sum(row["display_status"] == "verlopen" for row in rows)
        self.summary.setText(
            f"{open_count} open · {expired} verlopen · {due} wijziging(en) nu te verwerken · "
            f"{planned} gepland")

    def _selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def _open(self, *_):
        row = self._selected()
        if row:
            self.open_proposal(row["proposal_id"])
            self.refresh()

    def _process(self):
        row = self._selected()
        if not row:
            QMessageBox.information(self, "Akkoordbeheer", "Selecteer eerst een akkoord.")
            return
        if row["display_status"] not in ("te verwerken", "ingepland", "geaccepteerd"):
            QMessageBox.information(self, "Akkoordbeheer", "Dit akkoord heeft nu geen verwerkbare wijzigingen.")
            return
        if QMessageBox.question(
                self, "Licenties verwerken",
                "Alleen wijzigingen waarvan de ingangsdatum is bereikt worden lokaal verwerkt. Doorgaan?"
        ) != QMessageBox.Yes:
            return
        try:
            result = self.service.apply_license_changes(row["id"])
            QMessageBox.information(
                self, "Licentieplanning",
                f"{result['changed']} wijziging(en) verwerkt; {result['pending']} blijven ingepland.")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Licentieplanning", str(exc))

    def _revoke(self):
        row = self._selected()
        if not row:
            return
        if row["status"] not in ("voorbereid", "gepubliceerd"):
            QMessageBox.information(self, "Publicatie intrekken", "Alleen een open publicatie kan worden ingetrokken.")
            return
        if QMessageBox.question(self, "Publicatie intrekken", "Deze akkoordlink ongeldig maken?") != QMessageBox.Yes:
            return
        try:
            self.service.revoke(row["id"])
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Publicatie intrekken", str(exc))
