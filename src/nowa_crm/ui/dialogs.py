from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLineEdit, QMessageBox, QTextEdit, QVBoxLayout)


class CustomerDialog(QDialog):
    def __init__(self, parent=None, customer=None):
        super().__init__(parent); self.setWindowTitle("Klantgegevens"); self.setMinimumWidth(440)
        box = QVBoxLayout(self); form = QFormLayout()
        self.number = QLineEdit(customer.customer_number if customer else "")
        self.name = QLineEdit(customer.name if customer else "")
        self.email = QLineEdit(customer.email if customer else "")
        self.phone = QLineEdit(customer.phone if customer else "")
        self.mobile_phone = QLineEdit(customer.mobile_phone if customer else "")
        self.street = QLineEdit(customer.street if customer else "")
        self.postal_code = QLineEdit(customer.postal_code if customer else "")
        self.city = QLineEdit(customer.city if customer else "")
        self.country = QLineEdit(customer.country if customer else "")
        self.notes = QTextEdit(customer.notes if customer else ""); self.notes.setMaximumHeight(90)
        for label, widget in [("Klantnummer *",self.number),("Naam *",self.name),("E-mail",self.email),("Telefoon",self.phone),("Mobiele telefoon",self.mobile_phone),
                              ("Straat en huisnummer",self.street),("Postcode",self.postal_code),("Plaats",self.city),("Land",self.country),("Notities",self.notes)]: form.addRow(label,widget)
        box.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); box.addWidget(buttons)

    def _accept(self):
        if not self.number.text().strip() or not self.name.text().strip(): QMessageBox.warning(self,"Controle","Klantnummer en naam zijn verplicht."); return
        self.accept()

    def values(self): return [w.text().strip() for w in (self.number,self.name,self.email,self.phone,self.street,self.postal_code,self.city)] + [self.notes.toPlainText().strip(),self.mobile_phone.text().strip(),self.country.text().strip()]


class ContactDialog(QDialog):
    def __init__(self, parent=None, contact=None):
        super().__init__(parent); self.setWindowTitle("Contactpersoon"); self.setMinimumWidth(420)
        box=QVBoxLayout(self); form=QFormLayout()
        self.name=QLineEdit(contact.name if contact else ""); self.role=QLineEdit(contact.role if contact else "")
        self.email=QLineEdit(contact.email if contact else ""); self.phone=QLineEdit(contact.phone if contact else "")
        for label,widget in [("Naam *",self.name),("Functie / rol",self.role),("E-mail",self.email),("Telefoon",self.phone)]: form.addRow(label,widget)
        box.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); box.addWidget(buttons)

    def _accept(self):
        if not self.name.text().strip(): QMessageBox.warning(self,"Controle","Naam is verplicht."); return
        self.accept()

    def values(self): return [w.text().strip() for w in (self.name,self.role,self.email,self.phone)]


class VaultDialog(QDialog):
    def __init__(self, customers, parent=None):
        super().__init__(parent); self.setWindowTitle("Nieuw kluisitem"); self.setMinimumWidth(480); box=QVBoxLayout(self); form=QFormLayout()
        self.customer=QComboBox(); [self.customer.addItem(f"{c.customer_number} — {c.name}",c.id) for c in customers]
        self.category=QComboBox(); self.category.addItems(["Account","Microsoft 365","Netwerk","Domein","Hosting","Apparaat","Overig"])
        self.group_path=QLineEdit(); self.label=QLineEdit(); self.username=QLineEdit(); self.secret=QLineEdit(); self.secret.setEchoMode(QLineEdit.Password)
        self.url=QLineEdit(); self.host=QLineEdit(); self.notes=QTextEdit(); self.notes.setMaximumHeight(80)
        for label,widget in [("Klant *",self.customer),("Categorie",self.category),("Groep / pad",self.group_path),("Omschrijving *",self.label),
                             ("Gebruikersnaam",self.username),("Wachtwoord/geheim *",self.secret),("URL",self.url),("Host / IP",self.host),("Notities",self.notes)]: form.addRow(label,widget)
        box.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); box.addWidget(buttons)

    def _accept(self):
        if self.customer.currentData() is None or not self.label.text().strip() or not self.secret.text(): QMessageBox.warning(self,"Controle","Klant, omschrijving en geheim zijn verplicht."); return
        self.accept()
