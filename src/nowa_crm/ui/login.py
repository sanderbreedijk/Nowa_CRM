from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout
from nowa_crm.core.auth import AuthService, Session


class SetupDialog(QDialog):
    def __init__(self, auth: AuthService):
        super().__init__(); self.auth=auth; self.setWindowTitle("NOWA CRM eerste beheerder"); self.setMinimumWidth(440)
        box=QVBoxLayout(self); box.addWidget(QLabel("Maak de eerste beheerder aan. Dit account beheert gebruikers en beveiliging.")); form=QFormLayout()
        self.username=QLineEdit(); self.name=QLineEdit(); self.password=QLineEdit(); self.confirm=QLineEdit()
        self.password.setEchoMode(QLineEdit.Password); self.confirm.setEchoMode(QLineEdit.Password)
        for label,w in (("Gebruikersnaam",self.username),("Naam",self.name),("Wachtwoord",self.password),("Herhaal wachtwoord",self.confirm)):form.addRow(label,w)
        box.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); box.addWidget(buttons)
    def _save(self):
        if self.password.text()!=self.confirm.text(): QMessageBox.warning(self,"Controle","De wachtwoorden zijn niet gelijk."); return
        try:self.auth.create_user(self.username.text(),self.name.text(),self.password.text(),"administrator"); self.accept()
        except Exception as e: QMessageBox.warning(self,"Controle",str(e))


class LoginDialog(QDialog):
    def __init__(self, auth: AuthService):
        super().__init__(); self.auth=auth; self.session:Session|None=None; self.setWindowTitle("Aanmelden bij NOWA CRM"); self.setMinimumWidth(380)
        box=QVBoxLayout(self); box.addWidget(QLabel("Meld aan om klantgegevens te openen.")); form=QFormLayout(); self.username=QLineEdit(); self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.Password); self.password.returnPressed.connect(self._login); form.addRow("Gebruikersnaam",self.username); form.addRow("Wachtwoord",self.password); box.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(self._login); buttons.rejected.connect(self.reject); box.addWidget(buttons)
    def _login(self):
        self.session=self.auth.authenticate(self.username.text(),self.password.text())
        if not self.session: QMessageBox.warning(self,"Aanmelden","Onjuiste gebruikersnaam of wachtwoord."); self.password.clear(); return
        self.accept()
