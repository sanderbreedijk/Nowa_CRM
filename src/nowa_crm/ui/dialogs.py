from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLineEdit, QMessageBox, QVBoxLayout)


class CustomerDialog(QDialog):
    def __init__(self, parent=None, customer=None):
        super().__init__(parent); self.setWindowTitle("Klantgegevens"); self.setMinimumWidth(440)
        box = QVBoxLayout(self); form = QFormLayout()
        self.number = QLineEdit(customer.customer_number if customer else "")
        self.name = QLineEdit(customer.name if customer else "")
        self.email = QLineEdit(customer.email if customer else "")
        self.phone = QLineEdit(customer.phone if customer else "")
        self.city = QLineEdit(customer.city if customer else "")
        for label, widget in [("Klantnummer *",self.number),("Naam *",self.name),("E-mail",self.email),("Telefoon",self.phone),("Plaats",self.city)]: form.addRow(label,widget)
        box.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); box.addWidget(buttons)

    def _accept(self):
        if not self.number.text().strip() or not self.name.text().strip(): QMessageBox.warning(self,"Controle","Klantnummer en naam zijn verplicht."); return
        self.accept()

    def values(self): return [w.text().strip() for w in (self.number,self.name,self.email,self.phone,self.city)]


class VaultDialog(QDialog):
    def __init__(self, customers, parent=None):
        super().__init__(parent); self.setWindowTitle("Nieuw kluisitem"); self.setMinimumWidth(480); box=QVBoxLayout(self); form=QFormLayout()
        self.customer=QComboBox(); [self.customer.addItem(f"{c.customer_number} — {c.name}",c.id) for c in customers]
        self.category=QComboBox(); self.category.addItems(["Account","Microsoft 365","Netwerk","Domein","Hosting","Apparaat","Overig"])
        self.label=QLineEdit(); self.username=QLineEdit(); self.secret=QLineEdit(); self.secret.setEchoMode(QLineEdit.Password); self.url=QLineEdit()
        for label,widget in [("Klant *",self.customer),("Categorie",self.category),("Omschrijving *",self.label),("Gebruikersnaam",self.username),("Wachtwoord/geheim *",self.secret),("URL",self.url)]: form.addRow(label,widget)
        box.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); box.addWidget(buttons)

    def _accept(self):
        if self.customer.currentData() is None or not self.label.text().strip() or not self.secret.text(): QMessageBox.warning(self,"Controle","Klant, omschrijving en geheim zijn verplicht."); return
        self.accept()
